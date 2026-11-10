import base64
import contextlib
import importlib.util
import io
import json
from pathlib import Path
import socket
import subprocess
import sys
import types
import unittest
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[1]
sys.dont_write_bytecode = True
sys.path.insert(0, str(ROOT / 'tools'))
# No production common/config/session modules are imported.
_SAVED_MODULES = {name: sys.modules.get(name) for name in ('common', 'send_sticker', 'send_msg')}
COMMON = types.ModuleType('common')
STICKER = types.ModuleType('send_sticker')
sys.modules['common'] = COMMON
sys.modules['send_sticker'] = STICKER

def load(name, tree, filename):
    spec = importlib.util.spec_from_file_location(name, ROOT / tree / 'tools' / filename)
    mod = importlib.util.module_from_spec(spec)
    with contextlib.redirect_stdout(io.StringIO()):
        spec.loader.exec_module(mod)
    return mod

old_send = load('old_send', 'tests/fixtures/lossless_baseline', 'send_msg.py')
new_send = load('new_send', '', 'send_msg.py')
sys.modules['send_msg'] = old_send
old_burst = load('old_burst', 'tests/fixtures/lossless_baseline', 'chat_burst.py')
sys.modules['send_msg'] = new_send
new_burst = load('new_burst', '', 'chat_burst.py')
old_xi = load('old_xi', 'tests/fixtures/lossless_baseline', 'send_xi.py')
new_xi = load('new_xi', '', 'send_xi.py')
from text_input import read_json_text
for _name, _saved in _SAVED_MODULES.items():
    if _saved is None:
        sys.modules.pop(_name, None)
    else:
        sys.modules[_name] = _saved


TEXTS = ['$0.36', '$2/$0.10/$10', '每天$3.33', '"quoted" \'single\' “中文”',
         'line1\nline2\r\nline3', r'literal\n\n C:\path\file', '中文 🐱🍐',
         '--image', '--file', '--relay', '--json-stdin', '  padded\t\n']

