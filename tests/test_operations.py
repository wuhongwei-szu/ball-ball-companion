import contextlib
import datetime
import importlib.util
import io
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import types
import unittest
import zipfile
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
POWERSHELL = shutil.which('powershell.exe')


def temp_directory():
    base = ROOT / 'artifacts' / 'operations-tests'
    base.mkdir(parents=True, exist_ok=True)
    return tempfile.TemporaryDirectory(dir=base)


def load_module(name, path, fake_common=None):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    modules = {} if fake_common is None else {'common': fake_common}
    with patch.dict(sys.modules, modules):
        spec.loader.exec_module(module)
    return module


class SecretScanTests(unittest.TestCase):
    def setUp(self):
        self.temp = temp_directory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        subprocess.run(['git', 'init', '-q', str(self.root)], check=True)
        self.scan = load_module('operations_secret_scan', ROOT / 'scripts/secret_scan.py')
        self.scan.ROOT = str(self.root)

    def scan_output(self, staged=False):
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            if staged:
                result = self.scan.main(['--staged'])
            else:
                result = self.scan.main()
        return result, out.getvalue()

    def test_patch_extension_is_scanned(self):
        (self.root / 'change.patch').write_text('key=' + 'sk-' + 'x' * 30)
        result, output = self.scan_output()
        self.assertNotEqual(result, 0)
        self.assertIn('openai-key', output)
        self.assertNotIn('x' * 30, output)

    def test_windows_home_path_is_scanned(self):
        home_path = 'C:' + chr(92) + 'Users' + chr(92) + 'another-user' + chr(92) + 'private'
        (self.root / 'guide.md').write_text(home_path, encoding='utf-8')
        result, output = self.scan_output()
        self.assertNotEqual(result, 0)
        self.assertIn('windows-user-path', output)

    def test_private_memory_path_rejected_without_secret_pattern(self):
        p = self.root / 'memory' / 'MEMORY.md'
        p.parent.mkdir()
        p.write_text('ordinary private conversation', encoding='utf-8')
        result, output = self.scan_output()
        self.assertNotEqual(result, 0)
        self.assertIn('private-path', output)

    def test_staged_snapshot_is_scanned(self):
        p = self.root / 'notes.md'
        p.write_text('key=' + 'sk-' + 'x' * 30)
        subprocess.run(['git', '-C', str(self.root), 'add', 'notes.md'], check=True)
        p.write_text('safe working copy')
        result, output = self.scan_output(staged=True)
        self.assertNotEqual(result, 0)
        self.assertIn('openai-key', output)

    def test_force_added_private_config_is_rejected(self):
        (self.root / '.gitignore').write_text('config/local.json\n')
        p = self.root / 'config' / 'local.json'; p.parent.mkdir()
        p.write_text('{"preference":"private personal note"}')
        subprocess.run(['git', '-C', str(self.root), 'add', '-f', 'config/local.json'], check=True)
        result, output = self.scan_output(staged=True)
        self.assertNotEqual(result, 0)
        self.assertIn('private-path', output)

    def test_binary_archive_is_rejected_by_path(self):
        (self.root / 'recovery.zip').write_bytes(b'PK\0\0opaque fixture')
        self.assertNotEqual(self.scan_output()[0], 0)

    def test_force_added_original_voice_is_rejected(self):
        path = self.root / '.cc-connect' / 'attachments' / 'voice.silk'
        path.parent.mkdir(parents=True)
        path.write_bytes(b'\x02#!SILK_V3\0private recording')
        subprocess.run(['git', '-C', str(self.root), 'add', '-f', str(path)], check=True)
        result, output = self.scan_output(staged=True)
        self.assertNotEqual(result, 0)
        self.assertIn('private-path', output)

    def test_ignored_runtime_data_does_not_block_public_source_scan(self):
        (self.root / '.gitignore').write_text('memory/\n')
        p = self.root / 'memory' / 'MEMORY.md'
        p.parent.mkdir()
        p.write_text('key=' + 'sk-' + 'x' * 30)
        self.assertEqual(self.scan_output()[0], 0)


