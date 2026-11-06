"""P3-05: ajustes avançados (com confirmação), lista fechada, só na conta do usuário.

Fatia 1: um ajuste só, "Aceleração do mouse desligada" (a opção "Aumentar
precisão do ponteiro" do Painel de Controle). São três valores de texto
(REG_SZ) na mesma chave de HKEY_CURRENT_USER, aplicados e desfeitos juntos:

- ``MouseSpeed``: "1" -> "0";
- ``MouseThreshold1``: "6" -> "0";
- ``MouseThreshold2``: "10" -> "0".

Vale depois de sair da conta do Windows e entrar de novo. O app só grava
esses três valores: não roda comando nenhum e não avisa o Windows na hora.

``AdvancedRegistryAdapter`` é o adaptador do diário de alterações
(``change_journal``), com o tipo ``ADVANCED_KIND``. O diário guarda um valor
por chave, então os três textos vão juntos num texto só, separados por ``;``
(por exemplo ``"1;6;10"``); um valor que não existia fica vazio (``"1;;"``).

- ``read(chave)`` devolve esse texto juntado;
- ``apply(chave, valor)`` só aceita o valor da lista (``"0;0;0"``);
- ``revert(chave, valor)`` volta os três textos antigos; o que não existia
  antes é apagado (só o valor, nunca a chave).

Cada valor só pode ser um texto de 1 a 3 algarismos (0 a 9). Valor de outro
tipo (número DWORD, binário, texto expansível) ou texto fora desse padrão faz
o adaptador recusar sem gravar nada ("o app não mexe"). Se a gravação de um
dos três falhar, o adaptador volta os que já tinha gravado antes de avisar.
O módulo ``winreg`` é injetável (os testes usam um registro falso em memória)
e só é importado na hora de ler ou gravar.
"""
from __future__ import annotations

import os
import re
from dataclasses import dataclass

ADVANCED_KIND = 'hkcu_sz_advanced'
SEPARATOR = ';'
_TEXT_RE = re.compile(r'[0-9]{1,3}')
# O mesmo texto de optimization_ui.CHANGES_TAB_LABEL (o teste da tela confere).
CHANGES_TAB_NAME = '7  Alterações feitas'

MSG_UNKNOWN_KEY = 'Ajuste desconhecido pelo app; nada foi alterado.'
MSG_BAD_VALUE = 'Valor que o app não aceita para este ajuste; nada foi alterado.'
MSG_NOT_TEXT = ('O valor no Windows é de outro tipo ou está num formato diferente; por '
                'segurança, o app não mexe neste ajuste. Nada foi alterado.')
MSG_WRITE_FAILED = ('O Windows não aceitou gravar um dos valores; o app voltou os que já '
                    'tinha gravado.')
MSG_NOT_WINDOWS = 'Este recurso só funciona em computadores Windows.'
MEASURE_BEFORE_HINT = 'Para comparar, meça ANTES na aba 1 antes de aplicar.'


class AdvancedTweakError(RuntimeError):
    """O ajuste foi recusado ou não pôde ser gravado."""


class NotTextError(AdvancedTweakError):
    """Um dos valores existe, mas não é texto de 1 a 3 algarismos: o app não mexe."""


@dataclass(frozen=True)
class AdvancedValue:
    key: str        # nome no diário (só letras, números e _)
    path: str       # subchave dentro de HKEY_CURRENT_USER
    names: tuple    # nomes dos valores, gravados e desfeitos juntos
    desired: tuple  # texto que o ajuste grava em cada um
    label: str      # nome curto para a aba "Alterações feitas"


@dataclass(frozen=True)
class AdvancedTweak:
    id: str
    name: str       # nome em português simples
    what: str       # o que muda
    downside: str   # o lado ruim (aparece na pergunta)
    when: str       # quando passa a valer
    values: tuple


