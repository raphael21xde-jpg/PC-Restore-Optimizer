"""P2-01 fatia 2: fluxo "Colocar no lugar original" para a tela de restauração.

Sem Tk: a tela (restore_ui) só chama estas funções. Ordem do fluxo:

1. ``staging_info`` confere a pasta de conferência escolhida: tem de ter sido
   criada pelo app, a restauração tem de estar CONCLUÍDA e todos os arquivos
   conferidos (SHA-256), e ela tem de ser do mesmo backup.
2. ``restore_place.plan_placement(..., keys=info['keys'])`` monta a prévia só
   com os arquivos restaurados nessa pasta (em segundo plano, pela tela).
3. ``preview_summary`` e ``confirmation_text`` mostram a prévia em português.
4. ``run_placement`` recusa se o app estiver como administrador e só então
   chama ``place_files`` com a prévia confirmada.
5. ``friendly_report`` resume o resultado sem nomes internos.

O diário da colocação tem caminho fixo, ao lado da pasta de conferência (fora
dela): ``COLOCAR-NO-LUGAR-<nome da pasta>.json``. Assim, abrir a mesma pasta de
novo retoma de onde parou, sem duplicar nada.
"""
from __future__ import annotations

import os
from pathlib import Path

from backup_core import is_reparse
from backup_features import read_restore_record, verified_entries
from restore_elevation import require_not_elevated
from restore_place import place_files

JOURNAL_PREFIX = 'COLOCAR-NO-LUGAR-'

_PREVIEW_LINES = (
    ('novo', '{n} arquivo(s) novo(s): ainda não existem no lugar original e serão colocados.'),
    ('igual', '{n} arquivo(s) igual(is) ao que já está lá: não serão mexidos.'),
    ('renomear', '{n} arquivo(s) diferente(s): o app vai guardar o antigo com outro nome '
                 '(terminado em .antes-pcro-DATA) e colocar o novo. Nada é apagado.'),
    ('precisa_admin', '{n} arquivo(s) em pastas do sistema (Program Files, ProgramData ou '
                      'Windows): precisam de permissão de administrador.'),
    ('bloqueado', '{n} arquivo(s) bloqueado(s) por segurança: no lugar original há uma pasta, '
                  'um atalho ou algo inesperado. Eles não serão colocados.'),
    ('ignorado', '{n} arquivo(s) ignorado(s): o Windows cria esses arquivos sozinho '
                 '(desktop.ini).'),
)

_STATUS_TEXT = {
    'concluido': 'Concluído: todos os arquivos possíveis foram colocados e conferidos.',
    'concluido_com_falhas': 'Concluído, mas alguns arquivos não foram colocados (veja abaixo).',
    'cancelado': 'Cancelado. O que já foi colocado está conferido; '
                 'use "Retomar colocação interrompida" para continuar.',
}


def journal_path_for(staging):
    """Diário fixo ao lado da pasta de conferência (nunca dentro dela)."""
    staging = Path(staging)
    return staging.parent / (JOURNAL_PREFIX + staging.name + '.json')


def staging_info(folder, manifest):
    """Confere a pasta de conferência e devolve o que a colocação precisa.

    Devolve ``{'folder', 'manifest', 'keys', 'journal', 'has_journal'}``.
    Reaproveita as conferências de ``resume_information`` (pasta criada pelo
    app, registro seguro), mas aqui a restauração tem de estar concluída.
    """
    folder, data = read_restore_record(folder)
    manifest = Path(manifest).resolve(strict=True)
    if data.get('engine_version') != '0.5.19' or data.get('manifest_path') != str(manifest):
        raise ValueError('Esta pasta de conferência é de outro backup ou de uma versão antiga '
                         'do app. Escolha a pasta criada a partir deste backup.')
    if data.get('status') != 'concluida':
        raise ValueError('A restauração desta pasta não foi concluída. Termine a restauração '
                         '(ou use "Retomar restauração interrompida") antes de colocar os '
                         'arquivos no lugar original.')
    keys, verified = data.get('keys'), data.get('verified_keys')
    if (not isinstance(keys, list) or not keys or not isinstance(verified, list) or
            len(set(keys)) != len(keys) or len(set(verified)) != len(verified) or
            set(keys) != set(verified)):
        raise ValueError('Nem todos os arquivos desta pasta foram conferidos. '
                         'Faça uma restauração nova antes de colocar no lugar original.')
    entries = verified_entries(manifest)
    if any(not isinstance(key, str) or key not in entries for key in keys):
        raise ValueError('Os arquivos desta pasta não correspondem ao backup atual.')
    journal = journal_path_for(folder)
    if os.path.lexists(journal) and (is_reparse(journal) or not journal.is_file()):
        raise ValueError('O registro da colocação ao lado desta pasta é um atalho ou não é um '
                         'arquivo comum. Por segurança, nada será feito.')
    return {'folder': folder, 'manifest': manifest, 'keys': list(keys), 'journal': journal,
            'has_journal': journal.is_file()}


