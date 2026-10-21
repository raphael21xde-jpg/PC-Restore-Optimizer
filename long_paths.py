"""P2-03: caminhos longos (LongPathsEnabled), somente leitura.

Sem imports do projeto (igual a elevation_guard), para qualquer tela ou motor
poder usar. Este módulo só LÊ o registro do Windows: abre a chave com
``KEY_READ`` e consulta um valor. Nunca cria chave, nunca grava e nunca apaga
nada. Para ligar a opção, o app apenas mostra o comando; quem roda é a pessoa,
num Terminal de administrador.
"""
from __future__ import annotations

import sys
from pathlib import Path

# O Windows antigo aceita no máximo 260 caracteres contando o fim invisível
# do texto, então 259 caracteres visíveis é o maior caminho seguro.
LIMIT = 259

KEY_PATH = r'SYSTEM\CurrentControlSet\Control\FileSystem'
VALUE_NAME = 'LongPathsEnabled'

ENABLE_COMMAND = ('reg add "HKLM\\SYSTEM\\CurrentControlSet\\Control\\FileSystem" '
                  '/v LongPathsEnabled /t REG_DWORD /d 1 /f')

# Igual a backup_features.new_restore_folder: prefixo + 8 letras/números.
STAGING_PREFIX = 'TESTE-RESTAURACAO-v05-'
STAGING_SUFFIX_LENGTH = 8


def _windows_reader():
    """Lê o valor no registro real (só leitura). Valor ausente → FileNotFoundError."""
    import winreg
    with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, KEY_PATH, 0, winreg.KEY_READ) as key:
        value, kind = winreg.QueryValueEx(key, VALUE_NAME)
    if kind != winreg.REG_DWORD:
        raise TypeError('LongPathsEnabled não é um número (REG_DWORD).')
    return value


def read_long_paths_enabled(reader=None):
    """True (ligado), False (desligado ou ausente) ou None (não deu para ler).

    ``reader`` é injetável nos testes e devolve o valor bruto. Fora do
    Windows, sem leitor, a resposta é None.
    """
    try:
        if reader is None:
            if sys.platform != 'win32':
                return None
            reader = _windows_reader
        value = reader()
    except FileNotFoundError:
        return False
    except Exception:
        return None
    if isinstance(value, bool) or not isinstance(value, int):
        return None
    return value == 1


def count_long(paths, limit=LIMIT):
    """Quantos caminhos têm mais de ``limit`` caracteres."""
    return sum(1 for path in paths if len(str(path)) > limit)


def staging_target_length(destination, relative):
    """Tamanho exato do caminho do arquivo dentro da pasta nova de restauração."""
    folder = Path(destination).resolve() / (STAGING_PREFIX + 'x' * STAGING_SUFFIX_LENGTH)
    return len(str(folder / relative))


def warning_text(count, enabled):
    """Texto do aviso; vazio quando não há caminho longo."""
    if not count:
        return ''
    line = (f'{count} arquivo(s) vão ficar com o caminho mais longo que {LIMIT} '
            'caracteres (pastas dentro de pastas com nomes grandes).')
    if enabled is True:
        return line + (' Os caminhos longos estão ligados neste Windows, então isso '
                       'não deve atrapalhar.')
    situation = ('Os caminhos longos estão desligados neste Windows'
                 if enabled is False else
                 'O app não conseguiu ver se os caminhos longos estão ligados neste Windows')
    return (line + f' {situation}: alguns programas podem não abrir esses arquivos, '
            'ou a cópia deles pode falhar.\n'
            'Para ligar, abra o Terminal como administrador, cole o comando abaixo e '
            'depois reinicie o computador (o app não muda isso sozinho):\n'
            f'{ENABLE_COMMAND}')
