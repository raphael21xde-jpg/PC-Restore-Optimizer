"""v0.6.7 read-only Windows preservation completeness and EFI dependency audit.

No automatic selection, no filesystem writes, no format/partition commands.
Existing selected paths are *not* equivalent to verified backups.
"""
from __future__ import annotations

from datetime import datetime, timezone
import base64
import itertools
import json
import ntpath
import os
import stat
import subprocess
from pathlib import Path

from scan_gaps import report_by_drive
from volume_paths import volume_of

REPARSE = getattr(stat, 'FILE_ATTRIBUTE_REPARSE_POINT', 0x400)
MAX_SUGGESTIONS = 75


def _within(path, root):
    """Windows path containment; never use unsafe string startswith."""
    try:
        p, r = ntpath.normcase(ntpath.normpath(path)), ntpath.normcase(ntpath.normpath(root))
        return ntpath.commonpath([p, r]) == r and bool(ntpath.splitdrive(p)[0])
    except (ValueError, TypeError):
        return False


def selected_c_paths(plan):
    return [x for x in plan.get('requires_verified_backup', ())
            if isinstance(x, str) and volume_of(x) == 'C:']


def _path_for(base, *parts):
    return ntpath.normpath(ntpath.join(base, *parts))


def discover_candidate_locations(env=None, *, registry_folders=None):
    """Collect *potential* personal-data locations for the CURRENT user only.

    Never claims a folder contains saves and never marks it for backup.
    Returns nothing if the user profile is unavailable; no guessed username.
    """
    env = os.environ if env is None else env
    base = env.get('USERPROFILE', '')
    if not base or volume_of(base) != 'C:':
        return []
    roaming = env.get('APPDATA') or _path_for(base, 'AppData', 'Roaming')
    local = env.get('LOCALAPPDATA') or _path_for(base, 'AppData', 'Local')
    public = []
    for title, pieces in [
        ('Área de Trabalho', ('Desktop',)),
        ('Documentos', ('Documents',)),
        ('Downloads', ('Downloads',)),
        ('Imagens', ('Pictures',)),
        ('Vídeos', ('Videos',)),
        ('Músicas', ('Music',)),
        ('Favoritos do Windows', ('Favorites',)),
        ('Jogos salvos', ('Saved Games',)),
    ]:
        public.append((title, _path_for(base, *pieces), 'PESSOAL'))
    registry_folders = registry_folders or {}
    # The real locations can be redirected (e.g. OneDrive) by Windows.
    for i, (title, path, category) in enumerate(public):
        replacement = registry_folders.get(title)
        if replacement:
            public[i] = (title, ntpath.normpath(replacement), category)
    common = [
        ('AppData Roaming — revisar apps', roaming, 'CONFIGURAÇÕES'),
        ('AppData Local — revisar apps', local, 'CONFIGURAÇÕES'),
        ('AppData LocalLow — revisar apps', _path_for(base, 'AppData', 'LocalLow'), 'CONFIGURAÇÕES'),
        ('Dados de jogos em Documentos', _path_for(base, 'Documents', 'My Games'), 'JOGOS'),
        ('Minecraft Java', _path_for(roaming, '.minecraft'), 'JOGOS'),
        ('osu! clássico (dados locais)', _path_for(local, 'osu!'), 'JOGOS'),
        ('Steam userdata (instalação padrão)', r'C:\Program Files (x86)\Steam\userdata', 'JOGOS'),
        ('Chrome — perfis locais', _path_for(local, 'Google', 'Chrome', 'User Data'), 'NAVEGADORES'),
        ('Edge — perfis locais', _path_for(local, 'Microsoft', 'Edge', 'User Data'), 'NAVEGADORES'),
        ('Firefox — perfis', _path_for(roaming, 'Mozilla', 'Firefox', 'Profiles'), 'NAVEGADORES'),
        ('Brave — perfis locais', _path_for(local, 'BraveSoftware', 'Brave-Browser', 'User Data'), 'NAVEGADORES'),
        ('Opera — perfis', _path_for(roaming, 'Opera Software'), 'NAVEGADORES'),
        ('Pacotes Microsoft Store', _path_for(local, 'Packages'), 'APLICATIVOS'),
    ]
    one = env.get('OneDrive', '')
    if one and volume_of(one) == 'C:':
        common.append(('OneDrive local — sincronização não verificada', one, 'NUVEM'))
    rows = []
    seen = set()
    for name, path, group in itertools.chain(public, common):
        if volume_of(path) not in ('C:', 'D:', 'F:', 'G:'):
            # Unknown or network volume: no automatic inclusion in C: backup.
            continue
        key = ntpath.normcase(ntpath.normpath(path))
        if key not in seen:
            seen.add(key)
            rows.append({'name': name, 'path': path, 'category': group})
    return rows[:MAX_SUGGESTIONS]


