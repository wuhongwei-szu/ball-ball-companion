"""Offline reminder dispatch regressions; never call a bot or the timer API."""
import contextlib
import datetime as dt
import importlib.util
import json
from pathlib import Path
import sys
import tempfile
import types
import unittest
from unittest.mock import patch

TOOLS = Path(__file__).resolve().parents[1] / 'tools'
sys.path.insert(0, str(TOOLS))
import common as c
import reminder_send as reminders


class ReminderDispatchTests(unittest.TestCase):
    def setUp(self):
        base = TOOLS.parent / 'artifacts' / 'reminder-tests'; base.mkdir(parents=True, exist_ok=True)
        self.tmp = tempfile.TemporaryDirectory(dir=base); self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.now = dt.datetime(2099, 11, 10, 12, 0, tzinfo=dt.timezone(dt.timedelta(hours=8)))
        self.index = self.root / 'reminders.json'
        self.sent = []
        self.sticker_calls=[];self.sticker_result=3;self.sticker_error=None
        def sticker(owner,**kwargs):
            self.assertTrue(all(i['status']=='sent' for i in json.loads(self.index.read_text()) if i['time']=='12:00'))
            self.sticker_calls.append((owner,kwargs))
            if self.sticker_error:raise self.sticker_error
            if self.sticker_result == 0:c.record_outbound(owner,proactive=True)
            return self.sticker_result
        p=patch.dict(sys.modules,{'send_sticker':types.SimpleNamespace(send_one=sticker)})
        p.start();self.addCleanup(p.stop)
        self.items = [self.item('a', 'drink water'), self.item('b', 'take medicine')]
        self.index.write_text(json.dumps(self.items), encoding='utf-8')
        replacements = dict(REMINDERS_INDEX=str(self.index), OUTBOUND_STATE_FILE=str(self.root / 'outbound.json'),
                            WORK_DIR=str(self.root), CFG={'master_account_id':'owner-bot','xi_account_id':'partner-bot'},
                            MASTER_SESSION='owner-session', XI_SESSION='partner-session',
                            MASTER_BOT_ACCOUNT='owner-bot',XI_BOT_ACCOUNT='partner-bot',
                            PROJECT='fixture', CC_BIN='offline-cc.exe', LABELS={'master':'Owner','xi':'Partner'})
        for name, value in replacements.items():
            p = patch.object(c, name, value); p.start(); self.addCleanup(p.stop)
        p = patch.object(c, '_local_now', lambda:self.now); p.start(); self.addCleanup(p.stop)
        for name in ('append_raw', 'append_recent', 'append_care_log', 'assert_target'):
            p = patch.object(c, name, lambda *a, **k:None); p.start(); self.addCleanup(p.stop)

    def item(self, identifier, title, owner='master', time='12:00'):
        return dict(id=identifier, owner=owner, date='2099-11-10', time=time,
                    title=title, note='', status='scheduled', dispatch_version=1)

    def sender(self, owner, text):
        self.sent.append((owner, text))
        return {'outcome':'accepted', 'basis':'cc_exit_zero'}

    def dispatch(self, owner='master'):
        return reminders.dispatch(owner, '2099-11-10', '12:00', now=self.now, sender=self.sender)

    def test_same_recipient_same_minute_sends_complete_batch_once(self):
        self.assertEqual(self.dispatch()['status'], 'accepted')
        self.assertEqual(self.dispatch()['status'], 'accepted')
        self.assertEqual(len(self.sent), 1)
        self.assertIn('drink water', self.sent[0][1]); self.assertIn('take medicine', self.sent[0][1])
        self.assertTrue(all(i['status'] == 'sent' for i in json.loads(self.index.read_text())))
        state = json.loads(Path(c.OUTBOUND_STATE_FILE).read_text())
        self.assertEqual(state['master']['2099-11-10']['proactive'], 1)

    def test_ordinary_reminder_keeps_one_work_sticker_after_text_receipt(self):
        self.sticker_result=0
        self.dispatch();self.dispatch()
        self.assertEqual(len(self.sent),1);self.assertEqual(len(self.sticker_calls),1)
        self.assertEqual(self.sticker_calls[0],('master',{'category':'work','proactive':True,'skip_budget':True}))
        entry=json.loads(Path(c.OUTBOUND_STATE_FILE).read_text())['master']['2099-11-10']
        self.assertEqual(entry['proactive'],2)

    def test_sticker_failure_does_not_change_accepted_text_or_repeat_it(self):
        self.sticker_error=RuntimeError('synthetic uncertain image response')
        self.assertEqual(self.dispatch()['status'],'accepted');self.dispatch()
        self.assertEqual(len(self.sent),1);self.assertEqual(len(self.sticker_calls),1)
        self.assertTrue(all(i['status']=='sent' for i in json.loads(self.index.read_text())))

    def test_urgent_or_explicit_text_only_batches_do_not_send_a_sticker(self):
        self.items[0]['urgent']=True;self.items[1]['text_only']=True
        self.index.write_text(json.dumps(self.items));self.dispatch()
        self.assertEqual(self.sticker_calls,[])

    def test_optional_sticker_preserves_budget_for_other_pending_reminder_groups(self):
        self.items += [self.item('future'+str(i),'future reminder',time=clock) for i,clock in enumerate(('12:30','12:45','13:00'))]
        self.index.write_text(json.dumps(self.items));self.sticker_result=0
        self.dispatch()
        self.assertEqual(self.sticker_calls,[])
        self.assertEqual(len(self.sent),1)

    def test_uncertain_result_never_resends_or_counts_as_accepted(self):
        def uncertain(*args):
            self.sent.append(args); raise TimeoutError('synthetic lost response')
        for _ in range(2):
            result = reminders.dispatch('master', '2099-11-10', '12:00', now=self.now, sender=uncertain)
            self.assertEqual(result['status'], 'uncertain')
        self.assertEqual(len(self.sent), 1)
        self.assertFalse(Path(c.OUTBOUND_STATE_FILE).exists())

    def test_known_unsent_budget_block_recovers_within_window(self):
        c.record_outbound('master', proactive=True)
        self.assertEqual(self.dispatch()['status'], 'blocked')
        self.assertEqual(self.sent, [])
        self.now += dt.timedelta(minutes=5)
        self.assertEqual(self.dispatch()['status'], 'accepted')
        self.assertEqual(len(self.sent), 1)

    def test_missed_window_retains_unsent_items_without_transport(self):
        self.now += dt.timedelta(minutes=61)
        self.assertEqual(self.dispatch()['status'], 'missed')
        self.assertEqual(self.sent, [])
        self.assertTrue(all(i['status'] == 'missed' for i in json.loads(self.index.read_text())))

    def test_accepted_checkpoint_recovers_without_duplicate_budget_charge(self):
        original = c.save_json_atomic
        def fail_index_once(path, data):
            if path == str(self.index) and any(i.get('status') == 'sent' for i in data):
                raise OSError('synthetic index checkpoint failure')
            return original(path, data)
        with patch.object(c, 'save_json_atomic', side_effect=fail_index_once):
            with self.assertRaises(OSError): self.dispatch()
        self.assertEqual(self.dispatch()['status'], 'accepted')
        self.assertEqual(len(self.sent), 1)
        state = json.loads(Path(c.OUTBOUND_STATE_FILE).read_text())
        self.assertEqual(state['master']['2099-11-10']['proactive'], 1)

    def test_accounting_recovery_keeps_the_actual_acceptance_day(self):
        original = c.save_json_atomic
        def fail_index(path, data):
            if path == str(self.index):raise OSError('synthetic index checkpoint failure')
            return original(path,data)
        with patch.object(c,'save_json_atomic',side_effect=fail_index):
            with self.assertRaises(OSError):self.dispatch()
        self.now += dt.timedelta(days=1)
        self.assertEqual(self.dispatch()['status'],'accepted')
        state=json.loads(Path(c.OUTBOUND_STATE_FILE).read_text())
        self.assertEqual(state['master']['2099-11-10']['proactive'],1)
        self.assertEqual(state['master'].get('2099-11-11',{}).get('proactive',0),0)
        self.assertEqual(len(self.sent),1)

    def test_late_accounting_does_not_move_the_last_send_time_backwards(self):
        original=c.save_json_atomic
        def fail_budget(path,data):
            if path == c.OUTBOUND_STATE_FILE:raise OSError('synthetic accounting failure')
            return original(path,data)
        with patch.object(c,'save_json_atomic',side_effect=fail_budget):
            with self.assertRaises(OSError):self.dispatch()
        self.now += dt.timedelta(minutes=10)
        c.record_outbound('master',proactive=True)
        last=self.now.isoformat(timespec='seconds')
        self.dispatch()
        entry=json.loads(Path(c.OUTBOUND_STATE_FILE).read_text())['master']['2099-11-10']
        self.assertEqual(entry['proactive'],2);self.assertEqual(entry['last_proactive'],last)
        self.assertEqual(len(self.sent),1)

    def test_new_same_time_items_share_one_native_exec_timer(self):
        import add_reminder
        items=[];when=self.now.replace(tzinfo=None)+dt.timedelta(days=1)
        with patch.object(add_reminder.state,'add_timer',return_value=('timer-fixture','created')) as create:
            first=add_reminder.add_one('master',when,'first','note1',items)
            second=add_reminder.add_one('master',when,'second','note2',items)
        self.assertEqual(first[0],second[0]);self.assertEqual(create.call_count,1)
        self.assertEqual([i['title'] for i in items],['first','second'])
        self.assertIn('--exec',create.call_args.args[0]);self.assertIn('--mute',create.call_args.args[0])
        self.assertNotIn('--prompt',create.call_args.args[0])

    def test_gc_preserves_pending_window_and_records_missed_after_it(self):
        import reminder_admin
        fixture=self
        class Clock(dt.datetime):
            @classmethod
            def now(cls,tz=None):return fixture.now.replace(tzinfo=None)
        with patch.object(reminder_admin.datetime,'datetime',Clock), patch.object(sys,'argv',['reminder_admin.py','--gc']),contextlib.redirect_stdout(__import__('io').StringIO()):
            self.now += dt.timedelta(minutes=36)
            self.assertEqual(reminder_admin.main(),0)
            self.assertTrue(all(i['status']=='scheduled' for i in json.loads(self.index.read_text())))
            self.now += dt.timedelta(minutes=25)
            self.assertEqual(reminder_admin.main(),0)
        self.assertTrue(all(i['status']=='missed' for i in json.loads(self.index.read_text())))

    def test_due_sweeper_ignores_legacy_and_ended_entries(self):
        self.items[0].pop('dispatch_version');self.items[1]['status']='expired'
        self.index.write_text(json.dumps(self.items))
        with patch.object(sys,'argv',['reminder_send.py','--due']),patch.object(reminders,'dispatch') as dispatch,contextlib.redirect_stdout(__import__('io').StringIO()):
            self.assertEqual(reminders.main(),0)
        dispatch.assert_not_called()

    def test_existing_sending_marker_is_uncertain_not_retryable(self):
        group = reminders.group_id('master','2099-11-10','12:00')
        Path(str(self.index)+'.delivery.json').write_text(json.dumps({group:{'status':'sending'}}))
        self.assertEqual(self.dispatch()['status'], 'uncertain')
        self.assertEqual(self.sent, [])

    def test_legacy_prompt_reminders_require_explicit_migration(self):
        for item in self.items:item.pop('dispatch_version')
        self.index.write_text(json.dumps(self.items))
        self.assertEqual(self.dispatch()['status'], 'legacy')
        self.assertEqual(self.sent, [])

    def test_same_minute_different_recipient_is_not_merged(self):
        self.items[1]['owner']='xi';self.index.write_text(json.dumps(self.items))
        self.dispatch();self.dispatch('xi')
        self.assertEqual([i[0] for i in self.sent], ['master','xi'])
        self.assertNotIn('take medicine', self.sent[0][1])

    def test_cc_exit_zero_without_exact_success_ack_is_uncertain(self):
        with patch.object(c, '_cc_account_args', side_effect=lambda args:args), patch.object(c, 'run_cc', return_value=types.SimpleNamespace(returncode=0,stdout='usage help',stderr='')):
            self.assertEqual(reminders.send_via_cc('master','fixture')['outcome'], 'uncertain')

    def test_thirty_six_minutes_late_merges_all_three_items_once(self):
        self.items.append(self.item('c','bring keys'))
        self.index.write_text(json.dumps(self.items))
        self.now += dt.timedelta(minutes=36)
        self.assertEqual(self.dispatch()['status'],'accepted')
        self.dispatch()
        self.assertEqual(len(self.sent),1)
        for title in ('drink water','take medicine','bring keys'):self.assertIn(title,self.sent[0][1])

    def test_ended_items_are_never_replayed(self):
        for item in self.items:item['status']='expired'
        self.index.write_text(json.dumps(self.items))
        self.assertEqual(self.dispatch()['status'],'legacy')
        self.assertEqual(self.sent,[])

    def test_actual_quiet_hours_block_without_losing_pending_items(self):
        for item in self.items:item['time']='22:30'
        self.index.write_text(json.dumps(self.items))
        self.now=self.now.replace(hour=23,minute=0)
        result=reminders.dispatch('master','2099-11-10','22:30',now=self.now,sender=self.sender)
        self.assertEqual(result['status'],'blocked');self.assertEqual(self.sent,[])

    @unittest.skipUnless(sys.platform == 'win32','PowerShell execution')
    def test_native_timer_shell_runs_quoted_python_in_synthetic_state(self):
        import subprocess
        work=self.root/"shell ' & $path";folder=work/'tools';folder.mkdir(parents=True)
        (folder/'reminder_send.py').write_text('import json,sys;print(json.dumps(sys.argv[1:]))',encoding='utf-8')
        with patch.object(c,'WORK_DIR',str(work)):
            result=subprocess.run(['powershell.exe','-NoProfile','-ExecutionPolicy','Bypass','-Command',reminders.command('master','2099-11-10','12:00')],capture_output=True,text=True)
        self.assertEqual(result.returncode,0,result.stderr)
        self.assertEqual(json.loads(result.stdout),['master','--date','2099-11-10','--time','12:00'])

    @unittest.skipUnless(sys.platform == 'win32','native PowerShell timer execution')
    def test_exact_native_shell_dispatches_real_helper_against_offline_receipt(self):
        import shutil,subprocess
        work=self.root/'native fixture';folder=work/'tools';folder.mkdir(parents=True)
        for name in ('reminder_send.py','common.py','care_timer_state.py','local_state.py'):
            shutil.copy2(TOOLS/name,folder/name)
        calls=work/'calls.jsonl'
        # Use a real executable so Windows batch parsing cannot truncate multiline
        # message arguments. Only its synthetic `send` invocation is intercepted.
        (work/'sitecustomize.py').write_text("import json,sys,os\nfrom pathlib import Path\nif sys.argv[0]=='send':\n p=Path(__file__).with_name('calls.jsonl')\n with p.open('a',encoding='utf-8') as f:f.write(json.dumps(sys.argv)+chr(10))\n print('Message sent successfully.',flush=True)\n os._exit(0)\n",encoding='utf-8')
        config=work/'bot.json';toml=work/'cc.toml';sessions=work/'sessions.json'
        toml.write_text("[[projects]]\nname='fixture'\n[[projects.platforms]]\ntype='weixin'\n[projects.platforms.options]\naccount_id='owner-bot'\ntoken='fixture'\n[[projects.platforms]]\ntype='weixin'\n[projects.platforms.options]\naccount_id='partner-bot'\ntoken='fixture'\n",encoding='utf-8')
        sessions.write_text(json.dumps({'sessions':{'s1':{},'s2':{}},'user_sessions':{'weixin:dm:fixture-owner':['s1'],'weixin:dm:fixture-partner':['s2']}}))
        config.write_text(json.dumps(dict(work_dir=str(work),cc_project='fixture',cc_bin=sys.executable,cc_config_file=str(toml),session_file=str(sessions),master_account_id='owner-bot',xi_account_id='partner-bot')))
        moment=dt.datetime.now().astimezone()-dt.timedelta(minutes=36)
        day,clock=moment.strftime('%Y-%m-%d'),moment.strftime('%H:%M')
        index=work/'memory'/'reminders.json';index.parent.mkdir()
        index.write_text(json.dumps([dict(id=str(i),owner='master',date=day,time=clock,title=title,note='',status='scheduled',dispatch_version=1,allow_night=True) for i,title in enumerate(('first item','second item','third item'))]))
        with patch.object(c,'WORK_DIR',str(work)):
            command=reminders.command('master',day,clock)
        import os
        environment=dict(os.environ,BOT_CONFIG=str(config),PYTHONPATH=str(work))
        for _ in range(2):
            result=subprocess.run(['powershell.exe','-NoProfile','-ExecutionPolicy','Bypass','-Command',command],capture_output=True,text=True,env=environment)
            self.assertEqual(result.returncode,0,result.stdout+result.stderr)
        recorded=[json.loads(line) for line in calls.read_text(encoding='utf-8').splitlines()]
        self.assertEqual(len(recorded),1)
        payload=recorded[0][recorded[0].index('-m')+1]
        for title in ('first item','second item','third item'):self.assertIn(title,payload)
        self.assertTrue(all(item['status']=='sent' for item in json.loads(index.read_text())))

    def test_migration_validates_account_and_preserves_timer_history(self):
        config={'master_account_id':'owner-bot','xi_account_id':'partner-bot'}
        timers=[dict(id=i['id'], project='fixture', session_key='owner-session', platform_account='owner-bot',
                     scheduled_at='2099-11-10T12:00:00+08:00', prompt='legacy reminder', fired=False,
                     created_at='2099-11-01T12:00:00+08:00') for i in self.items]
        legacy=[{k:v for k,v in i.items() if k!='dispatch_version'} for i in self.items]
        with patch.object(c,'CFG',config):
            plan=reminders.migration_plan(legacy,timers,now=self.now-dt.timedelta(days=1))
            self.assertEqual(len(plan['upgraded_ids']),2)
            self.assertTrue(all(i['dispatch_version']==1 for i in plan['index']))
            self.assertTrue(all(i['mute'] and not i['prompt'] and 'reminder_send.py' in i['exec'] for i in plan['timers']))
            self.assertEqual(plan['timers'][0]['created_at'],timers[0]['created_at'])
            timers[0]['platform_account']='partner-bot'
            with self.assertRaises(c.local_state.StateError):
                reminders.migration_plan(legacy,timers,now=self.now-dt.timedelta(days=1))


if __name__ == '__main__':unittest.main()
