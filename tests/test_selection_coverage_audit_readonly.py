"""Stage 44: fake in-memory selections only, never touch real drives."""
import gc
import json
import tkinter as tk
from tkinter import ttk
import time
import unittest
from unittest.mock import patch

from backup_core import FileTask, Plan
from selection_coverage_audit import audit_selection_coverage, REASON_TEXT
from drive_safety_ui import show_drive_safety_dialog


def selected_file_plan():
    return Plan(
        files=[FileTask(
            source='Q:\\Data\\one.txt', size=1024,
            mtime_ns=1234, destination='Data/one.txt')],
        selected=['Q:\\Data'],
        skipped=[], warnings=[], total=1024)


def audit(**overrides):
    data = {
        'plan': selected_file_plan(),
        'choices': {'Q:\\Data': 'keep'},
        'catalog_choices': {},
        'catalog_items': {},
        'browser_keep_paths': set(),
        'auto_save_paths': set(),
    }
    data.update(overrides)
    plan = data.pop('plan')
    return audit_selection_coverage(plan, **data)


class SelectionCoverageAuditTests(unittest.TestCase):
    def test_only_existing_file_choices_can_consider_preview_estimate(self):
        result = audit()
        self.assertEqual(result['status'], 'no_unresolved_extra_choices')
        self.assertTrue(result['can_use_file_preview_estimate'])
        self.assertEqual(result['file_choices_outside_preview'], 0)
        self.assertEqual(result['reasons'], [])

    def test_second_drive_explicit_keep_is_not_in_single_drive_plan(self):
        result = audit(choices={
            'Q:\\Data': 'keep', 'R:\\Games': 'keep'})
        self.assertEqual(result['file_choices_outside_preview'], 1)
        self.assertIn('file_choices_outside_preview', result['reasons'])
        self.assertFalse(result['can_use_file_preview_estimate'])

    def test_skipped_items_do_not_add_bytes_or_coverage_blockers(self):
        result = audit(choices={
            'Q:\\Data': 'keep', 'S:\\NotCopy': 'skip'})
        self.assertEqual(result['status'], 'no_unresolved_extra_choices')

    def test_auto_save_outside_plan_has_its_own_warning(self):
        result = audit(choices={
            'Q:\\Data': 'keep', 'R:\\Save': 'keep'},
            auto_save_paths={'R:\\Save'})
        self.assertEqual(result['auto_saves_outside_preview'], 1)
        self.assertIn('auto_saves_outside_preview', result['reasons'])
        self.assertFalse(result['can_use_file_preview_estimate'])

    def test_selected_games_need_recovery_review_even_if_file_tasks_present(self):
        result = audit(catalog_choices={'game': 'keep'},
                       catalog_items={'game': {'paths': ['Q:\\Data']}})
        self.assertEqual(result['catalog_selected'], 1)
        self.assertIn('catalog_recovery_not_verified', result['reasons'])
        self.assertFalse(result['can_use_file_preview_estimate'])

    def test_catalog_possible_paths_are_reported_only_as_count(self):
        result = audit(catalog_choices={'game': 'keep'},
                       catalog_items={'game': {
                           'paths': ['Q:\\Data'],
                           'possible_paths': ['PRIVATE-PATH-A', 'PRIVATE-PATH-B']}})
        self.assertEqual(result['catalog_pending_paths'], 2)
        self.assertIn('catalog_paths_need_review', result['reasons'])
        encoded = json.dumps(result)
        self.assertNotIn('PRIVATE-PATH', encoded)
        self.assertNotIn('game', encoded)

    def test_selected_browser_profiles_not_assumed_recoverable_or_in_file_size(self):
        result = audit(browser_keep_paths={
            'PRIVATE-BROWSER-PROFILE-1', 'PRIVATE-BROWSER-PROFILE-2'})
        self.assertEqual(result['browser_profiles_selected'], 2)
        self.assertIn('browser_vaults_not_verified', result['reasons'])
        self.assertNotIn('PRIVATE-', json.dumps(result))

    def test_browser_and_catalog_codes_are_independent(self):
        result = audit(browser_keep_paths={'B'},
                       catalog_choices={'X': 'keep'},
                       catalog_items={'X': {'possible_paths': []}})
        self.assertEqual(result['catalog_selected'], 1)
        self.assertEqual(result['browser_profiles_selected'], 1)
        self.assertFalse(result['can_use_file_preview_estimate'])

    def test_missing_plan_with_outside_keep_cannot_pass(self):
        result = audit(plan=None, choices={'Q:\\Data': 'keep'})
        self.assertEqual(result['file_choices_outside_preview'], 1)
        self.assertFalse(result['can_use_file_preview_estimate'])

    def test_bad_choice_state_is_not_exported_as_raw_private_text(self):
        result = audit(choices={
            'Q:\\Data': 'keep',
            'PRIVATE-OTHER': 'keep'})
        self.assertIn('file_choices_outside_preview', result['reasons'])
        self.assertNotIn('PRIVATE-', json.dumps(result))

    def test_unavailable_or_invalid_metadata_fails_closed(self):
        for data in ({'choices': 'PRIVATE-INVALID'},
                     {'catalog_choices': ['keep']},
                     {'browser_keep_paths': 'PRIVATE-STRING'},
                     {'plan': object()}):
            with self.subTest(data=data):
                result = audit(**data)
                self.assertFalse(result['can_use_file_preview_estimate'])
                self.assertIn('selection_state_unavailable', result['reasons'])

    def test_no_filesystem_lookups_or_disk_queries_for_audit(self):
        with (patch('os.stat', side_effect=AssertionError('stat forbidden')),
              patch('os.scandir', side_effect=AssertionError('scandir forbidden'))):
            result = audit(choices={'Q:\\Data': 'keep'})
        self.assertTrue(result['can_use_file_preview_estimate'])

    def test_reasons_are_static_codes_not_user_paths(self):
        result = audit(choices={'R:\\SECRET': 'keep'})
        self.assertTrue(all(k in REASON_TEXT for k in result['reasons']))
        self.assertNotIn('SECRET', json.dumps(result))

    def test_no_new_authorization_keys_in_coverage(self):
        result = audit()
        self.assertNotIn('copy_authorized', result)
        self.assertNotIn('physical_independence_verified', result)
        self.assertNotIn('ready_for_format', result)
        self.assertNotIn('installation_authorized', result)


