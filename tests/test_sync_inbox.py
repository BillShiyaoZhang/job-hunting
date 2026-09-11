import json
from pathlib import Path
import shutil
import tempfile
import unittest
from unittest.mock import patch

from scripts import sync_inbox


class BatchHandoffTests(unittest.TestCase):
    def test_invalid_later_batch_leaves_checkout_clean_and_can_be_retried(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            checkout = root / 'checkout'
            shutil.copytree(sync_inbox.ROOT / 'jobradar', checkout / 'jobradar')
            (checkout / 'config').mkdir()
            shutil.copyfile(sync_inbox.ROOT / 'tests/fixtures/search.json', checkout / 'config/search.json')
            config = json.loads((checkout / 'config/search.json').read_text(encoding='utf-8'))
            source = next(s for s in config['sources'] if s['adapter'] == 'codex')
            valid = {'schema_version': 1, 'source_id': source['id'], 'collected_at': '2026-01-01T00:00:00Z', 'status': 'blocked', 'coverage': 'partial', 'message': 'Fixture: access unavailable', 'jobs': []}
            first, second = root / 'first.json', root / 'second.json'
            first.write_text(json.dumps(valid), encoding='utf-8')
            second.write_text(json.dumps({**valid, 'source_id': 'missing-source'}), encoding='utf-8')
            with patch.object(sync_inbox, 'CHECKOUT', checkout):
                with self.assertRaises(RuntimeError):
                    sync_inbox.import_batches([first, second])
                self.assertFalse((checkout / 'data/inbox').exists())
                second.write_text(json.dumps({**valid, 'message': 'Fixture: second observation'}), encoding='utf-8')
                targets = sync_inbox.import_batches([first, second])
                self.assertEqual(len(set(targets)), 2)
                before = {target: (checkout / target).read_bytes() for target in targets}
                self.assertEqual(sync_inbox.import_batches([first, second]), targets)
                self.assertEqual({target: (checkout / target).read_bytes() for target in targets}, before)


if __name__ == '__main__':
    unittest.main()