ADVANCED_TWEAKS = (
    AdvancedTweak(
        id='mouse_precision',
        name='Aceleração do mouse desligada',
        what=('Desliga a opção "Aumentar precisão do ponteiro" do Windows. O ponteiro passa a '
              'andar sempre a mesma distância para o mesmo movimento da mão, seja o movimento '
              'rápido ou devagar. Muita gente prefere assim em jogos de mira. É a mesma opção '
              'do Painel de Controle, em Mouse, aba "Opções de ponteiro".'),
        downside=('No começo o ponteiro pode parecer mais lento ou mais difícil de controlar, '
                  'principalmente com telas grandes, e pode ser preciso acertar de novo a '
                  'velocidade do ponteiro ou a sensibilidade do mouse. Vale só para a sua conta.'),
        when=('Vale depois de sair da sua conta do Windows e entrar de novo (ou reiniciar o '
              'computador). O desfazer também.'),
        values=(AdvancedValue('mouse_precision', r'Control Panel\Mouse',
                              ('MouseSpeed', 'MouseThreshold1', 'MouseThreshold2'),
                              ('0', '0', '0'), 'Aceleração do mouse'),),
    ),
)
TWEAKS_BY_ID = {tweak.id: tweak for tweak in ADVANCED_TWEAKS}
TWEAK_VALUES = {value.key: value for tweak in ADVANCED_TWEAKS for value in tweak.values}

STATE_TEXT = {
    'applied': 'já aplicado.',
    'not_applied': 'ainda não aplicado.',
    'other_type': ('o app não mexe (o valor no Windows é de outro tipo ou está num '
                   'formato diferente).'),
    'unreadable': 'Não foi possível ler o estado atual; o app não mexe.',
}


def _is_windows() -> bool:
    """Único ponto que confere o sistema; os testes trocam esta função."""
    return os.name == 'nt'


def _is_text(value) -> bool:
    """Texto de 1 a 3 algarismos ASCII (nada de '²' ou '١')."""
    return isinstance(value, str) and _TEXT_RE.fullmatch(value) is not None


def joined(texts) -> str:
    """Os textos de cada valor num texto só para o diário; ``None`` (ausente) fica vazio."""
    return SEPARATOR.join('' if text is None else text for text in texts)


def _split(value, count):
    """Texto juntado -> lista com um texto ou ``None`` por valor; recusa o resto."""
    if not isinstance(value, str):
        raise AdvancedTweakError(MSG_BAD_VALUE)
    parts = value.split(SEPARATOR)
    if len(parts) != count:
        raise AdvancedTweakError(MSG_BAD_VALUE)
    texts = []
    for part in parts:
        if part == '':
            texts.append(None)
        elif _is_text(part):
            texts.append(part)
        else:
            raise AdvancedTweakError(MSG_BAD_VALUE)
    return texts


class AdvancedRegistryAdapter:
    """Adaptador do diário para ``ADVANCED_TWEAKS`` (só HKCU, só texto de 1 a 3 algarismos)."""

    kind = ADVANCED_KIND
    label = 'Ajuste avançado do Windows'

    def __init__(self, registry=None):
        self._registry = registry

    def _reg(self):
        if self._registry is not None:
            return self._registry
        if not _is_windows():
            raise AdvancedTweakError(MSG_NOT_WINDOWS)
        import winreg  # só existe no Windows; importado só na hora de usar
        return winreg

    @staticmethod
    def _target(key):
        if not isinstance(key, str) or key not in TWEAK_VALUES:
            raise AdvancedTweakError(MSG_UNKNOWN_KEY)
        return TWEAK_VALUES[key]

    def label_for(self, key):
        target = TWEAK_VALUES.get(key) if isinstance(key, str) else None
        return target.label if target is not None else self.label

    @staticmethod
    def _query(reg, handle, name):
        """Texto atual ou ``None`` (não existe); outro tipo ou formato = NotTextError."""
        try:
            value, value_type = reg.QueryValueEx(handle, name)
        except FileNotFoundError:
            return None
        if value_type != reg.REG_SZ or not _is_text(value):
            raise NotTextError(MSG_NOT_TEXT)
        return value

    def _query_all(self, reg, handle, target):
        return [self._query(reg, handle, name) for name in target.names]

    def read(self, key):
        target = self._target(key)
        reg = self._reg()
        try:
            handle = reg.OpenKey(reg.HKEY_CURRENT_USER, target.path, 0, reg.KEY_READ)
        except FileNotFoundError:
            return joined([None] * len(target.names))
        with handle:
            return joined(self._query_all(reg, handle, target))

    @staticmethod
    def _put(reg, handle, name, text):
        """Grava um texto, ou apaga só o valor quando ``text`` é ``None``."""
        if text is not None:
            reg.SetValueEx(handle, name, 0, reg.REG_SZ, text)
            return
        try:
            reg.DeleteValue(handle, name)
        except FileNotFoundError:
            pass

    def _write_all(self, target, texts):
        """Grava os valores juntos; se um falhar, volta os anteriores e recusa."""
        reg = self._reg()
        access = reg.KEY_READ | reg.KEY_SET_VALUE
        if all(text is None for text in texts):
            # Só apagar: a chave que não existe não é criada.
            try:
                handle = reg.OpenKey(reg.HKEY_CURRENT_USER, target.path, 0, access)
            except FileNotFoundError:
                return
        else:
            handle = reg.CreateKeyEx(reg.HKEY_CURRENT_USER, target.path, 0, access)
        with handle:
            old = self._query_all(reg, handle, target)   # outro tipo: recusa antes de gravar
            done = []
            for name, text, previous in zip(target.names, texts, old):
                if text == previous:
                    continue
                done.append((name, previous))
                try:
                    self._put(reg, handle, name, text)
                except Exception:
                    for back_name, back_text in reversed(done):
                        try:
                            self._put(reg, handle, back_name, back_text)
                        except Exception:  # o diário confere depois e marca o estado
                            pass
                    raise AdvancedTweakError(MSG_WRITE_FAILED) from None

    def apply(self, key, value):
        target = self._target(key)
        if not isinstance(value, str) or value != joined(target.desired):
            raise AdvancedTweakError(MSG_BAD_VALUE)
        self._write_all(target, list(target.desired))

    def revert(self, key, value):
        target = self._target(key)
        self._write_all(target, _split(value, len(target.names)))


