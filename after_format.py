"""P2-11: assistente "Depois de formatar" (parte sem Tk, somente leitura).

Guarda as 5 etapas do assistente, confere as unidades (letras) deste
computador contra as letras de onde vieram os arquivos do backup e salva o
progresso (pendente / feito / pulado) num arquivo pequeno por backup.

Regras de segurança:
- nas unidades, só lê: lista as letras, o tipo e o espaço livre. Nunca troca
  letra, formata, particiona ou apaga nada. A troca de letra é só orientada e
  feita à mão pela pessoa no Gerenciamento de Disco;
- o único arquivo gravado é o do progresso, de forma atômica (.parcial de
  nome único + os.replace). Um arquivo de progresso estragado, grande demais,
  de outro backup ou que seja um link fica intocado: o assistente começa do
  zero num arquivo novo (-2, -3...).
- FIX-P2-11-02: o progresso é ligado ao backup (nome da pasta, started e
  plan_fingerprint do manifest.json), não à letra da unidade.
- FIX-P2-11-03: a tela não grava direto; pede a um ProgressSaver, que grava
  numa thread própria (a troca do arquivo pode esperar até ~2 s no Windows).
"""
from __future__ import annotations

import hashlib
import json
import ntpath
import os
import re
import shutil
import stat
import threading
import time
import uuid
from pathlib import Path

from backup_core import human_size
from backup_features import verified_entries
from plaintext_passwords import scan_paths
from windows_drive import windows_drive

STEPS = (
    {'id': 'discos', 'title': 'Conferir discos e letras',
     'text': 'Veja se as unidades (C:, D:, E:...) apareceram com as mesmas letras de antes. '
             'O aplicativo só olha; se uma letra mudou, ele mostra como trocá-la à mão.'},
    {'id': 'restaurar', 'title': 'Restaurar os arquivos',
     'text': 'Abra a restauração do backup escolhido e traga de volta os arquivos que você '
             'quiser. Os arquivos do backup continuam guardados.'},
    {'id': 'programas', 'title': 'Reinstalar os programas',
     'text': 'Veja a lista de programas que estavam instalados quando o backup foi feito e '
             'escolha quais instalar de novo.'},
    {'id': 'launchers', 'title': 'Religar os launchers de jogos',
     'text': 'Encontre as bibliotecas da Steam, Epic e outros launchers nas unidades e veja '
             'como religar cada uma, sem baixar os jogos de novo.'},
    {'id': 'navegador', 'title': 'Navegador e senhas',
     'text': 'Traga de volta favoritos e senhas do navegador, importando pelo próprio navegador.'},
)
STEP_IDS = tuple(step['id'] for step in STEPS)
PENDING, DONE, SKIPPED = 'pendente', 'feito', 'pulado'
STATUSES = (PENDING, DONE, SKIPPED)

SCHEMA = 'pcro-depois-de-formatar-v1'
PROGRESS_LIMIT = 64 * 1024
MAX_PROGRESS_FILES = 50
PARTIAL_SUFFIX = '.parcial'

CHANGE_LETTER_GUIDE = (
    'Como trocar a letra de uma unidade (feito por você, à mão):\n'
    '1. Clique com o botão direito no botão Iniciar e escolha "Gerenciamento de Disco".\n'
    '2. Ache a unidade certa pelo nome e pelo tamanho.\n'
    '3. Clique com o botão direito nela e escolha "Alterar letra de unidade e caminho".\n'
    '4. Clique em "Alterar", escolha a letra {letters} e confirme.\n'
    'Não mude a letra do disco do Windows. O aplicativo nunca troca letras sozinho.')

_DRIVE_TYPES = {2: 'Removível (pendrive ou cartão)', 3: 'Disco local', 4: 'Unidade de rede',
                5: 'CD ou DVD', 6: 'Disco na memória'}


def _on_windows():
    return os.name == 'nt'


