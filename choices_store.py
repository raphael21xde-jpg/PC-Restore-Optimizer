"""Junção das escolhas de duas janelas ao salvar (FIX-P3-06-09).

Antes, `_save_choices` gravava o estado inteiro da janela por cima do arquivo:
com duas janelas abertas, a última apagava as escolhas da outra. Aqui a
gravação relê o arquivo dentro de uma trava e faz uma junção em 3 vias: só
entra o que ESTA janela mudou em relação à sua base (o que ela leu ou salvou
por último); o resto fica como está no disco.

Módulo sem Tk e sem imports do app (só `atomic_write`). Nunca apaga arquivo
nenhum, nunca grava por cima de um arquivo que não conseguiu ler e nunca apaga
a trava de outra janela.
"""
from __future__ import annotations

import copy
import json
from pathlib import Path

from atomic_write import atomic_write_text, exclusive_lock

# Mapas de decisão: em conflito vence a opção mais segura (nada deixa de ser
# preservado sem revisão). Ausente (removido) nunca vence um valor.
DECISION_MAPS = ('choices', 'catalog_choices')
_DECISION_RANK = {'keep': 3, 'pending': 2, 'skip': 1}

# Outros mapas: por chave; remoção nunca vence valor; dois valores → o desta janela.
PLAIN_MAPS = ('approved_catalog_paths', 'browser_vaults', 'retained_discoveries',
              'catalog_snapshots')

# Listas (conjuntos): o que esta janela acrescentou entra, o que tirou sai.
SET_LISTS = ('personal_paths', 'browser_keep_paths', 'auto_save_paths', 'cleanup_candidates')

_MISSING = object()


def _as_dict(value) -> dict:
    return value if isinstance(value, dict) else {}


def _as_items(value) -> list:
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, (str, int, float, bool))]


def _decision_rank(value) -> int:
    if value is _MISSING:
        return -1
    return _DECISION_RANK.get(value, 0) if isinstance(value, str) else 0


def _merge_map(name, base, mine, disk, conflicts, decision):
    base, mine, disk = _as_dict(base), _as_dict(mine), _as_dict(disk)
    merged = dict(disk)
    for key in set(base) | set(mine):
        b = base.get(key, _MISSING)
        m = mine.get(key, _MISSING)
        if m == b:
            continue  # esta janela não mexeu: fica o que está no disco
        d = disk.get(key, _MISSING)
        if d == b or d == m:
            winner = m  # só esta janela mudou (ou as duas mudaram igual)
        else:
            conflicts.append((name, key))
            if m is _MISSING:
                winner = d
            elif d is _MISSING:
                winner = m
            elif decision and _decision_rank(d) > _decision_rank(m):
                winner = d
            else:
                winner = m
        if winner is _MISSING:
            merged.pop(key, None)
        else:
            merged[key] = winner
    return merged


def _merge_set(base, mine, disk):
    base_items, mine_items = _as_items(base), _as_items(mine)
    added = [item for item in mine_items if item not in base_items]
    removed = [item for item in base_items if item not in mine_items]
    result = [item for item in _as_items(disk) if item not in removed]
    for item in added:
        if item not in result:
            result.append(item)
    try:
        return sorted(result)
    except TypeError:
        return result


def merge_choices(base, mine, disk):
    """Junção em 3 vias. Devolve `(merged, conflitos)`.

    `conflitos` é a lista `(seção, chave)` dos itens que as duas janelas
    mudaram de jeitos diferentes. Nenhum argumento é alterado.
    """
    base = copy.deepcopy(_as_dict(base))
    mine = copy.deepcopy(_as_dict(mine))
    merged = copy.deepcopy(_as_dict(disk))  # chaves desconhecidas ficam
    conflicts: list = []
    for name in DECISION_MAPS:
        if name in mine or name in base:
            merged[name] = _merge_map(name, base.get(name), mine.get(name),
                                      merged.get(name), conflicts, decision=True)
    for name in PLAIN_MAPS:
        if name in mine or name in base:
            merged[name] = _merge_map(name, base.get(name), mine.get(name),
                                      merged.get(name), conflicts, decision=False)
    for name in SET_LISTS:
        if name in mine or name in base:
            merged[name] = _merge_set(base.get(name), mine.get(name), merged.get(name))
    if 'destination' in mine:
        if mine.get('destination') != base.get('destination', _MISSING) or 'destination' not in merged:
            merged['destination'] = mine['destination']
    if 'format_disks' in mine:
        merged['format_disks'] = mine['format_disks']  # como antes: valor desta janela
    return merged, conflicts


def decision_conflicts(conflicts) -> list:
    """Só os conflitos em decisões do usuário (`choices` e `catalog_choices`).

    Função pura: serve para o aviso contar só o que o usuário decidiu (Manter /
    Não preservar), e não fotos do catálogo ou cofres de navegador.
    """
    if not isinstance(conflicts, (list, tuple)):
        return []
    return [item for item in conflicts
            if isinstance(item, tuple) and len(item) == 2 and item[0] in DECISION_MAPS]


def _read_disk(path: Path):
    """Devolve ('ausente', None), ('ok', dict) ou ('ilegivel', None)."""
    if path.is_symlink():
        return 'ilegivel', None
    try:
        text = path.read_text(encoding='utf-8')
    except FileNotFoundError:
        return 'ausente', None
    except (OSError, UnicodeError):
        return 'ilegivel', None
    try:
        data = json.loads(text)
    except ValueError:
        return 'ilegivel', None
    if not isinstance(data, dict):
        return 'ilegivel', None
    return 'ok', data


def save_merged(path, mine, base, *, lock_timeout: float = 0):
    """Relê, junta e grava as escolhas, tudo dentro da trava do arquivo.

    Devolve `(status, merged, conflitos)`:
    - 'ok': gravou (`merged` é o que ficou no arquivo);
    - 'ocupado': outra janela está gravando; nada foi gravado;
    - 'ilegivel': o arquivo existe mas não deu para ler (JSON estragado, não é
      um objeto, ou é um link); nada foi gravado por cima.
    Erros de gravação (OSError) sobem para quem chamou.
    """
    path = Path(path)
    mine = json.loads(json.dumps(mine))
    base = json.loads(json.dumps(base)) if isinstance(base, dict) else {}
    try:
        with exclusive_lock(path, timeout=lock_timeout):
            state, disk = _read_disk(path)
            if state == 'ilegivel':
                return 'ilegivel', None, []
            if state == 'ausente':
                merged, conflicts = mine, []
            else:
                merged, conflicts = merge_choices(base, mine, disk)
            atomic_write_text(path, json.dumps(merged, indent=2))
            return 'ok', merged, conflicts
    except TimeoutError:
        return 'ocupado', None, []
