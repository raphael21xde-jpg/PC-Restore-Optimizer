"""Regressão: a navegação nunca deve confundir inventário e proteção de dados."""
from pathlib import Path
import unittest


class SafetyCopyTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.source = (Path(__file__).resolve().parents[1] / 'app.py').read_text(encoding='utf-8')

    def test_never_claim_disks_protected_in_sidebar(self):
        self.assertNotIn('SEUS DISCOS ESTÃO PROTEGIDOS', self.source)

    def test_sidebar_explicitly_explains_backup_is_not_verified(self):
        self.assertIn('BACKUP NÃO VERIFICADO NESTA TELA', self.source)
        self.assertIn('Detecção não protege dados.', self.source)

    def test_formatting_is_not_implicitly_promised(self):
        self.assertIn('Este aplicativo não formata SSDs nem reinstala o Windows.', self.source)


if __name__ == '__main__':
    unittest.main()