def windows_registry_folders():
    """Read HKCU User Shell Folders; never write registry values."""
    if os.name != 'nt':
        return {}
    try:
        import winreg
        key_name = r'Software\Microsoft\Windows\CurrentVersion\Explorer\User Shell Folders'
        aliases = {'Área de Trabalho': 'Desktop', 'Documentos': 'Personal',
                   'Downloads': '{374DE290-123F-4565-9164-39C4925E467B}',
                   'Imagens': 'My Pictures', 'Vídeos': 'My Video',
                   'Músicas': 'My Music', 'Favoritos do Windows': 'Favorites',
                   'Jogos salvos': '{4C5C32FF-BB9D-43B0-BF25-D97D4A0B3AA1}'}
        result = {}
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, key_name) as k:
            for title, key in aliases.items():
                try:
                    value, _ = winreg.QueryValueEx(k, key)
                    if isinstance(value, str) and value:
                        result[title] = os.path.expandvars(value)
                except OSError:
                    continue
        return result
    except OSError:
        return {}


def audit_candidate_rows(candidates, selected_paths, *, lstat=os.lstat, scandir=os.scandir):
    """Fast, bounded metadata checks. A selected directory does not prove copied."""
    selected_paths = list(selected_paths)
    result = []
    for candidate in candidates[:MAX_SUGGESTIONS]:
        path = candidate['path']
        row = dict(candidate)
        row.update(status='REVISAR', detail='Sem inspeção do conteúdo.',
                   covered_by='', backup_verified=False)
        covers = next((p for p in selected_paths if _within(path, p)), '')
        row['covered_by'] = covers
        other_volume = volume_of(path) != 'C:'
        try:
            metadata = lstat(path)
            if stat.S_ISLNK(metadata.st_mode) or (getattr(metadata, 'st_file_attributes', 0) & REPARSE):
                row.update(status='REVISAR LINK', detail='Link/junção: não seguir automaticamente.')
            elif other_volume:
                row.update(status='OUTRA UNIDADE — REVISAR',
                           detail='Local redirecionado fora do C:. Não apagar nem formatar esta unidade.')
            elif stat.S_ISDIR(metadata.st_mode):
                # Only check that at least one entry is present, no recursive crawl.
                with scandir(path) as entries:
                    has_entry = next(entries, None) is not None
                if has_entry:
                    row.update(status='SELECIONADO — NÃO COMPROVADO' if covers else 'REVISAR — NÃO SELECIONADO',
                               detail='Pasta com itens; conteúdo NÃO auditado recursivamente.')
                else:
                    row.update(status='VAZIO', detail='Pasta sem entradas diretas neste momento.')
            elif stat.S_ISREG(metadata.st_mode):
                row.update(status='SELECIONADO — NÃO COMPROVADO' if covers else 'REVISAR — NÃO SELECIONADO',
                           detail='Arquivo presente; conteúdo não verificado.')
            else:
                row.update(status='REVISAR', detail='Tipo especial de arquivo.')
        except FileNotFoundError:
            row.update(status='AUSENTE', detail='Caminho não encontrado. Pode ter sido movido.')
        except PermissionError:
            row.update(status='SEM ACESSO', detail='Acesso negado; não presumir proteção.')
        except OSError as exc:
            row.update(status='ERRO', detail=f'Falha de metadados: {type(exc).__name__}')
        result.append(row)
    return result