@unittest.skipUnless(POWERSHELL, 'Windows PowerShell required')
class BackupTests(unittest.TestCase):
    def test_destination_cannot_recurse_into_timers_or_original_attachments(self):
        with temp_directory() as temp:
            root = Path(temp); bot = root / 'bot'; cc = root / 'cc'
            bot.mkdir(); cc.mkdir()
            for source in (cc / 'timers', bot / '.cc-connect' / 'attachments'):
                with self.subTest(source=source.name):
                    source.mkdir(parents=True)
                    destination = source / 'nested-backup'
                    result = subprocess.run([
                        POWERSHELL, '-NoProfile', '-ExecutionPolicy', 'Bypass', '-File',
                        str(ROOT / 'tools/backup.ps1'), '-BotRoot', str(bot), '-CcDataDir', str(cc),
                        '-DestinationRoot', str(destination), '-Full',
                    ], capture_output=True, text=True)
                    self.assertNotEqual(result.returncode, 0)
                    self.assertIn('outside copied source directories', result.stderr)
                    self.assertFalse(destination.exists())

    def test_timers_and_full_original_attachments_are_restorable(self):
        for full in (False, True):
            with self.subTest(full=full), temp_directory() as temp:
                root = Path(temp); bot = root / 'bot'; cc = root / 'cc'; dest = root / 'backups'
                for path in (bot / 'memory', bot / 'tools', bot / 'config', cc / 'crons', cc / 'sessions'):
                    path.mkdir(parents=True)
                    (path / 'fixture.txt').write_text('recovery fixture')
                (cc / 'config.toml').write_text('fixture=true')
                timers = cc / 'timers' / 'jobs.json'; timers.parent.mkdir()
                timer_bytes = b'{"timers":[{"id":"fixture-pending","status":"pending"}]}'
                timers.write_bytes(timer_bytes)
                voice = bot / '.cc-connect' / 'attachments' / 'weixin' / 'voice.silk'
                voice.parent.mkdir(parents=True)
                voice_bytes = b'\x02#!SILK_V3\ncomplete offline recording fixture\0\xff'
                voice.write_bytes(voice_bytes)
                quote = lambda value: "'" + str(value).replace("'", "''") + "'"
                script = root / 'run.ps1'
                script.write_text('''$ErrorActionPreference = 'Stop'
function Get-Date {
 param([string]$Format)
 $fixed = [datetime]'2026-11-13T04:17:00'
 if ($Format) { return $fixed.ToString($Format) }
 return $fixed
}
function Get-AppxPackage { }
function Copy-Item {
 param([string]$LiteralPath, [string]$Destination, [switch]$Recurse, [switch]$Force, [string]$ErrorAction)
 if ($LiteralPath.EndsWith('cc-connect-weixin.lnk')) { return }
 Microsoft.PowerShell.Management\\Copy-Item -LiteralPath $LiteralPath -Destination $Destination -Recurse:$Recurse -Force:$Force -ErrorAction Stop
}
& ''' + quote(ROOT / 'tools/backup.ps1') + ' -NoPrune -BotRoot ' + quote(bot)
                    + ' -CcDataDir ' + quote(cc) + ' -DestinationRoot ' + quote(dest)
                    + (' -Full' if full else ''), encoding='utf-8')
                env = dict(os.environ, APPDATA=str(root / 'appdata'))
                result = subprocess.run([POWERSHELL, '-NoProfile', '-ExecutionPolicy', 'Bypass', '-File', str(script)], capture_output=True, text=True, env=env)
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                mode = 'full' if full else 'daily'
                archives = list(dest.glob('cc-weixin-' + mode + '-*.zip'))
                self.assertEqual(len(archives), 1)
                with zipfile.ZipFile(archives[0]) as archive:
                    self.assertIsNone(archive.testzip())
                    entries = {name.replace(chr(92), '/'): name for name in archive.namelist()}
                    self.assertIn('cc-connect/timers/jobs.json', entries)
                    self.assertEqual(archive.read(entries['cc-connect/timers/jobs.json']), timer_bytes)
                    original = 'bot/.cc-connect/attachments/weixin/voice.silk'
                    if full:
                        self.assertIn(original, entries)
                        self.assertEqual(archive.read(entries[original]), voice_bytes)
                    else:
                        self.assertNotIn(original, entries)

    def test_success_publishes_complete_archive_before_pruning(self):
        with temp_directory() as temp:
            root = Path(temp); bot = root / 'bot'; cc = root / 'cc'; dest = root / 'backups'
            for path in (bot / 'memory', bot / 'tools', bot / 'config', cc / 'crons', cc / 'sessions'):
                path.mkdir(parents=True)
                (path / 'fixture.txt').write_text('recovery fixture')
            (cc / 'config.toml').write_text('fixture=true')
            dest.mkdir()
            old = dest / 'cc-weixin-daily-20000101-000000.zip'; old.write_bytes(b'old')
            os.utime(old, (946684800, 946684800))
            quote = lambda value: "'" + str(value).replace("'", "''") + "'"
            script = root / 'run.ps1'
            script.write_text('''$ErrorActionPreference = 'Stop'
function Get-AppxPackage { }
function Copy-Item {
 param([string]$LiteralPath, [string]$Destination, [switch]$Recurse, [switch]$Force, [string]$ErrorAction)
 if ($LiteralPath.EndsWith('cc-connect-weixin.lnk')) { return $false }
 Microsoft.PowerShell.Management\\Copy-Item -LiteralPath $LiteralPath -Destination $Destination -Recurse:$Recurse -Force:$Force -ErrorAction Stop
}
& ''' + quote(ROOT / 'tools/backup.ps1') + ' -BotRoot ' + quote(bot) + ' -CcDataDir ' + quote(cc) + ' -DestinationRoot ' + quote(dest), encoding='utf-8')
            env = dict(os.environ, APPDATA=str(root / 'appdata'))
            result = subprocess.run([POWERSHELL, '-NoProfile', '-ExecutionPolicy', 'Bypass', '-File', str(script)], capture_output=True, text=True, env=env)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertIn('BACKUP_OK', result.stdout)
            self.assertFalse(old.exists())
            archives = list(dest.glob('cc-weixin-*.zip'))
            self.assertEqual(len(archives), 1)
            with zipfile.ZipFile(archives[0]) as archive:
                self.assertIsNone(archive.testzip())
                names = {name.replace(chr(92), '/') for name in archive.namelist()}
                self.assertIn('bot/memory/fixture.txt', names)
                self.assertIn('cc-connect/config.toml', names)
                self.assertIn('cc-connect/sessions/fixture.txt', names)
            self.assertEqual(list(dest.glob('stage-*')), [])
            self.assertEqual(list(dest.glob('pending-*')), [])

    def test_copy_failure_does_not_publish_or_prune_backups(self):
        with temp_directory() as temp:
            root = Path(temp)
            bot, cc, dest = root / 'bot', root / 'cc', root / 'backup'
            for name in ('memory', 'config', 'tools'):
                (bot / name).mkdir(parents=True)
                (bot / name / 'file.txt').write_text('fixture')
            for name in ('crons', 'sessions'):
                (cc / name).mkdir(parents=True)
                (cc / name / 'file.json').write_text('{}')
            (cc / 'config.toml').write_text('fixture=true')
            dest.mkdir()
            old = dest / 'cc-weixin-daily-20000101-000000.zip'
            old.write_bytes(b'retain prior recovery point')
            os.utime(old, (946684800, 946684800))
            # Replace only filesystem copying; all paths belong to this fixture.
            script = root / 'run.ps1'
            quote = lambda value: "'" + str(value).replace("'", "''") + "'"
            script.write_text('''$ErrorActionPreference = 'Stop'
function Get-AppxPackage { }
function Copy-Item {
 param([string]$LiteralPath, [string]$Destination, [switch]$Recurse, [switch]$Force, [string]$ErrorAction)
 if ((Split-Path -Leaf $LiteralPath) -eq 'memory') { throw 'simulated locked memory' }
 Microsoft.PowerShell.Management\\Copy-Item -LiteralPath $LiteralPath -Destination $Destination -Recurse:$Recurse -Force:$Force -ErrorAction Stop
}
& ''' + quote(ROOT / 'tools/backup.ps1') + ' -BotRoot ' + quote(bot) + ' -CcDataDir ' + quote(cc) + ' -DestinationRoot ' + quote(dest), encoding='utf-8')
            env = dict(os.environ, APPDATA=str(root / 'appdata'))
            result = subprocess.run([POWERSHELL, '-NoProfile', '-ExecutionPolicy', 'Bypass', '-File', str(script)], capture_output=True, text=True, env=env)
            self.assertNotEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertNotIn('BACKUP_OK', result.stdout)
            self.assertTrue(old.exists(), 'a failed backup must preserve recovery points')
            self.assertEqual(list(dest.glob('cc-weixin-full-*.zip')), [])
            self.assertEqual(list(dest.glob('cc-weixin-daily-*.zip')), [old])


