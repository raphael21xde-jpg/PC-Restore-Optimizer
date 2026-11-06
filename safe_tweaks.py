"""P3-04: ajustes seguros com 1 clique (lista fechada, só na conta do usuário).

Cada ajuste é um valor DWORD em HKEY_CURRENT_USER, a mesma opção que o próprio
usuário muda nas Configurações do Windows. Nada fora da lista ``SAFE_TWEAKS``:
nenhum outro ramo do registro, nenhum serviço, nenhum comando.

``RegistryTweakAdapter`` é o adaptador do diário de alterações
(``change_journal``), com o tipo ``TWEAK_KIND``:

- ``read(chave)`` devolve o DWORD atual ou ``ABSENT`` (o valor não existe);
- ``apply(chave, valor)`` só grava o valor da lista para aquela chave;
- ``revert(chave, valor)`` volta o DWORD antigo ou, se o diário diz que antes
  não existia (``ABSENT``), apaga só aquele valor; a chave (pasta) nunca é apagada.

Um valor de outro tipo (texto, binário, QWORD) faz o adaptador recusar sem
mudar nada. O módulo ``winreg`` é injetável (os testes usam um registro falso
em memória) e só é importado na hora de ler ou gravar.

Escolhas de design (as mais seguras, registradas em docs/BACKLOG.md):
- lista fechada e curta, só HKCU, sem administrador para o ajuste em si;
- valor que já está no desejado não entra no lote;
- ajuste com algum valor de outro tipo, ou que não pôde ser lido, fica fora
  do lote inteiro;
- o Game Bar muda só "Gravar o que aconteceu" (``HistoricalCaptureEnabled``):
  print e gravar na hora continuam como estavam (escolha do coordenador).
"""
from __future__ import annotations

import os
from dataclasses import dataclass

TWEAK_KIND = 'hkcu_dword'
ABSENT = None            # marcador de "o valor não existe" (valor simples para o diário)
MAX_DWORD = 0xFFFFFFFF
# O mesmo texto de optimization_ui.CHANGES_TAB_LABEL (o teste da tela confere).
CHANGES_TAB_NAME = '7  Alterações feitas'

MSG_UNKNOWN_KEY = 'Ajuste desconhecido pelo app; nada foi alterado.'
MSG_BAD_VALUE = 'Valor que o app não aceita para este ajuste; nada foi alterado.'
MSG_NOT_DWORD = ('O valor no Windows é de outro tipo; por segurança, o app não mexe '
                 'neste ajuste. Nada foi alterado.')
MSG_NOT_WINDOWS = 'Este recurso só funciona em computadores Windows.'
# Só sugere (não obriga): a comparação antes/depois é da aba 1 (P3-02).
MEASURE_BEFORE_HINT = 'Para comparar, meça ANTES na aba 1 antes de aplicar.'


class TweakError(RuntimeError):
    """O ajuste foi recusado; nada foi alterado."""


class NotDwordError(TweakError):
    """O valor existe, mas não é DWORD: o app não mexe."""


@dataclass(frozen=True)
class RegistryValue:
    key: str        # nome no diário (só letras, números e _)
    path: str       # subchave dentro de HKEY_CURRENT_USER
    name: str       # nome do valor
    desired: int    # valor que o ajuste grava
    label: str      # nome curto para a aba "Alterações feitas"


@dataclass(frozen=True)
class SafeTweak:
    id: str
    name: str       # nome em português simples
    what: str       # o que muda
    when: str       # quando passa a valer
    values: tuple


