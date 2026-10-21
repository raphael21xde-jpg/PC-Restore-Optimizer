"""P2-04: lista de programas do backup via `winget export` (só leitura).

O que este módulo faz:
- monta o comando `winget export` (nunca `install` nem `import`: quem instala
  é só o `winget_install.py`, depois da confirmação na tela);
- grava a lista numa subpasta NOVA `programas-winget/` dentro da pasta do
  backup (ou `programas-winget-2`, `-3`… quando a pessoa salva de novo), sem
  tocar no manifest.json, nos arquivos copiados nem nas listas anteriores;
- relê a lista válida mais nova conferindo o SHA-256 e organiza os pacotes
  por categoria.

Nada é instalado aqui. Nada é apagado: em falha, o arquivo `.parcial`
fica onde está e é ignorado.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import subprocess
from datetime import datetime
from pathlib import Path

from app_recovery import package_id
from backup_core import atomic_json

SUBFOLDER = 'programas-winget'
EXPORT_NAME = 'winget-export.json'
PARTIAL_NAME = EXPORT_NAME + '.parcial'
INFO_NAME = 'info.json'
TIMEOUT_SEC = 180
MAX_BYTES = 5 * 1024 * 1024
MAX_PACKAGES = 5000

CATEGORIES = ('Runtimes', 'Launchers', 'Periféricos', 'Dia a dia', 'Dev', 'Outros')

MISSING_TEXT = ('Este backup não tem a lista de programas. Ela é salva quando você '
                'responde "Sim" à pergunta feita no fim de um backup concluído. Backups '
                'anteriores a esta versão do aplicativo não têm a lista. Se você ainda não '
                'formatou, use "Salvar lista agora". Se já formatou, reinstale os programas '
                'pelo site oficial de cada um.')
READ_ERROR_TEXT = ('Não foi possível ler a lista (arquivo em uso ou sem permissão). '
                   'Os arquivos do backup não foram tocados.')
MAX_SAVES = 99
CHANGED_TEXT = ('A lista de programas foi alterada depois do backup e não será usada. '
                'Os arquivos do backup não foram tocados.')
TOO_BIG_TEXT = 'A lista de programas é grande demais para ser aberta com segurança.'
INVALID_TEXT = 'A lista de programas está danificada ou num formato desconhecido.'
AGREEMENT_TEXT = ('O winget pediu para aceitar os termos de uso da fonte de programas. '
                  'Abra o winget uma vez (no Terminal, digite: winget list), aceite os termos '
                  'e depois tente salvar a lista de novo.')
NOT_WINDOWS_TEXT = 'A lista de programas só pode ser salva no Windows.'
NO_WINGET_TEXT = ('O winget não foi encontrado neste computador. Atualize o "Instalador de '
                  'Aplicativo" pela Microsoft Store e tente de novo.')
MSSTORE_NOTE = 'Instale pela Microsoft Store.'
OSU_NOTE = ('O winget instala o osu!lazer, que é outro jogo. Para o osu! clássico, '
            'baixe o instalador no site oficial (osu.ppy.sh).')
UNKNOWN_SOURCE_NOTE = 'Fonte desconhecida: instale pelo site oficial do programa.'

# Tabela ordenada: a primeira regra que combinar decide. Dev vem antes de
# Periféricos para que "SonarSource" não caia em "sonar" (SteelSeries).
_PREFIXES = (
    ('Runtimes', ('microsoft.vcredist', 'microsoft.dotnet', 'microsoft.directx',
                  'microsoft.windowsappruntime', 'microsoft.edgewebview2runtime',
                  'microsoft.xnaredist', 'microsoft.vclibs', 'microsoft.ui.xaml',
                  'oracle.javaruntimeenvironment', 'oracle.jdk', 'eclipseadoptium.',
                  'nvidia.physx', 'openal.openal')),
    ('Launchers', ('valve.steam', 'epicgames.', 'electronicarts.', 'ubisoft.connect',
                   'gog.galaxy', 'riotgames.', 'rockstargames.', 'blizzard.',
                   'amazon.games', 'playnite.', 'microsoft.gamingapp', 'battle.net')),
    ('Dev', ('git.git', 'github.', 'python.python', 'microsoft.visualstudiocode',
             'microsoft.visualstudio', 'microsoft.powershell', 'microsoft.windowsterminal',
             'openjs.nodejs', 'jetbrains.', 'docker.', 'notepad++.', 'rustlang.',
             'golang.', 'postman.', 'sonarsource.', 'kitware.cmake', 'anaconda.')),
    ('Periféricos', ('logitech.', 'razer.', 'razerinc.', 'steelseries.', 'corsair.',
                     'hyperx.', 'nvidia.', 'amd.', 'elgato.', 'nzxt.', 'asus.',
                     'msi.', 'gigabyte.', 'wooting.', 'coolermaster.')),
    ('Dia a dia', ('google.chrome', 'mozilla.', 'brave.', 'opera.', 'discord.',
                   'spotify.', 'videolan.', '7zip.', 'rarlab.', 'zoom.', 'telegram.',
                   'microsoft.teams', 'microsoft.office', 'microsoft.edge',
                   'microsoft.onedrive', 'adobe.acrobat', 'obsproject.', 'thedocumentfoundation.',
                   'notion.', 'dropbox.', 'whatsapp.', 'irfanview.', 'gimp.')),
)

_MSSTORE_ID = re.compile(r'[A-Za-z0-9]{12}')


_SEPARATORS = re.compile(r'[._\-+]')
SHORT_TERM_MAX = 5  # termos curtos (ex.: "sonar", "swarm") só valem como pedaço inteiro do ID


def _peripheral_terms():
    try:
        from program_catalog import PERIPHERAL_TERMS
    except Exception:  # catálogo indisponível: só a tabela de prefixos vale
        return ()
    return tuple(t.casefold().replace(' ', '') for t in PERIPHERAL_TERMS)


def _matches_peripheral(pid):
    segments = {part for part in _SEPARATORS.split(pid) if part}
    compact = _SEPARATORS.sub('', pid)
    for term in _peripheral_terms():
        if not term:
            continue
        if len(term) <= SHORT_TERM_MAX:
            if term in segments:
                return True
        elif term in compact:
            return True
    return False


def categorize(package_id_value):
    """Categoria de um ID de pacote; sem diferenciar maiúsculas. Resto → Outros."""
    pid = str(package_id_value or '').strip().casefold()
    if not pid:
        return 'Outros'
    for name, prefixes in _PREFIXES:
        if name == 'Periféricos' and _matches_peripheral(pid):
            return name
        if pid.startswith(prefixes):
            return name
    return 'Outros'


def export_command(output_path, executable='winget'):
    return [str(executable), 'export', '--output', str(output_path), '--source', 'winget',
            '--include-versions', '--disable-interactivity']


def _is_link(path):
    path = Path(path)
    isjunction = getattr(os.path, 'isjunction', None)
    return path.is_symlink() or bool(isjunction and isjunction(path))


def _platform_is_windows():
    return os.name == 'nt'


def _find_winget():
    return shutil.which('winget')


def _default_runner(cmd):
    result = subprocess.run(cmd, shell=False, capture_output=True, text=True, encoding='utf-8',
                            errors='replace', timeout=TIMEOUT_SEC, stdin=subprocess.DEVNULL)
    return result.returncode, ((result.stdout or '') + '\n' + (result.stderr or '')).strip()


def _result(status, message, count=0, sha256=None):
    return {'status': status, 'count': count, 'sha256': sha256, 'message': message}


def _check_backup_folder(folder):
    """Mensagem de recusa ou None. Exige pasta real com manifest.json ao lado."""
    if not folder.is_dir() or _is_link(folder):
        return 'A pasta do backup não foi encontrada.'
    manifest = folder / 'manifest.json'
    if _is_link(manifest) or not manifest.is_file():
        return 'Esta pasta não é um backup do aplicativo (falta o manifest.json).'
    return None


def save_export(backup_folder, *, runner=None, executable=None, new_folder=False):
    """Salva a lista de programas numa subpasta nova. Nunca levanta exceção.

    Com ``new_folder=True`` ("Salvar lista agora"), se `programas-winget` já
    existir, usa a próxima pasta livre `programas-winget-2`, `-3`… Nunca
    sobrescreve nem apaga uma lista anterior.
    """
    try:
        return _save_export(Path(backup_folder), runner or _default_runner, executable,
                            new_folder)
    except Exception:
        return _result('falhou', 'Não foi possível salvar a lista de programas. '
                                 'O backup continua válido.')


def _next_free_subfolder(folder):
    for number in range(2, MAX_SAVES + 1):
        candidate = folder / f'{SUBFOLDER}-{number}'
        if not os.path.lexists(candidate):
            return candidate
    return None


def _save_export(folder, runner, executable, new_folder=False):
    refusal = _check_backup_folder(folder)
    if refusal:
        return _result('recusado', refusal)
    sub = folder / SUBFOLDER
    if new_folder and os.path.lexists(sub):
        sub = _next_free_subfolder(folder)
        if sub is None:
            return _result('recusado', 'Este backup já tem listas de programas demais. '
                                       'Nenhuma foi substituída.')
    if _is_link(sub):
        return _result('recusado', 'A pasta "programas-winget" deste backup é um atalho '
                                   '(link). Por segurança, nada foi gravado.')
    if os.path.lexists(sub):
        return _result('recusado', 'Este backup já tem uma pasta "programas-winget". '
                                   'Ela não será substituída.')
    if executable is None:
        if not _platform_is_windows():
            return _result('indisponivel', NOT_WINDOWS_TEXT)
        executable = _find_winget()
        if not executable:
            return _result('indisponivel', NO_WINGET_TEXT)
    os.mkdir(sub)  # falha se alguém criou entre a checagem e agora
    partial = sub / PARTIAL_NAME
    failed = 'Não foi possível salvar a lista de programas. O backup continua válido.'
    try:
        code, output = runner(export_command(partial, executable))
    except subprocess.TimeoutExpired:
        return _result('falhou', 'O winget demorou demais para responder. ' + failed)
    except OSError:
        return _result('falhou', failed)
    text = str(output or '').casefold()
    if code != 0:
        if 'agreement' in text or 'termos' in text or 'contrato' in text:
            return _result('falhou', AGREEMENT_TEXT)
        return _result('falhou', f'O winget terminou com erro (código {code}). ' + failed)
    try:
        if _is_link(partial) or not partial.is_file() or partial.stat().st_size > MAX_BYTES:
            raise ValueError
        raw = partial.read_bytes()
        packages = parse_export(json.loads(raw.decode('utf-8-sig')))
    except (OSError, ValueError, UnicodeDecodeError):
        return _result('falhou', 'O winget não gerou uma lista válida. ' + failed)
    digest = hashlib.sha256(raw).hexdigest()
    final = sub / EXPORT_NAME
    os.replace(partial, final)
    atomic_json(sub / INFO_NAME, {
        'formato': 1, 'arquivo': EXPORT_NAME, 'sha256': digest,
        'quantidade': len(packages), 'data': datetime.now().isoformat(timespec='seconds'),
    })
    return _result('salvo', f'Lista de programas salva: {len(packages)} programa(s).',
                   len(packages), digest)


def export_after_backup(folder, manifest, ask, runner=None, executable=None):
    """Só roda com backup `concluido` e se ask() responder True."""
    if not isinstance(manifest, dict) or manifest.get('status') != 'concluido':
        return None
    if not ask():
        return None
    return save_export(folder, runner=runner, executable=executable)


def _valid_id(value, source):
    if not isinstance(value, str):
        return None
    value = value.strip()
    if source == 'msstore' and _MSSTORE_ID.fullmatch(value):
        return value
    try:
        return package_id(value)
    except ValueError:
        return None


def parse_export(data):
    """Pacotes válidos do JSON do winget, sem duplicados, ordenados por categoria."""
    if not isinstance(data, dict) or not isinstance(data.get('Sources'), list):
        raise ValueError(INVALID_TEXT)
    seen, packages, total = set(), [], 0
    for block in data['Sources']:
        if not isinstance(block, dict):
            continue
        details = block.get('SourceDetails') if isinstance(block.get('SourceDetails'), dict) else {}
        source = str(details.get('Name') or '').strip().casefold() or 'desconhecida'
        items = block.get('Packages') if isinstance(block.get('Packages'), list) else []
        total += len(items)
        if total > MAX_PACKAGES:
            raise ValueError(TOO_BIG_TEXT)
        for item in items:
            if not isinstance(item, dict):
                continue
            pid = _valid_id(item.get('PackageIdentifier'), source)
            if pid is None or (source, pid.casefold()) in seen:
                continue
            seen.add((source, pid.casefold()))
            version = item.get('Version')
            version = version.strip()[:100] if isinstance(version, str) else ''
            selectable, note = True, ''
            if source == 'msstore':
                selectable, note = False, MSSTORE_NOTE
            elif source != 'winget':
                selectable, note = False, UNKNOWN_SOURCE_NOTE
            elif pid.casefold() == 'ppy.osu':
                selectable, note = False, OSU_NOTE
            packages.append({'id': pid, 'version': version, 'source': source,
                             'category': categorize(pid), 'selectable': selectable, 'note': note})
    order = {name: i for i, name in enumerate(CATEGORIES)}
    packages.sort(key=lambda p: (order[p['category']], p['id'].casefold()))
    return packages


def _candidate_subfolders(folder):
    """Pastas de lista, da mais nova (número mais alto) para a mais antiga."""
    found = []
    try:
        names = os.listdir(folder)
    except OSError:
        names = []
    pattern = re.compile(re.escape(SUBFOLDER) + r'-(\d{1,3})')
    for name in names:
        match = pattern.fullmatch(name)
        if match and 2 <= int(match.group(1)) <= MAX_SAVES:
            found.append((int(match.group(1)), folder / name))
    found.sort(reverse=True)
    return [path for _, path in found] + [folder / SUBFOLDER]


def load_export(backup_folder):
    """Relê a lista válida mais nova conferindo o SHA-256.

    Tenta `programas-winget-N` do número mais alto para o mais baixo e por fim
    `programas-winget`; usa a primeira que estiver íntegra. Levanta ValueError
    com texto simples (o da pasta mais nova) se nenhuma servir.
    """
    first_error = None
    for sub in _candidate_subfolders(Path(backup_folder)):
        try:
            return _load_subfolder(sub)
        except ValueError as exc:
            # "falta a lista" só é mostrado se nenhuma pasta tiver um erro mais útil
            if first_error is None and str(exc) != MISSING_TEXT:
                first_error = exc
    raise first_error if first_error is not None else ValueError(MISSING_TEXT)


def _load_subfolder(sub):
    try:
        return _read_subfolder(sub)
    except OSError:
        raise ValueError(READ_ERROR_TEXT) from None


def _read_subfolder(sub):
    if _is_link(sub):
        raise ValueError('A pasta "programas-winget" deste backup é um atalho (link) e não será lida.')
    final, info_path = sub / EXPORT_NAME, sub / INFO_NAME
    if not sub.is_dir() or not final.is_file() or not info_path.is_file():
        raise ValueError(MISSING_TEXT)
    if _is_link(final) or _is_link(info_path):
        raise ValueError(CHANGED_TEXT)
    if info_path.stat().st_size > 64 * 1024:
        raise ValueError(CHANGED_TEXT)
    with open(info_path, 'rb') as handle:
        info_raw = handle.read(64 * 1024 + 1)
    try:
        info = json.loads(info_raw.decode('utf-8-sig'))
        expected = str(info.get('sha256') or '')
    except (ValueError, UnicodeDecodeError, AttributeError):
        raise ValueError(CHANGED_TEXT) from None
    with open(final, 'rb') as handle:
        raw = handle.read(MAX_BYTES + 1)
    if len(raw) > MAX_BYTES:
        raise ValueError(TOO_BIG_TEXT)
    if hashlib.sha256(raw).hexdigest() != expected:
        raise ValueError(CHANGED_TEXT)
    try:
        data = json.loads(raw.decode('utf-8-sig'))
    except (ValueError, UnicodeDecodeError):
        raise ValueError(INVALID_TEXT) from None
    return parse_export(data)


def group_by_category(packages):
    groups = {name: [] for name in CATEGORIES}
    for package in packages:
        groups.get(package.get('category'), groups['Outros']).append(package)
    return groups


def default_selection(packages):
    """Nada vem marcado: quem escolhe é a pessoa."""
    return set()
