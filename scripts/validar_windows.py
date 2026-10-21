"""Validação no Windows de TODOS os branches pendentes, com um comando só.

Uso (Terminal NORMAL, não o de administrador), na pasta do repositório:

    py -3 scripts\\validar_windows.py

O que faz:
1. `git fetch` e lista a `main` e os branches remotos que ainda não estão na
   `main` (fix/, feature/, auto/, automacao/).
2. Para cada commit ainda não validado, cria uma cópia temporária (git
   worktree) e roda a suíte completa: `py -3 -m unittest discover -s tests`.
3. Grava um resumo **sanitizado** (sem nome de usuário, e-mail ou tokens) no
   branch `validacao-windows`, em `resultados/<branch>/<commit>.md`, e envia
   ao GitHub. É desse branch que o ciclo automático lê os resultados.

O que NÃO faz: não muda o seu branch atual, não faz merge, não dispara
GitHub Actions e não toca em discos ou dados reais (os testes usam só pastas
temporárias).
"""
from __future__ import annotations

import argparse
import ctypes
from datetime import datetime, timezone
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
from test_reporter import result_summary, sanitize_for_public_comment  # noqa: E402

RESULT_BRANCH = 'validacao-windows'
PREFIXES = ('fix/', 'feature/', 'auto/', 'automacao/')
SUITE_TIMEOUT = 2 * 60 * 60


def git(*args, cwd=None, check=True):
    # ROOT is read at call time (not bound as a default) so tests can redirect it.
    done = subprocess.run(['git', *args], cwd=cwd or ROOT, capture_output=True, text=True,
                          encoding='utf-8', errors='replace')
    if check and done.returncode != 0:
        raise RuntimeError(f"git {' '.join(args)} falhou: {done.stderr.strip()}")
    return done.stdout.strip()


def is_elevated() -> bool:
    if os.name != 'nt':
        return False
    try:
        return bool(ctypes.windll.shell32.IsUserAnAdmin())
    except OSError:
        return False


def pending_branches() -> list[str]:
    out = git('branch', '-r', '--no-merged', 'origin/main')
    names = []
    for line in out.splitlines():
        name = line.strip()
        if '->' in name or not name.startswith('origin/'):
            continue
        short = name[len('origin/'):]
        if short.startswith(PREFIXES):
            names.append(short)
    return ['main', *sorted(names)]


def slug(branch: str) -> str:
    return re.sub(r'[^A-Za-z0-9._-]+', '_', branch)


def cleanup_stale_worktrees() -> None:
    """Remove worktrees left by an earlier run that crashed (temp pcro-validacao-*)."""
    out = git('worktree', 'list', '--porcelain', check=False)
    for line in out.splitlines():
        if not line.startswith('worktree '):
            continue
        path = Path(line[len('worktree '):].strip())
        if path.parent.name.startswith('pcro-validacao-'):
            git('worktree', 'remove', '--force', str(path), check=False)
            shutil.rmtree(path.parent, ignore_errors=True)
    git('worktree', 'prune', check=False)


def results_worktree(base: Path) -> tuple[Path, str | None]:
    """Detached worktree of the results branch.

    No local branch is checked out (git 2.5x refuses a branch that another,
    possibly stale, worktree holds). Results are pushed with
    HEAD:refs/heads/validacao-windows. Returns (path, temporary branch to
    delete afterwards or None).
    """
    path = base / 'resultados-wt'
    exists = git('ls-remote', '--heads', 'origin', RESULT_BRANCH)
    if exists:
        git('fetch', 'origin', f'+refs/heads/{RESULT_BRANCH}:refs/remotes/origin/{RESULT_BRANCH}')
        git('worktree', 'add', '--detach', str(path), f'origin/{RESULT_BRANCH}')
        return path, None
    temp_branch = f'pcro-validacao-tmp-{base.name[-8:]}'
    git('worktree', 'add', '--detach', str(path), 'origin/main')
    git('checkout', '--orphan', temp_branch, cwd=path)
    git('rm', '-rf', '--quiet', '.', cwd=path)
    (path / 'README.md').write_text(
        '# Resultados da validação no Windows\n\n'
        'Gerado por `scripts/validar_windows.py`. Não editar à mão.\n',
        encoding='utf-8')
    return path, temp_branch


