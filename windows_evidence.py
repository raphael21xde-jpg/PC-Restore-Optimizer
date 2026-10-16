"""Windows metadata queries; never runs shortcuts or uninstall commands."""
import base64
import json
import os
from pathlib import Path
from scan_scope import in_scope
import subprocess

SCRIPT = r'''
$ErrorActionPreference = 'Stop'
[Console]::OutputEncoding = New-Object System.Text.UTF8Encoding($false)
$w = New-Object -ComObject WScript.Shell
$roots = @([Environment]::GetFolderPath('Desktop'), [Environment]::GetFolderPath('CommonDesktopDirectory'), [Environment]::GetFolderPath('StartMenu'), [Environment]::GetFolderPath('CommonStartMenu'))
$links = @(); $errors = @()
foreach ($root in $roots) {
 if (-not $root) { continue }
 try {
  Get-ChildItem -LiteralPath $root -Filter *.lnk -Recurse -ErrorAction Stop | ForEach-Object {
   try { $s=$w.CreateShortcut($_.FullName); $links += [pscustomobject]@{name=$_.BaseName; path=$_.FullName; target=$s.TargetPath} }
   catch { $errors += $_.Exception.Message }
  }
 } catch { $errors += $_.Exception.Message }
}
$packages = @()
try {
 $packages = @(Get-AppxPackage -ErrorAction Stop | Select-Object Name, PackageFamilyName, InstallLocation, Version, Publisher)
} catch { $errors += $_.Exception.Message }
[pscustomobject]@{shortcuts=@($links); packages=@($packages); errors=@($errors)} | ConvertTo-Json -Depth 5 -Compress
'''


def collect():
    if os.name != 'nt':return {'shortcuts':[],'packages':[],'errors':['Metadados Windows indisponíveis neste sistema.']}
    encoded=base64.b64encode(SCRIPT.encode('utf-16le')).decode('ascii')
    try:
        p=subprocess.run(['powershell.exe','-NoProfile','-NonInteractive','-EncodedCommand',encoded],
                         capture_output=True,text=True,encoding='utf-8',errors='replace',timeout=180)
        if p.returncode:raise ValueError(p.stderr.strip() or 'Consulta Windows falhou.')
        data=json.loads(p.stdout.lstrip('\ufeff'))
        return data
    except (OSError,ValueError,subprocess.TimeoutExpired) as exc:
        return {'shortcuts':[],'packages':[],'errors':[str(exc)]}


def evidence_apps(data, allowed_roots=None):
    apps=[]
    for link in data.get('shortcuts',[]):
        target=link.get('target') or ''
        if (allowed_roots is not None and not in_scope(target, allowed_roots)) or not target.lower().endswith('.exe') or not Path(target).is_file():continue
        apps.append({'id':'shortcut-target:'+link['path'].casefold(),'name':link['name'],
                     'publisher':'','version':'','install_location':str(Path(target).parent),
                     'executable':target,'source':'Destino de atalho resolvido (não executado)', 'category':'Aplicativo / atalho'})
    local=Path(os.getenv('LOCALAPPDATA',''))
    for pkg in data.get('packages',[]):
        family=pkg.get('PackageFamilyName')
        if not family:continue
        if allowed_roots is not None and not in_scope(pkg.get('InstallLocation',''), allowed_roots):continue
        apps.append({'id':'appx:'+family,'name':pkg.get('Name',family),'publisher':pkg.get('Publisher',''),
                     'version':str(pkg.get('Version','')),'install_location':pkg.get('InstallLocation',''),
                     'package_family':family,'package_data':str(local/'Packages'/family),
                     'source':'Pacote Microsoft Store do usuário atual','category':'Microsoft Store'})
    return apps


def executable_metadata(path):
    """Read VERSIONINFO resource through Win32. Never loads/runs the executable."""
    if os.name != 'nt':return {}
    import ctypes
    from ctypes import wintypes
    version=ctypes.WinDLL('version',use_last_error=True)
    version.GetFileVersionInfoSizeW.argtypes=[wintypes.LPCWSTR,ctypes.POINTER(wintypes.DWORD)]
    version.GetFileVersionInfoSizeW.restype=wintypes.DWORD
    version.GetFileVersionInfoW.argtypes=[wintypes.LPCWSTR,wintypes.DWORD,wintypes.DWORD,ctypes.c_void_p]
    version.GetFileVersionInfoW.restype=wintypes.BOOL
    version.VerQueryValueW.argtypes=[ctypes.c_void_p,wintypes.LPCWSTR,ctypes.POINTER(ctypes.c_void_p),ctypes.POINTER(wintypes.UINT)]
    version.VerQueryValueW.restype=wintypes.BOOL
    size=version.GetFileVersionInfoSizeW(str(path),None)
    if not size or size>4*1024**2:return {}
    buf=ctypes.create_string_buffer(size)
    if not version.GetFileVersionInfoW(str(path),0,size,buf):return {}
    ptr=ctypes.c_void_p();length=wintypes.UINT()
    translations=[]
    if version.VerQueryValueW(buf,'\\VarFileInfo\\Translation',ctypes.byref(ptr),ctypes.byref(length)) and length.value>=4:
        raw=ctypes.string_at(ptr,length.value)
        translations=[f'{int.from_bytes(raw[n:n+2],"little"):04x}{int.from_bytes(raw[n+2:n+4],"little"):04x}' for n in range(0,len(raw)-3,4)]
    result={}
    for field in ('ProductName','CompanyName','FileVersion','OriginalFilename'):
        for tr in translations or ['040904b0']:
            if version.VerQueryValueW(buf,'\\StringFileInfo\\'+tr+'\\'+field,ctypes.byref(ptr),ctypes.byref(length)) and ptr.value and length.value:
                result[field]=ctypes.wstring_at(ptr,length.value).rstrip('\x00');break
    return result
