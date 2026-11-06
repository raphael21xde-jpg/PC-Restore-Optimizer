"""Registro do Windows falso, só em memória, para os testes do P3-04 e do P3-05.

Imita o pedaço do módulo ``winreg`` que ``safe_tweaks`` e ``advanced_tweaks``
usam. Nunca toca no registro de verdade. ``DeleteKey`` falha o teste.

Por padrão só HKCU é aceito: qualquer acesso a HKLM falha o teste. Com
``FakeWinreg(hives=('HKLM',))`` (P3-05 fatia 2) só HKLM é aceito, e HKCU falha.
HKLM fica num dicionário separado (``machine_keys``): o mesmo caminho em HKCU e
em HKLM são chaves diferentes.
"""


class FakeKey:
    def __init__(self, registry, path, hive='HKCU'):
        self.registry = registry
        self.path = path
        self.hive = hive

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def Close(self):
        pass


class FakeWinreg:
    HKEY_CURRENT_USER = 'HKCU'
    HKEY_LOCAL_MACHINE = 'HKLM'
    REG_SZ = 1
    REG_EXPAND_SZ = 2
    REG_BINARY = 3
    REG_DWORD = 4
    REG_QWORD = 11
    KEY_READ = 0x20019
    KEY_SET_VALUE = 0x0002
    KEY_WOW64_64KEY = 0x0100

    def __init__(self, hives=('HKCU',)):
        self.hives = tuple(hives)
        self.keys = {}       # HKCU: caminho em minúsculas -> {nome do valor: (valor, tipo)}
        self.machine_keys = {}   # HKLM, separado do HKCU
        self.calls = []
        self.fail_set = set()   # nomes de valor cuja gravação falha (OSError)
        self.fail_read = set()  # nomes de valor cuja leitura falha (PermissionError)
        self.ignore_set = set() # nomes de valor cuja gravação "some" (não confirma)

    # ---------- ajuda dos testes ----------
    def _store(self, hive):
        return self.machine_keys if hive == self.HKEY_LOCAL_MACHINE else self.keys

    def put(self, path, name, value, kind=None, hive='HKCU'):
        self._store(hive).setdefault(path.lower(), {})[name] = (
            value, self.REG_DWORD if kind is None else kind)

    def get(self, path, name, hive='HKCU'):
        return self._store(hive).get(path.lower(), {}).get(name)

    # ---------- API do winreg ----------
    def _hive(self, hive):
        if hive not in (self.HKEY_CURRENT_USER, self.HKEY_LOCAL_MACHINE) or hive not in self.hives:
            raise AssertionError(f'acesso a {hive!r} em teste (permitido: {self.hives})')

    def OpenKey(self, hive, path, reserved=0, access=KEY_READ):
        self._hive(hive)
        self.calls.append(('OpenKey', path, access))
        if path.lower() not in self._store(hive):
            raise FileNotFoundError(2, 'O sistema não pode encontrar o arquivo especificado')
        return FakeKey(self, path.lower(), hive)

    def CreateKeyEx(self, hive, path, reserved=0, access=KEY_READ):
        self._hive(hive)
        self.calls.append(('CreateKeyEx', path, access))
        self._store(hive).setdefault(path.lower(), {})
        return FakeKey(self, path.lower(), hive)

    def QueryValueEx(self, key, name):
        self.calls.append(('QueryValueEx', key.path, name))
        if name in self.fail_read:
            raise PermissionError(5, r'Acesso negado C:\Users\Fulano')
        values = self._store(key.hive).get(key.path)
        if values is None or name not in values:
            raise FileNotFoundError(2, 'não existe')
        return values[name]

    def SetValueEx(self, key, name, reserved, kind, value):
        self.calls.append(('SetValueEx', key.path, name, kind, value))
        if name in self.fail_set:
            raise OSError(5, r'Acesso negado C:\Users\Fulano')
        if name in self.ignore_set:
            return
        self._store(key.hive).setdefault(key.path, {})[name] = (value, kind)

    def DeleteValue(self, key, name):
        self.calls.append(('DeleteValue', key.path, name))
        values = self._store(key.hive).get(key.path)
        if values is None or name not in values:
            raise FileNotFoundError(2, 'não existe')
        del values[name]

    def DeleteKey(self, *args, **kwargs):
        raise AssertionError('o app nunca apaga uma chave do registro')

    DeleteKeyEx = DeleteKey
