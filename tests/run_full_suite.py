"""Full synthetic regression runner; no automatic transfer hardware probing.

Old transfer tests omit strategy_inventory and otherwise repeatedly enumerate
real Windows disks. Supply unknown media only for those omitted inventories.
Explicit inventory classification and all diagnostics/API tests remain intact.
"""
from pathlib import Path
import argparse
import faulthandler
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import transfer_engine
import backup_core
import backup_features


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--timeout', type=int, default=120)
    options = parser.parse_args()
    original = transfer_engine.choose_strategy

    def synthetic_strategy(source, target, inventory=None):
        return original(source, target, inventory={} if inventory is None else inventory)

    faulthandler.dump_traceback_later(options.timeout, exit=True)
    try:
        with patch('transfer_engine.choose_strategy', synthetic_strategy), \
             patch('backup_core.choose_strategy', synthetic_strategy), \
             patch('backup_features.choose_strategy', synthetic_strategy):
            suite = unittest.defaultTestLoader.discover(str(Path(__file__).parent))
            result = unittest.TextTestRunner(verbosity=2).run(suite)
        return 0 if result.wasSuccessful() else 1
    finally:
        faulthandler.cancel_dump_traceback_later()


if __name__ == '__main__':
    raise SystemExit(main())