def preview_summary(plan):
    """Contagens da prévia em português simples."""
    counts = plan.counts()
    lines = [f'Prévia: {len(plan.items)} arquivo(s) conferido(s) nesta pasta.']
    lines += [text.format(n=counts[name]) for name, text in _PREVIEW_LINES if counts[name]]
    return '\n'.join(lines)


def confirmation_text(plan, allow_protected=False):
    """Texto da pergunta de confirmação, conforme a escolha das pastas do sistema."""
    counts = plan.counts()
    parts = [preview_summary(plan), '']
    protected = counts['precisa_admin']
    if protected and allow_protected is True:
        parts.append(f'Você escolheu incluir {protected} arquivo(s) de pastas do sistema. '
                     'O app não pede permissão de administrador: sem permissão, eles ficam '
                     'na lista de falhas e continuam na pasta de conferência.')
    elif protected:
        parts.append(f'{protected} arquivo(s) de pastas do sistema não serão colocados '
                     '(a opção de incluir Program Files/ProgramData está desmarcada).')
    parts.append('Nada será apagado: a pasta de conferência e o backup ficam como estão, e '
                 'arquivos diferentes que já existem são guardados com outro nome.')
    parts.append('Deseja colocar os arquivos no lugar original agora?')
    return '\n'.join(parts)


def run_placement(plan, *, allow_protected=False, cancelled=None, progress=None,
                  elevation_probe=None, journal_path=None):
    """Recusa como administrador; depois coloca os arquivos da prévia confirmada."""
    require_not_elevated(probe=elevation_probe)
    journal = journal_path or journal_path_for(plan.staging_folder)
    return place_files(plan, confirmed_preview=True, allow_protected=allow_protected is True,
                       journal_path=journal, cancelled=cancelled, progress=progress)


def friendly_report(plan, result):
    """Resumo do resultado para a pessoa, sem nomes internos."""
    targets = {item.key: str(item.target) for item in plan.items}
    lines = ['Colocar no lugar original — resultado', '',
             _STATUS_TEXT.get(result.get('status'), 'Situação desconhecida.'), '',
             f'Colocados agora: {len(result.get("placed", []))}',
             f'Já estavam iguais (não mexidos): {len(result.get("equal", []))}',
             f'Já colocados antes (conferidos de novo): {len(result.get("resumed", []))}',
             f'Ignorados (o Windows cria sozinho): {len(result.get("ignored", []))}']
    protected = result.get('skipped_protected', [])
    if protected:
        lines.append(f'{len(protected)} arquivo(s) de pastas do sistema não foram colocados '
                     '(opção desmarcada).')
    renamed = result.get('renamed', [])
    if renamed:
        lines += ['', 'Arquivos antigos guardados com outro nome (nunca apagados):']
        lines += [f'  {r["target"]}  →  {Path(r["aside"]).name}' for r in renamed]
    failures = result.get('failures', [])
    if failures:
        lines += ['', f'{len(failures)} arquivo(s) não foram colocados:']
        lines += [f'  {targets.get(f["key"], f["target"])}: {f["error"]}' for f in failures]
    lines += ['', 'A pasta de conferência foi conservada; apague-a só quando tiver certeza '
                  'de que está tudo certo.']
    return '\n'.join(lines) + '\n'