# Non-destructive PowerShell query. Disk numbers are session-local, never persistent IDs.
DISK_QUERY = r'''
$ErrorActionPreference = 'Stop'
[Console]::OutputEncoding = New-Object System.Text.UTF8Encoding($false)
$errors = @(); $windowsDisk = $null; $disks = @(); $efi = @(); $volumes = @()
try {
 $p = Get-Partition -DriveLetter C -ErrorAction Stop
 $windowsDisk = [int]$p.DiskNumber
} catch { $errors += ('C: ' + $_.Exception.Message) }
try {
 $disks = @(Get-Disk | ForEach-Object { [pscustomobject]@{number=$_.Number; friendly_name=$_.FriendlyName; serial_number=$_.SerialNumber; bus_type=([string]$_.BusType); partition_style=([string]$_.PartitionStyle); is_boot=$_.IsBoot; is_system=$_.IsSystem} })
} catch { $errors += ('Get-Disk: ' + $_.Exception.Message) }
try {
 $efi = @(Get-Partition | Where-Object { [string]$_.GptType -eq '{c12a7328-f81f-11d2-ba4b-00a0c93ec93b}' } | ForEach-Object { [pscustomobject]@{disk_number=$_.DiskNumber; partition_number=$_.PartitionNumber; size_bytes=$_.Size; gpt_type=([string]$_.GptType)} })
} catch { $errors += ('EFI: ' + $_.Exception.Message) }
foreach ($letter in @('C','D','F','G')) {
 try { $p = Get-Partition -DriveLetter $letter -ErrorAction Stop; $volumes += [pscustomobject]@{letter=$letter; disk_number=$p.DiskNumber; partition_number=$p.PartitionNumber} }
 catch { $errors += ($letter + ': ' + $_.Exception.Message) }
}
[pscustomobject]@{windows_disk_number=$windowsDisk; disks=@($disks); efi_partitions=@($efi); volumes=@($volumes); errors=@($errors)} | ConvertTo-Json -Depth 6 -Compress
'''


def collect_disk_evidence(*, platform=None, runner=None):
    """Read-only Windows disk inventory, never modifies EFI/BCD/volumes."""
    if platform is None:
        platform = os.name
    if platform != 'nt':
        return {'available': False, 'error': 'Somente disponível no Windows.', 'data': {}}
    runner = runner or subprocess.run
    encoded = base64.b64encode(DISK_QUERY.encode('utf-16le')).decode('ascii')
    try:
        completed = runner(['powershell.exe', '-NoProfile', '-NonInteractive',
                            '-EncodedCommand', encoded], capture_output=True,
                           text=True, encoding='utf-8', errors='replace', timeout=60)
        if completed.returncode:
            raise RuntimeError((completed.stderr or '')[:500] or 'PowerShell retornou falha.')
        data = json.loads(completed.stdout.lstrip('\ufeff'))
        if not isinstance(data, dict):
            raise ValueError('Resposta Windows inválida.')
        for key in ('disks', 'efi_partitions', 'volumes', 'errors'):
            item = data.get(key, [])
            data[key] = item if isinstance(item, list) else ([item] if item is not None else [])
        return {'available': True, 'data': data, 'error': ''}
    except (OSError, RuntimeError, ValueError, subprocess.TimeoutExpired) as exc:
        return {'available': False, 'error': str(exc)[:500], 'data': {}}


def classify_boot_evidence(evidence):
    """An EFI on C:'s disk is not *proof* of independent boot."""
    if not evidence.get('available'):
        return {'status': 'NÃO VERIFICADO', 'note': evidence.get('error') or 'Coleta indisponível',
                'windows_disk_number': None, 'efi_disk_numbers': [], 'manual_boot_test_needed': True}
    data = evidence.get('data', {})
    windows_disk = data.get('windows_disk_number')
    efi_disks = sorted({x.get('disk_number') for x in data.get('efi_partitions', [])
                        if isinstance(x, dict) and x.get('disk_number') is not None})
    if windows_disk is None:
        status, note = 'NÃO VERIFICADO', 'Não foi possível identificar o disco físico do C:.'
    elif not efi_disks:
        status, note = 'REVISAR', 'Nenhuma partição EFI GPT foi identificada pela consulta.'
    elif windows_disk not in efi_disks:
        status, note = 'DEPENDÊNCIA POSSÍVEL', 'EFI identificada em outro disco, não no disco do Windows (C:). NÃO alterar outros SSDs.'
    elif len(efi_disks) > 1:
        status, note = 'REVISAR', 'EFIs em múltiplos discos. Não é possível determinar a efetivamente utilizada apenas pela lista.'
    else:
        status, note = 'TESTE MANUAL NECESSÁRIO', 'EFI no mesmo disco do C:, mas inicialização independente NÃO comprovada.'
    return {'status': status, 'note': note, 'windows_disk_number': windows_disk,
            'efi_disk_numbers': efi_disks, 'manual_boot_test_needed': True}