class SelectionCoverageAuditUiTests(unittest.TestCase):
    def setUp(self):
        try:
            self.root = tk.Tk()
        except tk.TclError as exc:
            self.skipTest('Tk indisponível: ' + str(exc))
        self.root.withdraw()
        self.root.busy = False
        self.root.plan = selected_file_plan()
        self.root.choices = {'Q:\\Data': 'keep'}
        self.root.catalog_choices = {}
        self.root.catalog_items = {}
        self.root.browser_keep_paths = set()
        self.root.auto_save_paths = set()
        self.addCleanup(self.cleanup)

    def cleanup(self):
        self.root.destroy()
        self.root = None
        gc.collect()

    def open_dialog(self):
        dialog = show_drive_safety_dialog(
            self.root, available_letters=('Q', 'R'))
        self.addCleanup(lambda: dialog.winfo_exists() and dialog.destroy())
        buttons, fields, texts = {}, [], []
        def walk(parent):
            for child in parent.winfo_children():
                if isinstance(child, ttk.Button):
                    buttons[child.cget('text')] = child
                if isinstance(child, (ttk.Entry, tk.Entry)):
                    fields.append(child)
                if isinstance(child, tk.Text):
                    texts.append(child)
                walk(child)
        walk(dialog)
        self.assertEqual(len(fields), 3)
        self.assertEqual(len(texts), 1)
        fields[0].insert(0, 'Q:')
        fields[1].insert(0, 'R:')
        return buttons, fields, texts[0]

    def test_audit_button_does_not_access_hardware_or_fill_size(self):
        with patch('drive_safety_ui.inspect_fresh_drive_safety') as collect:
            controls, fields, details = self.open_dialog()
            controls['Conferir cobertura da seleção'].invoke()
            collect.assert_not_called()
            self.assertEqual(fields[2].get(), '')
            self.assertIn('AUDITORIA DA SELEÇÃO', details.get('1.0', 'end'))
            self.assertIn('não comprova', details.get('1.0', 'end'))

    def test_unresolved_browser_prevents_preview_estimate(self):
        self.root.browser_keep_paths.add('PRIVATE-PROFILE')
        with patch('drive_safety_ui.inspect_fresh_drive_safety') as collect:
            controls, fields, details = self.open_dialog()
            controls['Usar tamanho da prévia'].invoke()
            collect.assert_not_called()
            self.assertEqual(fields[2].get(), '')
            self.assertIn('outras escolhas pendentes', details.get('1.0', 'end'))
            self.assertNotIn('PRIVATE-PROFILE', details.get('1.0', 'end'))

    def test_unresolved_catalog_prevents_preview_estimate(self):
        self.root.catalog_choices['sample'] = 'keep'
        self.root.catalog_items['sample'] = {'possible_paths': ['SECRET-APP-PATH']}
        with patch('drive_safety_ui.inspect_fresh_drive_safety') as collect:
            controls, fields, details = self.open_dialog()
            controls['Usar tamanho da prévia'].invoke()
            collect.assert_not_called()
            self.assertEqual(fields[2].get(), '')
            controls['Conferir cobertura da seleção'].invoke()
            shown = details.get('1.0', 'end')
            self.assertIn('Jogos/aplicativos escolhidos: 1', shown)
            self.assertNotIn('SECRET-', shown)

    def test_existing_file_only_preview_still_populates_size_without_scan(self):
        with patch('drive_safety_ui.inspect_fresh_drive_safety') as collect:
            controls, fields, details = self.open_dialog()
            controls['Usar tamanho da prévia'].invoke()
            collect.assert_not_called()
            self.assertEqual(fields[2].get(), '0,001')
            self.assertIn('1 arquivos', details.get('1.0', 'end'))


if __name__ == '__main__':
    unittest.main()
