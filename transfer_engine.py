"""v0.5.19 - safe transfer tuning and measurements, with no destructive disk actions.

Device evidence is advisory. A SATA bus does NOT imply HDD or SSD, and
physical drive association is accepted only when unambiguous.
"""
from __future__ import annotations
from dataclasses import dataclass
import os
from pathlib import Path
import ntpath
import time

MIB = 1024 * 1024


def _same(a, b):
    return str(a or '').strip().casefold() == str(b or '').strip().casefold()


def classify_drive(path, inventory):
    """Classify a volume only when backed by defensible Windows disk evidence."""
    drive = (ntpath.splitdrive(str(path))[0] or os.path.splitdrive(os.path.abspath(str(path)))[0]).rstrip(':').upper()
    if not drive and os.name != 'nt':
        return 'desconhecido'
    volume_parts = [p for p in inventory.get('partitions', [])
                    if str(p.get('DriveLetter') or '').upper().rstrip(':') == drive]
    nums = {str(p.get('DiskNumber')) for p in volume_parts}
    if len(nums) != 1:
        return 'desconhecido'
    disks = [d for d in inventory.get('disks', []) if str(d.get('Number')) in nums]
    if len(disks) != 1:
        return 'desconhecido'
    disk = disks[0]
    bus = str(disk.get('BusType') or '').lower().strip()
    if bus == 'nvme':
        return 'ssd-nvme'
    if bus in ('spaces', 'iscsi', 'virtual', 'file backed virtual', 'unknown', 'usb', 'raid'):
        return 'desconhecido'
    media = str(disk.get('MediaType') or '').lower()
    physical = inventory.get('physical_disks', [])
    matches = [p for p in physical if
               ((disk.get('SerialNumber') and p.get('SerialNumber') and _same(disk['SerialNumber'], p['SerialNumber'])) or
                (disk.get('FriendlyName') and p.get('FriendlyName') and _same(disk['FriendlyName'], p['FriendlyName'])))]
    if len(matches) == 1:
        media = str(matches[0].get('MediaType') or '').lower()
    elif len(matches) > 1:
        media = ''  # no ambiguous mapping
    if media in ('4', 'ssd', 'solid state drive', 'solid state'):
        return 'ssd-sata' if bus in ('sata', 'ata') else 'ssd'
    if media in ('3', 'hdd', 'hard disk drive'):
        return 'hdd'
    return 'desconhecido'


@dataclass(frozen=True)
class Strategy:
    source: str
    target: str
    chunk: int
    workers: int

    @property
    def description(self):
        return f'{self.source} → {self.target} · bloco {self.chunk // MIB} MiB · {self.workers} fluxo seguro'


def choose_strategy(source, target, inventory=None):
    if inventory is None:
        try:
            from diagnostics import disk_inventory
            inventory = disk_inventory() if os.name == 'nt' else {}
        except Exception:
            inventory = {}
    origin = classify_drive(source, inventory)
    dest = classify_drive(target, inventory)
    # Sequential copy is the safe baseline when source/target may share hardware.
    # On rotational/unknown media, conservative small chunks are used.
    chunk = 8*MIB if origin == dest == 'ssd-nvme' else (4*MIB if origin.startswith('ssd') and dest.startswith('ssd') else MIB)
    return Strategy(origin, dest, chunk, 1)


class TransferMeter:
    def __init__(self, total_bytes, total_files):
        self.started = time.monotonic()
        self.total_bytes = int(total_bytes)
        self.total_files = int(total_files)
        self.bytes_done = 0
        self.files_done = 0

    def snapshot(self, *, bytes_done=None, files_done=None):
        if bytes_done is not None:
            self.bytes_done = int(bytes_done)
        if files_done is not None:
            self.files_done = int(files_done)
        elapsed = max(0, time.monotonic()-self.started)
        speed = self.bytes_done / max(elapsed, .00001)
        eta = ((self.total_bytes-self.bytes_done) / speed if speed > 0 and self.total_bytes > self.bytes_done else 0)
        # With lots of tiny files, also estimate by file rate; choose pessimistic.
        if self.files_done and self.total_files > self.files_done and elapsed > 0:
            eta = max(eta, elapsed*(self.total_files-self.files_done)/self.files_done)
        return dict(elapsed_sec=elapsed, bytes_per_sec=speed, files_per_sec=self.files_done/max(elapsed, .00001),
                    remaining_sec=max(0, eta), bytes_done=self.bytes_done, files_done=self.files_done)


class ProgressLimiter:
    def __init__(self, callback, interval=.15):
        self.callback = callback
        self.interval = interval
        self.previous = 0.0

    def send(self, *args, force=False):
        now = time.monotonic()
        if self.callback and (force or not self.previous or now-self.previous >= self.interval):
            self.previous = now
            self.callback(*args)


def time_text(seconds):
    if seconds is None:
        return '—'
    seconds = max(0, int(seconds))
    return f'{seconds//3600:02d}:{(seconds//60)%60:02d}:{seconds%60:02d}'


def performance_report(performance, status, device, title):
    """Human-readable per-operation report; no external telemetry or network."""
    rate = float(performance.get('bytes_per_sec') or 0)
    return ('PC Restore & Optimizer v0.5.19 - '+title+'\n'
            + '='*50+'\n'
            + f'Estado: {status}\n'
            + f'Armazenamento: {device}\n'
            + f'Tempo da operacao: {time_text(performance.get("elapsed_sec"))}\n'
            + f'Arquivos processados: {int(performance.get("files_done") or 0)}\n'
            + f'Bytes processados: {int(performance.get("bytes_done") or 0)}\n'
            + f'Velocidade media: {rate/MIB:.2f} MiB/s\n'
            + f'Arquivos/s: {float(performance.get("files_per_sec") or 0):.2f}\n'
            + '\nEstimativas sao medias, nao garantias de velocidade.\n')
