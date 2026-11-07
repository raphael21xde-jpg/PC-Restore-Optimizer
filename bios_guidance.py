"""P3-06: BIOS só orientação, a partir do inventário que o app já leu.

Funções puras: não executam comandos, não acessam registro nem disco e não
importam outros módulos do projeto (mesmo padrão de hardware_profile.py).
Toda entrada estranha vira "não confirmado", nunca exceção.

O app nunca altera a BIOS. Aqui só se estima o estado do XMP/EXPO pelo que o
Windows informa da memória, se identifica a família da placa e o ano da BIOS
e se mostra um passo a passo para a pessoa conferir sozinha.

Escolhas de design (as mais seguras, registradas em docs/BACKLOG.md):
- "provavelmente desligado": algum abaixo e nenhum acima, isto é, algum módulo
  com velocidade configurada menor que a informada pelo módulo (pode ser limite
  do processador/placa) e nenhum com a configurada maior; módulos uns abaixo e
  outros acima viram "não confirmado" com REASON_MIXED (módulos diferentes), e
  configurada exatamente metade da informada vira "não confirmado" com
  REASON_UNITS (metade exata, MHz x MT/s);
- "provavelmente ligado": só quando todos os módulos têm os dois valores e a
  configurada é maior; o resto é "não confirmado";
- "provavelmente ligado (velocidade acima do padrão)" (FIX-M3-T7): com XMP/EXPO
  ligado o Windows costuma informar a mesma velocidade nos dois campos (3600 e
  3600), então o app compara a configurada com o maior degrau JEDEC do tipo da
  memória (SMBIOSMemoryType: DDR3 2133, DDR4 3200, DDR5 8800 MT/s). Só vale se
  todos os módulos têm o mesmo tipo da tabela e a configurada fica acima do
  padrão e até o dobro dele; tipo desconhecido, LPDDR, misturado ou sem dado e
  configurada maior que o dobro (dado estranho) seguem a regra antiga. O texto
  sempre diz "provavelmente" e cita o ajuste manual da memória;
- na tela, o motivo de "desligado" com números só é exibido se os números forem
  coerentes (0 < configurada < informada e não metade exata); senão vira o
  motivo padrão (R-32, antiga R-34); o mesmo vale para o motivo de "acima do
  padrão" (tipo e padrão da tabela e padrão < configurada <= 2x padrão);
- Resizable BAR (fatia 2, FIX-P3-06-13, FIX-M3-T1): o estado é sempre "não
  confirmado". O Windows só informa o tamanho dos intervalos de memória de cada
  placa de vídeo, e isso não confirma o estado (RTX 5070, driver 621.01: janela de
  16 GiB com o Resizable BAR desligado no painel da NVIDIA). O tamanho só escolhe o
  motivo: todas as placas com algum intervalo maior que 256 MiB, REBAR_REASON_BIG;
  placas que discordam ou alguma sem dado (inclusive pequena + sem dado,
  FIX-P3-06-14), REBAR_REASON_MIXED (R-38); todas até 256 MiB, REBAR_REASON_SMALL;
  todas sem dado, REBAR_REASON_DEFAULT. Logo depois do motivo vêm os passos
  REBAR_CHECK_STEPS para conferir no painel da NVIDIA/AMD ou no GPU-Z. Relatório
  antigo com "provavelmente_ligado" aparece como "não confirmado" (R-32). Aceita o
  formato {"value": [...]} do ConvertTo-Json do PowerShell 5.1. Nunca diz "ligado"
  nem "desligado";
- guarda só família da placa, versão e ano da BIOS; nunca modelo da placa,
  número de série ou nome do PC;
- não recomenda atualizar a BIOS e não traz link nem download.
"""
from __future__ import annotations

import math
import re
from datetime import datetime, timezone

XMP_OFF = 'provavelmente_desligado'
XMP_ON = 'provavelmente_ligado'
XMP_UNKNOWN = 'nao_confirmado'
# FIX-M3-T7: configurada acima do padrão JEDEC do tipo da memória.
XMP_ON_STD = 'provavelmente_ligado_acima_padrao'