def default_drive_type(root):
    """Tipo da unidade (só leitura, GetDriveTypeW). Fora do Windows: desconhecido."""
    if not _on_windows():
        return 'Desconhecido'
    try:
        import ctypes
        code = ctypes.windll.kernel32.GetDriveTypeW(str(root))
    except Exception:
        return 'Desconhecido'
    return _DRIVE_TYPES.get(code, 'Desconhecido')


def _letter(path):
    drive = ntpath.splitdrive(str(path))[0]
    if len(drive) == 2 and drive[1] == ':' and drive[0].isalpha():
        return drive.upper()
    return None


def _default_roots(warnings):
    if not _on_windows():
        warnings.append('A conferência das unidades só funciona no Windows.')
        return []
    try:
        from deep_discovery import local_drives
        return list(local_drives())
    except Exception:
        warnings.append('Não foi possível listar as unidades deste computador. '
                        'Abra o Explorador de Arquivos e confira as letras você mesmo.')
        return []


def check_drives(manifest, roots=None, usage=shutil.disk_usage, environ=None,
                 drive_type=default_drive_type):
    """Confere as unidades atuais contra as letras dos arquivos do backup.

    Só leitura. Devolve {'drives', 'backup_letters', 'missing', 'windows',
    'warnings', 'guidance'}. Cada unidade: root, letter, type, total, free,
    total_text, free_text, windows (True se for o disco do Windows).
    """
    warnings = []
    windows, windows_warning = windows_drive(environ)
    if windows is None:
        warnings.append(windows_warning)
    if roots is None:
        roots = _default_roots(warnings)
    drives = []
    seen = set()
    for root in roots:
        root = str(root)
        key = os.path.normcase(root)
        if key in seen:
            continue
        seen.add(key)
        letter = _letter(root)
        try:
            total, _used, free = usage(root)[:3]
        except Exception:
            total = free = None
        try:
            kind = drive_type(root)
        except Exception:
            kind = 'Desconhecido'
        drives.append({
            'root': root, 'letter': letter or root, 'type': kind, 'total': total, 'free': free,
            'total_text': human_size(total) if total is not None else 'não deu para ler',
            'free_text': human_size(free) if free is not None else 'não deu para ler',
            'windows': bool(windows) and letter == windows})

    backup_letters = {}
    try:
        for item in verified_entries(manifest).values():
            letter = _letter(item.get('source', ''))
            if letter:
                backup_letters[letter] = backup_letters.get(letter, 0) + 1
    except Exception:
        warnings.append('Não deu para ler as letras de origem do backup escolhido. '
                        'Confira se escolheu o arquivo manifest.json certo.')

    current = {drive['letter'] for drive in drives}
    # sem a lista de unidades não dá para dizer que alguma letra sumiu
    missing = sorted(letter for letter in backup_letters
                     if letter not in current) if drives else []
    guidance = ''
    if missing:
        for letter in missing:
            warnings.append(
                f'Antes, {backup_letters[letter]} arquivo(s) do backup vieram da unidade '
                f'{letter}, e agora não há nenhuma unidade com essa letra. Talvez ela tenha '
                'ganhado outra letra.')
        guidance = CHANGE_LETTER_GUIDE.format(letters=' ou '.join(missing))
    return {'drives': drives, 'backup_letters': backup_letters, 'missing': missing,
            'windows': windows, 'warnings': warnings, 'guidance': guidance}


def password_alert(manifest):
    """Aviso (texto) sobre senhas exportadas sem proteção dentro do backup.

    Mostra só os nomes dos arquivos (sem pastas). Texto vazio se não há nada.
    """
    try:
        found = scan_paths(verified_entries(manifest).keys())
    except Exception:
        return ''
    names = sorted({Path(path).name for path in found}, key=str.casefold)
    if not names:
        return ''
    shown = ', '.join(names[:10]) + (f' e mais {len(names) - 10}' if len(names) > 10 else '')
    return (f'Atenção: o backup tem {len(names)} arquivo(s) que parecem senhas exportadas do '
            f'navegador, sem proteção (qualquer pessoa que abrir consegue ler): {shown}. '
            'Use-os só para importar as senhas no navegador e guarde-os num lugar seguro. '
            'O aplicativo nunca abre esses arquivos.')


