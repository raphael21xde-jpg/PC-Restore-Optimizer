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
- na tela, o motivo de "desligado" com números só é exibido se os números forem
  coerentes (0 < configurada < informada e não metade exata); senão vira o
  motivo padrão (R-34);
- Resizable BAR: não verificado nesta versão, só passo a passo;
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

XMP_LABELS = {
    XMP_OFF: 'provavelmente desligado (ou limitado pelo processador/placa)',
    XMP_ON: 'provavelmente ligado',
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
    XMP_UNKNOWN: 'O Windows não deu informação suficiente para saber.',
}
REASON_MIXED = 'Os módulos de memória informam velocidades diferentes; não dá para saber.'
REASON_UNITS = ('A velocidade configurada é metade da informada pelo módulo; pode ser só diferença '
                'de unidade (MHz e MT/s), então não dá para saber.')
# Motivos que a tela aceita para cada estado (R-32); o de "desligado" com números
# é conferido por _REASON_OFF.
_ACCEPTED_REASONS = {
    XMP_OFF: {_DEFAULT_REASONS[XMP_OFF]},
    XMP_ON: {_DEFAULT_REASONS[XMP_ON]},
    XMP_UNKNOWN: {_DEFAULT_REASONS[XMP_UNKNOWN], REASON_MIXED, REASON_UNITS},
}

_PATHLIKE = re.compile(r'[\\/:]|%|~')
_VERSION_OK = re.compile(r'^[A-Za-z0-9][A-Za-z0-9 ._()\-]*$')
_REASON_OFF = re.compile(r'^A memória está configurada a (\d{1,6}(?:\.\d+)?) MT/s e o módulo informa '
                         r'(\d{1,6}(?:\.\d+)?) MT/s\. O perfil XMP/EXPO pode estar desligado, ou o '
                         r'processador/placa limita a velocidade\.$')
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


def xmp_state(ram):
    """(estado, motivo) a partir de Win32_PhysicalMemory (Speed, ConfiguredClockSpeed).

    "Desligado" só com algum abaixo e nenhum acima; uns abaixo e outros acima é
    "não confirmado" com REASON_MIXED (módulos diferentes), e configurada metade
    exata da informada é "não confirmado" com REASON_UNITS (metade exata).
    """
    modules = _items(ram)
    if not modules:
        return XMP_UNKNOWN, _DEFAULT_REASONS[XMP_UNKNOWN]
    pairs = [(_num(m.get('Speed')), _num(m.get('ConfiguredClockSpeed'))) for m in modules]
    complete = [(s, c) for s, c in pairs if s is not None and c is not None]
    # Metade exata: pode ser o Windows misturando MHz e MT/s; não dá para concluir.
    if any(c * 2 == s for s, c in complete):
        return XMP_UNKNOWN, REASON_UNITS
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
    return {
        'xmp': state,
        'xmp_reason': reason,
        'family': family,
        'bios_version': _version(first.get('SMBIOSBIOSVersion')),
        'bios_year': bios_release_year(first.get('ReleaseDate')),
        'rebar': 'nao_verificado',
        'steps': _steps(family),
    }


def bios_guidance_lines(guidance):
    """Linhas em português simples para a aba de diagnóstico."""
    if not isinstance(guidance, dict):
        guidance = {}
    state = guidance.get('xmp') if guidance.get('xmp') in XMP_LABELS else XMP_UNKNOWN
    reason = guidance.get('xmp_reason')
    # R-32: só aceita os motivos que este módulo gera; qualquer outro texto vira o padrão.
    # R-34: o motivo de "desligado" com números só vale se os números forem coerentes.
    if not (isinstance(reason, str) and (reason in _ACCEPTED_REASONS[state]
                                         or (state == XMP_OFF and _off_reason_ok(reason)))):
        reason = _DEFAULT_REASONS[state]
    family = guidance.get('family') if guidance.get('family') in FAMILY_LABELS else 'desconhecido'
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
             '  Resizable BAR: não verificado nesta versão (veja abaixo como conferir).',
             '  O app não pede para atualizar a BIOS. Se você decidir atualizar, use só o site oficial do '
             'fabricante; atualizar BIOS tem risco (faltar energia no meio pode impedir o PC de ligar).',
             '  Como conferir na BIOS:']
    lines.extend(f'    {number}. {step}' for number, step in enumerate(steps, 1))
    return lines