# FIX-M3-T7: SMBIOSMemoryType -> (nome, maior velocidade JEDEC em MT/s). O maior degrau
# oficial evita dizer "ligado" sem motivo; tipo fora daqui (LPDDR, 0, ...) não entra.
JEDEC_MAX_MTS = {24: ('DDR3', 2133), 26: ('DDR4', 3200), 34: ('DDR5', 8800)}
_JEDEC_BY_NAME = {name: standard for name, standard in JEDEC_MAX_MTS.values()}

XMP_LABELS = {
    XMP_OFF: 'provavelmente desligado (ou limitado pelo processador/placa)',
    XMP_ON: 'provavelmente ligado',
    XMP_ON_STD: 'provavelmente ligado (velocidade acima do padrão)',
    XMP_UNKNOWN: 'não confirmado',
}

FAMILY_LABELS = {
    'asus': 'ASUS',
    'msi': 'MSI',
    'gigabyte': 'Gigabyte',
    'asrock': 'ASRock',
    'oem': 'notebook ou PC de marca',
    'desconhecido': 'não identificado',
}

NEVER_CHANGES = 'O app nunca altera a BIOS.'

_DEFAULT_REASONS = {
    XMP_OFF: 'A memória está rodando abaixo da velocidade que o módulo informa.',
    XMP_ON: 'A memória está rodando acima da velocidade básica que o módulo informa.',
    XMP_ON_STD: 'A memória está configurada acima do padrão oficial (JEDEC) do tipo dela.',
    XMP_UNKNOWN: 'O Windows não deu informação suficiente para saber.',
}
REASON_MIXED = 'Os módulos de memória informam velocidades diferentes; não dá para saber.'
REASON_UNITS = ('A velocidade configurada é metade da informada pelo módulo; pode ser só diferença '
                'de unidade (MHz e MT/s), então não dá para saber.')
# Motivos que a tela aceita para cada estado (R-32); o de "desligado" com números
# é conferido por _off_reason_ok() (padrão _REASON_OFF + números coerentes) e o de
# "acima do padrão" com números por _above_reason_ok() (FIX-M3-T7).
_ACCEPTED_REASONS = {
    XMP_OFF: {_DEFAULT_REASONS[XMP_OFF]},
    XMP_ON: {_DEFAULT_REASONS[XMP_ON]},
    XMP_ON_STD: {_DEFAULT_REASONS[XMP_ON_STD]},
    XMP_UNKNOWN: {_DEFAULT_REASONS[XMP_UNKNOWN], REASON_MIXED, REASON_UNITS},
}

# FIX-M3-T1: não existe mais "provavelmente ligado"; o tamanho da janela não confirma o estado.
REBAR_UNKNOWN = 'nao_confirmado'
REBAR_LABELS = {
    REBAR_UNKNOWN: 'não confirmado',
}
REBAR_REASON_BIG = ('O Windows informa uma janela de memória maior que 256 MiB, mas isso sozinho não '
                    'confirma o Resizable BAR (há placas que mostram isso com ele desligado).')
REBAR_REASON_SMALL = ('As janelas de memória da placa de vídeo que o Windows informa têm até 256 MiB; '
                      'isso não basta para confirmar o Resizable BAR.')
REBAR_REASON_DEFAULT = ('O Windows não informou a janela de memória da placa de vídeo; '
                        'não dá para saber.')
REBAR_REASON_MIXED = ('As placas de vídeo do PC não informam a mesma coisa (por exemplo, vídeo integrado '
                      'e placa dedicada, ou uma delas sem informação); não dá para confirmar o Resizable BAR.')
