import contextlib
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

TOOLS = Path(__file__).resolve().parents[1] / 'tools'
sys.path.insert(0, str(TOOLS))
import common as c


class OutboundStateTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(dir=TOOLS.parent, prefix='synthetic-')
        self.addCleanup(self.tmp.cleanup)
        self.path = str(Path(self.tmp.name) / 'outbound.json')

    def test_nested_send_keeps_one_lock_and_records_both_messages(self):
        @c.outbound_serialized
        def inner():
            c.record_outbound('master', proactive=True)
            return 0

        @c.outbound_serialized
        def burst():
            c.record_outbound('master', proactive=True)
            return inner()

        with patch.object(c, 'OUTBOUND_STATE_FILE', self.path):
            self.assertEqual(burst(), 0)
        data = json.loads(Path(self.path).read_text(encoding='utf-8'))
        self.assertEqual(next(iter(data['master'].values()))['proactive'], 2)

    def test_second_process_cannot_enter_send_while_first_is_running(self):
        import local_state
        code = "import sys;sys.path.insert(0,sys.argv[1]);import local_state;\ntry:\n with local_state.locked(sys.argv[2]):print('entered')\nexcept local_state.StateBusy:print('busy')"
        with local_state.locked(self.path):
            result = subprocess.run([sys.executable, '-c', code, str(TOOLS), self.path],
                                    capture_output=True, text=True, timeout=10)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.strip(), 'busy')

    def test_corrupt_budget_blocks_send_without_overwriting_evidence(self):
        Path(self.path).write_text('{broken', encoding='utf-8')
        called = []

        @c.outbound_serialized
        def send():
            c.proactive_remaining('master')
            called.append(True)
            return 0

        with patch.object(c, 'OUTBOUND_STATE_FILE', self.path), contextlib.redirect_stdout(io.StringIO()):
            self.assertNotEqual(send(), 0)
        self.assertFalse(called)
        self.assertEqual(Path(self.path).read_text(encoding='utf-8'), '{broken')

    def test_platform_credentials_are_scoped_to_selected_toml_project(self):
        path = Path(self.tmp.name) / 'cc.toml'
        path.write_text("[[projects]]\nname = 'other'\n[[projects.platforms]]\ntype='weixin'\n[projects.platforms.options]\naccount_id='other-bot'\ntoken='other-fixture'\n[[projects]]\nname='fixture'\n[[projects.platforms]]\ntype='weixin'\n[projects.platforms.options]\naccount_id='owner-bot'\ntoken='owner-fixture'\n", encoding='utf-8')
        with patch.object(c, 'PROJECT', 'fixture'):
            self.assertEqual(c._parse_weixin_platforms(str(path)), [('owner-bot', 'owner-fixture')])

    def test_nested_corrupt_counters_do_not_reset_daily_budget(self):
        today = c._local_now().date().isoformat()
        for state in ({'master': []}, {'master': {today: None}},
                      {'master': {today: {'proactive': -1}}},
                      {'master': {today: {'proactive': 'damaged'}}}):
            with self.subTest(state=state):
                raw = json.dumps(state)
                Path(self.path).write_text(raw, encoding='utf-8')
                with patch.object(c, 'OUTBOUND_STATE_FILE', self.path):
                    with self.assertRaises(c.local_state.StateError):
                        c.proactive_remaining('master')
                self.assertEqual(Path(self.path).read_text(encoding='utf-8'), raw)

    def test_account_namespace_is_not_part_of_recipient_peer(self):
        self.assertEqual(c.session_peer('weixin:dm:fixture#account:owner-bot'), 'fixture')


if __name__ == '__main__':
    unittest.main()