SAFE_TWEAKS = (
    SafeTweak(
        id='game_mode',
        name='Modo de Jogo ligado',
        what=('O Windows dá prioridade ao jogo aberto e evita instalar atualizações '
              'de drivers e mostrar avisos de reinício durante o jogo.'),
        when='Vale na hora.',
        values=(RegistryValue('game_mode', r'Software\Microsoft\GameBar',
                              'AutoGameModeEnabled', 1, 'Modo de Jogo'),),
    ),
    SafeTweak(
        id='game_bar_capture',
        name='Gravação em segundo plano do Xbox Game Bar desligada',
        what=('Desliga a opção "Gravar o que aconteceu" do Game Bar, que fica gravando '
              'o jogo em segundo plano e usa processador, placa de vídeo e disco. É a '
              'mesma opção que existe nas Configurações do Windows. Tirar print e gravar '
              'na hora continuam funcionando pelo Game Bar.'),
        when=('Vale para os jogos abertos depois; se um jogo já estiver aberto, '
              'feche e abra o jogo de novo.'),
        values=(RegistryValue('historical_capture', r'Software\Microsoft\Windows\CurrentVersion\GameDVR',
                              'HistoricalCaptureEnabled', 0,
                              'Gravação em segundo plano do Game Bar'),),
    ),
    SafeTweak(
        id='transparency',
        name='Efeitos de transparência desligados',
        what=('As janelas, o menu Iniciar e a barra de tarefas deixam de ter o efeito '
              'de vidro; a tela fica um pouco mais leve para a placa de vídeo.'),
        when='Vale na hora.',
        values=(RegistryValue('transparency', r'Software\Microsoft\Windows\CurrentVersion\Themes\Personalize',
                              'EnableTransparency', 0, 'Efeitos de transparência'),),
    ),
)
TWEAKS_BY_ID = {tweak.id: tweak for tweak in SAFE_TWEAKS}
TWEAK_VALUES = {value.key: value for tweak in SAFE_TWEAKS for value in tweak.values}

STATE_TEXT = {
    'applied': 'já aplicado.',
    'not_applied': 'ainda não aplicado.',
    'other_type': 'o app não mexe (o valor no Windows é de outro tipo).',
    'unreadable': 'Não foi possível ler o estado atual; o app não mexe.',
}


def _is_windows() -> bool:
    """Único ponto que confere o sistema; os testes trocam esta função."""
    return os.name == 'nt'


def _is_dword(value) -> bool:
    return (isinstance(value, int) and not isinstance(value, bool)
            and 0 <= value <= MAX_DWORD)


class RegistryTweakAdapter:
    """Adaptador do diário para os valores de ``SAFE_TWEAKS`` (só HKCU, só DWORD)."""

    kind = TWEAK_KIND
    label = 'Ajuste seguro do Windows'

    def __init__(self, registry=None):
        self._registry = registry

    def _reg(self):
        if self._registry is not None:
            return self._registry
        if not _is_windows():
            raise TweakError(MSG_NOT_WINDOWS)
        import winreg  # só existe no Windows; importado só na hora de usar
        return winreg

    @staticmethod
    def _target(key):
        if not isinstance(key, str) or key not in TWEAK_VALUES:
            raise TweakError(MSG_UNKNOWN_KEY)
        return TWEAK_VALUES[key]

    def label_for(self, key):
        target = TWEAK_VALUES.get(key) if isinstance(key, str) else None
        return target.label if target is not None else self.label

    @staticmethod
    def _query(reg, handle, name):
        """DWORD atual ou ABSENT; outro tipo = NotDwordError."""
        try:
            value, value_type = reg.QueryValueEx(handle, name)
        except FileNotFoundError:
            return ABSENT
        if value_type != reg.REG_DWORD or not _is_dword(value):
            raise NotDwordError(MSG_NOT_DWORD)
        return value

    def read(self, key):
        target = self._target(key)
        reg = self._reg()
        try:
            handle = reg.OpenKey(reg.HKEY_CURRENT_USER, target.path, 0, reg.KEY_READ)
        except FileNotFoundError:
            return ABSENT
        with handle:
            return self._query(reg, handle, target.name)

    def _write(self, target, value):
        reg = self._reg()
        with reg.CreateKeyEx(reg.HKEY_CURRENT_USER, target.path, 0,
                             reg.KEY_READ | reg.KEY_SET_VALUE) as handle:
            self._query(reg, handle, target.name)   # outro tipo: recusa antes de gravar
            reg.SetValueEx(handle, target.name, 0, reg.REG_DWORD, value)

    def _delete_value(self, target):
        """Apaga só o valor (nunca a chave); já ausente = nada a fazer."""
        reg = self._reg()
        try:
            handle = reg.OpenKey(reg.HKEY_CURRENT_USER, target.path, 0,
                                 reg.KEY_READ | reg.KEY_SET_VALUE)
        except FileNotFoundError:
            return
        with handle:
            if self._query(reg, handle, target.name) is ABSENT:
                return
            try:
                reg.DeleteValue(handle, target.name)
            except FileNotFoundError:
                return

    def apply(self, key, value):
        target = self._target(key)
        if not _is_dword(value) or value != target.desired:
            raise TweakError(MSG_BAD_VALUE)
        self._write(target, value)

    def revert(self, key, value):
        target = self._target(key)
        if value is ABSENT:
            # Só chega aqui quando o diário anotou que o valor não existia antes.
            self._delete_value(target)
        elif _is_dword(value):
            self._write(target, value)
        else:
            raise TweakError(MSG_BAD_VALUE)


