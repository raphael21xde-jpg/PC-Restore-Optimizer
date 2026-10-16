import json
import tempfile
from pathlib import Path
import unittest
from browser_recovery import inspect_recovery, prepare_bookmarks
from browser_vault import BrowserProfile, create_vault, restore_to_staging


class RecoveryTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.source = self.root/'source'; (self.source/'profile').mkdir(parents=True)
        self.out = self.root/'out'; self.out.mkdir()
    def bookmarks(self, url='https://example.org/?a=1&b=2'):
        p = self.source/'profile/Bookmarks'
        p.write_text(json.dumps({'roots': {'bookmark_bar': {'type': 'folder', 'name': '<Folder>', 'children': [{'type':'url', 'name':'A & B', 'url':url}]}}}))
        return p
    def test_conversion_escapes_and_keeps_folders(self):
        self.bookmarks(); out, count = prepare_bookmarks(self.source, self.out)
        self.assertEqual(count, 1)
        text = out.read_text(); self.assertIn('&lt;Folder&gt;', text); self.assertIn('A &amp; B', text); self.assertIn('&amp;b=2', text)
    def test_never_overwrites_source_or_prior_exports(self):
        p = self.bookmarks(); original = p.read_bytes()
        a, _ = prepare_bookmarks(self.source, self.out); b, _ = prepare_bookmarks(self.source, self.out)
        self.assertNotEqual(a, b); self.assertEqual(p.read_bytes(), original)
    def test_javascript_is_not_exported(self):
        self.bookmarks('javascript:alert(1)')
        with self.assertRaises(ValueError): prepare_bookmarks(self.source, self.out)
    def test_missing_passwords_are_explicit(self):
        self.bookmarks(); self.assertIsNone(inspect_recovery(self.source)['password_csv'])
    def test_legacy_password_filename(self):
        p = self.source/'senhas_exportadas_MANUALMENTE.csv'; p.write_text('name,url,username,password\n')
        self.assertEqual(inspect_recovery(self.source)['password_csv'], p)
    def test_symlink_is_rejected(self):
        p = self.root/'outside'; p.write_text('{}'); (self.source/'profile/Bookmarks').symlink_to(p)
        with self.assertRaises(ValueError): inspect_recovery(self.source)
    def test_malformed_bookmarks(self):
        (self.source/'profile/Bookmarks').write_text('{}')
        with self.assertRaises(ValueError): prepare_bookmarks(self.source, self.out)
    def test_html_export_is_preferred(self):
        p = self.source/'manual-export'; p.mkdir(); (p/'favoritos.html').write_text('existing-export')
        self.bookmarks(); out, count = prepare_bookmarks(self.source, self.out)
        self.assertEqual(out.read_text(), 'existing-export'); self.assertIsNone(count)
    def test_vault_to_import_end_to_end(self):
        self.bookmarks()
        profile = BrowserProfile('Opera GX', 'Default', self.source/'profile')
        vault, *_ = create_vault(profile, self.out, 'test-passphrase-123')
        staging = restore_to_staging(vault, self.out, 'test-passphrase-123')
        self.assertEqual(inspect_recovery(staging)['browser'], 'Opera GX')
        out, count = prepare_bookmarks(staging, self.out)
        self.assertEqual(count, 1); self.assertTrue(out.exists())