@unittest.skipUnless(POWERSHELL, 'Windows PowerShell required')
class SyncTests(unittest.TestCase):
    def test_prepare_preserves_history_and_unrelated_work(self):
        with temp_directory() as temp:
            root = Path(temp); repo = root / 'repo'; source = root / 'source'
            for directory in (repo / 'scripts', repo / 'tools', repo / 'docs', source / 'tools'):
                directory.mkdir(parents=True)
            shutil.copy2(ROOT / 'scripts/secret_scan.py', repo / 'scripts/secret_scan.py')
            (repo / 'tools/common.py').write_text('old = True\n')
            note = repo / 'docs/note.md'; note.write_text('original\n')
            (source / 'tools/common.py').write_text('new = True\n')
            env = dict(os.environ, GIT_AUTHOR_NAME='Fixture', GIT_COMMITTER_NAME='Fixture', GIT_AUTHOR_EMAIL='fixture@example.invalid', GIT_COMMITTER_EMAIL='fixture@example.invalid')
            def git(*args):
                return subprocess.run(['git', '-C', str(repo), *args], capture_output=True, text=True, env=env, check=True).stdout.strip()
            git('init', '-q'); git('add', '.'); git('commit', '-qm', 'fixture')
            original = git('rev-parse', 'HEAD')
            note.write_text('unrelated local work\n')
            result = subprocess.run([POWERSHELL, '-NoProfile', '-ExecutionPolicy', 'Bypass', '-File', str(ROOT / 'scripts/sync_to_github.ps1'), '-Source', str(source), '-Repo', str(repo)], capture_output=True, text=True, env=env)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertEqual(git('rev-parse', 'HEAD'), original)
            self.assertEqual(git('diff', '--cached', '--name-only'), '')
            self.assertEqual(note.read_text(), 'unrelated local work\n')
            self.assertIn('PREPARED', result.stdout)


