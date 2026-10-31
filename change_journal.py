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
- entradas nunca são apagadas, só mudam de estado;
- P3-03 fatia 2b-2: "Conferir de novo" (``recheck``) só lê e acerta os estados
  numa única gravação; um ``applied`` com valor estranho não vira ``unknown``;
- FIX-P3-03-02: cada instância guarda o SHA-256 do arquivo que leu ou gravou;
  se outra janela do app (ou outro programa) mudou, apagou ou criou o arquivo
  depois disso, a instância recusa tudo e não sobrescreve nada. Uma falha ao
  gravar também deixa a instância recusando tudo até o app ser reaberto;
- se a gravação falha no meio de um lote, o app desfaz pelo adaptador o que já
  tinha aplicado nesse lote (do mais novo ao mais antigo), sem gravar mais nada.
  Limite conhecido: entre a conferência e a troca do arquivo há uma janela de
  milissegundos; o app não tranca o arquivo.
"""
from __future__ import annotations

import copy
import hashlib
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
_NUMBER_RE = re.compile(r'[0-9]{1,9}')
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
MSG_OTHER_WINDOW = ('O diário de alterações foi alterado por outra janela do app; '
                    'feche e abra o app de novo. Nada foi gravado.')
MSG_SAVE_FAILED_BEFORE = ('O diário de alterações não pôde ser gravado da última vez; '
                          'feche e abra o app de novo. Nada foi gravado.')
MSG_BATCH_SAVE_FAILED_NONE = 'Não foi possível gravar o diário; nenhum ajuste foi aplicado.'
MSG_UNDO_NOT_NOTED = ('O ajuste foi desfeito no sistema, mas o diário não pôde ser anotado; '
                      'feche e abra o app de novo.')
MSG_UNDO_UNKNOWN_NOT_NOTED = ('O app tentou desfazer o ajuste no sistema, mas não conseguiu confirmar '
                              'e o diário não pôde ser anotado; confira manualmente e '
                              'feche e abra o app de novo.')
NOTE_UNDO = 'desfazer'
MSG_BATCH_SAVE_FAILED = 'Não foi possível gravar o diário; os ajustes deste lote foram desfeitos.'
MSG_BATCH_SAVE_FAILED_CHECK = ('Não foi possível gravar o diário; confira manualmente: '
                               '{n} ajuste(s) não voltaram ao valor anterior.')


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


def _valid_number(text) -> bool:
    """Só algarismos ASCII (nada de '²' ou '١'), de 1 a 9 casas."""
    return isinstance(text, str) and _NUMBER_RE.fullmatch(text) is not None


def _valid_key(key) -> bool:
    return isinstance(key, str) and bool(_KEY_RE.match(key))


def _valid_entry(entry) -> bool:
    if not isinstance(entry, dict) or set(entry) - set(_ENTRY_FIELDS) - {'note'}:
        return False
    if any(f not in entry for f in _ENTRY_FIELDS):
        return False
    if not all(isinstance(entry[f], str) for f in ('id', 'batch', 'kind', 'created', 'updated')):
        return False
    if not (_valid_number(entry['id']) and _valid_number(entry['batch'])):
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
        self._disk_digest = None   # SHA-256 do arquivo como esta instância o deixou
        self._stale = False        # True: outra janela mudou o diário ou a gravação falhou
        self._stale_message = ''
        self._entries = self._load()

    # ---------- arquivo ----------
    def _load(self):
        if os.path.islink(self._path):
            raise JournalError('O diário de alterações é um atalho (link); por segurança, nada será feito.')
        if not self._path.exists():
            self._disk_digest = None
            return []
        try:
            raw = self._path.read_bytes()
            data = json.loads(raw.decode('utf-8'))
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
        self._disk_digest = hashlib.sha256(raw).hexdigest()
        return entries

    def _current_disk_digest(self):
        """SHA-256 do arquivo agora; None se não existe; '?' se não deu para ler."""
        try:
            return hashlib.sha256(self._path.read_bytes()).hexdigest()
        except FileNotFoundError:
            return None
        except OSError:
            return '?'

    def _mark_stale(self, message):
        if not self._stale:
            self._stale = True
            self._stale_message = message

    def _check_disk_unchanged(self):
        """Recusa se o arquivo não é mais o que esta instância leu ou gravou."""
        if self._stale:
            raise JournalError(self._stale_message)
        if self._current_disk_digest() != self._disk_digest:
            self._mark_stale(MSG_OTHER_WINDOW)
            raise JournalError(MSG_OTHER_WINDOW)

    def _persist(self):
        """Grava; qualquer falha deixa esta instância recusando tudo."""
        try:
            self._save()
        except JournalError:
            self._mark_stale(MSG_SAVE_FAILED_BEFORE)
            raise

    def _save(self):
        if os.path.islink(self._path):
            self._mark_stale(MSG_SAVE_FAILED_BEFORE)
            raise JournalError('O diário de alterações virou um atalho (link); por segurança, nada será gravado.')
        self._check_disk_unchanged()
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
            self._mark_stale(MSG_SAVE_FAILED_BEFORE)
            raise
        except OSError:
            self._discard_tmp(tmp)
            self._mark_stale(MSG_SAVE_FAILED_BEFORE)
            raise JournalError('Não foi possível gravar o diário de alterações.') from None
        self._disk_digest = hashlib.sha256(payload).hexdigest()

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
        self._persist()

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
        numbers = [int(e['id']) for e in self._entries if _valid_number(e['id'])]
        return str(max(numbers, default=0) + 1)

    def _next_batch(self):
        numbers = [int(e['batch']) for e in self._entries if _valid_number(e['batch'])]
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
        """Aplica um lote; devolve a lista de ids. Recusa com ``BatchRefused``.

        Se o diário mudou por fora, recusa com ``JournalError`` antes de criar o
        ponto de restauração ou chamar qualquer adaptador."""
        self._check_disk_unchanged()
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
        touched = []   # itens deste lote em que o adaptador já foi chamado
        try:
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
                self._persist()
                touched.append(entry)
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
        except JournalError:
            # O diário não pôde ser gravado: desfaz pelo adaptador, sem gravar mais nada.
            self._mark_stale(MSG_SAVE_FAILED_BEFORE)
            if not touched:
                raise BatchRefused(MSG_BATCH_SAVE_FAILED_NONE) from None
            not_back = self._rollback(touched, persist=False)
            if not_back:
                raise BatchRefused(MSG_BATCH_SAVE_FAILED_CHECK.format(n=not_back)) from None
            raise BatchRefused(MSG_BATCH_SAVE_FAILED) from None
        return [e['id'] for e in done]

    def _rollback(self, entries, persist=True):
        """Desfaz do mais novo ao mais antigo; devolve quantos não voltaram.

        Com ``persist=False`` só chama o adaptador e não grava o diário."""
        not_back = 0
        for entry in reversed(entries):
            back = self._rollback_one(entry)
            not_back += not back
            if persist:
                self._set(entry, 'failed' if back else 'unknown')
        return not_back

    def undo(self, change_id):
        """Desfaz um item aplicado; devolve (ok, motivo).

        Se o diário mudou por fora, recusa com ``JournalError`` sem chamar o adaptador."""
        self._check_disk_unchanged()
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
        # O adaptador já foi chamado: se a anotação falhar, a mensagem diz o que
        # mudou no sistema e nunca "Nada foi gravado" (R-19).
        if ok and same_value(current, entry['before']):
            try:
                self._set(entry, 'reverted')
            except JournalError:
                raise JournalError(MSG_UNDO_NOT_NOTED) from None
            return True, ''
        if ok and same_value(current, entry['after']):
            return False, 'O ajuste não voltou ao valor anterior; ele continua aplicado.'
        try:
            # P3-03 fatia 2b-2: a nota diz que o "unknown" veio de um desfazer, para o
            # "Conferir de novo" saber que voltar ao valor anterior é "desfeita".
            self._set(entry, 'unknown', note=NOTE_UNDO)
        except JournalError:
            raise JournalError(MSG_UNDO_UNKNOWN_NOT_NOTED) from None
        return False, 'Não foi possível confirmar que o ajuste voltou ao valor anterior; confira manualmente.'

    def undo_all(self):
        """Desfaz do mais novo para o mais antigo; para na primeira falha.

        Devolve (ids desfeitos, ``pending``, motivo). ``pending`` são os ids que
        estavam aplicados e não foram desfeitos agora: o que falhou (primeiro da
        lista) e os mais antigos, que nem foram tentados. Eles continuam no
        estado em que estavam (``applied``, ou ``unknown`` se o próprio desfazer
        não pôde ser confirmado). Se o diário mudou por fora, recusa com
        ``JournalError`` antes de qualquer coisa; se a anotação de um item falhar
        depois de ele ter sido desfeito no sistema, o ``JournalError`` de ``undo``
        sobe com o texto que diz isso (os itens anteriores já ficaram anotados).

        P3-03 fatia 2b-1: um ``JournalError`` no meio do laço sobe com
        ``exc.done`` (ids já desfeitos antes do erro), para a tela nunca dizer
        "Nada foi gravado" depois de algo desfeito. O texto não muda."""
        self._check_disk_unchanged()
        applied = [e['id'] for e in reversed(self._entries) if e['status'] == 'applied']
        done = []
        for change_id in applied:
            try:
                ok, reason = self.undo(change_id)
            except JournalError as exc:
                exc.done = list(done)
                raise
            if not ok:
                pending = [i for i in applied if i not in done]
                return done, pending, reason
            done.append(change_id)
        return done, [], ''

    def recover_interrupted(self):
        """Confere itens ``prepared`` sem aplicar nem desfazer nada.

        Valor atual igual ao anterior vira ``failed`` (o ajuste não chegou a
        valer); igual ao novo vira ``applied``; o resto vira ``unknown``.
        Devolve lista de (id, novo estado)."""
        self._check_disk_unchanged()
        result = []
        for entry in self._entries:
            if entry['status'] != 'prepared':
                continue
            ok, current = self._read(entry) if entry['kind'] in self._adapters else (False, None)
            if ok and same_value(current, entry['before']):
                status = 'failed'
            elif ok and same_value(current, entry['after']):
                status = 'applied'
            else:
                status = 'unknown'
            self._set(entry, status)
            result.append((entry['id'], status))
        return result

    def recheck(self):
        """P3-03 fatia 2b-2: "Conferir de novo". Só lê o valor atual e acerta o diário.

        Nunca chama ``apply``/``revert`` nem cria ponto de restauração; uma leitura
        por item. Só itens ``applied`` e ``unknown`` com adaptador e com valor
        anterior diferente do novo são lidos. Regras (A = antes, N = novo):

        - ``applied``: valor = A vira ``reverted``; = N não muda; outro valor não
          muda e o id vai para ``outside`` (o app não sobrescreve);
        - ``unknown``: valor = N vira ``applied``; = A vira ``reverted`` se veio de
          um desfazer (nota ``desfazer``), senão ``failed``; outro continua ``unknown``;
        - leitura com erro: nada muda e o id vai para ``unreadable``.

        Todas as mudanças vão numa única gravação. Se ela falhar, os estados em
        memória voltam ao que eram e o ``JournalError`` sobe (nada foi gravado).
        Uma exceção no meio da conferência também devolve a memória e sobe.
        Devolve ``{'changed': [(id, antigo, novo)], 'outside': [...], 'unreadable': [...]}``."""
        self._check_disk_unchanged()
        result = {'changed': [], 'outside': [], 'unreadable': []}
        saved = []   # (entrada, cópia de antes) para voltar se a gravação falhar
        # FIX-P3-03-09: qualquer exceção no meio do laço (até KeyboardInterrupt, que
        # ``_read`` não engole) devolve a memória ao que era antes de repassar.
        try:
            for entry in self._entries:
                status = entry['status']
                if status not in ('applied', 'unknown') or entry['kind'] not in self._adapters:
                    continue
                if same_value(entry['before'], entry['after']):
                    continue
                ok, current = self._read(entry)
                if not ok:
                    result['unreadable'].append(entry['id'])
                    continue
                new = None
                if status == 'applied':
                    if same_value(current, entry['before']):
                        new = 'reverted'
                    elif not same_value(current, entry['after']):
                        result['outside'].append(entry['id'])
                elif same_value(current, entry['after']):
                    new = 'applied'
                elif same_value(current, entry['before']):
                    # Na dúvida, "não aplicada" em vez de "desfeita".
                    new = 'reverted' if entry.get('note') == NOTE_UNDO else 'failed'
                if new is None:
                    continue
                saved.append((entry, dict(entry)))
                entry['status'] = new
                entry['updated'] = _now()
                result['changed'].append((entry['id'], status, new))
        except BaseException:
            self._restore_saved(saved)
            raise
        if saved:
            try:
                self._persist()
            except JournalError:
                self._restore_saved(saved)
                raise
        return result

    @staticmethod
    def _restore_saved(saved):
        """Volta cada entrada mudada pelo ``recheck`` à cópia guardada antes."""
        for entry, before in saved:
            entry.clear()
            entry.update(before)

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
