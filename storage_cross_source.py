"""Read-only reconciliation of conflicting Windows storage evidence.

Models uncertainty instead of guessing a physical disk or active EFI.
Never clears reinstall/format or backup-destination preflight requirements.
"""
from __future__ import annotations


def _valid_disk_number(value):
    return value if type(value) is int and 0 <= value < 65536 else None


def assess_cross_source_storage(disks, extents_mapping, partitions_mapping, boot_layout):
    """Join three independent metadata views, with conservative conclusions."""
    listed = {number for disk in disks if isinstance(disk, dict)
              if (number := _valid_disk_number(disk.get('Number'))) is not None}
    extents = extents_mapping.get('volumes', []) if isinstance(extents_mapping, dict) else []
    partitions = partitions_mapping.get('letter_mapping', []) if isinstance(partitions_mapping, dict) else []
    boot_layout = boot_layout if isinstance(boot_layout, dict) else {}

    partition_by_letter = {}
    for p in partitions:
        if not isinstance(p, dict):
            continue
        letter = p.get('letter')
        if isinstance(letter, str) and len(letter) == 1 and letter.isascii() and letter.isalpha():
            partition_by_letter[letter.upper()] = {
                x for n in p.get('disk_numbers', []) if (x := _valid_disk_number(n)) is not None
            }

    observed = {}
    hidden_on_unlisted = {}
    conflicts = []
    records = []
    for v in extents:
        if not isinstance(v, dict):
            continue
        nums = {n for value in v.get('disk_numbers', []) if (n := _valid_disk_number(value)) is not None}
        if v.get('status') == 'unknown':
            continue
        letters = [x.upper() for x in v.get('letters', [])
                   if isinstance(x, str) and len(x) == 1 and x.isascii() and x.isalpha()]
        for n in nums:
            entry = observed.setdefault(n, {'letters': set(), 'unmounted_count': 0})
            entry['letters'].update(letters)
            if not letters:
                entry['unmounted_count'] += 1
                if n not in listed:
                    hidden_on_unlisted[n] = hidden_on_unlisted.get(n, 0) + 1
        for letter in letters:
            other = partition_by_letter.get(letter)
            if other and other != nums:
                conflicts.append((letter, sorted(other), sorted(nums)))
        records.append({'letters': sorted(set(letters)), 'disk_numbers': sorted(nums),
                        'source_status': str(v.get('status', 'unknown'))[:48]})

    absent = sorted(set(observed) - listed)
    messages = []
    for n in absent:
        evidence = observed[n]
        letters = ', '.join(x + ':' for x in sorted(evidence['letters'])) or 'nenhuma letra'
        messages.append(
            f'ALERTA: volume(s) no Disco {n} pela API de extensões ({letters}), '
            'mas o Disco não aparece em Get-Disk. Dispositivo físico e saúde ainda não confirmados.')
    for n, count in sorted(hidden_on_unlisted.items()):
        messages.append(
            f'REVISÃO OBRIGATÓRIA: {count} volume(s) sem letra no Disco {n}, '
            'não enumerado em Get-Disk. Não presumir EFI, recuperação nem dispensabilidade.')
    for letter, partition_disks, extent_disks in conflicts:
        messages.append(
            f'CONFLITO: volume {letter}: Get-Partition aponta para '
            f'{partition_disks}, extensões apontam para {extent_disks}. Conferir manualmente.')
    if extents_mapping.get('status') not in ('observed_metadata', 'requires_review'):
        messages.append('Não foi possível validar a consulta de extensões; situação indeterminada.')
    if not records:
        messages.append('Nenhuma extensão utilizável; não interpretar como ausência de discos.')

    windows_boot_disks = {x for n in boot_layout.get('boot_disks', [])
                          if (x := _valid_disk_number(n)) is not None}
    if windows_boot_disks and any(n not in windows_boot_disks for n in hidden_on_unlisted):
        messages.append(
            'RISCO DE INICIALIZAÇÃO: volumes reservados em disco diferente do Windows '
            'em uso. A presença de EFI ativa NÃO foi comprovada; exigir verificação do boot.')
    if boot_layout.get('status') != 'same_disk_reported':
        messages.append(
            'Inicialização Windows/EFI não verificada. Não aprovar reinstalação.')
    spaces = sorted({n for d in disks if isinstance(d, dict)
                     if (n := _valid_disk_number(d.get('Number'))) is not None
                     and str(d.get('BusType', '')).casefold() in ('spaces', 'storage spaces')})
    if spaces:
        messages.append(
            'Storage Spaces: número de disco lógico não informa os dispositivos físicos '
            'nem comprova redundância do destino de backup.')

    return {
        'schema': 'pcro-storage-cross-source-v1',
        'status': 'requires_review',
        'unlisted_extent_disks': absent,
        'unmounted_volumes_on_unlisted_disks': dict(sorted(hidden_on_unlisted.items())),
        'source_conflicts': [{'letter': letter, 'get_partition': a, 'ioctl': b}
                             for letter, a, b in conflicts],
        'reported_records': records,
        'issues': messages,
        'efi_active_verified': False,
        'backup_destination_verified': False,
        'approved_for_format': False,
        'notice': 'Metadados insuficientes para autorizar alterações destrutivas.',
    }
