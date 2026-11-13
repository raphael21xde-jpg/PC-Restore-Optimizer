# Como gerar o instalador (.exe)

Este documento explica como gerar e testar o pacote executável (`.exe`) do
**PC Restore & Optimizer** no Windows usando o PyInstaller (item P4-03).

> **Aviso importante (build de teste):** este `.exe` é um **build de teste**
> enquanto o achado de subprocesso (`volume_extents.py` chamado via
> `sys.executable` em `storage_extents_diagnostic.py` e `audit_v069.py`) não for
> corrigido num FIX separado. No uso diário, continue abrindo pelo `INICIAR.bat`
> ou `py -3 app.py`.

## 1. Instalar o PyInstaller (uma vez só)

Na pasta do projeto, instale a versão fixada em `requirements-build.txt`:

```powershell
py -3 -m pip install -r requirements-build.txt
```

## 2. Gerar o executável

Rode o script de build:

```powershell
py -3 scripts\build_exe.py
```

O pacote será criado na pasta `dist\PCRestoreOptimizer\` (que fica **fora do git**),
com o executável principal em:

```text
dist\PCRestoreOptimizer\PCRestoreOptimizer.exe
```

## 3. Onde ficam os dados quando o `.exe` roda

Quando você abre o `PCRestoreOptimizer.exe`:
- `preferencias-v05.json`, `deteccao-detalhada-v065.json`, o diário de
  otimização e o progresso do assistente ficam em
  `%LOCALAPPDATA%\PC-Restore-Optimizer\`.
- Quando você abre pelo Python (`INICIAR.bat` ou `py -3 app.py`), nada muda: o
  caminho continua sendo a pasta do projeto, como antes.
- O build não inclui `preferencias-v05.json`, relatórios nem arquivos pessoais.

## 4. Testar o pacote gerado

Depois de gerar o `.exe`, rode o teste do pacote:

```powershell
py -3 -m unittest tests/test_installer_p4_03.py
```

O teste confere que `dist\PCRestoreOptimizer\PCRestoreOptimizer.exe` existe, não
contém arquivos pessoais e abre e fecha sozinho (`--smoke-test`) sem erro e sem
tocar em discos reais.
