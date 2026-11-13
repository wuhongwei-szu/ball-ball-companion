"""Offline regressions for delivery and reminder creation; no gateway calls."""
import contextlib
import importlib.util
import io
import sys
import types
import unittest
from pathlib import Path
from unittest import mock


TOOLS = Path(__file__).resolve().parents[1] / "tools"


def load_tool(name, common, **dependencies):
    spec = importlib.util.spec_from_file_location("delivery_test_" + name, TOOLS / (name + ".py"))
    module = importlib.util.module_from_spec(spec)
    with mock.patch.dict(sys.modules, {"common": common, **dependencies}):
        spec.loader.exec_module(module)
    return module


class DeliveryTests(unittest.TestCase):
    def native_voice_tool(self, payload):
        common = types.SimpleNamespace(
            outbound_serialized=lambda function: function,
            assert_target=lambda target: None,
            record_outbound=mock.Mock(),
            WEIXIN_API_BASE="https://offline.invalid", WEIXIN_API_URL="https://offline.invalid/send",
        )
        helper = load_tool("send_xi", common)
        tool = load_tool("send_voice", common, send_xi=helper)
        tool._target = lambda target: ("offline-token", "offline-session", "offline-context")
        tool._peer_context = lambda *args: ("offline-peer", "offline-context")
        tool.Cipher = lambda *args: types.SimpleNamespace(encryptor=lambda: types.SimpleNamespace(
            update=lambda data: data, finalize=lambda: b""))
        tool._post_json = lambda url, body, token, stage: (
            200, {}, b'{"upload_full_url":"https://offline.invalid/upload"}'
            if stage == "getuploadurl" else payload,
        )
        response = types.SimpleNamespace(headers={"x-encrypted-param": "offline"}, read=lambda: b"")
        tool._opener = lambda: types.SimpleNamespace(
            open=lambda *args, **kwargs: contextlib.nullcontext(response))
        return tool

    def test_native_voice_does_not_accept_invalid_or_rejected_response(self):
        for payload in (b"invalid JSON", b"null", b"[]", b'{"ret":0,"errcode":-2}'):
            with self.subTest(payload=payload):
                tool = self.native_voice_tool(payload)
                with mock.patch("builtins.open", mock.mock_open(read_data=b"#!AMR\nvoice")), \
                        mock.patch.object(tool.os.path, "isfile", return_value=True):
                    with self.assertRaises(tool.VoiceError):
                        tool.send_voice("master", "offline.amr")
                tool.c.record_outbound.assert_not_called()

    def test_native_voice_accepted_response_records_once(self):
        tool = self.native_voice_tool(b'{"ret":0}')
        with mock.patch("builtins.open", mock.mock_open(read_data=b"#!AMR\nvoice")), \
                mock.patch.object(tool.os.path, "isfile", return_value=True):
            result = tool.send_voice("master", "offline.amr")
        self.assertEqual(result["outcome"], "accepted")
        tool.c.record_outbound.assert_called_once_with("master")

    def test_uncertain_tts_send_is_attempted_once(self):
        # The helper owns route selection and reports an uncertain cc exit.
        # Each invocation here represents a potentially delivered file.
        attempts = []

        def run_cc(*args, **kwargs):
            attempts.append("file")
            return types.SimpleNamespace(returncode=1, stdout="", stderr="")

        def send_file(path):
            run_cc(path)
            raise RuntimeError("delivery uncertain; do not retry")

        common = types.SimpleNamespace(
            EDGE_TTS_VOICE="test", XI_SESSION="test-session", PROJECT="test",
            current_target=lambda: "xi", run_cc=run_cc,
            outbound_serialized=lambda function: function,
        )
        tool = load_tool("send_tts", common, send_xi=types.SimpleNamespace(send_file=send_file))
        with self.assertRaisesRegex(RuntimeError, "uncertain"):
            tool._send_xi("offline.mp3")
        self.assertEqual(attempts, ["file"])

    def test_both_reminder_retry_creates_only_missing_owner(self):
        items = []
        attempts = []
        fail_partner = True

        def run_cc(args):
            owner = args[args.index("-s") + 1]
            attempts.append(owner)
            if owner == "partner-session" and fail_partner:
                return types.SimpleNamespace(returncode=1, stdout="", stderr="offline failure")
            return types.SimpleNamespace(returncode=0, stdout="Timer created: timer-" + owner, stderr="")

        common = types.SimpleNamespace(
            MASTER_SESSION="owner-session", XI_SESSION="partner-session", PROJECT="test",
            WORK_DIR="C:/offline", LABELS={}, run_cc=run_cc,
            require=lambda value, name: None,
            REMINDERS_INDEX="offline-index.json",
        )
        class NotStarted(RuntimeError):
            pass

        def add_timer(args):
            result = run_cc(args)
            if result.returncode:
                raise NotStarted("offline executable unavailable")
            return result.stdout.split(":", 1)[1].strip(), result.stdout

        state = types.SimpleNamespace(add_timer=add_timer, NotStarted=NotStarted,
                                      StateError=RuntimeError, locked=lambda path: contextlib.nullcontext())
        tool = load_tool("add_reminder", common, care_timer_state=state)
        tool.load_index = lambda: items
        tool.save_index = lambda saved: None
        argv = ["add_reminder.py", "--owner", "both", "--date", "2099-11-10",
                "--time", "12:00", "--title", "offline reminder"]
        with mock.patch.object(sys, "argv", argv), contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(tool.main(), 1)
            fail_partner = False
            self.assertEqual(tool.main(), 0)
        self.assertEqual(attempts, ["owner-session", "partner-session", "partner-session"])
        self.assertEqual({item["owner"] for item in items}, {"master", "xi"})

    def test_uncertain_reminder_creation_is_not_retried(self):
        items = []
        attempts = []
        common = types.SimpleNamespace(
            MASTER_SESSION="owner-session", XI_SESSION="partner-session", PROJECT="test",
            WORK_DIR="C:/offline", LABELS={}, REMINDERS_INDEX="offline-index.json",
            require=lambda value, name: None,
        )

        class NotStarted(RuntimeError):
            pass

        def add_timer(args):
            attempts.append("timer")
            raise TimeoutError("response lost after possible creation")

        state = types.SimpleNamespace(add_timer=add_timer, NotStarted=NotStarted,
                                      StateError=RuntimeError, locked=lambda path: contextlib.nullcontext())
        tool = load_tool("add_reminder", common, care_timer_state=state)
        tool.load_index = lambda: items
        tool.save_index = lambda saved: None
        argv = ["add_reminder.py", "--owner", "master", "--date", "2099-11-10",
                "--time", "12:00", "--title", "offline reminder"]
        with mock.patch.object(sys, "argv", argv), contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(tool.main(), 1)
            self.assertEqual(tool.main(), 1)
        self.assertEqual(attempts, ["timer"])
        self.assertEqual(items[0]["status"], "uncertain")


if __name__ == "__main__":
    unittest.main(verbosity=2)
