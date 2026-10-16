"""Inventário local de aplicativos e atalhos: só leitura, sem alteração de registro.

Aparência na área de trabalho NÃO prova que o aplicativo esteja instalado. A
lista auxilia decisões de REINSTALAÇÃO, não promete migrar executáveis.
"""
from __future__ import annotations
from pathlib import Path
import os
import re

PERIPHERAL_TERMS = (
    'logitech', 'g hub', 'razer', 'synapse', 'steelseries', 'sonar',
    'corsair', 'icue', 'hyperx', 'ngenuity', 'roccat', 'swarm',
    'alienware', 'command center', 'armoury crate', 'msi center',
    'mystic light', 'nzxt cam', 'audeze', 'elgato', 'stream deck',
    'cooler master', 'glorious', 'redragon', 'wooting', 'keychron',
    'asus aura', 'gigabyte control center', 'amd software', 'nvidia app',
)

def category(name, publisher=''):
    joined = f'{name} {publisher}'.casefold()
    return 'Hardware / periféricos' if any(term in joined for term in PERIPHERAL_TERMS) else 'Aplicativo'


def _raw_registry():
    if os.name != 'nt':
        return []
    import winreg
    uninstall = r'SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall'
    locations = ((winreg.HKEY_LOCAL_MACHINE, winreg.KEY_WOW64_64KEY),
                 (winreg.HKEY_LOCAL_MACHINE, winreg.KEY_WOW64_32KEY),
                 (winreg.HKEY_CURRENT_USER, 0))
    def read_string(key, prop):
        try:
            value = winreg.QueryValueEx(key, prop)[0]
            return value.strip() if isinstance(value, str) else ''
        except OSError:
            return ''
    records = []
    for hive, view in locations:
        try:
            root = winreg.OpenKey(hive, uninstall, 0, winreg.KEY_READ | view)
        except OSError:
            continue
        with root:
            for index in range(winreg.QueryInfoKey(root)[0]):
                try:
                    subname = winreg.EnumKey(root, index)
                    with winreg.OpenKey(root, subname) as item:
                        name = read_string(item, 'DisplayName')
                        if not name:
                            continue
                        if read_string(item, 'SystemComponent') == '1':
                            continue
                        try:
                            if winreg.QueryValueEx(item, 'SystemComponent')[0] == 1:
                                continue
                        except OSError:
                            pass
                        parent = read_string(item, 'ParentKeyName')
                        release = read_string(item, 'ReleaseType').casefold()
                        if parent or release in ('security update', 'update rollup', 'hotfix'):
                            continue
                        publisher = read_string(item, 'Publisher')
                        records.append({'name': name, 'publisher': publisher,
                                        'version': read_string(item, 'DisplayVersion'),
                                        'install_location': read_string(item, 'InstallLocation'),
                                        'display_icon': read_string(item, 'DisplayIcon'),
                                        'uninstall_command': read_string(item, 'UninstallString'),
                                        'category': category(name, publisher),
                                        'source': 'Registro de aplicativos instalados',
                                        'id': f'reg:{hive}:{view}:{subname}'.casefold()})
                except OSError:
                    continue
    return records


def find_desktop_shortcuts():
    """Atalhos são só candidatos, não equivalem a programas instalados."""
    if os.name != 'nt':
        return []
    home = Path(os.getenv('USERPROFILE', str(Path.home())))
    folders = [home / 'Desktop', home / 'OneDrive' / 'Desktop']
    public = os.getenv('PUBLIC')
    if public:
        folders.append(Path(public) / 'Desktop')
    for key in ('OneDrive', 'OneDriveConsumer'):
        if os.getenv(key):
            folders.append(Path(os.environ[key]) / 'Desktop')
    found = []
    seen = set()
    for folder in folders:
        if not folder.is_dir():
            continue
        try:
            files = list(folder.iterdir())
        except OSError:
            continue
        for path in files:
            if path.suffix.casefold() not in ('.lnk', '.url', '.exe') or not path.is_file():
                continue
            stem = path.stem.strip()
            if not stem or stem.casefold() in seen:
                continue
            seen.add(stem.casefold())
            found.append({'name': stem, 'category': category(stem),
                          'source': 'Atalho/arquivo encontrado na área de trabalho',
                          'path': str(path), 'status': 'não confirma instalação'})
    return sorted(found, key=lambda r: r['name'].casefold())


def discover_apps():
    records = _raw_registry()
    # Duplicações entre as duas visões do registro são comuns.
    dedup = {}
    for record in records:
        key = (re.sub(r'\s+', ' ', record['name']).casefold(),
               record['publisher'].casefold())
        if key not in dedup or (not dedup[key].get('install_location') and record.get('install_location')):
            dedup[key] = record
    return sorted(dedup.values(), key=lambda r: (r['category'] != 'Hardware / periféricos', r['name'].casefold()))


def catalog_summary(apps, shortcuts):
    installed = {re.sub(r'\W+', '', a['name']).casefold() for a in apps}
    extras = [s for s in shortcuts if re.sub(r'\W+', '', s['name']).casefold() not in installed]
    return extras
