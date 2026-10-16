"""Read-only volume-to-disk metadata. No mounting, writes or partition changes.

Microsoft IOCTL_VOLUME_GET_VOLUME_DISK_EXTENTS; CreateFile desired access 0.
Run in a separate process so the GUI collector can enforce a timeout.
"""
import json
import os
import re
import struct
import sys

IOCTL_VOLUME_GET_VOLUME_DISK_EXTENTS = 0x00560000
MAX_EXTENTS = 4096


def parse_extents(raw):
    # Windows ABI: DWORD count + 4-byte padding; DISK_EXTENT = DWORD,
    # 4-byte padding, LARGE_INTEGER offset, LARGE_INTEGER length (24 bytes).
    if len(raw) < 8:
        raise ValueError('Resposta de volume truncada.')
    count = struct.unpack_from('<I', raw)[0]
    if not 1 <= count <= MAX_EXTENTS or len(raw) < 8 + count * 24:
        raise ValueError('Quantidade/tamanho de extensões inválido.')
    rows = []
    for i in range(count):
        number, start, length = struct.unpack_from('<I4xqq', raw, 8 + i * 24)
        if start < 0 or length <= 0:
            raise ValueError('Extensão de volume inválida.')
        rows.append({'disk_number': number, 'starting_offset': start, 'extent_length': length})
    return rows


def query_volume(device_id):
    if os.name != 'nt':
        raise OSError('Consulta disponível somente no Windows.')
    # Only accept GUID volume names obtained from Win32_Volume, never files/devices supplied by a report.
    if not isinstance(device_id, str) or not re.fullmatch(
            r'\\\\\?\\Volume\{[0-9a-fA-F-]{36}\}\\?', device_id):
        raise ValueError('Identificador de volume inválido.')
    import ctypes
    from ctypes import wintypes
    kernel = ctypes.WinDLL('kernel32', use_last_error=True)
    kernel.CreateFileW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD,
                                  ctypes.c_void_p, wintypes.DWORD, wintypes.DWORD, wintypes.HANDLE]
    kernel.CreateFileW.restype = wintypes.HANDLE
    kernel.DeviceIoControl.argtypes = [wintypes.HANDLE, wintypes.DWORD, ctypes.c_void_p,
                                      wintypes.DWORD, ctypes.c_void_p, wintypes.DWORD,
                                      ctypes.POINTER(wintypes.DWORD), ctypes.c_void_p]
    kernel.DeviceIoControl.restype = wintypes.BOOL
    kernel.CloseHandle.argtypes = [wintypes.HANDLE]
    kernel.CloseHandle.restype = wintypes.BOOL
    handle = kernel.CreateFileW(device_id.rstrip('\\'), 0, 3, None, 3, 0, None)
    if handle == ctypes.c_void_p(-1).value:
        raise ctypes.WinError(ctypes.get_last_error())
    try:
        size = 32
        for _ in range(4):
            buffer = ctypes.create_string_buffer(size)
            returned = wintypes.DWORD()
            ok = kernel.DeviceIoControl(handle, IOCTL_VOLUME_GET_VOLUME_DISK_EXTENTS,
                                        None, 0, buffer, size, ctypes.byref(returned), None)
            if ok:
                return parse_extents(buffer.raw[:returned.value])
            error = ctypes.get_last_error()
            if error not in (234, 122):
                raise ctypes.WinError(error)
            count = struct.unpack_from('<I', buffer.raw)[0]
            if count > MAX_EXTENTS:
                raise ValueError('Volume excede o limite de extensões.')
            size = min(8 + MAX_EXTENTS * 24, max(size * 2, 8 + count * 24))
        raise ValueError('Não foi possível obter todas as extensões do volume.')
    finally:
        kernel.CloseHandle(handle)


def collect_extents(volumes, query=query_volume):
    results = []
    for volume in volumes:
        if not isinstance(volume, dict) or not volume.get('device_id'):
            continue
        row = {'device_id': volume['device_id'], 'source': 'IOCTL_VOLUME_GET_VOLUME_DISK_EXTENTS'}
        try:
            row['extents'] = query(volume['device_id'])
            row['status'] = 'mapped'
        except (OSError, ValueError) as exc:
            row.update(status='unmapped', extents=[], error=str(exc)[:250])
        results.append(row)
    return results


if __name__ == '__main__':
    volumes = json.load(sys.stdin)
    print(json.dumps(collect_extents(volumes), ensure_ascii=True))
