"""v0.6.8: opt-in, bounded review and evidence reconciliation; never authorizes formatting.

Real disk metadata collection is read-only. A validated manifest proves that the
files *listed* in that manifest still match; it does not prove complete selection.
"""
from __future__ import annotations

import base64
from datetime import datetime, timezone
import ntpath
import os
from pathlib import Path
import stat
import subprocess

from completeness_audit_v067 import (build_completeness_report, _within, REPARSE)
from drive_catalog import safe_to_mark
from inventory_import import read_inventory
from scan_sessions import merge_cache
from selective_recovery import verify_complete_manifest
from backup_features import read_manifest

MAX_BROWSE_ITEMS = 100

# Uses both Storage and CIM providers. On dynamic disks Get-Partition may not
# map a volume; CIM still reveals the physical disk and volumes, and the result
# remains inconclusive rather than falsely declaring that there is no EFI.
DISK_QUERY_068 = r'''
$ErrorActionPreference='Continue'
[Console]::OutputEncoding = New-Object System.Text.UTF8Encoding($false)
$errors=@(); $warnings=@(); $windowsDisk=$null
$disks=@(); $efi=@(); $partitions=@(); $volumes=@(); $physical=@(); $legacyVolumes=@()
try { $systemLetter=$env:SystemDrive.TrimEnd(':'); $cp=Get-Partition -DriveLetter $systemLetter -ErrorAction Stop; $windowsDisk=[int]$cp.DiskNumber }
catch { $errors+=('C: '+$_.Exception.Message) }
try { $disks=@(Get-Disk -ErrorAction Stop | ForEach-Object { [pscustomobject]@{
 number=$_.Number; friendly_name=$_.FriendlyName; serial_number=$_.SerialNumber;
 bus_type=([string]$_.BusType); partition_style=([string]$_.PartitionStyle);
 is_boot=$_.IsBoot; is_system=$_.IsSystem } }) }
catch { $errors+=('Get-Disk: '+$_.Exception.Message) }
try { $physical=@(Get-CimInstance Win32_DiskDrive -ErrorAction Stop | ForEach-Object {
 [pscustomobject]@{index=$_.Index; model=$_.Model; serial_number=$_.SerialNumber;
 interface_type=$_.InterfaceType; size_bytes=$_.Size; pnp_device_id=$_.PNPDeviceID} }) }
catch { $errors+=('Win32_DiskDrive: '+$_.Exception.Message) }
try { $partitions=@(Get-Partition -ErrorAction Stop | ForEach-Object {
 [pscustomobject]@{disk_number=$_.DiskNumber; partition_number=$_.PartitionNumber;
 drive_letter=([string]$_.DriveLetter); gpt_type=([string]$_.GptType);
 type=([string]$_.Type); size_bytes=$_.Size; is_system=$_.IsSystem;
 is_boot=$_.IsBoot; is_active=$_.IsActive } }) }
catch { $errors+=('Get-Partition: '+$_.Exception.Message) }
$efi=@($partitions | Where-Object {
 $_.gpt_type -ieq '{c12a7328-f81f-11d2-ba4b-00a0c93ec93b}' -or $_.type -eq 'System'
} | ForEach-Object { [pscustomobject]@{disk_number=$_.disk_number;
 partition_number=$_.partition_number; size_bytes=$_.size_bytes; gpt_type=$_.gpt_type;
 type=$_.type} })
try { $legacyVolumes=@(Get-CimInstance Win32_Volume -ErrorAction Stop | Where-Object {
 $_.DriveType -eq 3 -or $_.SystemVolume -eq $true
} | ForEach-Object { [pscustomobject]@{letter=$_.DriveLetter;
 label=$_.Label; filesystem=$_.FileSystem; capacity=$_.Capacity;
 system_volume=$_.SystemVolume; boot_volume=$_.BootVolume;
 device_id=$_.DeviceID} }) }
catch { $errors+=('Win32_Volume: '+$_.Exception.Message) }
foreach ($letter in @($legacyVolumes | Where-Object { $_.letter } | ForEach-Object { $_.letter.TrimEnd(':') } | Sort-Object -Unique)) {
 try { $p=Get-Partition -DriveLetter $letter -ErrorAction Stop;
  $volumes+= [pscustomobject]@{letter=$letter; disk_number=$p.DiskNumber;
    partition_number=$p.PartitionNumber; source='Get-Partition'} }
 catch { $warnings+=($letter+': Get-Partition não mapeou esta letra (volume dinâmico possível).') }
}
[pscustomobject]@{windows_disk_number=$windowsDisk; disks=@($disks);
 physical_disks=@($physical); partitions=@($partitions);
 efi_partitions=@($efi); volumes=@($volumes);
 legacy_volumes=@($legacyVolumes); warnings=@($warnings);
 errors=@($errors)} | ConvertTo-Json -Depth 8 -Compress
'''


