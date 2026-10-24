"""P2-09 fatia 3b-1: controller of the real protected-copy screen (no Tk).

It only orders the steps the future screen will show, and runs no command
of its own:

1. ``request_disk_check()`` shows a warning before the first disk query;
2. ``confirm_disk_check(True)`` (exactly ``True``) builds the preview with
   ``multi_source_executor.preview_real_execution``, which reads the disk
   list once through the ``disk_collector``. Any other answer goes back to
   the start without reading anything;
3. ``confirm_copy(confirmed)`` turns the person's answer into an
   authorization (``copy_authorization.authorize_copy``);
4. ``run()`` calls ``multi_source_executor.run_real_copy``, which checks
   everything again (including a new disk query) and uses the
   authorization up.

``reset()`` and ``cancel()`` use the authorization up and go back to the
start. Any error becomes the state ``recusado`` with a short reason in
plain Portuguese, never a path. Sources are only read; nothing here
formats, erases or installs anything.
"""
from __future__ import annotations

from pathlib import Path

import backup_core
import multi_source_executor as executor
from copy_authorization import authorize_copy, discard_authorization

INICIO = 'inicio'
AVISO_CONSULTA = 'aviso_consulta'
PREVIA = 'previa'
CONFIRMADO = 'confirmado'
CONCLUIDO = 'concluido'
RECUSADO = 'recusado'

AVISO_CONSULTA_TEXTO = (
    'Para montar a prévia, vou só ler a lista de discos deste computador '
    '(e ler de novo logo antes de copiar): nada é gravado, formatado nem '
    'apagado. Quer continuar?')
CANCELADO = 'Cancelado. Nada foi gravado.'
NAO_CONFIRMADO = ('A cópia não foi confirmada. Nada foi gravado. Para copiar, '
                  'confirme a prévia.')

# Short reasons. Messages from the engine may carry a path with the user
# name, so they are never shown; only these texts are.
MSG_PREVIA = ('Não deu para montar a prévia: a origem ou o destino não '
              'passou na conferência. Nada foi gravado.')
MSG_UNIDADE = ('O destino precisa ser uma pasta que já existe, em outro disco '
               'fora do C:, num computador com Windows. Nada foi gravado.')
MSG_SOBREPOR = ('O destino não pode ficar dentro da origem, nem a origem '
                'dentro do destino. Nada foi gravado.')
MSG_LINK = ('A origem ou o destino passa por um atalho de pasta (link ou '
            'junção), o que não é permitido. Nada foi gravado.')
MSG_RAIZ = ('A origem ou o destino não pode ser a pasta principal de uma '
            'unidade: escolha uma pasta dentro dela. Nada foi gravado.')
MSG_MUDOU = ('A origem ou o destino mudou desde a prévia. Faça a prévia de '
             'novo. Nada foi gravado.')
MSG_INESPERADO = ('Aconteceu um erro inesperado. Trate a cópia como não '
                  'verificada e faça a prévia de novo.')

_BY_PREFIX = (
    (executor.REFUSED_CONFIRM, executor.REFUSED_CONFIRM),
    (executor.REFUSED_DISKS, executor.REFUSED_DISKS),
    ('Escolha uma pasta existente em unidade diferente de C:', MSG_UNIDADE),
    ('Selecione uma pasta de destino existente', MSG_UNIDADE),
    ('Destino precisa ser uma pasta existente', MSG_UNIDADE),
    (executor.ROOT_REFUSED, MSG_RAIZ),
    ('Link/junção proibido', MSG_LINK),
)
_SOBREPOR = ('não pode se sobrepor', 'pode se sobrepor à origem')
_MUDOU = ('mudou', 'mudaram', 'divergente', 'alterad', 'modificad',
          'desapareceu')

VERDICT_TEXT = {
    'independentes': 'Os destinos ficam em outro disco, separado da origem.',
}
VERDICT_DOUBT = ('Não deu para confirmar que os destinos ficam em outro disco, '
                 'separado da origem. A cópia vai ser recusada.')


def _reason(error):
    """Short Portuguese reason for an error; never the original message."""
    if not isinstance(error, ValueError):
        return MSG_INESPERADO
    text = str(error)
    for prefix, reason in _BY_PREFIX:
        if text.startswith(prefix):
            return reason
    if any(word in text for word in _SOBREPOR):
        return MSG_SOBREPOR
    if any(word in text for word in _MUDOU):
        return MSG_MUDOU
    return MSG_PREVIA


def _drive(value):
    drive = Path(value).drive if isinstance(value, str) else ''
    return drive if len(drive) == 2 and drive[1] == ':' else None