_REBAR_REASONS = {
    REBAR_UNKNOWN: {REBAR_REASON_DEFAULT, REBAR_REASON_SMALL, REBAR_REASON_MIXED, REBAR_REASON_BIG},
}
_REBAR_DEFAULTS = {REBAR_UNKNOWN: REBAR_REASON_DEFAULT}
REBAR_CHECK_TITLE = 'Como conferir sem entrar na BIOS:'
# Subtítulo da mesma lista na janela "Ver passo a passo".
REBAR_CHECK_WINDOW_TITLE = 'Resizable BAR (fora da BIOS) — como conferir:'
# Onde a pessoa confere o estado real, sem link e sem download.
REBAR_CHECK_STEPS = (
    'NVIDIA: abra o Painel de controle da NVIDIA > Informações do sistema (canto de baixo à esquerda) '
    'e veja a linha "BAR redimensionável" (Resizable BAR).',
    'AMD: abra o AMD Software: Adrenalin Edition e procure "Smart Access Memory" (o lugar muda '
    'conforme a versão).',
    'Se você já usa o GPU-Z, veja o campo "Resizable BAR" na primeira aba.',
)
_BAR_LIMIT = 256 * 1024 ** 2
# Acima de 1 TiB não é janela de placa de vídeo real; é dado estranho e é ignorado.
_BAR_MAX = 1024 ** 4

_PATHLIKE = re.compile(r'[\\/:]|%|~')
_VERSION_OK = re.compile(r'^[A-Za-z0-9][A-Za-z0-9 ._()\-]*$')
_REASON_OFF = re.compile(r'^A memória está configurada a (\d{1,6}(?:\.\d+)?) MT/s e o módulo informa '
                         r'(\d{1,6}(?:\.\d+)?) MT/s\. O perfil XMP/EXPO pode estar desligado, ou o '
                         r'processador/placa limita a velocidade\.$')
_REASON_ABOVE = re.compile(r'^A memória está configurada a (\d{1,6}(?:\.\d+)?) MT/s, acima do padrão '
                           r'oficial \(JEDEC\) do (DDR[345]), que é (\d{1,6}) MT/s\. Isso costuma '
                           r'indicar o perfil XMP/EXPO ligado \(ou um ajuste manual da memória\)\.$')
_DATE_MS = re.compile(r'^/Date\((-?\d{1,15})\)/$')
_DATE_DIGITS = re.compile(r'^(\d{4})(\d{2})(\d{2})')

_BOARD_BRANDS = (
    ('asrock', re.compile(r'asrock', re.I)),
    ('asus', re.compile(r'asus', re.I)),
    ('msi', re.compile(r'micro[-\s]?star|\bmsi\b', re.I)),
    ('gigabyte', re.compile(r'gigabyte', re.I)),
)
_OEM = re.compile(r'\bdell\b|hewlett|\bhp\b|lenovo|\bacer\b|positivo|samsung|toshiba|\bsony\b|vaio'
                  r'|fujitsu|microsoft|\bapple\b|huawei|xiaomi|\blg\b|multilaser|compaq', re.I)


def _items(value):
    if isinstance(value, dict):
        value = [value]
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, dict)]