def collect_disk_evidence_068(*, platform=None, runner=None):
    platform = os.name if platform is None else platform
    if platform != 'nt':
        return {'available': False, 'data': {}, 'error': 'Disponível somente no Windows.'}
    runner = runner or subprocess.run
    encoded = base64.b64encode(DISK_QUERY_068.encode('utf-16le')).decode('ascii')
    try:
        result = runner(['powershell.exe', '-NoProfile', '-NonInteractive',
                         '-EncodedCommand', encoded], capture_output=True,
                        text=True, encoding='utf-8', errors='replace', timeout=75)
        if result.returncode:
            raise RuntimeError((result.stderr or '')[:350] or 'Consulta PowerShell falhou.')
        import json
        data = json.loads(result.stdout.lstrip('\ufeff'))
        if not isinstance(data, dict):
            raise ValueError('Resposta Windows inválida.')
        for key in ('disks', 'physical_disks', 'partitions', 'efi_partitions', 'volumes',
                    'legacy_volumes', 'warnings', 'errors'):
            value = data.get(key, [])
            data[key] = value if isinstance(value, list) else ([] if value is None else [value])
        return {'available': True, 'data': data, 'error': ''}
    except (OSError, RuntimeError, ValueError, subprocess.TimeoutExpired) as exc:
        return {'available': False, 'data': {}, 'error': str(exc)[:350]}


def classify_boot_068(evidence):
    """Do not equate disk presence or a 'System' partition with proven boot."""
    if not evidence.get('available'):
        return {'status': 'NÃO VERIFICADO', 'note': evidence.get('error', 'Coleta indisponível.'),
                'windows_disk_number': None, 'efi_disk_numbers': [], 'manual_boot_test_needed': True}
    data = evidence.get('data', {})
    win = data.get('windows_disk_number')
    efi = sorted({row.get('disk_number') for row in data.get('efi_partitions', [])
                  if isinstance(row, dict) and isinstance(row.get('disk_number'), int)})
    system_candidates = [v for v in data.get('legacy_volumes', [])
                         if isinstance(v, dict) and v.get('system_volume') is True]
    mapped_letters = {str(v.get('letter', '')).rstrip(':').upper() for v in data.get('volumes', []) if isinstance(v, dict)}
    unmapped = any(isinstance(v, dict) and v.get('letter') and str(v['letter']).rstrip(':').upper() not in mapped_letters for v in data.get('legacy_volumes', []))
    if win is None:
        status, note = 'NÃO VERIFICADO', 'Disco do C: não identificado pela consulta.'
    elif not efi:
        status, note = ('MAPEAMENTO INCOMPLETO',
                        'Nenhuma EFI foi mapeada a disco físico. Volumes dinâmicos podem não aparecer no Get-Partition. '
                        'Isso NÃO significa que a EFI não exista.')
    elif win not in efi:
        status, note = ('DEPENDÊNCIA POSSÍVEL',
                        'EFI encontrada em outro disco. A consulta não prova qual EFI está sendo utilizada. Não alterar discos.')
    elif len(efi) > 1:
        status, note = 'REVISAR', 'Mais de uma EFI mapeada; EFI efetivamente usada não confirmada.'
    else:
        status, note = 'TESTE MANUAL NECESSÁRIO', 'EFI detectada no disco do C:, mas boot independente NÃO comprovado.'
    if unmapped or system_candidates:
        note += ' Conferir volumes FAT32/Sistema e associação do disco correspondente no Gerenciamento de Disco.'
    return {'status': status, 'note': note, 'windows_disk_number': win,
            'efi_disk_numbers': efi, 'system_volume_candidates': system_candidates,
            'physical_disks_detected': len(data.get('physical_disks', [])),
            'manual_boot_test_needed': True}