# ---------------------------------------------------------------- progresso

def default_base(environ=None):
    environ = os.environ if environ is None else environ
    local = environ.get('LOCALAPPDATA') or str(Path.home() / 'AppData' / 'Local')
    return Path(local) / 'PC-Restore-Optimizer' / 'depois-de-formatar'


IDENTITY_FULL_READ_LIMIT = 8 * 1024 * 1024
IDENTITY_HEAD_LIMIT = 1024 * 1024
_IDENTITY_FIELDS = ('started', 'plan_fingerprint')
_TOP_LEVEL_FIELD = re.compile(r'^  "(started|plan_fingerprint)": ("(?:[^"\\\r\n]|\\.)*")',
                              re.MULTILINE)
NO_IDENTITY_WARNING = (
    'Não deu para identificar este backup pelo arquivo manifest.json. O progresso fica '
    'ligado ao lugar do arquivo e não será achado se a letra da unidade mudar.')


def _identity_fields(manifest):
    """Campos de topo 'started' e 'plan_fingerprint' do manifest.json (só leitura)."""
    with open(manifest, 'rb') as handle:
        size = os.fstat(handle.fileno()).st_size
        if size <= IDENTITY_FULL_READ_LIMIT:
            doc = json.loads(handle.read(IDENTITY_FULL_READ_LIMIT + 1).decode('utf-8'))
            if not isinstance(doc, dict):
                return {}
            return {key: doc.get(key) for key in _IDENTITY_FIELDS}
        # manifesto enorme (muitos arquivos): os campos de topo ficam no começo
        # (gravado por backup_core.atomic_json com indent=2); lê só o primeiro 1 MiB
        head = handle.read(IDENTITY_HEAD_LIMIT).decode('utf-8', errors='replace')
    found = {}
    for match in _TOP_LEVEL_FIELD.finditer(head):
        found.setdefault(match.group(1), json.loads(match.group(2)))
    return found


def backup_identity(manifest):
    """{'folder', 'started', 'plan_fingerprint'} do backup, ou None.

    Não depende da letra da unidade: usa o nome da pasta do backup (em
    minúsculas) e os campos de topo do manifest.json. Só lê.
    """
    manifest = Path(manifest)
    try:
        fields = _identity_fields(manifest)
    except (OSError, ValueError, UnicodeDecodeError):
        return None
    return identity_from(manifest.parent.name, fields)


def identity_from(folder_name, doc):
    """Identidade a partir de um manifesto já lido (dict); None se faltar algo."""
    if not isinstance(doc, dict):
        return None
    started = doc.get('started')
    fingerprint = doc.get('plan_fingerprint')
    folder = str(folder_name).casefold()
    for value in (started, fingerprint):
        if not isinstance(value, str) or not value.strip() or len(value) > 200:
            return None
    if not folder:
        return None
    return {'folder': folder, 'started': started, 'plan_fingerprint': fingerprint}


def _stable_key(identity):
    text = '|'.join(('v2', identity['folder'], identity['started'],
                     identity['plan_fingerprint']))
    return hashlib.sha256(text.encode('utf-8')).hexdigest()[:12]


def _manifest_key(manifest):
    """Chave antiga (P2-11): pelo caminho completo do manifesto."""
    text = os.path.normcase(os.path.abspath(str(manifest)))
    return hashlib.sha256(text.encode('utf-8')).hexdigest()[:12]