def _num(value):
    """Número positivo e finito; bool, texto, negativos, NaN e infinito viram None."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    if isinstance(value, float) and not math.isfinite(value):
        return None
    return value if value > 0 else None


def _manufacturer(value):
    entries = _items(value)
    text = entries[0].get('Manufacturer') if entries else None
    return text if isinstance(text, str) else ''


def _memory_type(value):
    """SMBIOSMemoryType da tabela JEDEC_MAX_MTS (int de verdade); bool, texto e o resto viram None."""
    if isinstance(value, bool) or not isinstance(value, int):
        return None
    return value if value in JEDEC_MAX_MTS else None


def _above_standard(modules):
    """(menor configurada, nome, padrão) se todos os módulos estão acima do padrão JEDEC; senão None.

    Todos com o mesmo tipo da tabela, configurada válida e padrão < configurada <= 2x
    padrão (acima do dobro é dado estranho). O campo Speed não entra.
    """
    kinds = {_memory_type(m.get('SMBIOSMemoryType')) for m in modules}
    if len(kinds) != 1 or None in kinds:
        return None
    name, standard = JEDEC_MAX_MTS[kinds.pop()]
    configured = [_num(m.get('ConfiguredClockSpeed')) for m in modules]
    if any(c is None or not standard < c <= 2 * standard for c in configured):
        return None
    return min(configured), name, standard


def xmp_state(ram):
    """(estado, motivo) a partir de Win32_PhysicalMemory (Speed, ConfiguredClockSpeed, SMBIOSMemoryType).

    Ordem: sem módulos é "não confirmado"; configurada metade exata da informada é
    "não confirmado" com REASON_UNITS (metade exata); todos os módulos do mesmo tipo
    da tabela JEDEC_MAX_MTS com a configurada acima do padrão (até o dobro) é
    XMP_ON_STD, com a menor configurada no texto (FIX-M3-T7); depois a regra antiga:
    "desligado" só com algum abaixo e nenhum acima; uns abaixo e outros acima é
    "não confirmado" com REASON_MIXED (módulos diferentes).
    """
    modules = _items(ram)
    if not modules:
        return XMP_UNKNOWN, _DEFAULT_REASONS[XMP_UNKNOWN]
    pairs = [(_num(m.get('Speed')), _num(m.get('ConfiguredClockSpeed'))) for m in modules]
    complete = [(s, c) for s, c in pairs if s is not None and c is not None]
    # Metade exata: pode ser o Windows misturando MHz e MT/s; não dá para concluir.
    if any(c * 2 == s for s, c in complete):
        return XMP_UNKNOWN, REASON_UNITS
    above_std = _above_standard(modules)
    if above_std:
        configured, name, standard = above_std
        return XMP_ON_STD, (f'A memória está configurada a {configured:g} MT/s, acima do padrão oficial '
                            f'(JEDEC) do {name}, que é {standard} MT/s. Isso costuma indicar o perfil '
                            'XMP/EXPO ligado (ou um ajuste manual da memória).')
    below = [(s, c) for s, c in complete if c < s]
    above = [(s, c) for s, c in complete if c > s]
    if below and above:
        return XMP_UNKNOWN, REASON_MIXED
    if below:
        speed, configured = below[0]
        return XMP_OFF, (f'A memória está configurada a {configured:g} MT/s e o módulo informa '
                         f'{speed:g} MT/s. O perfil XMP/EXPO pode estar desligado, ou o '
                         'processador/placa limita a velocidade.')
    if len(complete) == len(pairs) and len(above) == len(pairs):
        return XMP_ON, _DEFAULT_REASONS[XMP_ON]
    return XMP_UNKNOWN, _DEFAULT_REASONS[XMP_UNKNOWN]


def _bar_size(value):
    """Tamanho inteiro entre 1 byte e 1 TiB; bool, texto, NaN, fração e o resto viram None."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    if isinstance(value, float):
        if not math.isfinite(value) or not value.is_integer():
            return None
        value = int(value)
    return value if 0 < value <= _BAR_MAX else None


def _ps_list(value):
    """Lista a partir do que o ConvertTo-Json devolve; nunca lança erro.

    Lista fica como está; {"value": [...]} (PowerShell 5.1 com -InputObject) vira a
    lista de dentro; qualquer outro valor vira lista vazia.
    """
    if isinstance(value, dict) and 'value' in value:
        value = value['value']
    return list(value) if isinstance(value, list) else []


_GPU_BIG, _GPU_SMALL, _GPU_NO_DATA = 'grande', 'pequena', 'sem_dado'


def _gpu_bar_state(gpu):
    """grande (alguma janela > 256 MiB), pequena (janelas válidas, todas até 256 MiB) ou sem dado."""
    if not isinstance(gpu, dict):
        return _GPU_NO_DATA
    values = gpu.get('Sizes')
    values = _ps_list(values) if isinstance(values, (list, dict)) else [values]
    sizes = [size for size in map(_bar_size, values) if size is not None]
    if not sizes:
        return _GPU_NO_DATA
    return _GPU_BIG if any(size > _BAR_LIMIT for size in sizes) else _GPU_SMALL


