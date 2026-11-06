"""P3-04 (R-55): o app está aberto com a mesma conta que está usando o PC?

Os ajustes seguros gravam em HKEY_CURRENT_USER, que é o registro da conta do
*processo*. Se o app for aberto como administrador com OUTRA conta (o Windows
pede a senha de outro usuário), o HKCU seria o daquela conta, e não o de quem
está usando o computador. Este módulo só *lê* duas informações do Windows e as
compara:

- o SID da conta do processo (``OpenProcessToken`` + ``GetTokenInformation``
  com ``TokenUser``);
- o SID da conta dona da sessão interativa (``WTSQuerySessionInformationW`` com
  ``WTS_CURRENT_SESSION``, nome de usuário e domínio, e ``LookupAccountNameW``).

A resposta é sempre uma de três: ``SAME`` (mesma conta), ``OTHER`` (outra
conta) ou ``UNKNOWN`` (não deu para saber). Qualquer erro, ou fora do Windows,
é ``UNKNOWN``. Nada é gravado, nenhuma permissão muda, nenhum comando roda.
"""
from __future__ import annotations

import sys

SAME = 'mesma conta'
OTHER = 'outra conta'
UNKNOWN = 'não deu para saber'
ANSWERS = (SAME, OTHER, UNKNOWN)

_TOKEN_QUERY = 0x0008
_TOKEN_USER = 1                 # TOKEN_INFORMATION_CLASS.TokenUser
_WTS_CURRENT_SESSION = 0xFFFFFFFF
_WTS_USER_NAME = 5              # WTS_INFO_CLASS.WTSUserName
_WTS_DOMAIN_NAME = 7            # WTS_INFO_CLASS.WTSDomainName


def _wts_text(wtsapi32, info_class):
    """Texto da sessão atual (nome de usuário ou domínio); erro = None."""
    import ctypes
    from ctypes import wintypes
    buffer = wintypes.LPWSTR()
    size = wintypes.DWORD()
    if not wtsapi32.WTSQuerySessionInformationW(None, _WTS_CURRENT_SESSION, info_class,
                                                ctypes.byref(buffer), ctypes.byref(size)):
        return None
    try:
        return buffer.value
    finally:
        wtsapi32.WTSFreeMemory(buffer)


def _windows_probe() -> str:
    """Só leitura, via ctypes. Qualquer falha = UNKNOWN."""
    import ctypes
    from ctypes import wintypes

    advapi32 = ctypes.WinDLL('advapi32', use_last_error=True)
    kernel32 = ctypes.WinDLL('kernel32', use_last_error=True)
    wtsapi32 = ctypes.WinDLL('wtsapi32', use_last_error=True)

    kernel32.GetCurrentProcess.restype = wintypes.HANDLE
    kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
    advapi32.OpenProcessToken.argtypes = [wintypes.HANDLE, wintypes.DWORD,
                                          ctypes.POINTER(wintypes.HANDLE)]
    advapi32.OpenProcessToken.restype = wintypes.BOOL
    advapi32.GetTokenInformation.argtypes = [wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p,
                                             wintypes.DWORD, ctypes.POINTER(wintypes.DWORD)]
    advapi32.GetTokenInformation.restype = wintypes.BOOL
    advapi32.LookupAccountNameW.argtypes = [wintypes.LPCWSTR, wintypes.LPCWSTR, ctypes.c_void_p,
                                            ctypes.POINTER(wintypes.DWORD), wintypes.LPWSTR,
                                            ctypes.POINTER(wintypes.DWORD),
                                            ctypes.POINTER(ctypes.c_int)]
    advapi32.LookupAccountNameW.restype = wintypes.BOOL
    advapi32.IsValidSid.argtypes = [ctypes.c_void_p]
    advapi32.IsValidSid.restype = wintypes.BOOL
    advapi32.EqualSid.argtypes = [ctypes.c_void_p, ctypes.c_void_p]
    advapi32.EqualSid.restype = wintypes.BOOL
    wtsapi32.WTSQuerySessionInformationW.argtypes = [wintypes.HANDLE, wintypes.DWORD, ctypes.c_int,
                                                     ctypes.POINTER(wintypes.LPWSTR),
                                                     ctypes.POINTER(wintypes.DWORD)]
    wtsapi32.WTSQuerySessionInformationW.restype = wintypes.BOOL
    wtsapi32.WTSFreeMemory.argtypes = [ctypes.c_void_p]
    wtsapi32.WTSFreeMemory.restype = None

    # 1) SID da conta do processo.
    token = wintypes.HANDLE()
    if not advapi32.OpenProcessToken(kernel32.GetCurrentProcess(), _TOKEN_QUERY,
                                     ctypes.byref(token)):
        return UNKNOWN
    try:
        needed = wintypes.DWORD()
        advapi32.GetTokenInformation(token, _TOKEN_USER, None, 0, ctypes.byref(needed))
        if not needed.value:
            return UNKNOWN
        token_user = ctypes.create_string_buffer(needed.value)
        if not advapi32.GetTokenInformation(token, _TOKEN_USER, token_user, needed,
                                            ctypes.byref(needed)):
            return UNKNOWN
        # TOKEN_USER começa com SID_AND_ATTRIBUTES, cujo primeiro campo é o ponteiro do SID.
        process_sid = ctypes.cast(token_user, ctypes.POINTER(ctypes.c_void_p))[0]
        if not process_sid or not advapi32.IsValidSid(process_sid):
            return UNKNOWN

        # 2) SID da conta dona da sessão interativa.
        user = _wts_text(wtsapi32, _WTS_USER_NAME)
        domain = _wts_text(wtsapi32, _WTS_DOMAIN_NAME)
        if not user:
            return UNKNOWN
        account = f'{domain}\\{user}' if domain else user
        sid_size = wintypes.DWORD()
        domain_size = wintypes.DWORD()
        use = ctypes.c_int()
        advapi32.LookupAccountNameW(None, account, None, ctypes.byref(sid_size), None,
                                    ctypes.byref(domain_size), ctypes.byref(use))
        if not sid_size.value or not domain_size.value:
            return UNKNOWN
        session_sid = ctypes.create_string_buffer(sid_size.value)
        domain_buffer = ctypes.create_unicode_buffer(domain_size.value)
        if not advapi32.LookupAccountNameW(None, account, session_sid, ctypes.byref(sid_size),
                                           domain_buffer, ctypes.byref(domain_size),
                                           ctypes.byref(use)):
            return UNKNOWN
        if not advapi32.IsValidSid(session_sid):
            return UNKNOWN
        return SAME if advapi32.EqualSid(process_sid, session_sid) else OTHER
    finally:
        kernel32.CloseHandle(token)


def session_owner(probe=None) -> str:
    """``SAME``, ``OTHER`` ou ``UNKNOWN``. ``probe`` é injetável nos testes.

    Uma resposta fora das três, uma exceção ou um sistema que não é Windows
    vira ``UNKNOWN`` (na dúvida, o app não mexe)."""
    try:
        if probe is not None:
            answer = probe()
        elif sys.platform != 'win32':
            return UNKNOWN
        else:
            answer = _windows_probe()
    except Exception:
        return UNKNOWN
    return answer if isinstance(answer, str) and answer in ANSWERS else UNKNOWN