class RealCopyFlow:
    """Steps of the real copy screen, in memory, with no window."""

    def __init__(self, plan, target_preview, *, volume_lookup, usage,
                 disk_collector):
        self.plan = plan
        self.target_preview = target_preview
        self._volume_lookup = volume_lookup
        self._usage = usage
        self._disk_collector = disk_collector
        self._authorization = None
        self.state = INICIO
        self.message = None
        self.preview = None
        self.result = None
        self.report = None

    # -- helpers ---------------------------------------------------------
    def _drop_authorization(self):
        discard_authorization(self._authorization)
        self._authorization = None

    def _refuse(self, reason):
        self._drop_authorization()
        self.state = RECUSADO
        self.message = reason
        return self.state

    # -- steps -----------------------------------------------------------
    def request_disk_check(self):
        """Show the warning before reading the disk list (reads nothing)."""
        self._drop_authorization()
        self.preview = self.result = self.report = None
        self.state = AVISO_CONSULTA
        self.message = AVISO_CONSULTA_TEXTO
        return self.state

    def confirm_disk_check(self, confirmed):
        """Only ``True`` after the warning reads the disks and builds the preview."""
        if self.state != AVISO_CONSULTA or confirmed is not True:
            return self.reset()
        try:
            self.preview = executor.preview_real_execution(
                self.plan, self.target_preview, volume_lookup=self._volume_lookup,
                usage=self._usage, disk_collector=self._disk_collector)
        except Exception as error:  # noqa: BLE001 - shown as a short reason
            self.preview = None
            return self._refuse(_reason(error))
        self.state = PREVIA
        self.message = None
        return self.state

    def confirm_copy(self, confirmed):
        """Turn the person's answer to the preview into an authorization."""
        if self.state not in (PREVIA, CONFIRMADO):
            return self._refuse(NAO_CONFIRMADO)
        self._drop_authorization()
        auth = authorize_copy(self.preview, user_confirmed=confirmed)
        self._authorization = auth
        if auth.get('copy_authorized') is not True:
            self.state = PREVIA
            self.message = auth.get('motivo') or NAO_CONFIRMADO
        else:
            self.state = CONFIRMADO
            self.message = None
        return self.state

    def run(self, cancelled=None, progress=None):
        """Copy now (synchronous). Without a valid confirmation it refuses."""
        auth, self._authorization = self._authorization, None
        if self.state != CONFIRMADO or auth is None:
            discard_authorization(auth)
            return self._refuse(executor.REFUSED_CONFIRM)
        try:
            result = executor.run_real_copy(
                self.plan, self.target_preview, volume_lookup=self._volume_lookup,
                usage=self._usage, disk_collector=self._disk_collector,
                authorization=auth, cancelled=cancelled, progress=progress)
            report = executor.format_report_pt(result)
        except Exception as error:  # noqa: BLE001 - shown as a short reason
            discard_authorization(auth)
            return self._refuse(_reason(error))
        self.result = result
        self.report = report
        self.state = CONCLUIDO
        self.message = None
        return self.state

    def reset(self):
        """Back to the start; any authorization is used up."""
        self._drop_authorization()
        self.preview = self.result = self.report = None
        self.state = INICIO
        self.message = None
        return self.state

    def cancel(self):
        """The person gave up: same as reset, with a short message."""
        self.reset()
        self.message = CANCELADO
        return self.state

    # -- texts -----------------------------------------------------------
    def preview_text(self):
        """Plain-Portuguese preview with no full path, serial or model."""
        preview = self.preview
        if self.state not in (PREVIA, CONFIRMADO) or not isinstance(preview, dict):
            return 'A prévia ainda não foi feita.'
        sources = preview.get('sources') or []
        drives = sorted({d for d in (_drive(s) for s in sources) if d})
        line = f'Origens: {len(sources)} pasta(s)'
        if drives:
            line += ' na(s) unidade(s) ' + ', '.join(drives)
        lines = ['PRÉVIA DA CÓPIA PROTEGIDA', '', line + '.']
        for row in preview.get('destinations') or []:
            label = f'Destino {row.get("number")}'
            volume = row.get('volume')
            if isinstance(volume, str) and len(volume) == 2 and volume[1] == ':':
                label += f' (unidade {volume})'
            lines.append(f'- {label}')
        size = backup_core.human_size(int(preview.get('bytes_per_copy') or 0))
        total = backup_core.human_size(int(preview.get('bytes_total') or 0))
        lines += ['',
                  f'Cada cópia tem {preview.get("files_per_copy", 0)} '
                  f'arquivo(s), {size}.',
                  f'Cópias: {preview.get("copies", 0)}; total a gravar: {total}.',
                  'A origem só é lida: nada nela é gravado ou apagado.',
                  '', 'Conferência dos discos:']
        check = preview.get('physical_check')
        veredito = check.get('veredito') if isinstance(check, dict) else None
        lines.append(VERDICT_TEXT.get(veredito, VERDICT_DOUBT))
        texto = check.get('texto') if isinstance(check, dict) else None
        if isinstance(texto, str) and texto.strip():
            lines += texto.splitlines()
        return '\n'.join(lines)
