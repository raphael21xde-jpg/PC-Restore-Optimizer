"""Read-only simulation of a proposed backup origin, destination and size.

Consumes an existing Windows diagnostic snapshot. No disk I/O, network
requests, cloud upload, restore, copy, formatting, or drive mutations.
A scenario never certifies a destination, physical independence, or boot safety.
"""
from __future__ import annotations

from decimal import Decimal, InvalidOperation, ROUND_CEILING
import re

from backup_target_preflight import assess_backup_target, mark_candidate_boot_risks

GIB = 1024 ** 3
MAX_BYTES = (1 << 63) - 1
GIB_INPUT = re.compile(r'^[0-9]{1,8}(?:[,.][0-9]{1,3})?$')


def parse_gib(value):
    """Accept e.g. '20', '20,5', '0.001'; never float math or negative sizes."""
    if not isinstance(value, str) or not GIB_INPUT.fullmatch(value.strip()):
        raise ValueError('Tamanho inválido: informe GiB como 20 ou 20,5 (máximo 3 casas).')
    try:
        amount = Decimal(value.strip().replace(',', '.'))
    except InvalidOperation as exc:
        raise ValueError('Tamanho inválido.') from exc
    if amount <= 0:
        raise ValueError('Informe um tamanho estimado maior que zero GiB.')
    bytes_value = int((amount * GIB).to_integral_value(rounding=ROUND_CEILING))
    if bytes_value > MAX_BYTES:
        raise ValueError('Tamanho estimado excede o limite do aplicativo.')
    return bytes_value


def _letters(volumes):
    result = set()
    for row in volumes if isinstance(volumes, list) else []:
        if not isinstance(row, dict):
            continue
        text = str(row.get('DriveLetter') or '').strip().upper().rstrip(':')
        if len(text) == 1 and text.isascii() and text.isalpha():
            result.add(text)
    return result


