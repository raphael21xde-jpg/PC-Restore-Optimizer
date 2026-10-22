"""scripts/validar_windows.py against a throwaway local git remote (synthetic only)."""
import contextlib
import importlib.util
import io
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
GIT = shutil.which('git')


def load_module():
    spec = importlib.util.spec_from_file_location('validar_windows', ROOT / 'scripts' / 'validar_windows.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@unittest.skipUnless(GIT, 'git não instalado')
class ValidarWindowsTests(unittest.TestCase):
    def setUp(self):
        # P2-07: the script prints its progress; keep the test run output clean.
        self.enterContext(contextlib.redirect_stdout(io.StringIO()))
        self.tmp = tempfile.TemporaryDirectory()
        base = Path(self.tmp.name)
        self.env = mock.patch.dict(os.environ, {
            'GIT_AUTHOR_NAME': 'Teste', 'GIT_AUTHOR_EMAIL': 'teste@example.invalid',
            'GIT_COMMITTER_NAME': 'Teste', 'GIT_COMMITTER_EMAIL': 'teste@example.invalid',
            'GIT_CONFIG_GLOBAL': os.devnull, 'GIT_CONFIG_NOSYSTEM': '1',
            'PCRO_VALIDACAO_LOCK': str(base / 'pcro-validacao.lock')})
        self.env.start()
        self.remote = base / 'remote.git'
        self.repo = base / 'repo'
        run = lambda *a, cwd=base: subprocess.run(['git', *a], cwd=cwd, check=True, capture_output=True)
        run('init', '-q', '--bare', '-b', 'main', str(self.remote))
        run('init', '-q', '-b', 'main', str(self.repo))
        (self.repo / 'tests').mkdir()
        (self.repo / 'a.txt').write_text('a')
        run('add', '.', cwd=self.repo)
        run('commit', '-q', '-m', 'base', cwd=self.repo)
        run('remote', 'add', 'origin', str(self.remote), cwd=self.repo)
        run('push', '-q', 'origin', 'main', cwd=self.repo)
        run('switch', '-q', '-c', 'fix/exemplo', cwd=self.repo)
        (self.repo / 'b.txt').write_text('b')
        run('add', '.', cwd=self.repo)
        run('commit', '-q', '-m', 'fix', cwd=self.repo)
        run('push', '-q', 'origin', 'fix/exemplo', cwd=self.repo)
        run('push', '-q', 'origin', 'main:outro/ignorado', cwd=self.repo)
        self.mod = load_module()
        self.mod.ROOT = self.repo
        # Safety net: every git call must hit the throwaway repo, never the real one.
        real_git = self.mod.git

        def guarded(*args, cwd=None, check=True):
            target = Path(cwd or self.mod.ROOT).resolve()
            allowed = (str(target).startswith(str(base.resolve()))
                       or Path(target).name.startswith(('resultados-wt', 'wt-'))
                       and Path(target).parent.name.startswith('pcro-validacao-'))
            self.assertTrue(allowed, target)
            return real_git(*args, cwd=cwd, check=check)
        self.mod.git = guarded

    def tearDown(self):
        self.env.stop()
        self.tmp.cleanup()

    def test_runs_pending_branches_and_publishes_sanitized_results(self):
        log = 'Ran 3 tests in 0.1s\nOK\nC:\\Users\\fulano\\x.py token=abc123\n'
        with mock.patch.object(self.mod, 'run_suite', return_value=(0, log)) as suite, \
                mock.patch.object(self.mod, 'is_elevated', return_value=False):
            self.assertEqual(self.mod.main([]), 0)
            self.assertEqual(suite.call_count, 2)  # main + fix/exemplo; outro/ ignorado
            self.assertEqual(self.mod.main([]), 0)  # second run: already validated
            self.assertEqual(suite.call_count, 2)
        files = subprocess.run(['git', 'ls-tree', '-r', '--name-only', 'validacao-windows'],
                               cwd=self.remote, capture_output=True, text=True, check=True).stdout.split()
        self.assertEqual(len([f for f in files if f.startswith('resultados/main/')]), 1)
        self.assertEqual(len([f for f in files if f.startswith('resultados/fix_exemplo/')]), 1)
        content = subprocess.run(['git', 'show', f"validacao-windows:{[f for f in files if 'fix_exemplo' in f][0]}"],
                                 cwd=self.remote, capture_output=True, text=True, check=True).stdout
        self.assertIn('PASSOU', content)
        self.assertNotIn('fulano', content)
        self.assertNotIn('abc123', content)
        # The user's own checkout is untouched.
        branch = subprocess.run(['git', 'branch', '--show-current'], cwd=self.repo,
                                capture_output=True, text=True).stdout.strip()
        self.assertEqual(branch, 'fix/exemplo')

    def test_recovers_from_stale_worktree_holding_the_results_branch(self):
        """Regression (PC do Raphael, 21/10/2026): a crashed run left a worktree
        holding 'validacao-windows'; the next run must still publish."""
        log = 'Ran 1 test in 0.1s\nOK\n'
        with mock.patch.object(self.mod, 'run_suite', return_value=(0, log)), \
                mock.patch.object(self.mod, 'is_elevated', return_value=False):
            self.assertEqual(self.mod.main([]), 0)
            stale = Path(self.tmp.name) / 'pcro-validacao-stale' / 'resultados-wt'
            subprocess.run(['git', 'fetch', '-q', 'origin',
                            '+refs/heads/validacao-windows:refs/remotes/origin/validacao-windows'],
                           cwd=self.repo, check=True)
            subprocess.run(['git', 'worktree', 'add', '-q', '-B', 'validacao-windows', str(stale),
                            'origin/validacao-windows'], cwd=self.repo, check=True)
            (self.repo / 'c.txt').write_text('c')
            subprocess.run(['git', 'add', '.'], cwd=self.repo, check=True)
            subprocess.run(['git', 'commit', '-q', '-m', 'novo'], cwd=self.repo, check=True)
            subprocess.run(['git', 'push', '-q', 'origin', 'fix/exemplo'], cwd=self.repo, check=True)
            self.assertEqual(self.mod.main([]), 0)
        files = subprocess.run(['git', 'ls-tree', '-r', '--name-only', 'validacao-windows'],
                               cwd=self.remote, capture_output=True, text=True, check=True).stdout.split()
        self.assertEqual(len([f for f in files if f.startswith('resultados/fix_exemplo/')]), 2)
        worktrees = subprocess.run(['git', 'worktree', 'list'], cwd=self.repo,
                                   capture_output=True, text=True, check=True).stdout
        self.assertNotIn('pcro-validacao', worktrees)

    def test_skips_old_agent_branches_and_non_agent_prefixes(self):
        run = lambda *a, **kw: subprocess.run(['git', *a], cwd=self.repo, check=True, capture_output=True, **kw)
        run('switch', '-q', '-c', 'auto/velho', 'main')
        (self.repo / 'v.txt').write_text('v')
        run('add', '.')
        old = dict(os.environ, GIT_COMMITTER_DATE='2026-01-01T00:00:00', GIT_AUTHOR_DATE='2026-01-01T00:00:00')
        run('commit', '-q', '-m', 'velho', env=old)
        run('push', '-q', 'origin', 'auto/velho')
        run('switch', '-q', '-c', 'feature/antigo', 'main')
        (self.repo / 'f.txt').write_text('f')
        run('add', '.')
        run('commit', '-q', '-m', 'feature')
        run('push', '-q', 'origin', 'feature/antigo')
        run('fetch', '-q', 'origin')
        self.assertEqual(self.mod.pending_branches(), ['main', 'fix/exemplo'])

    def test_second_run_is_skipped_while_lock_is_held(self):
        lock = Path(os.environ['PCRO_VALIDACAO_LOCK'])
        lock.write_text('outra rodada')
        with mock.patch.object(self.mod, 'run_suite') as suite, \
                mock.patch.object(self.mod, 'is_elevated', return_value=False):
            self.assertEqual(self.mod.main([]), 0)
            suite.assert_not_called()
        self.assertTrue(lock.exists())  # a trava de outra rodada não é apagada

    def test_each_branch_is_published_as_soon_as_it_finishes(self):
        calls = []

        def suite(wt):
            calls.append(wt)
            if len(calls) == 2:
                raise KeyboardInterrupt  # rodada interrompida no 2º branch
            return 0, 'Ran 1 test in 0.1s\nOK\n'
        with mock.patch.object(self.mod, 'run_suite', side_effect=suite), \
                mock.patch.object(self.mod, 'is_elevated', return_value=False):
            with self.assertRaises(KeyboardInterrupt):
                self.mod.main([])
        files = subprocess.run(['git', 'ls-tree', '-r', '--name-only', 'validacao-windows'],
                               cwd=self.remote, capture_output=True, text=True, check=True).stdout.split()
        self.assertEqual(len([f for f in files if f.startswith('resultados/main/')]), 1)
        self.assertFalse(Path(os.environ['PCRO_VALIDACAO_LOCK']).exists())

    def test_refuses_elevated_terminal(self):
        with mock.patch.object(self.mod, 'is_elevated', return_value=True), \
                mock.patch.object(self.mod, 'run_suite') as suite:
            self.assertEqual(self.mod.main([]), 2)
            suite.assert_not_called()


if __name__ == '__main__':
    unittest.main()
