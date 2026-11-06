"""P3-05: ajustes avançados (com confirmação), lista fechada.

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

Fatia 2: 2º ajuste, "Agendamento de GPU acelerado por hardware ligado" (a
opção de Configurações > Sistema > Tela > Elementos gráficos). É um número
(REG_DWORD) em HKEY_LOCAL_MACHINE, então vale para o computador inteiro (todas
as contas) e só depois de reiniciar:

- ``SYSTEM\\CurrentControlSet\\Control\\GraphicsDrivers``, valor ``HwSchMode``: 1 -> 2.

``MachineDwordAdapter`` é o adaptador do diário para este tipo
(``MACHINE_KIND``), separado do adaptador do mouse. Sentido único: só liga
(1 -> 2); desfazer volta exatamente ao 1 anotado. Só aceita os números 1 e 2,
do tipo REG_DWORD (um ``bool`` é recusado). Antes de ler o valor, confere a
versão do Windows (``CurrentBuildNumber``, texto só com algarismos); versão
antiga (antes da 19041), ilegível ou fora do padrão, valor ausente, chave
ausente, 0, 3 ou outro tipo = ``NotSupportedError`` ("o Windows ou a placa de
vídeo deste PC não oferece; o app não mexe"). O adaptador nunca cria nem apaga
a chave ou o valor: só abre a chave que já existe e troca o número.
"""
from __future__ import annotations

import os
import re
from dataclasses import dataclass

ADVANCED_KIND = 'hkcu_sz_advanced'
MACHINE_KIND = 'hklm_dword_advanced'
_BUILD_RE = re.compile(r'[0-9]{1,6}')
VERSION_PATH = r'SOFTWARE\Microsoft\Windows NT\CurrentVersion'
BUILD_NAME = 'CurrentBuildNumber'
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
MSG_NOT_SUPPORTED = ('O Windows ou a placa de vídeo deste PC não oferece este ajuste; o app não '
                     'mexe. Nada foi alterado.')
MEASURE_BEFORE_HINT = 'Para comparar, meça ANTES na aba 1 antes de aplicar.'


class AdvancedTweakError(RuntimeError):
    """O ajuste foi recusado ou não pôde ser gravado."""


class NotTextError(AdvancedTweakError):
    """Um dos valores existe, mas não é texto de 1 a 3 algarismos: o app não mexe."""


class NotSupportedError(AdvancedTweakError):
    """Windows antigo, chave ou valor ausente, ou valor fora da lista: o app não mexe."""


@dataclass(frozen=True)
class AdvancedValue:
    key: str        # nome no diário (só letras, números e _)
    path: str       # subchave dentro de HKEY_CURRENT_USER
    names: tuple    # nomes dos valores, gravados e desfeitos juntos
    desired: tuple  # o que o ajuste grava em cada um
    label: str      # nome curto para a aba "Alterações feitas"
    kind: str = ADVANCED_KIND   # tipo no diário (qual adaptador lê e grava)
    scope: str = 'conta'        # 'conta' (só a sua conta) ou 'computador' (todas as contas)
    revert_to: object = None    # MACHINE_KIND: o único valor que o desfazer aceita


@dataclass(frozen=True)
class AdvancedTweak:
    id: str
    name: str       # nome em português simples
    what: str       # o que muda
    downside: str   # o lado ruim (aparece na pergunta)
    when: str       # quando passa a valer
    values: tuple
    needs_build: object = None  # versão mínima do Windows (CurrentBuildNumber), se houver

    @property
    def scope(self):
        return ('computador' if any(v.scope == 'computador' for v in self.values) else 'conta')


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
    AdvancedTweak(
        id='gpu_hw_scheduling',
        name='Agendamento de GPU acelerado por hardware ligado',
        what=('Liga a opção "Agendamento de GPU acelerado por hardware" do Windows. A placa de '
              'vídeo passa a organizar sozinha parte do próprio trabalho, o que em alguns PCs '
              'deixa jogos um pouco mais rápidos de responder; em outros não muda nada. É a mesma '
              'opção de Configurações > Sistema > Tela > Elementos gráficos > "Alterar '
              'configurações gráficas padrão".'),
        downside=('Alguns jogos, drivers de vídeo antigos, programas de captura ou de gravação '
                  'de tela podem travar, engasgar ou ficar mais lentos com esta opção ligada. '
                  'Vale para todas as contas deste computador, não só para a sua.'),
        when=('Vale depois de reiniciar o computador, e o desfazer também. O app nunca reinicia '
              'o computador sozinho.'),
        values=(AdvancedValue('gpu_hw_scheduling', r'SYSTEM\CurrentControlSet\Control\GraphicsDrivers',
                              ('HwSchMode',), (2,), 'Agendamento de GPU por hardware',
                              kind=MACHINE_KIND, scope='computador', revert_to=1),),
        needs_build=19041,
    ),
)
TWEAKS_BY_ID = {tweak.id: tweak for tweak in ADVANCED_TWEAKS}
TWEAK_VALUES = {value.key: value for tweak in ADVANCED_TWEAKS for value in tweak.values}

