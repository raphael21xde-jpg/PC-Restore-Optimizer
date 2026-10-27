"""P3-03: diário de alterações da otimização, com desfazer item e desfazer tudo.

Este módulo não muda nada no PC sozinho: quem lê e grava cada ajuste é um
"adaptador" injetado, um por tipo (``kind``), com três métodos:

- ``read(key)`` devolve o valor atual;
- ``apply(key, valor)`` grava o valor novo;
- ``revert(key, valor)`` volta o valor antigo.

O adaptador pode ter ``label`` (texto curto, em português) para os resumos.
O ponto de restauração também é injetado: ``create_restore_point(descricao)``
precisa devolver um valor verdadeiro; falso ou exceção recusa o lote inteiro.

Sem Tk, sem comandos e sem registro: só biblioteca padrão.

Escolhas de design (as mais seguras, registradas em docs/BACKLOG.md):
- sem ponto de restauração o lote é recusado e nada é aplicado;
- desfazer só acontece se o valor atual for o que o app gravou;
- "desfazer tudo" para na primeira falha;
- item pendente (``prepared``) ou desconhecido (``unknown``) bloqueia lotes novos;
- diário ilegível, de schema errado ou que seja link bloqueia tudo;
- só valores simples (texto, número, sim/não, vazio), sem caminhos;
- entradas nunca são apagadas, só mudam de estado.
"""
from __future__ import annotations

import copy
import json
import math
import os
import re
import uuid
from datetime import datetime, timezone
from pathlib import Path

SCHEMA = 'pcro-journal-1'
STATUSES = ('prepared', 'applied', 'failed', 'reverted', 'unknown')
BLOCKING = ('prepared', 'unknown')
MAX_TEXT = 200
MAX_BATCH = 100

_KEY_RE = re.compile(r'^[A-Za-z0-9][A-Za-z0-9_.\-]{0,79}$')
_DRIVE_RE = re.compile(r'^[A-Za-z]:')
_ENTRY_FIELDS = ('id', 'batch', 'kind', 'key', 'before', 'after', 'status', 'created', 'updated')

STATUS_TEXT = {
    'prepared': 'interrompida (o app vai conferir)',
    'applied': 'aplicada',
    'failed': 'não aplicada (voltou ao valor anterior)',
    'reverted': 'desfeita',
    'unknown': 'estado desconhecido (confira manualmente)',
}

MSG_CHANGED_OUTSIDE = ('O valor foi mudado por outro programa depois do ajuste; '
                       'o app não vai sobrescrever.')


class JournalError(Exception):
    """O diário não pode ser usado (ilegível, schema errado, link ou falha ao gravar)."""


class BatchRefused(Exception):
    """O lote foi recusado; o texto explica o motivo em português."""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec='seconds')


def _looks_like_path(text: str) -> bool:
    return ('\\' in text or '/' in text or '%' in text or text.startswith('~')
            or bool(_DRIVE_RE.match(text)))


def is_simple_value(value) -> bool:
    """Texto curto sem caminho, número finito, sim/não ou vazio."""
    if value is None or isinstance(value, bool):
        return True
    if isinstance(value, int):
        return True
    if isinstance(value, float):
        return math.isfinite(value)
    if isinstance(value, str):
        return len(value) <= MAX_TEXT and not _looks_like_path(value)
    return False


def same_value(a, b) -> bool:
    """Igualdade estrita: ``True`` não é igual a ``1``."""
    return type(a) is type(b) and a == b


def _valid_key(key) -> bool:
    return isinstance(key, str) and bool(_KEY_RE.match(key))


def _valid_entry(entry) -> bool:
    if not isinstance(entry, dict) or set(entry) - set(_ENTRY_FIELDS) - {'note'}:
        return False
    if any(f not in entry for f in _ENTRY_FIELDS):
        return False
    if not all(isinstance(entry[f], str) for f in ('id', 'batch', 'kind', 'created', 'updated')):
        return False
    if entry['status'] not in STATUSES or not _valid_key(entry['key']):
        return False
    if not _valid_key(entry['kind']):
        return False
    if not (is_simple_value(entry['before']) and is_simple_value(entry['after'])):
        return False
    note = entry.get('note', '')
    return isinstance(note, str) and not _looks_like_path(note)


