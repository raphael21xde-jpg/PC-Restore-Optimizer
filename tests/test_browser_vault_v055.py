"""Safety and round-trip tests without requiring any real user's browser data."""
import io
from pathlib import Path
import os
import sys
import tarfile
import tempfile
import unittest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from browser_vault import (BrowserProfile, discover_profiles, profile_files, create_vault,
                           verify_vault, restore_to_staging, _inspect_tar)

PASSWORD='passphrase-for-test-2026-long'

class BrowserVaultTests(unittest.TestCase):
    def build(self, base, name='Google Chrome', kind='Default'):
        profile=Path(base)/'browser-profile';profile.mkdir()
        (profile/'Bookmarks').write_text('favorites-123',encoding='utf-8')
        (profile/'Preferences').write_text('{"prefs":1}',encoding='utf-8')
        (profile/'Login Data').write_text('DO-NOT-COPY-PASSWORD-DATABASE',encoding='utf-8')
        (profile/'Cookies').write_text('DO-NOT-COPY-COOKIES',encoding='utf-8')
        (profile/'Local State').write_text('DO-NOT-COPY-KEY',encoding='utf-8')
        (profile/'Extensions').mkdir()
        (profile/'Extensions'/'someext.txt').write_text('extension-setting',encoding='utf-8')
        return BrowserProfile(name,kind,profile)

    def test_discover_multiple_profiles_without_secret_access(self):
        with tempfile.TemporaryDirectory() as td:
            local=Path(td)/'local';roam=Path(td)/'roaming'
            p=local/'Google'/'Chrome'/'User Data'/'Profile 2';p.mkdir(parents=True)
            (p/'Bookmarks').write_text('yes')
            f=roam/'Mozilla'/'Firefox'/'Profiles'/'abc.default-release';f.mkdir(parents=True)
            (f/'prefs.js').write_text('user_pref();')
            found=discover_profiles({'LOCALAPPDATA':str(local),'APPDATA':str(roam)})
            self.assertIn(('Google Chrome','Profile 2'),[(x.browser,x.label) for x in found])
            self.assertIn(('Mozilla Firefox','abc.default-release'),[(x.browser,x.label) for x in found])

    def test_encrypted_round_trip_with_manual_csv_no_credentials_auto(self):
        with tempfile.TemporaryDirectory() as td:
            base=Path(td);p=self.build(base);csv=base/'exported.csv';csv.write_text('url,username,password\na,b,secret-pass')
            html=base/'bookmarks.html';html.write_text('<html>safe bookmarks</html>')
            target,count,size,has_csv,has_html=create_vault(p,base/'backup',PASSWORD,csv_path=csv,bookmarks_html=html)
            self.assertEqual(count,3)
            self.assertTrue(has_csv)
            self.assertTrue(has_html)
            self.assertTrue(target.is_file())
            names=verify_vault(target,PASSWORD)
            self.assertIn('manual-export/senhas-exportadas.csv',names)
            self.assertIn('manual-export/favoritos.html',names)
            self.assertNotIn('profile/Login Data',names)
            self.assertNotIn('profile/Cookies',names)
            self.assertNotIn('profile/Local State',names)
            self.assertNotIn(b'secret-pass',target.read_bytes())
            output=restore_to_staging(target,base,PASSWORD)
            self.assertEqual((output/'profile'/'Bookmarks').read_text(),'favorites-123')
            self.assertEqual((output/'manual-export'/'senhas-exportadas.csv').read_text(),csv.read_text())
            self.assertEqual((output/'manual-export'/'favoritos.html').read_text(),html.read_text())
            self.assertTrue((p.path/'Login Data').exists())
            self.assertFalse((output/'profile'/'Login Data').exists())

    def test_wrong_password_and_corruption_leave_no_restored_directory(self):
        with tempfile.TemporaryDirectory() as td:
            base=Path(td);p=self.build(base)
            target,*_=create_vault(p,base/'backup',PASSWORD)
            with self.assertRaises(Exception):verify_vault(target,'incorrect password too long')
            broken=base/'corrupted.pcbrowser'
            payload=bytearray(target.read_bytes());payload[-1]^=0x13;broken.write_bytes(payload)
            with self.assertRaises(Exception):restore_to_staging(broken,base,PASSWORD)
            self.assertFalse(any(base.glob('CONFERIR-NAVEGADOR-*')))

    def test_firefox_excludes_login_database_but_preserves_bookmarks(self):
        with tempfile.TemporaryDirectory() as td:
            p=Path(td)/'firefox';p.mkdir()
            (p/'places.sqlite').write_bytes(b'bookmarks')
            (p/'prefs.js').write_text('prefs')
            (p/'logins.json').write_text('encrypted-credentials')
            (p/'key4.db').write_text('key')
            files=profile_files(BrowserProfile('Mozilla Firefox','abc.default',p))
            self.assertEqual({x.name for x in files},{'places.sqlite','prefs.js'})

    def test_symlink_does_not_escape_profile(self):
        with tempfile.TemporaryDirectory() as td:
            base=Path(td);p=self.build(base);secret=base/'private'
            secret.write_text('never include this')
            try:(p.path/'Bookmarks.bak').symlink_to(secret)
            except (OSError,NotImplementedError):self.skipTest('Symlink creation unavailable')
            files=profile_files(p)
            self.assertNotIn(p.path/'Bookmarks.bak',files)

    def test_tar_traversal_is_rejected(self):
        data=io.BytesIO()
        with tarfile.open(fileobj=data,mode='w') as arc:
            payload=b'test';info=tarfile.TarInfo('profile/../../bad.csv');info.size=len(payload)
            arc.addfile(info,io.BytesIO(payload))
        data.seek(0)
        with tarfile.open(fileobj=data,mode='r|') as arc:
            with self.assertRaises(ValueError):_inspect_tar(arc)

if __name__=='__main__':unittest.main()