def read_states(adapter):
    """Só lê. Para cada ajuste: ``id``, ``state`` e ``changes`` (o que falta).

    ``state``: ``applied``, ``not_applied``, ``other_type`` ou ``unreadable``.
    Nos dois últimos, ``changes`` fica vazio (o app não mexe)."""
    states = []
    for tweak in ADVANCED_TWEAKS:
        state = 'applied'
        changes = []
        for value in tweak.values:
            desired = joined(value.desired)
            try:
                current = adapter.read(value.key)
            except NotTextError:
                state = 'other_type'
                break
            except Exception:  # permissão, sistema, adaptador: "não foi possível ler"
                state = 'unreadable'
                break
            if current != desired:
                changes.append({'kind': ADVANCED_KIND, 'key': value.key, 'after': desired})
        if state == 'applied' and changes:
            state = 'not_applied'
        if state in ('other_type', 'unreadable'):
            changes = []
        states.append({'id': tweak.id, 'state': state, 'changes': changes})
    return states


def state_for(states, tweak_id):
    for item in states or ():
        if item.get('id') == tweak_id:
            return item
    return None


def state_lines(states):
    lines = ['ESTADO ATUAL (lido agora, sem mudar nada)']
    for item in states:
        tweak = TWEAKS_BY_ID.get(item.get('id'))
        if tweak is None:
            continue
        lines.append(f'• {tweak.name}: {STATE_TEXT.get(item.get("state"), STATE_TEXT["unreadable"])}')
    return lines


def intro_lines():
    lines = ['AJUSTES AVANÇADOS (só na sua conta do Windows; cada um tem um lado ruim)', '']
    for tweak in ADVANCED_TWEAKS:
        lines += [f'• {tweak.name}', f'  O que muda: {tweak.what}',
                  f'  Lado ruim: {tweak.downside}', f'  {tweak.when}']
    return lines


def confirmation_text(tweak):
    return (f'Aplicar o ajuste avançado "{tweak.name}" na sua conta do Windows?\n\n'
            f'O que muda: {tweak.what}\n\n'
            f'Lado ruim: {tweak.downside}\n\n'
            f'Quando vale: {tweak.when}\n\n'
            'Antes, o app cria um ponto de restauração do Windows e anota tudo no diário de '
            'alterações. Para voltar, use "Desfazer tudo" na aba "' + CHANGES_TAB_NAME + '".\n\n'
            + MEASURE_BEFORE_HINT)
