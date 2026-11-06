"""Offline regression checks. Fixtures contain invented identities only."""

import json
import unittest
import uuid
import queue
from unittest.mock import Mock
from pathlib import Path

from openpyxl import load_workbook
from collector import Collector, ENDPOINT, FanStore, import_har, normalize_user


class StoreTests(unittest.TestCase):
    def setUp(self):
        self.root = Path('.verification') / str(uuid.uuid4())
        self.store = FanStore(self.root)
        self.url = f'https://www.douyin.com{ENDPOINT}?sec_user_id=example&max_time=0'

    def add(self, users, complete=False):
        self.store.accept(self.url, {'status_code': 0, 'has_more': not complete,
                                     'min_time': 10, 'followers': users, 'private_metadata': 'discard'})

    def test_only_allowed_fields_are_persisted(self):
        self.add([{'uid': '1', 'nickname': 'Example', 'follower_count': 5,
                   'email': 'discard@example.invalid', 'youtube_refresh_token': 'discard'}])
        saved = json.loads(next(self.store.directory.glob('batch-*.json')).read_text(encoding='utf-8'))
        serialized = json.dumps(saved)
        self.assertNotIn('discard', serialized)
        self.assertNotIn('sec_user_id', saved['request'])
        self.assertFalse((self.store.directory / 'account.json').exists())

    def test_session_export_excludes_history_only_accounts(self):
        self.add([{'uid': '1', 'nickname': 'Historical', 'follower_count': 20}], complete=True)
        self.store = FanStore(self.root)
        self.add([{'uid': '2', 'nickname': '=literal', 'follower_count': 10}])
        self.assertFalse(self.store.complete)
        session = load_workbook(self.store.export('session')).active
        history = load_workbook(self.store.export('history')).active
        self.assertEqual(session.max_row, 6)
        self.assertEqual(history.max_row, 7)
        self.assertEqual(session['B6'].value, '=literal')
        self.assertEqual(session['B6'].data_type, 's')
        self.assertEqual(history['C6'].value, 20)
        self.assertEqual(self.store.counts(), {'history': 1, 'session': 1, 'new': 1, 'total': 2})

    def test_invalid_batch_does_not_change_saved_state(self):
        self.add([{'uid': '1', 'follower_count': 5}])
        with self.assertRaises(ValueError):
            self.add([{'uid': '2', 'follower_count': 'invalid'}])
        self.assertEqual(self.store.batches, 1)
        self.assertEqual(len(self.store.users), 1)
        self.assertEqual(len(list(self.store.directory.glob('batch-*.json'))), 1)

    def test_missing_count_stays_missing_and_controls_are_removed(self):
        user = normalize_user({'uid': '1', 'nickname': 'a\x00b'})
        self.assertEqual(user['nickname'], 'ab')
        self.assertIsNone(user['follower_count'])

    def test_corrupt_recovery_remains_blocked_on_retry(self):
        self.add([{'uid': '1'}])
        next(self.store.directory.glob('batch-*.json')).write_text('{invalid', encoding='utf-8')
        recovered = FanStore(self.root)
        for _ in range(2):
            with self.assertRaises(ValueError):
                recovered.open('example')
        self.assertIsNone(recovered.owner)

    def test_empty_har_does_not_export_previous_account(self):
        self.add([{'uid': '1'}])
        path = self.root / 'empty.har'
        path.write_text('{"log":{"entries":[]}}', encoding='utf-8')
        with self.assertRaises(ValueError):
            import_har(path, self.store)

    def test_rate_limit_pauses_without_saving_response(self):
        collector = Collector(queue.Queue(), queue.Queue(), self.root)
        request = Mock()
        request.url = self.url
        request.method = 'GET'
        request.response.return_value.status = 429
        collector.on_request(request)
        collector.running = True
        collector.on_finished(request)
        self.assertFalse(collector.running)
        self.assertEqual(collector.store.batches, 0)
        request.response.return_value.json.assert_not_called()


if __name__ == '__main__':
    unittest.main()
