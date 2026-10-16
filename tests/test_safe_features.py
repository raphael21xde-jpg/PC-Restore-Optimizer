from pathlib import Path
import json
import sys
import tempfile
import unittest

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from backup_core import build_plan, copy_backup
from backup_features import verified_entries, restore_selected, set_backup_label, backup_labels, safe_relative
from recovery_kit import create_plan, load_plan, summarize_plan
from diagnostics import make_recommendations, system_inventory

class SafeWorkflowTests(unittest.TestCase):
    def test_backup_and_chosen_restore_integrity(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)
            original=root/'user'/'saves'/'Terraria'
            original.mkdir(parents=True)
            (original/'Players').mkdir()
            (original/'Worlds').mkdir()
            (original/'Players'/'player.plr').write_bytes(b'player-test')
            (original/'Worlds'/'world.wld').write_bytes(b'world-test')
            plan=build_plan({str(original):'keep'},[str(root)])
            self.assertEqual(plan.count,2)
            dest=root/'external'
            backup,m=copy_backup(plan,dest,display_name='Terraria e saves')
            self.assertEqual(m['status'],'concluido')
            self.assertEqual(m['display_name'],'Terraria e saves')
            manifest=backup/'manifest.json'
            names=verified_entries(manifest)
            self.assertEqual(len(names),2)
            output,number=restore_selected(manifest,list(names),root)
            self.assertEqual(number,2)
            self.assertEqual(len(list(output.rglob('*.plr'))),1)
            self.assertEqual((original/'Players'/'player.plr').read_bytes(),b'player-test')
            set_backup_label(manifest,'Novo nome amigável')
            self.assertEqual(backup_labels(dest)[backup.name],'Novo nome amigável')

    def test_reject_traversal(self):
        for path in ['../evil','C:/Windows/x','/root/a',r'Foo\\..\\evil','COM1.txt','file:stream']:
            with self.subTest(path=path):
                with self.assertRaises(ValueError):safe_relative(path)

    def test_recovery_plan_round_trip(self):
        with tempfile.TemporaryDirectory() as tmp:
            file=Path(tmp)/'kit.json'
            catalog={'steam:123':dict(kind='game',name='Jogo exemplo',source='Steam',paths=[r'C:\\Users\\Test\\My Games\\Example']),
                     'app:a':dict(kind='app',name='Software do headset',source='Registro')}
            n=create_plan(file,catalog,{'steam:123':'keep','app:a':'keep'},['save'],str(tmp))
            self.assertEqual(n,2)
            report=load_plan(file)
            self.assertEqual(len(report['items']),2)
            self.assertIn('Jogo exemplo',summarize_plan(report))
            self.assertIn('Software do headset',summarize_plan(report))

    def test_optimization_is_advice_only(self):
        disk={'volumes':[{'DriveLetter':'D','Size':100,'SizeRemaining':5}], 'alerts':['Verificar EFI']}
        lines=make_recommendations(disk,{})
        self.assertTrue(any('10%' in p for p in lines))
        self.assertTrue(any('EFI' in p for p in lines))

    def test_non_windows_hardware_snapshot_safe(self):
        report=system_inventory()
        self.assertIn('platform',report)

if __name__=='__main__':
    unittest.main()