def rebar_state(gpu_bar):
    """(estado, motivo) a partir dos tamanhos dos intervalos de memória das placas de vídeo.

    Entrada: dict ou lista de dicts {"Sizes": [bytes, ...]} (um por placa); a lista e
    o Sizes também podem vir como {"value": [...]} (PowerShell 5.1). O estado é
    sempre REBAR_UNKNOWN (FIX-M3-T1): o tamanho da janela não confirma o Resizable
    BAR. Cada placa é avaliada sozinha (R-38) só para escolher o motivo: todas com
    algum intervalo maior que 256 MiB, REBAR_REASON_BIG; placas que discordam ou
    alguma sem dado (inclusive uma pequena junto de uma sem dado), REBAR_REASON_MIXED;
    todas pequenas, REBAR_REASON_SMALL; todas sem dado, REBAR_REASON_DEFAULT. Nunca
    devolve "ligado" nem "desligado" e nunca lança erro.
    """
    # dict sem 'value' = uma placa só; com 'value' = lista embrulhada pelo PowerShell 5.1
    if isinstance(gpu_bar, dict) and 'value' not in gpu_bar:
        gpus = [gpu_bar]
    else:
        gpus = _ps_list(gpu_bar)
    states = [_gpu_bar_state(gpu) for gpu in gpus]
    if states and all(state == _GPU_BIG for state in states):
        return REBAR_UNKNOWN, REBAR_REASON_BIG
    if len(set(states)) > 1:
        return REBAR_UNKNOWN, REBAR_REASON_MIXED
    if states and all(state == _GPU_SMALL for state in states):
        return REBAR_UNKNOWN, REBAR_REASON_SMALL
    return REBAR_UNKNOWN, REBAR_REASON_DEFAULT


def _off_reason_ok(reason):
    """True só se o motivo de "desligado" tem o formato gerado e números coerentes.

    Coerente: 0 < configurada < informada e configurada * 2 != informada (a metade
    exata é "não confirmado" em xmp_state). Nunca lança erro.
    """
    if not isinstance(reason, str):
        return False
    match = _REASON_OFF.match(reason)
    if not match:
        return False
    try:
        configured, speed = float(match.group(1)), float(match.group(2))
    except (TypeError, ValueError):
        return False
    return 0 < configured < speed and configured * 2 != speed


def _above_reason_ok(reason):
    """True só se o motivo de "acima do padrão" tem o formato gerado e números coerentes.

    Coerente: tipo da tabela JEDEC_MAX_MTS, padrão igual ao da tabela e padrão <
    configurada <= 2x padrão (FIX-M3-T7). Nunca lança erro.
    """
    if not isinstance(reason, str):
        return False
    match = _REASON_ABOVE.match(reason)
    if not match:
        return False
    standard = _JEDEC_BY_NAME.get(match.group(2))
    try:
        configured, shown = float(match.group(1)), int(match.group(3))
    except (TypeError, ValueError):
        return False
    return standard is not None and shown == standard and standard < configured <= 2 * standard


def board_family(board, bios, form_factor):
    """asus | msi | gigabyte | asrock | oem | desconhecido (só o fabricante, nunca o modelo)."""
    if form_factor == 'notebook':
        return 'oem'
    maker = _manufacturer(board)
    for family, pattern in _BOARD_BRANDS:
        if pattern.search(maker):
            return family
    if _OEM.search(maker) or _OEM.search(_manufacturer(bios)):
        return 'oem'
    return 'desconhecido'


def bios_release_year(value):
    """Ano da BIOS a partir de "/Date(ms)/" ou "AAAAMMDD..."; senão None."""
    if not isinstance(value, str):
        return None
    value = value.strip()
    year = None
    match = _DATE_MS.match(value)
    if match:
        try:
            year = datetime.fromtimestamp(int(match.group(1)) / 1000, tz=timezone.utc).year
        except (OverflowError, OSError, ValueError):
            return None
    else:
        match = _DATE_DIGITS.match(value)
        if not match:
            return None
        year, month, day = (int(part) for part in match.groups())
        if not (1 <= month <= 12 and 1 <= day <= 31):
            return None
    if year < 1990 or year > datetime.now(timezone.utc).year:
        return None
    return year