def simulate_backup_preflight(snapshot, *, source_letters, target_letter, estimate_gib):
    """Reconcile an explicit simulated plan with read-only diagnostic evidence.

    Snapshot is the disk_inventory() dict (not the enclosing GUI report).
    Capacity review includes the same minimum reservation as the existing
    backup engine: max(10 GiB, 10% of free space), though capacity can change.
    """
    if not isinstance(snapshot, dict):
        raise ValueError('Execute um diagnóstico de discos antes de simular.')
    volumes = snapshot.get('volumes')
    available = _letters(volumes)
    if not available:
        raise ValueError('Diagnóstico sem volumes reconhecidos; execute a análise novamente.')
    if not isinstance(source_letters, (list, tuple)) or not source_letters or len(source_letters) > 26:
        raise ValueError('Selecione uma ou mais unidades de origem.')
    selected = []
    for source in source_letters:
        if not isinstance(source, str):
            raise ValueError('Letra de origem inválida.')
        code = source.strip().upper().rstrip(':')
        if code not in available:
            raise ValueError('A origem '+repr(code)+' não consta no diagnóstico.')
        if code not in selected:
            selected.append(code)
    if not isinstance(target_letter, str):
        raise ValueError('Letra de destino inválida.')
    target = target_letter.strip().upper().rstrip(':')
    if target not in available:
        raise ValueError('O destino não consta no diagnóstico atual.')
    estimate = parse_gib(estimate_gib)

    assessment = assess_backup_target(
        snapshot.get('disks', []), volumes, snapshot.get('extent_mapping', {}),
        snapshot.get('spaces_membership', {}), target_letter=target,
        source_letters=selected, expected_backup_bytes=estimate)
    result = mark_candidate_boot_risks(
        [assessment], boot_layout=snapshot.get('boot_layout', {}),
        boot_dependency=snapshot.get('boot_dependency', {}),
        firmware_order=snapshot.get('firmware_order', {}))[0]

    blocked = list(result.get('blockers', []))
    free = result.get('free_bytes_reported')
    reserve = max(10 * GIB, free // 10) if type(free) is int and free >= 0 else None
    if free is None or reserve is None:
        capacity = 'unknown'
    elif estimate > max(0, free - reserve):
        capacity = 'insufficient_after_reserve'
        blocked.append('Capacidade reportada não comporta a estimativa mais '
                       'a reserva de segurança de 10 GiB ou 10% do espaço livre.')
    else:
        capacity = 'reported_sufficient_with_reserve'
    usable = max(0, free - reserve) if reserve is not None and type(free) is int else None
    # The basic candidate assessment intentionally does not use a safety reserve.
    # Only its contextual message is stale here: this simulator *does* account
    # for a reserve, without actually reserving space on disk.
    basic_message = 'Espaço reportado é apenas uma estimativa pontual, sem reserva de segurança.'
    result['issues'] = [
        issue for issue in result.get('issues', []) if issue != basic_message
    ]
    if free is not None:
        result['issues'].append(
            'Espaço livre observado em um instante; a reserva simulada '
            'NÃO bloqueia espaço real na unidade.')
    result.update({
        'schema': 'pcro-backup-scenario-readonly-v1',
        'source_letters': selected,
        'expected_backup_bytes': estimate,
        'expected_gib_input': estimate_gib.strip(),
        'capacity_status': capacity,
        'reserve_bytes': reserve,
        'usable_after_reserve_bytes': usable,
        'blockers': list(dict.fromkeys(blocked)),
        'status': 'blocked' if blocked else 'requires_review',
        'preview_only': True,
        'physical_independence_verified': False,
        'bootcurrent_verified': False,
        'backup_destination_verified': False,
        'backup_integrity_verified': False,
        'approved_for_copy': False,
        'approved_for_format': False,
        'notice': ('SIMULAÇÃO SOMENTE LEITURA. A estimativa não veio de arquivos '
                   'selecionados. O espaço pode mudar. Nenhuma cópia, exclusão '
                   'ou formatação foi realizada. A ausência de bloqueio conhecido '
                   'não valida hardware independente, boot ou restauração.')
    })
    return result


def scenario_text(result):
    """Readable section to copy from GUI, without serials, paths or tokens."""
    if not isinstance(result, dict) or result.get('schema') != 'pcro-backup-scenario-readonly-v1':
        raise ValueError('Resultado de simulação inválido.')
    def format_size(n):
        return f'{n / GIB:.2f} GiB ({n} bytes)' if type(n) is int else 'NÃO IDENTIFICADO'
    dest = result.get('target_letter', '?')
    origins = result.get('source_letters', [])
    lines = [
        'SIMULAÇÃO DE DESTINO DE BACKUP — SOMENTE LEITURA:',
        '  Origem(ns) declarada(s): ' + ', '.join(str(x)+':' for x in origins),
        '  Destino declarado: '+str(dest)+':',
        '  Tamanho estimado (informado manualmente): ' +
            format_size(result.get('expected_backup_bytes')),
        '  Espaço livre no diagnóstico: '+format_size(result.get('free_bytes_reported')),
        '  Reserva mínima simulada: '+format_size(result.get('reserve_bytes')),
        '  Espaço considerado após reserva: '+format_size(
            result.get('usable_after_reserve_bytes')),
        '  Avaliação da capacidade: '+str(result.get('capacity_status', 'unknown')),
        '  Resultado: '+str(result.get('status', 'requires_review')),
    ]
    for blocker in result.get('blockers') or []:
        lines.append('  BLOQUEIO: '+str(blocker))
    for risk in result.get('risk_details') or []:
        lines.append('  ATENÇÃO: '+str(risk))
    for issue in result.get('issues') or []:
        if isinstance(issue, str):
            lines.append('  OBSERVAÇÃO: '+issue)
    lines.extend([
        '  Independência física: NÃO VERIFICADA; BootCurrent: NÃO VERIFICADO.',
        '  SHA-256/restauração: NÃO REALIZADOS.',
        '  Esta simulação NÃO autoriza cópia, exclusão, formatação ou reinstalação.'
    ])
    return '\n'.join(lines)