class HealthTests(unittest.TestCase):
    def run_health(self, stale=False, tasks='cc-connect-watchdog=Ready\ncc-connect-backup=Ready',
                   jobs=None, timer_output='Pending timers (0)', timer_code=0):
        with temp_directory() as temp:
            root = Path(temp)
            memory = root / 'memory'; memory.mkdir()
            for name in ('MEMORY.md', 'STATE.md', 'EVENTS.md', 'WEEKLY.md', 'IMPROVEMENTS.md', 'CARE_LOG.md', 'last-consolidation.txt'):
                (memory / name).write_text('fixture')
            (root / 'crons').mkdir()
            (root / 'crons/jobs.json').write_text(json.dumps([{'id':'capture01','enabled':True}] if jobs is None else jobs))
            (root / 'config.toml').write_text('fixture=true')
            session = root / 'session.json'; session.write_text('{"sessions":{"s1":{}}}')
            backups = root / 'backups'; backups.mkdir()
            archive = backups / 'cc-weixin-daily-20260101.zip'; archive.write_bytes(b'fixture')
            if stale: os.utime(archive, (946684800, 946684800))
            fake = types.SimpleNamespace(DATA_DIR=str(root), WORK_DIR=str(root), MEMORY_DIR=str(memory), SESSION_FILE=str(session), STICKER_DIR=str(root), CAPTURE_STATE_FILE=str(root / 'capture'), CARE_PLAN_FILE=str(root / 'care'), CFG={}, BOT_NAME='Fixture', load_json=lambda *args: {'stickers':[{}]}, run_cc=lambda *args, **kwargs: types.SimpleNamespace(stdout=timer_output, returncode=timer_code))
            (root / 'manifest.json').write_text('{}')
            cap = types.SimpleNamespace(capture_health=lambda *args: {'capture_status':'ok','coverage_status':'no_recorded_gaps','review_pending':0,'review_boundaries':0,'reason':''})
            with patch.dict(sys.modules, {'capture_runtime':cap}):
                health = load_module('operations_healthcheck', ROOT / 'tools/healthcheck.py', fake)
            health.ps = lambda command: tasks if 'Get-ScheduledTask' in command else '1'
            with contextlib.redirect_stdout(io.StringIO()):
                return health.main()

    def test_missing_tasks_fail_healthcheck(self):
        self.assertEqual(self.run_health(tasks=''), 1)

    def test_stale_backup_fails_healthcheck(self):
        self.assertEqual(self.run_health(stale=True), 1)

    def test_healthy_fixture_passes(self):
        self.assertEqual(self.run_health(), 0)

    def test_invalid_jobs_fail_without_crashing(self):
        self.assertEqual(self.run_health(jobs={'jobs':'unexpected'}), 1)

    def test_timer_cli_failure_fails_healthcheck(self):
        self.assertEqual(self.run_health(timer_output='query failed', timer_code=1), 1)


if __name__ == '__main__':
    unittest.main()