def read_states(adapter):
    """Só lê. Para cada ajuste: ``id``, ``state`` e ``changes`` (o lote que falta).

    ``state``: ``applied`` (tudo no valor desejado), ``not_applied``, ``other_type``
    ou ``unreadable``. Nos dois últimos, ``changes`` fica vazio (o ajuste inteiro
    fica fora do lote)."""
    states = []
    for tweak in SAFE_TWEAKS:
        state = 'applied'
        changes = []
        for value in tweak.values:
            try:
                current = adapter.read(value.key)
            except NotDwordError:
                state = 'other_type'
                break
            except Exception:  # permissão, sistema, adaptador: "não foi possível ler"
                state = 'unreadable'
                break
            if not (_is_dword(current) and current == value.desired):
                changes.append({'kind': TWEAK_KIND, 'key': value.key, 'after': value.desired})
        if state == 'applied' and changes:
            state = 'not_applied'
        if state in ('other_type', 'unreadable'):
            changes = []
        states.append({'id': tweak.id, 'state': state, 'changes': changes})
    return states


def pending_changes(states):
    """Lote para ``apply_batch``: só os valores que ainda não estão no desejado."""
    return [dict(change) for item in states if item.get('state') == 'not_applied'
            for change in item.get('changes', [])]


def pending_tweaks(states):
    return [TWEAKS_BY_ID[item['id']] for item in states
            if item.get('state') == 'not_applied' and item.get('id') in TWEAKS_BY_ID]


def state_lines(states):
    lines = ['ESTADO ATUAL (lido agora, sem mudar nada)']
    for item in states:
        tweak = TWEAKS_BY_ID.get(item.get('id'))
        if tweak is None:
            continue
        lines.append(f'• {tweak.name}: {STATE_TEXT.get(item.get("state"), STATE_TEXT["unreadable"])}')
    return lines


def intro_lines():
    lines = ['AJUSTES SEGUROS (só na sua conta do Windows)', '']
    for tweak in SAFE_TWEAKS:
        lines += [f'• {tweak.name}', f'  {tweak.what}', f'  {tweak.when}']
    return lines


def confirmation_text(tweaks):
    items = '\n'.join(f'• {tweak.name}: {tweak.what} {tweak.when}' for tweak in tweaks)
    return (f'Aplicar {len(tweaks)} ajuste(s) seguro(s) na sua conta do Windows?\n\n'
            f'{items}\n\n'
            'Antes, o app cria um ponto de restauração do Windows e anota tudo no diário de '
            'alterações. Para voltar, use "Desfazer tudo" na aba "' + CHANGES_TAB_NAME + '".\n\n'
            'Ajustes que já estão no valor certo não são mexidos.\n\n'
            + MEASURE_BEFORE_HINT)


def applied_lines(tweaks):
    return [f'• {tweak.name}: {tweak.when}' for tweak in tweaks]