def window_key(manifest):
    """Chave para não abrir duas janelas do mesmo backup (igual entre letras)."""
    identity = backup_identity(manifest)
    if identity is not None:
        return 'b-' + _stable_key(identity)
    return 'p-' + os.path.normcase(os.path.abspath(str(manifest)))


def _base(base):
    return default_base() if base is None else Path(base)


def legacy_progress_path(manifest, base=None):
    """Arquivo antigo (P2-11): progresso-<chave do caminho>.json. Só é lido."""
    return _base(base) / f'progresso-{_manifest_key(manifest)}.json'


def progress_path(manifest, base=None, identity=None):
    """Arquivo de progresso deste backup.

    Com identidade: progresso-b-<chave estável>.json (não muda com a letra).
    Sem identidade: o nome antigo, pelo caminho do manifesto.
    """
    if identity is None:
        identity = backup_identity(manifest)
    if identity is None:
        return legacy_progress_path(manifest, base)
    return _base(base) / f'progresso-b-{_stable_key(identity)}.json'


def _candidate(first, number):
    if number == 1:
        return first
    return first.with_name(f'{first.stem}-{number}{first.suffix}')


def _empty_steps():
    return {step: PENDING for step in STEP_IDS}


def validate_steps(steps):
    """Confere as marcações; ValueError se houver etapa ou valor desconhecido."""
    if not isinstance(steps, dict):
        raise ValueError('Progresso inválido.')
    clean = _empty_steps()
    for key, value in steps.items():
        if key not in clean:
            raise ValueError(f'Etapa desconhecida: {key!r}.')
        if value not in STATUSES:
            raise ValueError(f'Marcação inválida: {value!r} (use pendente, feito ou pulado).')
        clean[key] = value
    return clean


def _is_link(info):
    reparse = getattr(stat, 'FILE_ATTRIBUTE_REPARSE_POINT', 0x400)
    return stat.S_ISLNK(info.st_mode) or bool((getattr(info, 'st_file_attributes', 0) or 0) & reparse)


_ANY = object()


def _read(path, identity=_ANY):
    """('ausente', None) | ('ok', passos) | ('ruim', motivo). Nunca altera o arquivo.

    identity: se dado, o bloco 'backup' gravado tem de ser igual a ele.
    """
    try:
        info = os.lstat(path)
    except FileNotFoundError:
        return 'ausente', None
    except OSError:
        return 'ruim', 'não deu para ler'
    if _is_link(info):
        return 'ruim', 'é um atalho (link)'
    if not stat.S_ISREG(info.st_mode):
        return 'ruim', 'não é um arquivo comum'
    if info.st_size > PROGRESS_LIMIT:
        return 'ruim', 'grande demais'
    try:
        with open(path, 'rb') as handle:
            data = handle.read(PROGRESS_LIMIT + 1)
        if len(data) > PROGRESS_LIMIT:
            return 'ruim', 'grande demais'
        doc = json.loads(data.decode('utf-8'))
        if not isinstance(doc, dict) or doc.get('schema') != SCHEMA:
            return 'ruim', 'formato desconhecido'
        steps = validate_steps(doc.get('steps'))
    except (OSError, ValueError, UnicodeDecodeError):
        return 'ruim', 'estragado'
    if identity is not _ANY and doc.get('backup') != identity:
        return 'ruim', 'é de outro backup'
    return 'ok', steps


def _bad_warning(path, reason):
    return (f'O progresso salvo "{path.name}" não pôde ser usado ({reason}). '
            'Ele foi deixado como está e o assistente começou do zero.')


def _scan(first, identity, warnings):
    """Primeiro arquivo bom da sequência first, -2, -3... ou o primeiro livre."""
    for number in range(1, MAX_PROGRESS_FILES + 1):
        path = _candidate(first, number)
        kind, value = _read(path, identity)
        if kind in ('ok', 'ausente'):
            return kind, value, path
        warnings.append(_bad_warning(path, value))
    return 'cheio', None, None


