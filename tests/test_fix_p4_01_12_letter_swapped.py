"""FIX-P4-01-12: "Conferir discos e letras" avisa quando outra unidade ficou
com a letra de onde vieram os arquivos do backup.

Só dados sintéticos: o manifesto fica num TemporaryDirectory e as unidades
são textos ('C:\\', 'D:\\') com tamanho, tipo e nome simulados. Nunca lista
discos reais, nunca lê o nome de uma unidade de verdade e não grava nada nas
"unidades". Sem Tk.
"""
import hashlib
import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import after_format as af

WIN_ENV = {'SystemRoot': r'C:\Windows', 'SystemDrive': 'C:'}
GIB = 1024 ** 3
FORBIDDEN = ('formate', 'formatar o', 'apague', 'apagar', 'exclua', 'excluir',
             'desinstal', 'particion', 'nada é apagado', 'não mexe')


def _flat(text):
    return ' '.join(text.split())


def _write_manifest(folder, sources, source_drives=None):
    folder = Path(folder)
    folder.mkdir(parents=True, exist_ok=True)
    files = []
    for index, source in enumerate(sources):
        files.append({'source': source, 'relative': f'f{index}.dat', 'verified': True,
                      'size': 1, 'sha256': hashlib.sha256(str(index).encode()).hexdigest()})
    doc = {'schema': 'pc-restore-backup-v0.5', 'files': files}
    if source_drives is not None:
        doc['source_drives'] = source_drives
    path = folder / 'manifest.json'
    path.write_text(json.dumps(doc, indent=2, ensure_ascii=False), encoding='utf-8')
    return path


class SwappedLetterTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.base = Path(tmp.name)
        self.sizes = {'C:\\': 500 * GIB, 'D:\\': 1000 * GIB}
        self.labels = {'C:\\': 'Windows', 'D:\\': 'Jogos'}
        self.label_calls = []

    def manifest(self, source_drives=None):
        return _write_manifest(self.base / 'backup' / 'b1',
                               [r'C:\Users\x\a.txt', r'D:\Jogos\save.dat',
                                r'D:\Jogos\save2.dat'], source_drives)

    def usage(self, root):
        total = self.sizes[root]
        return (total, total // 2, total // 2)

    def label(self, root):
        self.label_calls.append(root)
        value = self.labels.get(root)
        if isinstance(value, Exception):
            raise value
        return value

    def check(self, manifest, roots=('C:\\', 'D:\\'), environ=WIN_ENV):
        return af.check_drives(manifest, roots=list(roots), usage=self.usage,
                               environ=environ, drive_type=lambda root: 'Disco local',
                               volume_label=self.label)

    def test_other_disk_with_backup_letter_is_warned(self):
        manifest = self.manifest({'D:': {'label': 'Jogos', 'total': 2000 * GIB}})
        self.labels['D:\\'] = 'Backup'
        result = self.check(manifest)
        self.assertEqual(result['missing'], [])
        self.assertEqual(result['changed'], ['D:'])
        text = _flat(' '.join(result['warnings']))
        self.assertIn('D:', text)
        self.assertIn('"Jogos"', text)
        self.assertIn('"Backup"', text)
        self.assertIn('Talvez outro disco tenha ficado com essa letra', text)
        self.assertIn('Não use "Colocar no lugar original"', text)
        self.assertIn('Restaurar arquivos marcados para pasta nova', text)
        self.assertIn('primeiro dê outra letra livre à unidade que está com a D: agora', text)
        self.assertIn('Gerenciamento de Disco', result['guidance'])
        self.assertIn('D:', result['guidance'])

    def test_only_size_differs_is_warned(self):
        manifest = self.manifest({'D:': {'label': 'Jogos', 'total': 2000 * GIB}})
        result = self.check(manifest)
        self.assertEqual(result['changed'], ['D:'])

    def test_only_name_differs_is_warned(self):
        manifest = self.manifest({'D:': {'label': 'Jogos', 'total': 1000 * GIB}})
        self.labels['D:\\'] = 'Fotos'
        result = self.check(manifest)
        self.assertEqual(result['changed'], ['D:'])

    def test_name_compared_without_case(self):
        manifest = self.manifest({'D:': {'label': 'JOGOS', 'total': 1000 * GIB}})
        result = self.check(manifest)
        self.assertEqual(result['changed'], [])
        self.assertEqual(result['confirmed'], ['D:'])
        self.assertEqual(result['unconfirmed'], [])
        self.assertEqual(result['guidance'], '')
        self.assertEqual(result['warnings'], [])

    def test_empty_name_matches_empty_name(self):
        manifest = self.manifest({'D:': {'label': '', 'total': 1000 * GIB}})
        self.labels['D:\\'] = ''
        result = self.check(manifest)
        self.assertEqual(result['confirmed'], ['D:'])

    def test_without_saved_data_warns_could_not_confirm(self):
        result = self.check(self.manifest())
        self.assertEqual(result['changed'], [])
        self.assertEqual(result['unconfirmed'], ['D:'])
        text = _flat(' '.join(result['warnings']))
        self.assertIn('Não deu para confirmar', text)
        self.assertIn('D:', text)
        self.assertIn('pelo nome e pelo tamanho', text)
        self.assertEqual(result['guidance'], '')
        # sem dado guardado, nem tenta ler o nome da unidade
        self.assertEqual(self.label_calls, [])

    def test_unreadable_current_name_warns_could_not_confirm(self):
        manifest = self.manifest({'D:': {'label': 'Jogos', 'total': 1000 * GIB}})
        for broken in (None, OSError('sem acesso')):
            with self.subTest(broken=broken):
                self.labels['D:\\'] = broken
                result = self.check(manifest)
                self.assertEqual(result['unconfirmed'], ['D:'])
                self.assertEqual(result['changed'], [])

    def test_unreadable_current_size_warns_could_not_confirm(self):
        manifest = self.manifest({'D:': {'label': 'Jogos', 'total': 1000 * GIB}})

        def broken(root):
            raise OSError('sem acesso')
        result = af.check_drives(manifest, roots=['C:\\', 'D:\\'], usage=broken,
                                 environ=WIN_ENV, drive_type=lambda root: 'Disco local',
                                 volume_label=self.label)
        self.assertEqual(result['unconfirmed'], ['D:'])

    def test_bad_saved_data_is_not_confirmation(self):
        for saved in ({'D:': {'label': 'Jogos'}}, {'D:': {'total': 1000 * GIB}},
                      {'D:': {'label': 'Jogos', 'total': 'mil'}},
                      {'D:': {'label': 'Jogos', 'total': True}},
                      {'D:': 'Jogos'}, ['D:'], 'x'):
            with self.subTest(saved=saved):
                result = self.check(self.manifest(saved))
                self.assertEqual(result['unconfirmed'], ['D:'])
                self.assertEqual(result['confirmed'], [])

    def test_windows_disk_is_not_compared(self):
        # o disco do Windows foi formatado pelo instalador: nome e tamanho podem mudar
        manifest = self.manifest({'C:': {'label': 'Antigo', 'total': 1 * GIB},
                                  'D:': {'label': 'Jogos', 'total': 1000 * GIB}})
        result = self.check(manifest)
        self.assertEqual(result['changed'], [])
        self.assertEqual(result['unconfirmed'], [])
        self.assertNotIn('C:\\', self.label_calls)

    def test_unknown_windows_disk_compares_every_letter(self):
        manifest = self.manifest({'C:': {'label': 'Antigo', 'total': 1 * GIB},
                                  'D:': {'label': 'Jogos', 'total': 1000 * GIB}})
        result = self.check(manifest, environ={})
        self.assertEqual(result['changed'], ['C:'])
        self.assertEqual(result['confirmed'], ['D:'])

    def test_missing_and_changed_share_one_guide(self):
        manifest = _write_manifest(self.base / 'backup' / 'b2',
                                   [r'D:\a.dat', r'E:\b.dat'],
                                   {'D:': {'label': 'Jogos', 'total': 2000 * GIB}})
        result = self.check(manifest)
        self.assertEqual(result['missing'], ['E:'])
        self.assertEqual(result['changed'], ['D:'])
        self.assertIn('D: ou E:', result['guidance'])

    def test_letter_saved_in_lowercase_is_found(self):
        manifest = self.manifest({'d:': {'label': 'Fotos', 'total': 1000 * GIB}})
        result = self.check(manifest)
        self.assertEqual(result['changed'], ['D:'])

    def test_texts_follow_safety_rules(self):
        changed = self.check(self.manifest({'D:': {'label': 'X', 'total': 1}}))
        unconfirmed = self.check(self.manifest())
        for result in (changed, unconfirmed):
            text = _flat(' '.join(result['warnings']) + ' ' + result['guidance']).lower()
            for word in FORBIDDEN:
                self.assertNotIn(word, text)

    def test_nothing_written(self):
        manifest = self.manifest({'D:': {'label': 'Jogos', 'total': 2000 * GIB}})
        before = sorted((p.as_posix(), p.stat().st_size, p.stat().st_mtime_ns)
                        for p in self.base.rglob('*'))
        self.check(manifest)
        after = sorted((p.as_posix(), p.stat().st_size, p.stat().st_mtime_ns)
                       for p in self.base.rglob('*'))
        self.assertEqual(before, after)

    def test_default_label_reader_outside_windows_reads_nothing(self):
        if af._on_windows():
            self.skipTest('Só fora do Windows (não lê o nome de uma unidade real).')
        self.assertIsNone(af.default_volume_label('C:\\'))


if __name__ == '__main__':
    unittest.main()
