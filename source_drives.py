"""FIX-P4-01-12-01: nome e tamanho das unidades de onde vêm os arquivos do backup.

Só leitura: lê o nome (GetVolumeInformationW) e o tamanho (shutil.disk_usage)
de cada unidade de origem, para o manifesto guardar no campo opcional
'source_drives' ({'D:': {'label': 'Jogos', 'total': <bytes>}}). O
"Conferir discos e letras" (after_format.check_drives) compara esses dados com
os de agora. Nunca grava, formata nem apaga nada em nenhuma unidade.
"""
from __future__ import annotations

import ntpath
import shutil


def source_letter(path):
    """'D:' para um caminho como D:\\Jogos\\x; None para caminho sem letra."""
    drive = ntpath.splitdrive(str(path))[0]
    if len(drive) == 2 and drive[1] == ':' and drive[0].isalpha():
        return drive.upper()
    return None


def read_source_drives(sources, *, volume_label=None, usage=None, letter=source_letter):
    """{'D:': {'label', 'total'}} das unidades de origem; nunca levanta erro.

    Uma unidade só entra se o nome passar pela mesma limpeza da tela
    (after_format._clean_label: até 32 caracteres, sem aspas e sem caractere
    de controle ou invisível; '' é unidade sem nome) e o tamanho for um número
    inteiro maior que zero. Falha ao ler o nome ou o tamanho deixa a unidade
    de fora (o "Conferir discos e letras" cai em "não deu para confirmar").
    O tamanho só é lido depois de o nome ser lido com sucesso (fora do Windows
    o nome não é lido, então nada é lido).
    """
    from after_format import _clean_label, default_volume_label
    volume_label = volume_label or default_volume_label
    usage = usage or shutil.disk_usage
    letters = set()
    try:
        for source in sources:
            try:
                found = letter(source)
            except Exception:
                found = None
            if isinstance(found, str):
                letters.add(found)
    except Exception:
        return {}
    result = {}
    for drive in sorted(letters):
        root = drive + '\\'
        try:
            label = _clean_label(volume_label(root))
        except Exception:
            label = None
        if label is None:
            continue
        try:
            total = usage(root)[0]
        except Exception:
            continue
        if isinstance(total, bool) or not isinstance(total, int) or total <= 0:
            continue
        result[drive] = {'label': label, 'total': total}
    return result