def load_progress(manifest, base=None):
    """Progresso salvo deste backup.

    Devolve {'steps', 'path', 'backup', 'warnings'}. 'path' é onde salvar (None
    se não houver lugar seguro); 'backup' é a identidade a gravar junto.
    Arquivos ruins ou de outro backup ficam intocados e são pulados. Sem
    progresso novo, o arquivo antigo (pelo caminho) é lido só para leitura: o
    próximo save grava no novo, e o antigo nunca é reescrito nem apagado.
    """
    identity = backup_identity(manifest)
    warnings = []
    if identity is None:
        warnings.append(NO_IDENTITY_WARNING)
        kind, value, path = _scan(legacy_progress_path(manifest, base), _ANY, warnings)
    else:
        kind, value, path = _scan(progress_path(manifest, base, identity), identity, warnings)
        if kind == 'ausente':
            old_warnings = []
            old_kind, old_value, _old = _scan(legacy_progress_path(manifest, base), _ANY,
                                              old_warnings)
            if old_kind == 'ok':
                kind, value = 'ok', old_value
    if kind == 'ok':
        return {'steps': value, 'path': path, 'backup': identity, 'warnings': warnings}
    if kind == 'ausente':
        return {'steps': _empty_steps(), 'path': path, 'backup': identity,
                'warnings': warnings}
    warnings.append('Não há onde salvar o progresso; as marcações valem só até fechar a janela.')
    return {'steps': _empty_steps(), 'path': None, 'backup': identity, 'warnings': warnings}


def progress_error_text(exc):
    """Aviso fixo de falha ao salvar o progresso (FIX-P2-11-01).

    Leva no máximo o nome do arquivo (sem pastas) e o nome da classe do erro;
    nunca o caminho completo nem a mensagem do sistema, que podem ter o nome
    de usuário.
    """
    detail = type(exc).__name__
    filename = getattr(exc, 'filename', None)
    if filename:
        name = ntpath.basename(str(filename).replace('/', '\\'))
        if name:
            detail = f'{name}, {detail}'
    return (f'Não deu para salvar o progresso ({detail}). As marcações valem só até '
            'fechar a janela.')


# Espera crescente entre as tentativas de os.replace: 5, 10, 20... até 200 ms
# por vez e cerca de 2 s no total (no Windows, a troca falha enquanto outra
# janela ou um leitor está com o arquivo aberto).
REPLACE_FIRST_WAIT = 0.005
REPLACE_MAX_WAIT = 0.2
REPLACE_TOTAL_WAIT = 2.0


def _replace_with_retry(partial, path, sleep=None):
    sleep = time.sleep if sleep is None else sleep
    wait = REPLACE_FIRST_WAIT
    waited = 0.0
    while True:
        try:
            os.replace(partial, path)
            return
        except PermissionError:
            if waited >= REPLACE_TOTAL_WAIT:
                raise
            step = min(wait, REPLACE_MAX_WAIT, REPLACE_TOTAL_WAIT - waited)
            sleep(step)
            waited += step
            wait *= 2


def save_progress(path, steps, backup=None):
    """Grava as marcações de forma atômica.

    Escreve num .parcial de nome único (<arquivo>.parcial-<8 letras>, criado
    com O_EXCL, nunca por cima de nada), faz fsync e troca com os.replace. Se
    algo falhar, o .parcial fica (nada é apagado). Recusa (OSError) gravar por
    cima de um link ou de algo que não seja um arquivo comum. ValueError se
    alguma marcação for inválida. backup: identidade gravada junto.
    """
    clean = validate_steps(steps)
    path = Path(path)
    try:
        info = os.lstat(path)
    except FileNotFoundError:
        info = None
    if info is not None and (_is_link(info) or not stat.S_ISREG(info.st_mode)):
        raise OSError(f'O arquivo de progresso "{path.name}" não é um arquivo comum; '
                      'nada foi gravado.')
    path.parent.mkdir(parents=True, exist_ok=True)
    doc = {'schema': SCHEMA, 'steps': clean}
    if backup is not None:
        doc['backup'] = backup
    data = json.dumps(doc, ensure_ascii=False, indent=2).encode('utf-8')
    partial = path.with_name(f'{path.name}{PARTIAL_SUFFIX}-{uuid.uuid4().hex[:8]}')
    flags = os.O_CREAT | os.O_EXCL | os.O_WRONLY | getattr(os, 'O_BINARY', 0)
    handle = os.open(partial, flags, 0o600)
    try:
        view = memoryview(data)
        while view:
            view = view[os.write(handle, view):]
        os.fsync(handle)
    finally:
        os.close(handle)
    _replace_with_retry(partial, path)
    return clean


