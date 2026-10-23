"""Synthetic disk inventories for P2-09 slice 2b tests (no real disk).

Shape follows the collector used by drive_safety_report: Get-Disk rows,
partitions, volumes, extent mapping and Storage Spaces membership. Every
value is made up; serial numbers and models are fake markers so the tests
can check they never leak into texts.
"""
from __future__ import annotations

import copy

FAKE_SERIAL = 'SERIE-FALSA-123'
FAKE_MODEL = 'Modelo Ficticio'

# Disk 0: Windows (boot). Sources A: and B: on disk 1. Targets T: and U:
# on disks 2 and 3. C: is on the boot disk.
DEFAULT_LAYOUT = {'C': 0, 'A': 1, 'B': 1, 'T': 2, 'U': 3}
DEFAULT_BUS = {0: 'NVMe', 1: 'NVMe', 2: 'SATA', 3: 'SATA'}


def fake_inventory(layout=None, bus=None, names=None, boot=(0,)):
    """Return a fresh synthetic inventory dict."""
    layout = dict(DEFAULT_LAYOUT if layout is None else layout)
    bus = dict(DEFAULT_BUS if bus is None else bus)
    names = dict(names or {})
    numbers = sorted(set(layout.values()) | set(bus))
    disks = []
    for number in numbers:
        row = {'Number': number, 'BusType': bus.get(number, 'SATA'),
               'FriendlyName': names.get(number, f'{FAKE_MODEL} {number}'),
               'SerialNumber': f'{FAKE_SERIAL}-{number}'}
        if number in boot:
            row.update(IsBoot=True, IsSystem=True)
        disks.append(row)
    partitions = []
    for letter, number in layout.items():
        item = {'DriveLetter': letter, 'DiskNumber': number}
        if number in boot and letter == 'C':
            item['IsBoot'] = True
        partitions.append(item)
    return {
        'disks': disks,
        'partitions': partitions,
        'volumes': [{'DriveLetter': letter, 'SizeRemaining': 100 * 1024 ** 3,
                     'Path': '\\\\?\\Volume{falso}\\'}
                    for letter in layout],
        'extent_mapping': {'volumes': [
            {'letters': [letter], 'disk_numbers': [number],
             'status': 'logical_disk_reported'}
            for letter, number in layout.items()]},
        'spaces_membership': {},
    }


class CountingCollector:
    """Collector stand-in that counts calls and can change between calls."""

    def __init__(self, *inventories, error=None):
        self.inventories = list(inventories) or [fake_inventory()]
        self.error = error
        self.calls = 0

    def __call__(self):
        self.calls += 1
        if self.error is not None:
            raise self.error
        index = min(self.calls, len(self.inventories)) - 1
        return copy.deepcopy(self.inventories[index])