class ChangeJournal:
    def __init__(self, path, adapters, create_restore_point):
        self._path = Path(path)
        if not isinstance(adapters, dict) or not adapters:
            raise JournalError('Nenhum tipo de ajuste foi registrado no diário.')
        for kind, adapter in adapters.items():
            if not _valid_key(kind) or not all(
                    callable(getattr(adapter, m, None)) for m in ('read', 'apply', 'revert')):
                raise JournalError('Um tipo de ajuste do diário está incompleto.')
        if not callable(create_restore_point):
            raise JournalError('Falta a função que cria o ponto de restauração.')
        self._adapters = dict(adapters)
        self._restore_point = create_restore_point
        self._entries = self._load()

    # ---------- arquivo ----------
    def _load(self):
        if os.path.islink(self._path):
            raise JournalError('O diário de alterações é um atalho (link); por segurança, nada será feito.')
        if not self._path.exists():
            return []
        try:
            data = json.loads(self._path.read_text(encoding='utf-8'))
        except (OSError, UnicodeDecodeError, ValueError):
            raise JournalError('O diário de alterações está ilegível; por segurança, nada será feito.') from None
        if not isinstance(data, dict) or data.get('schema') != SCHEMA:
            raise JournalError('O diário de alterações é de outro formato; por segurança, nada será feito.')
        entries = data.get('entries')
        if not isinstance(entries, list) or not all(_valid_entry(e) for e in entries):
            raise JournalError('O diário de alterações está ilegível; por segurança, nada será feito.')
        ids = [e['id'] for e in entries]
        if len(set(ids)) != len(ids):
            raise JournalError('O diário de alterações está ilegível; por segurança, nada será feito.')
        return entries

    def _save(self):
        if os.path.islink(self._path):
            raise JournalError('O diário de alterações virou um atalho (link); por segurança, nada será gravado.')
        payload = json.dumps({'schema': SCHEMA, 'entries': self._entries},
                             ensure_ascii=False, indent=2).encode('utf-8')
        tmp = self._path.with_name(f'.{self._path.name}.{uuid.uuid4().hex}.tmp')
        flags = os.O_CREAT | os.O_EXCL | os.O_WRONLY | getattr(os, 'O_BINARY', 0)
        try:
            fd = os.open(tmp, flags, 0o600)
        except OSError:
            raise JournalError('Não foi possível gravar o diário de alterações.') from None
        try:
            try:
                os.write(fd, payload)
                os.fsync(fd)
            finally:
                os.close(fd)
            if os.path.islink(self._path):
                raise JournalError('O diário de alterações virou um atalho (link); por segurança, nada será gravado.')
            os.replace(tmp, self._path)
        except JournalError:
            self._discard_tmp(tmp)
            raise
        except OSError:
            self._discard_tmp(tmp)
            raise JournalError('Não foi possível gravar o diário de alterações.') from None

    @staticmethod
    def _discard_tmp(tmp):
        # Só o arquivo temporário criado agora por este app (O_EXCL), nunca dados do usuário.
        try:
            os.unlink(tmp)
        except OSError:
            pass

    # ---------- ajuda ----------
    def _set(self, entry, status, note=''):
        entry['status'] = status
        entry['updated'] = _now()
        if note:
            entry['note'] = note
        self._save()

    def _find(self, change_id):
        for entry in self._entries:
            if entry['id'] == change_id:
                return entry
        return None

    def _read(self, entry):
        """Lê o valor atual; devolve (ok, valor)."""
        try:
            return True, self._adapters[entry['kind']].read(entry['key'])
        except Exception:  # adaptador falso ou real: qualquer falha vira "não confirmado"
            return False, None

    def _next_id(self):
        numbers = [int(e['id']) for e in self._entries if e['id'].isdigit()]
        return str(max(numbers, default=0) + 1)

    def _next_batch(self):
        numbers = [int(e['batch']) for e in self._entries if e['batch'].isdigit()]
        return str(max(numbers, default=0) + 1)

    def _check_batch(self, changes):
        if any(e['status'] in BLOCKING for e in self._entries):
            raise BatchRefused('Há uma alteração interrompida ou sem confirmação. '
                               'Confira as alterações antes de aplicar outras.')
        if not isinstance(changes, list) or not changes or len(changes) > MAX_BATCH:
            raise BatchRefused('Lista de ajustes inválida.')
        seen = set()
        for change in changes:
            if not isinstance(change, dict) or set(change) != {'kind', 'key', 'after'}:
                raise BatchRefused('Um ajuste da lista está incompleto.')
            if change['kind'] not in self._adapters:
                raise BatchRefused('Um ajuste da lista não é conhecido pelo app.')
            if not _valid_key(change['key']):
                raise BatchRefused('Um ajuste da lista tem um nome inválido.')
            if not is_simple_value(change['after']):
                raise BatchRefused('Um ajuste da lista tem um valor que o app não aceita.')
            ident = (change['kind'], change['key'])
            if ident in seen:
                raise BatchRefused('O mesmo ajuste aparece duas vezes na lista.')
            seen.add(ident)

    def _rollback_one(self, entry):
        """Volta um item deste lote ao valor anterior; devolve True se confirmado."""
        ok, current = self._read(entry)
        if ok and same_value(current, entry['before']):
            return True
        try:
            self._adapters[entry['kind']].revert(entry['key'], entry['before'])
        except Exception:
            return False
        ok, current = self._read(entry)
        return ok and same_value(current, entry['before'])

    # ---------- API ----------
    def apply_batch(self, changes):
        """Aplica um lote; devolve a lista de ids. Recusa com ``BatchRefused``."""
        self._check_batch(changes)
        if os.path.islink(self._path):
            raise JournalError('O diário de alterações virou um atalho (link); por segurança, nada será feito.')
        try:
            created = self._restore_point(f'PC Restore & Optimizer: {len(changes)} ajuste(s)')
        except Exception:
            created = False
        if not created:
            raise BatchRefused('Não foi possível criar o ponto de restauração; nenhum ajuste foi aplicado.')

        batch = self._next_batch()
        done = []
        for change in changes:
            entry = {'id': self._next_id(), 'batch': batch, 'kind': change['kind'],
                     'key': change['key'], 'before': None, 'after': change['after'],
                     'status': 'prepared', 'created': _now(), 'updated': _now()}
            ok, before = self._read(entry)
            if not ok or not is_simple_value(before):
                self._rollback(done)
                raise BatchRefused('Não foi possível ler o valor atual de um ajuste; '
                                   'os ajustes deste lote foram desfeitos.')
            entry['before'] = before
            self._entries.append(entry)
            self._save()
            try:
                self._adapters[entry['kind']].apply(entry['key'], entry['after'])
                applied_ok = True
            except Exception:
                applied_ok = False
            if applied_ok:
                ok, current = self._read(entry)
                applied_ok = ok and same_value(current, entry['after'])
            if not applied_ok:
                if self._rollback_one(entry):
                    self._set(entry, 'failed')
                else:
                    self._set(entry, 'unknown')
                self._rollback(done)
                raise BatchRefused('Um ajuste não foi confirmado; os ajustes deste lote foram desfeitos.')
            self._set(entry, 'applied')
            done.append(entry)
        return [e['id'] for e in done]

    def _rollback(self, done):
        for entry in reversed(done):
            if self._rollback_one(entry):
                self._set(entry, 'failed')
            else:
                self._set(entry, 'unknown')

    def undo(self, change_id):
        """Desfaz um item aplicado; devolve (ok, motivo)."""
        entry = self._find(change_id)
        if entry is None:
            return False, 'Essa alteração não está no diário.'
        if entry['status'] != 'applied':
            return False, 'Essa alteração não está aplicada; não há o que desfazer.'
        if entry['kind'] not in self._adapters:
            return False, 'O app não sabe mais desfazer esse tipo de ajuste.'
        ok, current = self._read(entry)
        if not ok:
            return False, 'Não foi possível ler o valor atual; nada foi desfeito.'
        if not same_value(current, entry['after']):
            return False, MSG_CHANGED_OUTSIDE
        try:
            self._adapters[entry['kind']].revert(entry['key'], entry['before'])
        except Exception:
            pass
        ok, current = self._read(entry)
        if ok and same_value(current, entry['before']):
            self._set(entry, 'reverted')
            return True, ''
        if ok and same_value(current, entry['after']):
            return False, 'O ajuste não voltou ao valor anterior; ele continua aplicado.'
        self._set(entry, 'unknown')
        return False, 'Não foi possível confirmar que o ajuste voltou ao valor anterior; confira manualmente.'

    def undo_all(self):
        """Desfaz do mais novo para o mais antigo; para na primeira falha.

        Devolve (ids desfeitos, ids que continuam aplicados, motivo)."""
        applied = [e['id'] for e in reversed(self._entries) if e['status'] == 'applied']
        done = []
        for change_id in applied:
            ok, reason = self.undo(change_id)
            if not ok:
                pending = [i for i in applied if i not in done]
                return done, pending, reason
            done.append(change_id)
        return done, [], ''

    def recover_interrupted(self):
        """Confere itens ``prepared`` sem aplicar nem desfazer nada.

        Devolve lista de (id, novo estado)."""
        result = []
        for entry in self._entries:
            if entry['status'] != 'prepared':
                continue
            ok, current = self._read(entry) if entry['kind'] in self._adapters else (False, None)
            if ok and same_value(current, entry['before']):
                status = 'reverted'
            elif ok and same_value(current, entry['after']):
                status = 'applied'
            else:
                status = 'unknown'
            self._set(entry, status)
            result.append((entry['id'], status))
        return result

    def entries(self):
        return copy.deepcopy(self._entries)

    def has_blocking(self):
        return any(e['status'] in BLOCKING for e in self._entries)

    def summary_lines(self):
        if not self._entries:
            return ['Nenhuma alteração registrada.']
        lines = []
        for number, entry in enumerate(self._entries, 1):
            adapter = self._adapters.get(entry['kind'])
            label = getattr(adapter, 'label', None)
            if not isinstance(label, str) or not label or _looks_like_path(label):
                label = 'ajuste'
            lines.append(f'{number}. {label}: {STATUS_TEXT[entry["status"]]}.')
        applied = sum(e['status'] == 'applied' for e in self._entries)
        lines.append(f'Alterações aplicadas agora: {applied}.')
        return lines