class ProgressSaver:
    """Grava o progresso de um backup fora da thread da interface (FIX-P2-11-03).

    Uma única thread de gravação (não-daemon) por gravador. Ela grava sempre o
    pedido mais recente: pedidos feitos enquanto uma gravação está em curso são
    juntados e só o último é gravado depois. Assim nunca há gravação fora de
    ordem e a última marcação vence. A thread termina quando não há mais nada
    a gravar e volta a ser criada no próximo pedido (nunca há duas ao mesmo
    tempo). Por não ser daemon, sair do aplicativo espera a gravação pendente.

    Nada aqui toca no Tk: a tela lê poll_error() pelo seu próprio timer.
    save(path, steps, backup) é save_progress (trocável nos testes).
    """

    def __init__(self, path, backup=None, *, save=None):
        self.path = Path(path)
        self.backup = backup
        self._save = save
        self._lock = threading.Lock()
        self._idle = threading.Condition(self._lock)
        self._wanted = None    # pedido mais recente ainda não começado
        self._writing = None   # pedido sendo gravado agora
        self._error = None     # texto do último erro, entregue uma vez
        self._thread = None
        self.closed = False

    def request(self, steps):
        """Pede para gravar uma cópia destas marcações. Volta na hora."""
        copy = dict(steps)
        with self._lock:
            self._wanted = copy
            self.closed = False  # a mesma janela (ou a reaberta) voltou a pedir
            if self._thread is None:
                self._thread = threading.Thread(target=self._run, name='pcro-progresso',
                                                daemon=False)
                self._thread.start()

    def _run(self):
        save = self._save if self._save is not None else save_progress
        while True:
            with self._lock:
                steps = self._wanted
                if steps is None:
                    self._writing = None
                    self._thread = None
                    self._idle.notify_all()
                    return
                self._wanted = None
                self._writing = steps
            try:
                save(self.path, steps, self.backup)
                error = None
            except Exception as exc:  # noqa: BLE001 - qualquer falha vira aviso fixo
                error = progress_error_text(exc)
            with self._lock:
                self._writing = None
                if error is not None:
                    self._error = error

    def poll_error(self):
        """Texto do último erro de gravação (sem caminho completo) ou None."""
        with self._lock:
            error, self._error = self._error, None
            return error

    def pending_steps(self):
        """Cópia das marcações pedidas que ainda não foram gravadas, ou None."""
        with self._lock:
            steps = self._wanted if self._wanted is not None else self._writing
            return None if steps is None else dict(steps)

    def busy(self):
        """True enquanto há pedido esperando ou gravação em curso."""
        with self._lock:
            return self._thread is not None

    def close(self):
        """A janela fechou: não virão mais pedidos dela. Não cancela nada."""
        with self._lock:
            self.closed = True

    def join(self, timeout=None):
        """Espera terminar o que foi pedido. True se terminou dentro do tempo."""
        deadline = None if timeout is None else time.monotonic() + timeout
        with self._lock:
            while self._thread is not None:
                left = None if deadline is None else deadline - time.monotonic()
                if left is not None and left <= 0:
                    return False
                self._idle.wait(left)
            return True