def _version(value):
    """Versão curta e com caracteres simples; caminho ou texto longo viram None."""
    if not isinstance(value, str):
        return None
    value = ' '.join(value.split())
    if not value or len(value) > 40 or _PATHLIKE.search(value) or not _VERSION_OK.match(value):
        return None
    return value


def _year(value):
    if isinstance(value, bool) or not isinstance(value, int):
        return None
    return value if 1990 <= value <= datetime.now(timezone.utc).year else None


_XMP_WHERE = {
    'asus': 'Aperte F7 para o "Modo Avançado", abra a aba "AI Tweaker" e procure '
            '"D.O.C.P", "XMP" ou "EXPO".',
    'msi': 'Abra a aba "OC" (ou use o botão "XMP"/"A-XMP" na tela inicial) e procure "XMP" ou "EXPO".',
    'gigabyte': 'Abra a aba "Tweaker" e procure "Extreme Memory Profile (XMP)" ou "EXPO".',
    'asrock': 'Abra a aba "OC Tweaker" e procure "Load XMP Setting" ou "EXPO".',
    'desconhecido': 'Procure uma aba com nome parecido com "OC", "Tweaker", "Avançado" ou '
                    '"Memória" e a opção "XMP" ou "EXPO".',
}


def _steps(family):
    if family not in FAMILY_LABELS:
        family = 'desconhecido'
    key = 'DEL ou F2'
    if family in ('desconhecido', 'oem'):
        key = 'DEL ou F2 (ou a tecla indicada na tela de abertura)'
    steps = ['Salve seus trabalhos e reinicie o PC.',
             f'Assim que a tela acender, aperte várias vezes a tecla {key} para entrar na BIOS ou '
             'UEFI (o nome atual da BIOS).']
    if family == 'oem':
        steps.append('Muitas BIOS de notebook e de PCs de marca (Dell, HP, Lenovo, Acer, Positivo, '
                     'Samsung...) não têm XMP/EXPO nem Resizable BAR. Consulte o manual do '
                     'fabricante do seu PC antes de procurar.')
    else:
        steps.append('XMP/EXPO: ' + _XMP_WHERE[family] + ' Só confira se está em "Perfil 1" ou '
                     '"Desligado/Auto".')
    steps.extend([
        'Resizable BAR (também chamado "Re-Size BAR" ou "Smart Access Memory"): costuma ficar em '
        '"Avançado" > "PCI" ou "PCIe" e depende de Above 4G Decoding (opção que deixa a '
        'placa de vídeo usar mais memória). Não mude o CSM (modo de compatibilidade antigo) '
        'nem o modo de inicialização: isso pode impedir o Windows de abrir.',
        'Se não tiver certeza, saia sem salvar (Esc e depois "Sair sem salvar"). Qualquer mudança '
        'é por sua conta; o app não faz nenhuma.',
        'Se o PC não ligar depois de uma mudança, limpe a CMOS (volta a BIOS ao padrão de '
        'fábrica, pelo botão ou jumper descrito no manual).',
    ])
    return steps


def build_bios_guidance(hardware, profile):
    """Orientação de BIOS; só família, versão e ano, nunca modelo nem número de série."""
    hardware = hardware if isinstance(hardware, dict) else {}
    profile = profile if isinstance(profile, dict) else {}
    state, reason = xmp_state(hardware.get('ram'))
    family = board_family(hardware.get('board'), hardware.get('bios'), profile.get('form_factor'))
    bios = _items(hardware.get('bios'))
    first = bios[0] if bios else {}
    rebar, rebar_reason = rebar_state(hardware.get('gpu_bar'))
    return {
        'xmp': state,
        'xmp_reason': reason,
        'family': family,
        'bios_version': _version(first.get('SMBIOSBIOSVersion')),
        'bios_year': bios_release_year(first.get('ReleaseDate')),
        'rebar': rebar,
        'rebar_reason': rebar_reason,
        'steps': _steps(family),
    }


