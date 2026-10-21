"""P2-10: medição de cópia (copy_bench + scripts/medir_copia.py).

Tudo sintético: origem e destino ficam dentro de TemporaryDirectory, o
espaço livre é simulado (``usage`` falso) e o relógio também, quando o teste
confere velocidades. Nada consulta discos ou hardware reais.
"""
import contextlib
import datetime
import hashlib
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
import types
import unittest
from unittest import mock

import copy_bench

MIB = 1024 * 1024
GIB = 1024 * MIB
ROOT = Path(__file__).resolve().parents[1]


def plenty(_path):
    return types.SimpleNamespace(total=1000 * GIB, used=0, free=900 * GIB)


def snapshot(folder):
    result = {}
    for path in sorted(Path(folder).rglob('*')):
        if path.is_file() and not path.is_symlink():
            data = path.read_bytes()
            stat = path.stat()
            result[str(path.relative_to(folder))] = (
                hashlib.sha256(data).hexdigest(), stat.st_size, stat.st_mtime_ns)
    return result


def make_source(folder, sizes):
    folder = Path(folder)
    folder.mkdir(parents=True, exist_ok=True)
    for index, size in enumerate(sizes):
        sub = folder / ('sub%d' % (index % 3))
        sub.mkdir(exist_ok=True)
        (sub / ('arquivo%03d.dat' % index)).write_bytes(
            bytes((index + i) % 251 for i in range(size)))
    return folder


class TickClock:
    """Relógio falso: cada chamada avança exatamente 1 segundo."""

    def __init__(self):
        self.now = 0.0

    def __call__(self):
        self.now += 1.0
        return self.now


