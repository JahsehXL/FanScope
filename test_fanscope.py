"""Offline regression checks. Fixtures contain invented identities only."""

import json
import unittest
import uuid
import queue
import os
import tempfile
from unittest.mock import Mock, patch
from pathlib import Path

from openpyxl import load_workbook
from collector import Collector, ENDPOINT, FanStore, import_har, normalize_user, resolve_app_home


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

    def test_har_import_and_excel_export_with_network_disabled(self):
        path = self.root / 'offline.har'
        self.root.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps({'log': {'entries': [{
            'request': {'method': 'GET', 'url': self.url},
            'response': {'content': {'text': json.dumps({
                'status_code': 0, 'has_more': False,
                'followers': [{'uid': 'offline-example', 'nickname': 'Offline', 'follower_count': 12}]
            })}}
        }]}}), encoding='utf-8')
        with patch('socket.socket', side_effect=AssertionError('Network socket requested')), \
                patch('socket.create_connection', side_effect=AssertionError('Network connection requested')):
            target = import_har(path, self.store)
            self.assertEqual(load_workbook(target).active['B6'].value, 'Offline')


class PathTests(unittest.TestCase):
    def test_default_directory_uses_current_users_environment(self):
        with tempfile.TemporaryDirectory() as directory:
            with patch.dict(os.environ, {'LOCALAPPDATA': directory, 'FANSCOPE_HOME': ''}):
                self.assertEqual(resolve_app_home(), Path(directory).resolve() / 'FanScope')
            with patch.dict(os.environ, {'LOCALAPPDATA': '', 'FANSCOPE_HOME': ''}), \
                    patch('collector.Path.home', return_value=Path(directory)):
                self.assertEqual(resolve_app_home(), Path(directory).resolve() / 'AppData' / 'Local' / 'FanScope')

    def test_custom_directory_expands_environment_and_home(self):
        with tempfile.TemporaryDirectory() as directory:
            with patch.dict(os.environ, {'FANSCOPE_PATH_TEST': directory,
                                         'FANSCOPE_HOME': '$FANSCOPE_PATH_TEST/portable'}):
                self.assertEqual(resolve_app_home(), Path(directory).resolve() / 'portable')
            with patch.dict(os.environ, {'FANSCOPE_HOME': '~/FanScope-test'}):
                self.assertEqual(resolve_app_home(), (Path.home() / 'FanScope-test').resolve())

    def test_relative_store_remains_anchored_after_working_directory_changes(self):
        original = Path.cwd()
        with tempfile.TemporaryDirectory() as directory:
            first, second = Path(directory) / 'first', Path(directory) / 'second'
            first.mkdir()
            second.mkdir()
            try:
                os.chdir(first)
                with patch.dict(os.environ, {'FANSCOPE_HOME': './portable'}):
                    home = resolve_app_home()
                store = FanStore('./records')
                os.chdir(second)
                store.accept(f'https://www.douyin.com{ENDPOINT}?sec_user_id=path-example',
                             {'status_code': 0, 'has_more': False, 'followers': [{'uid': 'path-example'}]})
                self.assertEqual(home, first.resolve() / 'portable')
                self.assertTrue(store.export().is_relative_to(first.resolve()))
                self.assertFalse((second / 'records').exists())
            finally:
                os.chdir(original)


if __name__ == '__main__':
    unittest.main()
