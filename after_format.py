"""P2-11: assistente "Depois de formatar" (parte sem Tk, somente leitura).

Guarda as 5 etapas do assistente, confere as unidades (letras) deste
computador contra as letras de onde vieram os arquivos do backup e salva o
progresso (pendente / feito / pulado) num arquivo pequeno por backup.

Regras de segurança:
- nas unidades, só lê: lista as letras, o tipo e o espaço livre. Nunca troca
  letra, formata, particiona ou apaga nada. A troca de letra é só orientada e
  feita à mão pela pessoa no Gerenciamento de Disco;
- o único arquivo gravado é o do progresso, de forma atômica (.parcial +
  os.replace). Um arquivo de progresso estragado, grande demais ou que seja um
  link fica intocado: o assistente começa do zero num arquivo novo (-2, -3...).
"""
from __future__ import annotations

import hashlib
import json
import ntpath
import os
import shutil
import stat
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


def _manifest_key(manifest):
    text = os.path.normcase(os.path.abspath(str(manifest)))
    return hashlib.sha256(text.encode('utf-8')).hexdigest()[:12]


def progress_path(manifest, base=None):
    """Arquivo de progresso deste backup: progresso-<12 letras do SHA-256>.json."""
    base = default_base() if base is None else Path(base)
    return base / f'progresso-{_manifest_key(manifest)}.json'


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
    return stat.S_ISLNK(info.st_mode) or bool(getattr(info, 'st_file_attributes', 0) & reparse)


def _read(path):
    """('ausente', None) | ('ok', passos) | ('ruim', motivo). Nunca altera o arquivo."""
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
        return 'ok', validate_steps(doc.get('steps'))
    except (OSError, ValueError, UnicodeDecodeError):
        return 'ruim', 'estragado'


def load_progress(manifest, base=None):
    """Progresso salvo deste backup.

    Devolve {'steps', 'path', 'warnings'}. 'path' é onde salvar (None se não
    houver lugar seguro). Arquivos ruins ficam intocados e são pulados.
    """
    first = progress_path(manifest, base)
    warnings = []
    for number in range(1, MAX_PROGRESS_FILES + 1):
        path = _candidate(first, number)
        kind, value = _read(path)
        if kind == 'ok':
            return {'steps': value, 'path': path, 'warnings': warnings}
        if kind == 'ausente':
            return {'steps': _empty_steps(), 'path': path, 'warnings': warnings}
        warnings.append(f'O progresso salvo "{path.name}" não pôde ser usado ({value}). '
                        'Ele foi deixado como está e o assistente começou do zero.')
    warnings.append('Não há onde salvar o progresso; as marcações valem só até fechar a janela.')
    return {'steps': _empty_steps(), 'path': None, 'warnings': warnings}


def save_progress(path, steps):
    """Grava as marcações de forma atômica (.parcial + os.replace).

    Recusa (OSError) gravar por cima de um link ou de algo que não seja um
    arquivo comum. ValueError se alguma marcação for inválida.
    """
    clean = validate_steps(steps)
    path = Path(path)
    partial = path.with_name(path.name + PARTIAL_SUFFIX)
    for target in (path, partial):
        try:
            info = os.lstat(target)
        except FileNotFoundError:
            continue
        if _is_link(info) or not stat.S_ISREG(info.st_mode):
            raise OSError(f'O arquivo de progresso "{target.name}" não é um arquivo comum; '
                          'nada foi gravado.')
    path.parent.mkdir(parents=True, exist_ok=True)
    data = json.dumps({'schema': SCHEMA, 'steps': clean}, ensure_ascii=False, indent=2)
    with open(partial, 'w', encoding='utf-8') as handle:
        handle.write(data)
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(partial, path)
    return clean