def _family(guidance):
    family = guidance.get('family') if isinstance(guidance, dict) else None
    return family if isinstance(family, str) and family in FAMILY_LABELS else 'desconhecido'


def bios_steps_text(guidance):
    """Texto da janela "Ver passo a passo"; sempre regenerado pela família (R-32).

    O campo ``steps`` do dict é ignorado de propósito. Sem link e sem download.
    Termina com os passos para conferir o Resizable BAR sem entrar na BIOS (FIX-M3-T1).
    """
    family = _family(guidance)
    lines = ['Passo a passo para conferir na BIOS',
             f'{NEVER_CHANGES} Aqui só mostramos como conferir; qualquer mudança é sua.',
             f'Fabricante da placa: {FAMILY_LABELS[family]}', '']
    lines.extend(f'{number}. {step}' for number, step in enumerate(_steps(family), 1))
    lines.extend(['', REBAR_CHECK_WINDOW_TITLE])
    lines.extend(f'- {step}' for step in REBAR_CHECK_STEPS)
    return '\n'.join(lines)


def bios_guidance_lines(guidance):
    """Linhas em português simples para a aba de diagnóstico."""
    if not isinstance(guidance, dict):
        guidance = {}
    state = guidance.get('xmp') if guidance.get('xmp') in XMP_LABELS else XMP_UNKNOWN
    reason = guidance.get('xmp_reason')
    # R-32: só aceita os motivos que este módulo gera; qualquer outro texto vira o padrão.
    # (R-32, antiga R-34): o motivo de "desligado" com números só vale se os números forem coerentes.
    # FIX-M3-T7: o motivo de "acima do padrão" com números só vale para XMP_ON_STD e coerente.
    if not (isinstance(reason, str) and (reason in _ACCEPTED_REASONS[state]
                                         or (state == XMP_OFF and _off_reason_ok(reason))
                                         or (state == XMP_ON_STD and _above_reason_ok(reason)))):
        reason = _DEFAULT_REASONS[state]
    family = _family(guidance)
    rebar = guidance.get('rebar')
    rebar = rebar if isinstance(rebar, str) and rebar in REBAR_LABELS else REBAR_UNKNOWN
    rebar_reason = guidance.get('rebar_reason')
    # R-32: só aceita os motivos de Resizable BAR que este módulo gera; estado antigo
    # "provavelmente_ligado" (antes do FIX-M3-T1) não está em REBAR_LABELS e vira "não confirmado".
    if not (isinstance(rebar_reason, str) and rebar_reason in _REBAR_REASONS[rebar]):
        rebar_reason = _REBAR_DEFAULTS[rebar]
    version = _version(guidance.get('bios_version')) or 'não disponível'
    year = _year(guidance.get('bios_year'))
    # R-32: o passo a passo é sempre regenerado; guidance['steps'] é ignorado.
    steps = _steps(family)
    lines = ['BIOS — SÓ ORIENTAÇÃO',
             f'  {NEVER_CHANGES} Aqui só mostramos o que o Windows informa e como conferir.',
             f'  Perfil de memória (XMP/EXPO): {XMP_LABELS[state]}',
             f'    {reason}',
             f'  Fabricante da placa: {FAMILY_LABELS[family]}',
             f"  BIOS: versão {version} | ano {year if year is not None else 'não disponível'}",
             f'  Resizable BAR: {REBAR_LABELS[rebar]} (veja abaixo como conferir).',
             f'    {rebar_reason}',
             f'    {REBAR_CHECK_TITLE}',
             *(f'      - {step}' for step in REBAR_CHECK_STEPS),
             '  O app não pede para atualizar a BIOS. Se você decidir atualizar, use só o site oficial do '
             'fabricante; atualizar BIOS tem risco (faltar energia no meio pode impedir o PC de ligar).',
             '  Como conferir na BIOS:']
    lines.extend(f'    {number}. {step}' for number, step in enumerate(steps, 1))
    return lines