def run_suite(worktree: Path) -> tuple[int, str]:
    env = os.environ.copy()
    env['PYTHONIOENCODING'] = 'utf-8:replace'
    try:
        done = subprocess.run(
            [sys.executable, '-m', 'unittest', 'discover', '-s', 'tests'],
            cwd=worktree, capture_output=True, text=True, encoding='utf-8',
            errors='replace', env=env, timeout=SUITE_TIMEOUT)
        return done.returncode, done.stdout + done.stderr
    except subprocess.TimeoutExpired as exc:
        log = (exc.stdout or '') + (exc.stderr or '')
        if isinstance(log, bytes):
            log = log.decode('utf-8', 'replace')
        return 124, log + '\nTEMPO ESGOTADO\n'


def failure_lines(log: str) -> list[str]:
    return [line for line in log.splitlines() if re.match(r'^(ERROR|FAIL):', line)]


def write_result(results: Path, branch: str, sha: str, code: int, log: str) -> Path:
    folder = results / 'resultados' / slug(branch)
    folder.mkdir(parents=True, exist_ok=True)
    clean = sanitize_for_public_comment(log)
    status = 'PASSOU' if code == 0 else 'FALHOU'
    body = [
        f'# {branch} @ {sha[:12]}',
        '',
        f'- Status: **{status}** (código {code})',
        f"- Data UTC: {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M')}",
        f'- Python: {sys.version.split()[0]} · Windows: {sys.getwindowsversion().build if os.name == "nt" else "n/a"}',
        '- Comando: `py -3 -m unittest discover -s tests`',
        '',
        '## Resumo',
        '```',
        sanitize_for_public_comment(result_summary(log)),
        '```',
        '',
        '## Falhas e erros',
        *([f'- `{x}`' for x in failure_lines(clean)] or ['- nenhum']),
        '',
        '## Final do log (sanitizado)',
        '```',
        clean[-20000:],
        '```',
    ]
    target = folder / f'{sha[:12]}.md'
    target.write_text('\n'.join(body) + '\n', encoding='utf-8')
    return target


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description='Valida no Windows todos os branches pendentes.')
    parser.add_argument('--sem-enviar', action='store_true',
                        help='Roda e grava localmente, mas não envia ao GitHub.')
    parser.add_argument('--refazer', action='store_true',
                        help='Roda de novo mesmo os commits já validados.')
    args = parser.parse_args(argv)
    if is_elevated():
        print('Rode num Terminal NORMAL (não de administrador). '
              'Como administrador, os testes de permissão dão resultado diferente do uso real.')
        return 2
    git('fetch', 'origin', '--prune')
    cleanup_stale_worktrees()
    branches = pending_branches()
    base = Path(tempfile.mkdtemp(prefix='pcro-validacao-'))
    results = base / 'resultados-wt'
    temp_branch = None
    summary = []
    try:
        results, temp_branch = results_worktree(base)
        for branch in branches:
            sha = git('rev-parse', f'origin/{branch}')
            done_file = results / 'resultados' / slug(branch) / f'{sha[:12]}.md'
            if done_file.exists() and not args.refazer:
                summary.append((branch, sha, 'já validado'))
                continue
            wt = base / f'wt-{slug(branch)}'
            print(f'\n=== {branch} @ {sha[:12]} ===', flush=True)
            git('worktree', 'add', '--detach', str(wt), sha)
            try:
                code, log = run_suite(wt)
            finally:
                git('worktree', 'remove', '--force', str(wt), check=False)
            write_result(results, branch, sha, code, log)
            summary.append((branch, sha, f"{'PASSOU' if code == 0 else 'FALHOU'} · {result_summary(log).splitlines()[-1]}"))
            print(summary[-1][2], flush=True)
        git('add', '-A', cwd=results)
        if git('status', '--porcelain', cwd=results):
            git('commit', '-q', '-m', 'test(windows): resultados da validação [skip ci]', cwd=results)
            if not args.sem_enviar:
                git('push', '-q', 'origin', f'HEAD:refs/heads/{RESULT_BRANCH}', cwd=results)
    finally:
        git('worktree', 'remove', '--force', str(results), check=False)
        shutil.rmtree(base, ignore_errors=True)
        git('worktree', 'prune', check=False)
        if temp_branch:
            git('branch', '-D', temp_branch, check=False)
    print('\nResumo:')
    for branch, sha, text in summary:
        print(f'  {branch:55} {sha[:8]}  {text}')
    print('\nResultados enviados ao branch', RESULT_BRANCH if not args.sem_enviar else '(não enviados)')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