NEEDS_BUILD = {value.key: tweak.needs_build for tweak in ADVANCED_TWEAKS for value in tweak.values}

STATE_TEXT = {
    'applied': 'já aplicado.',
    'not_applied': 'ainda não aplicado.',
    'other_type': ('o app não mexe (o valor no Windows é de outro tipo ou está num '
                   'formato diferente).'),
    'unsupported': 'o Windows ou a placa de vídeo deste PC não oferece; o app não mexe.',
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

    @classmethod
    def _target(cls, key):
        """Só as chaves da lista com o tipo deste adaptador."""
        target = TWEAK_VALUES.get(key) if isinstance(key, str) else None
        if target is None or target.kind != cls.kind:
            raise AdvancedTweakError(MSG_UNKNOWN_KEY)
        return target

    def label_for(self, key):
        target = TWEAK_VALUES.get(key) if isinstance(key, str) else None
        return target.label if target is not None and target.kind == self.kind else self.label

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


def _is_dword(value) -> bool:
    """Número inteiro de verdade (``True``/``False`` não contam)."""
    return type(value) is int


class MachineDwordAdapter:
    """Adaptador do diário para os ajustes ``MACHINE_KIND`` (HKLM, um REG_DWORD da lista).

    Só abre chaves que já existem (``OpenKey``) e só troca o número; nunca cria
    nem apaga valor ou chave."""

    kind = MACHINE_KIND
    label = 'Ajuste avançado do Windows (computador)'

    def __init__(self, registry=None):
        self._registry = registry

    _reg = AdvancedRegistryAdapter._reg
    _target = classmethod(AdvancedRegistryAdapter._target.__func__)
    label_for = AdvancedRegistryAdapter.label_for

    @staticmethod
    def _allowed(target):
        return (target.revert_to, target.desired[0])

    @staticmethod
    def _check_build(reg, key):
        """Só lê a versão do Windows; antiga, ilegível ou fora do padrão = NotSupportedError."""
        needed = NEEDS_BUILD.get(key)
        if needed is None:
            return
        try:
            with reg.OpenKey(reg.HKEY_LOCAL_MACHINE, VERSION_PATH, 0,
                             reg.KEY_READ | reg.KEY_WOW64_64KEY) as handle:
                value, value_type = reg.QueryValueEx(handle, BUILD_NAME)
        except OSError:
            raise NotSupportedError(MSG_NOT_SUPPORTED) from None
        if (value_type != reg.REG_SZ or not isinstance(value, str)
                or _BUILD_RE.fullmatch(value) is None or int(value) < needed):
            raise NotSupportedError(MSG_NOT_SUPPORTED)

    def _query(self, reg, handle, target):
        """Número atual da lista; ausente, outro tipo ou fora da lista = NotSupportedError."""
        try:
            value, value_type = reg.QueryValueEx(handle, target.names[0])
        except FileNotFoundError:
            raise NotSupportedError(MSG_NOT_SUPPORTED) from None
        if value_type != reg.REG_DWORD or not _is_dword(value) or value not in self._allowed(target):
            raise NotSupportedError(MSG_NOT_SUPPORTED)
        return value

    def read(self, key):
        target = self._target(key)
        reg = self._reg()
        self._check_build(reg, key)
        try:
            handle = reg.OpenKey(reg.HKEY_LOCAL_MACHINE, target.path, 0,
                                 reg.KEY_READ | reg.KEY_WOW64_64KEY)
        except FileNotFoundError:
            raise NotSupportedError(MSG_NOT_SUPPORTED) from None
        with handle:
            return self._query(reg, handle, target)

    def _write(self, target, key, number):
        reg = self._reg()
        self._check_build(reg, key)
        access = reg.KEY_READ | reg.KEY_SET_VALUE | reg.KEY_WOW64_64KEY
        try:
            handle = reg.OpenKey(reg.HKEY_LOCAL_MACHINE, target.path, 0, access)
        except FileNotFoundError:
            raise NotSupportedError(MSG_NOT_SUPPORTED) from None
        with handle:
            # Relê na hora: se mudou para fora da lista, recusa sem gravar.
            if self._query(reg, handle, target) == number:
                return
            try:
                reg.SetValueEx(handle, target.names[0], 0, reg.REG_DWORD, number)
            except Exception:
                raise AdvancedTweakError(MSG_WRITE_FAILED) from None

    def apply(self, key, value):
        target = self._target(key)
        if not _is_dword(value) or value != target.desired[0]:
            raise AdvancedTweakError(MSG_BAD_VALUE)
        self._write(target, key, value)

    def revert(self, key, value):
        target = self._target(key)
        if not _is_dword(value) or value != target.revert_to:
            raise AdvancedTweakError(MSG_BAD_VALUE)
        self._write(target, key, value)


def _desired(value):
    """O que o diário guarda como valor novo: número (HKLM) ou texto juntado (HKCU)."""
    return value.desired[0] if value.kind == MACHINE_KIND else joined(value.desired)


def read_states(adapter, machine_adapter=None):
    """Só lê. Para cada ajuste: ``id``, ``state`` e ``changes`` (o que falta).

    ``adapter`` lê os ajustes da conta (``ADVANCED_KIND``) e ``machine_adapter``
    os do computador (``MACHINE_KIND``); sem ``machine_adapter``, esses ficam
    ``unreadable``. ``state``: ``applied``, ``not_applied``, ``other_type``,
    ``unsupported`` ou ``unreadable``. Nos três últimos, ``changes`` fica vazio
    (o app não mexe)."""
    adapters = {ADVANCED_KIND: adapter, MACHINE_KIND: machine_adapter}
    states = []
    for tweak in ADVANCED_TWEAKS:
        state = 'applied'
        changes = []
        for value in tweak.values:
            desired = _desired(value)
            reader = adapters.get(value.kind)
            if reader is None:
                state = 'unreadable'
                break
            try:
                current = reader.read(value.key)
            except NotSupportedError:
                state = 'unsupported'
                break
            except NotTextError:
                state = 'other_type'
                break
            except Exception:  # permissão, sistema, adaptador: "não foi possível ler"
                state = 'unreadable'
                break
            if type(current) is not type(desired) or current != desired:
                changes.append({'kind': value.kind, 'key': value.key, 'after': desired})
        if state == 'applied' and changes:
            state = 'not_applied'
        if state in ('other_type', 'unsupported', 'unreadable'):
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
    lines = ['AJUSTES AVANÇADOS (cada um tem um lado ruim; a maioria vale só na sua conta, e o '
             'que vale para o computador inteiro avisa)', '']
    for tweak in ADVANCED_TWEAKS:
        lines += [f'• {tweak.name}', f'  O que muda: {tweak.what}',
                  f'  Lado ruim: {tweak.downside}', f'  {tweak.when}']
    return lines


def confirmation_text(tweak):
    where = ('neste computador (todas as contas)' if tweak.scope == 'computador'
             else 'na sua conta do Windows')
    return (f'Aplicar o ajuste avançado "{tweak.name}" {where}?\n\n'
            f'O que muda: {tweak.what}\n\n'
            f'Lado ruim: {tweak.downside}\n\n'
            f'Quando vale: {tweak.when}\n\n'
            'Antes, o app cria um ponto de restauração do Windows e anota tudo no diário de '
            'alterações. Para voltar, use "Desfazer tudo" na aba "' + CHANGES_TAB_NAME + '".\n\n'
            + MEASURE_BEFORE_HINT)