def inspect_children_once(folder, *, offset=0, limit=MAX_BROWSE_ITEMS):
    """At most one immediate directory page, never recursively enters a folder."""
    if offset < 0 or limit < 1 or limit > MAX_BROWSE_ITEMS:
        raise ValueError('Página inválida.')
    p = Path(folder)
    info = p.lstat()
    if not stat.S_ISDIR(info.st_mode) or stat.S_ISLNK(info.st_mode) or \
            (getattr(info, 'st_file_attributes', 0) & REPARSE):
        raise ValueError('A pasta é link, junção ou não é diretório.')
    rows = []
    from itertools import islice
    with os.scandir(p) as stream:
        for item in islice(stream, offset, offset + limit + 1):
            try:
                meta = item.stat(follow_symlinks=False)
                flag = bool(getattr(meta, 'st_file_attributes', 0) & REPARSE) or item.is_symlink()
                typ = 'LINK — NÃO SEGUIR' if flag else 'PASTA' if stat.S_ISDIR(meta.st_mode) else 'ARQUIVO'
                rows.append({'name': item.name, 'path': item.path, 'type': typ,
                             'bytes': int(meta.st_size) if typ == 'ARQUIVO' else None})
            except OSError as exc:
                rows.append({'name': item.name, 'path': item.path, 'type': 'SEM ACESSO',
                             'reason': type(exc).__name__, 'bytes': None})
    has_more = len(rows) > limit
    return {'rows': rows[:limit], 'has_more': has_more, 'next_offset': offset + limit if has_more else None,
            'note': 'Apenas entradas imediatas. Nenhum conteúdo foi copiado ou selecionado.'}


def safe_review_choice(path, candidate_locations, *, deny_broad=False):
    """Selection only for paths present in the current audit, never a drive root."""
    if not isinstance(path, str) or not safe_to_mark(path) or not ntpath.isabs(path):
        raise ValueError('Caminho inseguro ou não absoluto.')
    if not any(ntpath.normcase(ntpath.normpath(path)) == ntpath.normcase(ntpath.normpath(row.get('path', '')))
               for row in candidate_locations):
        raise ValueError('Escolha fora dos locais auditados.')
    from volume_paths import volume_of
    if volume_of(path) != 'C:':
        raise ValueError('Esta opção só seleciona fontes do C:. Para outro disco, use Meu Computador.')
    if deny_broad and ntpath.basename(ntpath.normpath(path)).casefold() in ('local', 'roaming', 'locallow', 'packages'):
        raise ValueError('Escolha uma subpasta específica deste aplicativo, não todo o AppData.')
    return ntpath.normcase(ntpath.normpath(path))


def import_snapshot_068(filename, existing):
    """Merge only missing volume snapshots. Never reset current selections."""
    imported = read_inventory(filename)
    merged = dict(existing or {})
    added = {}
    for drive, snap in imported.items():
        if drive not in merged:
            merged[drive] = snap
            added[drive] = snap
    return merged, added


def inspect_verified_manifest(path):
    """Actually rehash backed-up bytes; no trust in an exported success report."""
    proof = verify_complete_manifest(path)
    doc = read_manifest(path)
    sources = [x.get('source', '') for x in doc.get('files', []) if isinstance(x, dict)]
    return {**proof, 'verified_source_files': sources,
            'scope_notice': 'Somente arquivos listados no manifesto são comprovados; cobertura do C: NÃO certificada.'}


def enhance_report_068(report, *, proof=None):
    report = dict(report)
    report['schema'] = 'pcro-completeness-audit-v068'
    report['created_utc'] = datetime.now(timezone.utc).isoformat()
    report['backup_evidence'] = {'status': 'NÃO CONFERIDO NESTA SESSÃO', 'files_verified': 0}
    if proof and proof.get('backup_verified') is True:
        sources = proof.get('verified_source_files', [])
        report['backup_evidence'] = {
            'status': 'MANIFESTO VERIFICADO — COBERTURA NÃO COMPROVADA',
            'manifest': proof.get('manifest', ''), 'files_verified': proof.get('files_verified', 0),
            'bytes_verified': proof.get('bytes_verified', 0),
            'matching_selected_paths': [p for p in report.get('selected_c_paths', [])
                                        if any(_within(s, p) for s in sources)],
            'note': proof.get('scope_notice', ''),
        }
    for row in report.get('recovery_map', []):
        row['status'] = 'REVER BACKUP E RECUPERAÇÃO ANTES DE REINSTALAR'
    report.update(ready_for_format=False, installation_authorized=False,
                  deletions_authorized=False, backup_verified=False, restore_verified=False,
                  limitations='Auditoria de metadados não recursiva. Manifesto, quando verificado, certifica só os arquivos listados. '
                              'Não é autorização para reinstalar Windows, apagar dados ou alterar EFI.')
    return report
