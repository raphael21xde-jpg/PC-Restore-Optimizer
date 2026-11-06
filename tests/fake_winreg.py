"""Registro do Windows falso, só em memória, para os testes do P3-04.

Imita o pedaço do módulo ``winreg`` que ``safe_tweaks`` usa. Nunca toca no
registro de verdade. ``DeleteKey`` e qualquer acesso fora de HKCU falham o teste.
"""


class FakeKey:
    def __init__(self, registry, path):
        self.registry = registry
        self.path = path

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
    REG_BINARY = 3
    REG_DWORD = 4
    REG_QWORD = 11
    KEY_READ = 0x20019
    KEY_SET_VALUE = 0x0002

    def __init__(self):
        self.keys = {}       # caminho em minúsculas -> {nome do valor: (valor, tipo)}
        self.calls = []
        self.fail_set = set()   # nomes de valor cuja gravação falha (OSError)
        self.fail_read = set()  # nomes de valor cuja leitura falha (PermissionError)
        self.ignore_set = set() # nomes de valor cuja gravação "some" (não confirma)

    # ---------- ajuda dos testes ----------
    def put(self, path, name, value, kind=None):
        self.keys.setdefault(path.lower(), {})[name] = (value, self.REG_DWORD if kind is None else kind)

    def get(self, path, name):
        return self.keys.get(path.lower(), {}).get(name)

    # ---------- API do winreg ----------
    def _hive(self, hive):
        if hive != self.HKEY_CURRENT_USER:
            raise AssertionError('acesso fora de HKCU em teste')

    def OpenKey(self, hive, path, reserved=0, access=KEY_READ):
        self._hive(hive)
        self.calls.append(('OpenKey', path, access))
        if path.lower() not in self.keys:
            raise FileNotFoundError(2, 'O sistema não pode encontrar o arquivo especificado')
        return FakeKey(self, path.lower())

    def CreateKeyEx(self, hive, path, reserved=0, access=KEY_READ):
        self._hive(hive)
        self.calls.append(('CreateKeyEx', path, access))
        self.keys.setdefault(path.lower(), {})
        return FakeKey(self, path.lower())

    def QueryValueEx(self, key, name):
        self.calls.append(('QueryValueEx', key.path, name))
        if name in self.fail_read:
            raise PermissionError(5, r'Acesso negado C:\Users\Fulano')
        values = self.keys.get(key.path)
        if values is None or name not in values:
            raise FileNotFoundError(2, 'não existe')
        return values[name]

    def SetValueEx(self, key, name, reserved, kind, value):
        self.calls.append(('SetValueEx', key.path, name, kind, value))
        if name in self.fail_set:
            raise OSError(5, r'Acesso negado C:\Users\Fulano')
        if name in self.ignore_set:
            return
        self.keys.setdefault(key.path, {})[name] = (value, kind)

    def DeleteValue(self, key, name):
        self.calls.append(('DeleteValue', key.path, name))
        values = self.keys.get(key.path)
        if values is None or name not in values:
            raise FileNotFoundError(2, 'não existe')
        del values[name]

    def DeleteKey(self, *args, **kwargs):
        raise AssertionError('o app nunca apaga uma chave do registro')

    DeleteKeyEx = DeleteKey