class Base(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp = Path(self._tmp.name)
        self.origem = self.tmp / 'origem'
        self.destino = self.tmp / 'destino'
        self.destino.mkdir()

    def tearDown(self):
        self._tmp.cleanup()

    def run_bench(self, **kwargs):
        kwargs.setdefault('usage', plenty)
        kwargs.setdefault('chunks', (1,))
        return copy_bench.run_bench(str(self.origem), str(self.destino), **kwargs)


class SourceIsOnlyReadTests(Base):
    def test_origem_igual_antes_e_depois(self):
        make_source(self.origem, [10, 3000, 70000, 0, 5])
        before = snapshot(self.origem)
        result = self.run_bench(chunks=(1, 4))
        self.assertEqual(result.status, 'concluída')
        self.assertEqual(snapshot(self.origem), before)

    def test_so_uma_pasta_nova_no_destino(self):
        make_source(self.origem, [100, 200])
        (self.destino / 'ja-existia.txt').write_text('fica')
        result = self.run_bench()
        entries = sorted(p.name for p in self.destino.iterdir())
        self.assertEqual(entries, sorted(['ja-existia.txt', result.folder_name]))
        self.assertTrue(result.folder_name.startswith('PCRO-MEDICAO-'))
        self.assertEqual((self.destino / 'ja-existia.txt').read_text(), 'fica')
        folder = self.destino / result.folder_name
        self.assertTrue((folder / 'relatorio.txt').is_file())
        self.assertTrue((folder / 'relatorio.json').is_file())

    def test_copias_conferidas_por_sha256(self):
        make_source(self.origem, [1234, 5 * MIB // 2])
        result = self.run_bench(chunks=(1,))
        round_ = result.rounds[0]
        self.assertEqual(round_.files_ok, 2)
        self.assertEqual(round_.mismatches, 0)
        self.assertEqual(round_.bytes, 1234 + 5 * MIB // 2)


class MismatchTests(Base):
    def test_sha256_diferente_conta_divergencia_e_fica_fora_das_velocidades(self):
        make_source(self.origem, [2 * MIB, 2 * MIB])
        real_verify = copy_bench._verify_one
        calls = {'n': 0}

        def flaky_verify(*args, **kwargs):
            calls['n'] += 1
            digest = real_verify(*args, **kwargs)
            return '0' * 64 if calls['n'] == 1 else digest

        with mock.patch.object(copy_bench, '_verify_one', side_effect=flaky_verify):
            result = self.run_bench(clock=TickClock())
        round_ = result.rounds[0]
        self.assertEqual(round_.mismatches, 1)
        self.assertEqual(round_.files_ok, 1)
        self.assertEqual(round_.bytes, 2 * MIB)
        # Só o arquivo conferido entra: 2 MiB em 2 leituras de 1 s.
        self.assertAlmostEqual(round_.read_s, 2.0)
        self.assertAlmostEqual(round_.read_mib_s, 1.0)
        self.assertAlmostEqual(round_.write_mib_s, 1.0)
        text, data = copy_bench.bench_report(result)
        self.assertIn('não bateram com o original', text)
        self.assertEqual(data['rodadas'][0]['divergencias_sha256'], 1)

    def test_erro_de_leitura_nao_soma_tempo(self):
        make_source(self.origem, [MIB, MIB])
        real_copy = copy_bench._copy_one
        calls = {'n': 0}

        def failing_copy(source, target, size, chunk, clock, cancelled, times):
            calls['n'] += 1
            if calls['n'] == 1:
                times.read_s += 50.0
                raise PermissionError('simulado')
            return real_copy(source, target, size, chunk, clock, cancelled, times)

        with mock.patch.object(copy_bench, '_copy_one', side_effect=failing_copy):
            result = self.run_bench(clock=TickClock())
        round_ = result.rounds[0]
        self.assertEqual(round_.errors, 1)
        self.assertEqual(round_.files_ok, 1)
        self.assertAlmostEqual(round_.read_s, 1.0)


class StoppedAfterFolderTests(Base):
    def test_erro_ao_gravar_relatorio_avisa_que_a_pasta_ficou(self):
        make_source(self.origem, [10])
        with mock.patch.object(copy_bench, '_write_new',
                               side_effect=OSError(28, 'sem espaço')):
            with self.assertRaises(copy_bench.BenchStopped) as ctx:
                self.run_bench()
        name = ctx.exception.folder_name
        self.assertTrue(name.startswith('PCRO-MEDICAO-'))
        self.assertTrue((self.destino / name).is_dir())

    def test_erro_ao_criar_subpasta_vira_interrompida(self):
        make_source(self.origem, [10])
        real_mkdir = os.mkdir

        def mkdir(path, *args, **kwargs):
            if os.path.basename(path).startswith('bloco-'):
                raise PermissionError('simulado')
            return real_mkdir(path, *args, **kwargs)

        with mock.patch.object(copy_bench.os, 'mkdir', side_effect=mkdir):
            result = self.run_bench()
        self.assertEqual(result.status, 'interrompida')
        text = (self.destino / result.folder_name / 'relatorio.txt').read_text(
            encoding='utf-8')
        self.assertIn('Motivo da interrupção', text)


class RefusalTests(Base):
    def assertRefused(self, fragment, **kwargs):
        with self.assertRaises(copy_bench.BenchRefused) as ctx:
            self.run_bench(**kwargs)
        self.assertIn(fragment, str(ctx.exception))
        return ctx.exception

    def test_destino_link_recusado(self):
        make_source(self.origem, [10])
        real = self.tmp / 'real'
        real.mkdir()
        link = self.tmp / 'link'
        try:
            os.symlink(real, link, target_is_directory=True)
        except (OSError, NotImplementedError):
            self.skipTest('o sistema não deixou criar link')
        with self.assertRaises(copy_bench.BenchRefused) as ctx:
            copy_bench.run_bench(str(self.origem), str(link), usage=plenty)
        self.assertIn('atalho', str(ctx.exception))
        self.assertEqual(list(real.iterdir()), [])

    def test_destino_dentro_da_origem_recusado(self):
        make_source(self.origem, [10])
        inside = self.origem / 'dentro'
        inside.mkdir()
        before = snapshot(self.origem)
        with self.assertRaises(copy_bench.BenchRefused) as ctx:
            copy_bench.run_bench(str(self.origem), str(inside), usage=plenty)
        self.assertIn('dentro da origem', str(ctx.exception))
        self.assertEqual(list(inside.iterdir()), [])
        self.assertEqual(snapshot(self.origem), before)

    def test_origem_dentro_do_destino_recusada(self):
        origem = self.destino / 'origem'
        make_source(origem, [10])
        with self.assertRaises(copy_bench.BenchRefused) as ctx:
            copy_bench.run_bench(str(origem), str(self.destino), usage=plenty)
        self.assertIn('dentro do destino', str(ctx.exception))
        self.assertEqual([p.name for p in self.destino.iterdir()], ['origem'])

    def test_mesma_pasta_recusada(self):
        make_source(self.origem, [10])
        with self.assertRaises(copy_bench.BenchRefused):
            copy_bench.run_bench(str(self.origem), str(self.origem), usage=plenty)

    def test_espaco_insuficiente_recusado(self):
        make_source(self.origem, [1000, 1000])
        seen = []

        def tight(path):
            seen.append(path)
            return types.SimpleNamespace(total=10 * GIB, used=0, free=2 * GIB + 1999)

        self.assertRefused('Espaço livre insuficiente', usage=tight)
        self.assertTrue(seen)
        self.assertEqual(list(self.destino.iterdir()), [])

    def test_espaco_conta_uma_copia_por_tamanho_de_bloco(self):
        make_source(self.origem, [1000, 1000])

        def enough_for_one(path):
            return types.SimpleNamespace(total=10 * GIB, used=0, free=2 * GIB + 2000)

        self.assertRefused('Espaço livre insuficiente',
                           usage=enough_for_one, chunks=(1, 4))
        result = self.run_bench(usage=enough_for_one, chunks=(1,))
        self.assertEqual(result.status, 'concluída')

    def test_destino_inexistente_recusado(self):
        make_source(self.origem, [10])
        with self.assertRaises(copy_bench.BenchRefused):
            copy_bench.run_bench(str(self.origem), str(self.tmp / 'nao-existe'),
                                 usage=plenty)
        self.assertFalse((self.tmp / 'nao-existe').exists())

    def test_origem_vazia_recusada(self):
        self.origem.mkdir()
        self.assertRefused('Nenhum arquivo')
        self.assertEqual(list(self.destino.iterdir()), [])

    def test_bloco_invalido_recusado(self):
        make_source(self.origem, [10])
        self.assertRefused('bloco', chunks=(0,))
        self.assertRefused('bloco', chunks=(1000,))


class FolderNameTests(Base):
    def test_nao_sobrescreve_pasta_existente(self):
        make_source(self.origem, [10])
        fixed = datetime.datetime(2026, 10, 21, 14, 5, 9)
        name = 'PCRO-MEDICAO-20261021-140509'
        old = self.destino / name
        old.mkdir()
        (old / 'relatorio.txt').write_text('antigo')
        (self.destino / (name + '-2')).write_text('arquivo com o nome')
        result = self.run_bench(now=lambda: fixed)
        self.assertEqual(result.folder_name, name + '-3')
        self.assertEqual((old / 'relatorio.txt').read_text(), 'antigo')
        self.assertEqual(list(old.iterdir()), [old / 'relatorio.txt'])
        self.assertEqual((self.destino / (name + '-2')).read_text(),
                         'arquivo com o nome')


class LimitTests(Base):
    def test_limite_de_bytes(self):
        make_source(self.origem, [400] * 10)
        sample = copy_bench.pick_sample(str(self.origem), 1000, 5000)
        self.assertEqual(len(sample.files), 2)
        self.assertLessEqual(sample.total_bytes, 1000)
        self.assertTrue(sample.truncated)

    def test_limite_de_arquivos(self):
        make_source(self.origem, [10] * 12)
        sample = copy_bench.pick_sample(str(self.origem), GIB, 5)
        self.assertEqual(len(sample.files), 5)
        self.assertTrue(sample.truncated)
        result = self.run_bench(max_files=5)
        self.assertEqual(result.rounds[0].files_ok, 5)

    def test_arquivo_maior_que_o_limite_fica_de_fora(self):
        make_source(self.origem, [5000, 10])
        sample = copy_bench.pick_sample(str(self.origem), 1000, 5000)
        self.assertEqual([size for _, size in sample.files], [10])
        self.assertEqual(sample.too_big, 1)

    def test_amostra_estavel(self):
        make_source(self.origem, [10] * 8)
        first = copy_bench.pick_sample(str(self.origem), GIB, 3)
        second = copy_bench.pick_sample(str(self.origem), GIB, 3)
        self.assertEqual(first.files, second.files)


class LinkTests(Base):
    def test_links_da_origem_sao_pulados(self):
        make_source(self.origem, [10, 20])
        outside = self.tmp / 'fora'
        make_source(outside, [999, 999, 999])
        try:
            os.symlink(outside, self.origem / 'pasta-link', target_is_directory=True)
            os.symlink(outside / 'sub0' / 'arquivo000.dat', self.origem / 'arq-link')
        except (OSError, NotImplementedError):
            self.skipTest('o sistema não deixou criar link')
        sample = copy_bench.pick_sample(str(self.origem), GIB, 5000)
        self.assertEqual(sorted(size for _, size in sample.files), [10, 20])
        self.assertEqual(sample.skipped_links, 2)
        for path, _ in sample.files:
            self.assertNotIn('fora', path)

    @unittest.skipUnless(os.name == 'nt', 'junção só existe no Windows')
    def test_juncao_real_na_origem_e_pulada(self):
        import _winapi
        make_source(self.origem, [10, 20])
        outside = make_source(self.tmp / 'fora', [999, 999])
        junction = self.origem / 'jogos-em-outro-disco'
        try:
            _winapi.CreateJunction(str(outside), str(junction))
        except OSError:
            self.skipTest('o sistema não deixou criar junção')
        sample = copy_bench.pick_sample(str(self.origem), GIB, 5000)
        self.assertEqual(sorted(size for _, size in sample.files), [10, 20])
        self.assertEqual(sample.skipped_links, 1)
        result = self.run_bench()
        self.assertEqual(result.rounds[0].files_ok, 2)
        with self.assertRaises(copy_bench.BenchRefused):
            copy_bench.run_bench(str(junction), str(self.destino), usage=plenty)
        os.rmdir(junction)  # remove só a junção sintética; o alvo fica

    def test_origem_que_e_link_recusada(self):
        real = make_source(self.tmp / 'real', [10])
        link = self.tmp / 'origem-link'
        try:
            os.symlink(real, link, target_is_directory=True)
        except (OSError, NotImplementedError):
            self.skipTest('o sistema não deixou criar link')
        with self.assertRaises(copy_bench.BenchRefused):
            copy_bench.run_bench(str(link), str(self.destino), usage=plenty)


class CancelTests(Base):
    def test_event_interrompe(self):
        make_source(self.origem, [3 * MIB, 3 * MIB])
        event = threading.Event()
        calls = {'n': 0}

        def clock():
            calls['n'] += 1
            if calls['n'] == 3:
                event.set()
            return float(calls['n'])

        result = self.run_bench(cancelled=event, clock=clock)
        self.assertEqual(result.status, 'interrompida')
        folder = self.destino / result.folder_name
        partial = list(folder.rglob('*.parcial'))
        self.assertEqual(len(partial), 1)
        text = (folder / 'relatorio.txt').read_text(encoding='utf-8')
        self.assertIn('interrompida', text)
        data = json.loads((folder / 'relatorio.json').read_text(encoding='utf-8'))
        self.assertEqual(data['situacao'], 'interrompida')

    def test_ctrl_c_interrompe(self):
        make_source(self.origem, [3 * MIB, 3 * MIB])
        calls = {'n': 0}

        def clock():
            calls['n'] += 1
            if calls['n'] == 4:
                raise KeyboardInterrupt
            return float(calls['n'])

        result = self.run_bench(clock=clock)
        self.assertEqual(result.status, 'interrompida')
        folder = self.destino / result.folder_name
        self.assertTrue((folder / 'relatorio.txt').is_file())
        self.assertEqual(len(list(folder.rglob('*.parcial'))), 1)

    def test_callable_tambem_serve(self):
        make_source(self.origem, [100, 100])
        state = {'calls': 0}

        def clock():
            state['calls'] += 1
            return float(state['calls'])

        result = self.run_bench(cancelled=lambda: state['calls'] > 0, clock=clock)
        self.assertEqual(result.status, 'interrompida')
        # O primeiro arquivo cabe num bloco só e termina; o segundo não começa.
        self.assertEqual(result.rounds[0].files_ok, 1)

    def test_cancelado_antes_de_comecar_nao_grava(self):
        make_source(self.origem, [100])
        with self.assertRaises(copy_bench.BenchRefused) as ctx:
            self.run_bench(cancelled=lambda: True)
        self.assertIn('Nada foi gravado', str(ctx.exception))
        self.assertEqual(list(self.destino.iterdir()), [])


class SpeedTests(Base):
    def test_mib_por_segundo_com_relogio_simulado(self):
        make_source(self.origem, [2 * MIB, 2 * MIB])
        result = self.run_bench(chunks=(1, 4), clock=TickClock())
        one, four = result.rounds
        # Bloco de 1 MiB: 4 leituras de 1 s para 4 MiB = 1 MiB/s.
        self.assertAlmostEqual(one.read_mib_s, 1.0)
        self.assertAlmostEqual(one.write_mib_s, 1.0)
        self.assertAlmostEqual(one.verify_mib_s, 1.0)
        # Bloco de 4 MiB: cada arquivo cabe num bloco só = 2 MiB/s.
        self.assertAlmostEqual(four.read_mib_s, 2.0)
        self.assertAlmostEqual(four.write_mib_s, 2.0)
        self.assertAlmostEqual(four.verify_mib_s, 2.0)
        self.assertEqual(result.suggestion['bloco_mib'], 4)
        # Estimativa conservadora pela 1ª rodada: cópia a 0,5 MiB/s
        # (leitura + escrita) mais uma releitura a 1 MiB/s.
        minutes = (120 * 1024 / 0.5 + 120 * 1024 / 1.0) / 60
        self.assertAlmostEqual(result.suggestion['minutos_para_120_gib'],
                               round(minutes, 1))
        self.assertIn('primeira rodada', result.suggestion['base_da_estimativa'])

    def test_bloco_escolhido_pela_escrita(self):
        slow = copy_bench.RoundResult(chunk_mib=1, bytes=MIB, read_s=1, write_s=1,
                                      verify_s=1, complete=True, files_ok=1)
        fast_verify = copy_bench.RoundResult(chunk_mib=4, bytes=MIB, read_s=1,
                                             write_s=2, verify_s=0.001,
                                             complete=True, files_ok=1)
        suggestion = copy_bench._suggest([slow, fast_verify])
        self.assertEqual(suggestion['bloco_mib'], 1)

    def test_mib_s_sem_tempo(self):
        self.assertIsNone(copy_bench.mib_per_s(MIB, 0))
        self.assertAlmostEqual(copy_bench.mib_per_s(10 * MIB, 4), 2.5)


class ReportTests(Base):
    def test_relatorio_sem_caminhos(self):
        make_source(self.origem, [100, 200])
        result = self.run_bench(chunks=(1, 4))
        text, data = copy_bench.bench_report(result)
        folder = self.destino / result.folder_name
        saved_text = (folder / 'relatorio.txt').read_text(encoding='utf-8')
        saved_json = (folder / 'relatorio.json').read_text(encoding='utf-8')
        json.loads(saved_json)
        for blob in (text, json.dumps(data, ensure_ascii=False), saved_text, saved_json):
            for forbidden in (str(self.tmp), str(self.origem), str(self.destino),
                              'arquivo000', 'sub0', os.sep + 'origem'):
                self.assertNotIn(forbidden, blob)
        self.assertIn('pode ser apagada à mão', text)
        self.assertIn('nenhum arquivo da origem foi gravado ou apagado', text)
        self.assertNotIn('nada foi alterado', text)
        self.assertIn('cache', text)
        self.assertIn('otimistas', text)
        self.assertIn('otimistas', data['aviso_cache'])
        self.assertIn('fsync', data['o_que_cada_tempo_mede'])
        self.assertIn('Sugestão', text)
        self.assertEqual(data['situacao'], 'concluída')
        self.assertEqual(data['amostra']['arquivos'], 2)
        self.assertEqual(data['amostra']['bytes'], 300)

    def test_relatorio_nao_manda_apagar_nada_automaticamente(self):
        make_source(self.origem, [10])
        result = self.run_bench()
        text, _ = copy_bench.bench_report(result)
        self.assertIn('Nada foi apagado', text)

    def test_letra_da_unidade(self):
        self.assertEqual(copy_bench.drive_label('C:\\Jogos\\osu!'), 'C:')
        self.assertEqual(copy_bench.drive_label('d:\\x'), 'D:')
        self.assertEqual(copy_bench.drive_label('\\\\servidor\\pasta\\x'), 'rede')
        self.assertEqual(copy_bench.drive_label('/home/fulano/x'), 'sem letra')


class ScriptTests(unittest.TestCase):
    def run_script(self, *args):
        return subprocess.run(
            [sys.executable, str(ROOT / 'scripts' / 'medir_copia.py'), *args],
            capture_output=True, text=True, encoding='utf-8', timeout=120)

    def test_help(self):
        done = self.run_script('--help')
        self.assertEqual(done.returncode, 0)
        self.assertIn('--origem', done.stdout)
        self.assertIn('--destino', done.stdout)

    def test_script_recusa_sem_gravar(self):
        with tempfile.TemporaryDirectory() as tmp:
            origem = make_source(Path(tmp) / 'origem', [10])
            inside = origem / 'dentro'
            inside.mkdir()
            done = self.run_script('--origem', str(origem), '--destino', str(inside))
            self.assertEqual(done.returncode, 2)
            self.assertIn('dentro da origem', done.stdout)
            self.assertEqual(list(inside.iterdir()), [])

    def test_script_interrompido_depois_da_pasta_nao_diz_nao_feita(self):
        sys.path.insert(0, str(ROOT / 'scripts'))
        try:
            import medir_copia
        finally:
            sys.path.pop(0)
        stop = copy_bench.BenchStopped('PCRO-MEDICAO-20261021-140509',
                                       'erro do sistema ao gravar o relatório')
        outputs = {}
        for label, error, expected_code in (
                ('parou', stop, 1), ('ctrl-c', KeyboardInterrupt(), 1),
                ('erro', OSError(28, 'sem espaço'), 2)):
            with mock.patch.object(medir_copia.copy_bench, 'run_bench',
                                   side_effect=error):
                with contextlib.redirect_stdout(io.StringIO()) as out:
                    code = medir_copia.main(['--origem', 'x', '--destino', 'y'])
            text = out.getvalue()
            outputs[label] = text
            self.assertEqual(code, expected_code)
            self.assertNotIn('NÃO FEITA', text)
            self.assertNotIn('antes de começar', text)
            self.assertIn('pode ser apagada à mão', text)
        self.assertIn('INTERROMPIDA', outputs['parou'])
        self.assertIn('PCRO-MEDICAO-20261021-140509', outputs['parou'])

    def test_script_mede_amostra_pequena(self):
        with tempfile.TemporaryDirectory() as tmp:
            origem = make_source(Path(tmp) / 'origem', [100, 200])
            destino = Path(tmp) / 'destino'
            destino.mkdir()
            sys.path.insert(0, str(ROOT / 'scripts'))
            try:
                import medir_copia
            finally:
                sys.path.pop(0)
            with contextlib.redirect_stdout(io.StringIO()) as out:
                code = medir_copia.main(
                    ['--origem', str(origem), '--destino', str(destino),
                     '--max-mib', '1', '--max-arquivos', '10', '--blocos', '1'],
                    usage=plenty)
            self.assertEqual(code, 0)
            self.assertNotIn(str(origem), out.getvalue())
            self.assertNotIn(str(destino), out.getvalue())
            self.assertEqual(len(list(destino.iterdir())), 1)


if __name__ == '__main__':
    unittest.main()
