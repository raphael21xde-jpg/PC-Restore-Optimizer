"""Gerar o pacote executável (.exe) do PC Restore & Optimizer com PyInstaller (P4-03).

Uso:
    py -3 scripts\\build_exe.py

O pacote é gerado em dist\\PCRestoreOptimizer\\PCRestoreOptimizer.exe (fora do git).
Não inclui preferências, relatórios nem arquivos pessoais.
"""
from __future__ import annotations

import os
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
APP_NAME = 'PCRestoreOptimizer'
FORBIDDEN_NAMES = frozenset({
    'preferencias-v05.json',
    'deteccao-detalhada-v065.json',
    'deteccao-detalhada-v064.json',
    'deteccao-detalhada-v063.json',
    'deteccao-detalhada-v062.json',
    'deteccao-detalhada-v060.json',
    'deteccao-detalhada-v0514.json',
    'otimizacao-diario.json',
    'otimizacao-energia-reversao.json',
    'otimizacao-benchmarks.json',
    'otimizacao-medicoes.json',
})


def build_command(root: Path = ROOT, *, python_executable: str | None = None) -> list[str]:
    """Monta o comando seguro do PyInstaller (--onedir, --noconsole, sem --uac-admin)."""
    root = Path(root).resolve()
    py = python_executable or sys.executable
    entry = root / 'app.py'
    dist_dir = root / 'dist'
    work_dir = root / 'build' / 'pyinstaller'
    spec_dir = root / 'build'
    return [
        str(py), '-m', 'PyInstaller',
        '--noconfirm',
        '--clean',
        '--onedir',
        '--noconsole',
        '--name', APP_NAME,
        '--distpath', str(dist_dir),
        '--workpath', str(work_dir),
        '--specpath', str(spec_dir),
        str(entry),
    ]


def verify_clean_bundle(bundle_dir: Path) -> list[str]:
    """Confere que a pasta gerada não contém preferências, relatórios nem bancos locais."""
    bundle_dir = Path(bundle_dir)
    if not bundle_dir.is_dir():
        return []
    found: list[str] = []
    for dirpath, _dirnames, filenames in os.walk(bundle_dir):
        for name in filenames:
            lowered = name.lower()
            if (lowered in FORBIDDEN_NAMES
                    or lowered.startswith('preferencias-')
                    or lowered.startswith('deteccao-detalhada-')):
                rel = Path(dirpath, name).relative_to(bundle_dir)
                found.append(str(rel))
    return sorted(found)


def run_build(root: Path = ROOT, *, runner=subprocess.run,
              python_executable: str | None = None) -> tuple[int, Path]:
    """Executa o PyInstaller e confere o pacote gerado.

    Devolve `(codigo_saida, caminho_do_exe)`.
    """
    root = Path(root).resolve()
    entry = root / 'app.py'
    if not entry.is_file():
        print('BUILD NÃO FEITO: app.py não foi encontrado na pasta do projeto.')
        return 2, root / 'dist' / APP_NAME / f'{APP_NAME}.exe'

    cmd = build_command(root, python_executable=python_executable)
    result = runner(cmd, cwd=str(root), check=False)
    exe_path = root / 'dist' / APP_NAME / f'{APP_NAME}.exe'
    if result.returncode != 0:
        print(f'BUILD FALHOU: PyInstaller terminou com código {result.returncode}.')
        return result.returncode or 1, exe_path

    if not exe_path.is_file():
        print(f'BUILD INCOMPLETO: {exe_path.name} não foi encontrado em dist\\{APP_NAME}.')
        return 1, exe_path

    forbidden = verify_clean_bundle(exe_path.parent)
    if forbidden:
        print('BUILD RECUSADO: arquivos pessoais ou relatórios encontrados no pacote: '
              + ', '.join(forbidden))
        return 1, exe_path

    print(f'Build concluído: dist\\{APP_NAME}\\{APP_NAME}.exe')
    return 0, exe_path


def main() -> int:
    code, _exe = run_build()
    return code


if __name__ == '__main__':
    raise SystemExit(main())