def build_completeness_report(plan, scan_report=None, saved_scans=None, *, env=None,
                              candidates=None, lstat=os.lstat, scandir=os.scandir,
                              disk_evidence=None):
    """Build report with explicit unknowns, without starting full disk scans."""
    selected = selected_c_paths(plan)
    candidates = discover_candidate_locations(env, registry_folders=windows_registry_folders()) if candidates is None else candidates
    reviewed = audit_candidate_rows(candidates, selected, lstat=lstat, scandir=scandir)
    gaps = report_by_drive(scan_report or {}, saved_scans or {})
    cg = gaps.get('C:', {})
    c_errors = list(cg.get('errors', []))
    c_skipped = list(cg.get('skipped', []))
    disk_evidence = collect_disk_evidence() if disk_evidence is None else disk_evidence
    boot = classify_boot_evidence(disk_evidence)
    needs_review = [x for x in reviewed if x['status'] in
                    ('REVISAR — NÃO SELECIONADO', 'REVISAR', 'REVISAR LINK', 'SEM ACESSO', 'ERRO',
                     'OUTRA UNIDADE — REVISAR')]
    return {
        'schema': 'pcro-completeness-audit-v067',
        'created_utc': datetime.now(timezone.utc).isoformat(),
        'system_volume': 'C:',
        'selected_c_paths': selected,
        'recovery_map': [
            {'source_path': path,
             'restore_target_after_windows': path,
             'status': 'CÓPIA / RESTAURAÇÃO NÃO COMPROVADAS POR ESTA AUDITORIA',
             'note': 'Restaurar somente após reinstalar o aplicativo correspondente e validar compatibilidade.'}
            for path in selected
        ],
        'candidate_locations': reviewed,
        'counts': {'locations_reviewed': len(reviewed), 'locations_needing_review': len(needs_review),
                   'selected_c_paths': len(selected), 'c_scan_errors': len(c_errors),
                   'c_scan_skipped': len(c_skipped)},
        'scan_c': {'status': cg.get('status', 'SEM INVENTÁRIO'), 'errors': c_errors,
                   'skipped': c_skipped, 'last_scanned_utc': cg.get('last_scanned_utc', ''),
                   'note': 'Inventário antigo ou parcial NÃO garante cobertura completa.'},
        'boot': boot,
        'disk_evidence': disk_evidence,
        'manual_tasks': [
            'Revisar candidatos presentes e não selecionados, inclusive redirecionamentos de pastas pessoais.',
            'Revisar perfis de navegadores, senhas/passkeys e sincronização; copiar pastas não garante restaurar credenciais.',
            'Conferir saves de todos os jogos, inclusive Steam e osu! clássico, e configurações locais dos aplicativos.',
            'Resolver/revisar erros e exclusões relevantes do inventário do C:.',
            'Confirmar backups dos dados escolhidos e recuperação sem sobrescrever originais.',
            'Manter cópia adicional independente e confiável; G: Storage Spaces simples não tem redundância.',
            'Verificar identificação física dos discos e boot EFI independente após plano de reinstalação.',
            'Conferir chave de recuperação de criptografia (se habilitada) e mídia oficial do Windows.',
        ],
        'ready_for_format': False, 'installation_authorized': False,
        'deletions_authorized': False, 'backup_verified': False,
        'restore_verified': False,
        'limitations': ('Somente metadados limitados de locais candidatos; não é varredura completa, '
                        'não adiciona escolhas automaticamente, não abre nem copia arquivos, '
                        'não certifica conteúdo de pastas, saves, EFI ou backup.'),
    }