class Tests(unittest.TestCase):
    def setUp(self):
        self.network = patch.object(socket, 'socket', side_effect=AssertionError('network forbidden'))
        self.network.start()
        self.addCleanup(self.network.stop)

    def call(self, module, args, payload=''):
        with patch.object(sys, 'argv', [module.__name__] + args), patch.object(sys, 'stdin', io.StringIO(payload)), contextlib.redirect_stdout(io.StringIO()):
            try:
                return module.main()
            except SystemExit as exc:
                return exc.code

    def configure(self, current='master', fresh=False, remaining=4, result=0):
        trace = []
        COMMON.MASTER_SESSION = 'test-master'
        COMMON.XI_SESSION = 'test-xi'
        COMMON.XI_CONTEXT_TOKENS = 'test-context'
        COMMON.PROJECT = 'test-project'
        COMMON.require = Mock()
        COMMON.assert_target = Mock(side_effect=lambda *a, **k: trace.append(('guard', a, k)))
        COMMON.current_target = Mock(return_value=current)
        COMMON.context_token_fresh = Mock(return_value=fresh)
        COMMON.run_cc = Mock(side_effect=lambda *a, **k: (trace.append(('cc', a, k)) or types.SimpleNamespace(returncode=result, stdout='', stderr='')))
        COMMON.append_raw = Mock(side_effect=lambda *a: trace.append(('raw', a)))
        COMMON.append_recent = Mock(side_effect=lambda *a: trace.append(('recent', a)))
        COMMON.proactive_remaining = Mock(return_value=(remaining, 'test quota'))
        COMMON.record_outbound = Mock(side_effect=lambda *a, **k: trace.append(('record', a, k)))
        STICKER.send_one = Mock(side_effect=lambda *a, **k: (trace.append(('sticker', a, k)) or 0))
        return trace

    def test_parser_utf8_bytes(self):
        for many, value in [(False, t) for t in TEXTS] + [(True, TEXTS)]:
            for bom in (b'', b'\xef\xbb\xbf'):
                source = io.TextIOWrapper(io.BytesIO(bom + json.dumps(value, ensure_ascii=False).encode('utf-8')), encoding='ascii')
                with patch.object(sys, 'stdin', source):
                    actual = read_json_text(many=many)
                self.assertEqual(actual, value)
                if not many:
                    self.assertEqual(actual.encode('utf-8'), value.encode('utf-8'))

    def test_invalid_inputs(self):
        for many, values in [(False, ['', 'null', 'false', '4', '{}', '[]', '""', '"  "', '"\\ud800"', '"\\u0000"', '"ok" "extra"']), (True, ['', 'null', '{}', '"str"', '[]', '[1]', '[null]', '["ok", ""]', '["ok", false]'])]:
            for payload in values:
                with self.subTest(many=many, payload=payload), patch.object(sys, 'stdin', io.StringIO(payload)):
                    with self.assertRaises(ValueError):
                        read_json_text(many=many)
        with patch.object(sys, 'stdin', io.TextIOWrapper(io.BytesIO(b'"\xff"'))):
            with self.assertRaises(ValueError):
                read_json_text()

    def test_send_entry_exact_and_legacy(self):
        for text in TEXTS:
            self.configure()
            with patch.object(new_send, 'send_master', return_value=0) as send:
                self.assertEqual(self.call(new_send, ['master', '--json-stdin'], json.dumps(text)), 0)
                self.assertEqual(send.call_args.args[0].encode('utf-8'), text.encode('utf-8'))
        for args in [['master', '  hello ', ' world  '], ['xi', '--relay', 'hello'], ['master', ''], ['bad', 'hello']]:
            outputs=[]
            for module in (old_send, new_send):
                trace=self.configure(current='xi')
                outputs.append((self.call(module,args), trace))
            self.assertEqual(*outputs)

    def test_burst_exact_and_policy_parity(self):
        self.configure(current='xi')
        with patch.object(new_send, 'send_xi', return_value=0) as send, patch.object(new_burst.time, 'sleep'):
            for text in TEXTS:
                self.assertEqual(self.call(new_burst, ['xi', '--json-stdin'], json.dumps([text])),0)
                self.assertEqual(send.call_args.args[0].encode('utf-8'),text.encode('utf-8'))
                self.assertTrue(send.call_args.kwargs['lossless'])
        for proactive in (False,True):
            for remaining in (0,1,2,4):
                for sticker in (False,True):
                    for failure in (0,1,2):
                        records=[]
                        for module, use_json in [(old_burst,False),(new_burst,False),(new_burst,True)]:
                            trace=self.configure(remaining=remaining,result=failure)
                            messages=['one','two','three','four','five','six','seven']
                            args=['master']+(['--proactive'] if proactive else [])+(['--sticker','happy'] if sticker else [])
                            args += ['--json-stdin'] if use_json else messages
                            with patch.object(module.time,'sleep'), patch.object(module.random,'random',return_value=0), patch.object(module.random,'uniform',return_value=0):
                                code=self.call(module,args,json.dumps(messages) if use_json else '')
                            records.append((code,trace))
                        self.assertEqual(records[0],records[1])
                        self.assertEqual(records[0],records[2])

    def test_routes_no_retry_and_direct_exact(self):
        for current,relay,fresh in [('xi',False,False),('master',True,True),('master',True,False)]:
            for result in (0,1,2):
                self.configure(current=current,fresh=fresh,result=result)
                def helper(argv, **kwargs):
                    self.assertEqual(argv[-1],'--json-stdin')
                    with patch.object(new_xi,'send_text',return_value={'ok':True}) as send:
                        code=self.call(new_xi,['--json-stdin'],kwargs['input'])
                        self.assertEqual(send.call_args.args[0].encode('utf-8'),text.encode('utf-8'))
                    return types.SimpleNamespace(returncode=code,stdout='',stderr='')
                for text in TEXTS:
                    with patch.object(new_send.subprocess,'run',side_effect=helper) as proc, contextlib.redirect_stdout(io.StringIO()):
                        new_send.send_xi(text,relay=relay,lossless=True)
                        self.assertEqual(proc.call_count,0 if current=='xi' or fresh else 1)
                if current=='xi' or fresh:
                    self.assertEqual(COMMON.run_cc.call_count,len(TEXTS))
        self.configure(current='xi')
        COMMON.run_cc.side_effect=subprocess.TimeoutExpired('mock',1)
        with patch.object(new_send.subprocess,'run') as proc, contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(new_send.send_xi('text',lossless=True),1)
            proc.assert_not_called()

    @unittest.skipUnless(sys.platform == 'win32', 'Windows PowerShell encoding check')
    def test_real_powershell_echo_only(self):
        for many, value in [(False, t) for t in TEXTS] + [(True, TEXTS)]:
            payload = json.dumps(value, ensure_ascii=False)
            helper = ROOT / 'tests/fixtures/echo_json.py'
            command = ("$OutputEncoding = [System.Text.UTF8Encoding]::new($false);\n@'\n"
                       + payload + "\n'@ | & '" + sys.executable + "' -B -X utf8 '" + str(helper) + "' "
                       + ('many' if many else 'one'))
            result = subprocess.run(['powershell.exe', '-NoProfile', '-NonInteractive', '-EncodedCommand',
                                     base64.b64encode(command.encode('utf-16-le')).decode('ascii')],
                                    capture_output=True, check=True, timeout=30)
            actual = json.loads(result.stdout.decode('utf-8'))
            self.assertEqual(actual, value)
            self.assertEqual(json.dumps(actual, ensure_ascii=False).encode('utf-8'),
                             json.dumps(value, ensure_ascii=False).encode('utf-8'))

    def test_invalid_modes_no_send(self):
        for module,args,payload in [(new_send,['master','--json-stdin','extra'],'"ok"'),(new_send,['master','--json-stdin'],'[]'),(new_burst,['master','--json-stdin','extra'],'["ok"]'),(new_burst,['master','--json-stdin'],'["ok",null]'),(new_xi,['--json-stdin','extra'],'"ok"')]:
            self.configure()
            with patch.object(new_xi,'send_text') as direct,patch.object(new_send.subprocess,'run') as proc:
                self.assertNotEqual(self.call(module,args,payload),0)
                COMMON.run_cc.assert_not_called()
                STICKER.send_one.assert_not_called()
                direct.assert_not_called()
                proc.assert_not_called()

if __name__ == '__main__':
    unittest.main(verbosity=2)
