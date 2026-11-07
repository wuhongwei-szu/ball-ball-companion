import ast, datetime, json, tempfile, types, unittest, contextlib, io
from pathlib import Path
P=Path(__file__).resolve().parents[1]/'tools'
def functions(path,names,env):
 tree=ast.parse(path.read_text(encoding='utf-8'))
 nodes=[n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name in names]
 assert len(nodes)==len(names)
 exec(compile(ast.Module(body=nodes,type_ignores=[]),str(path),'exec'),env)
 return env
cap={}
exec(compile((P/'capture_runtime.py').read_text(encoding='utf-8'),'capture_runtime.py','exec'),cap)
c=functions(P/'common.py',{'_outbound_entry','proactive_remaining'},dict(datetime=datetime,re=__import__('re')))
tree=ast.parse((P/'care_scheduler.py').read_text(encoding='utf-8'))
prompts=[ast.literal_eval(n.value) for n in tree.body if isinstance(n,ast.Assign) and any(isinstance(t,ast.Name) and t.id in ('CARE_PROMPT','LEGACY_PROMPT') for t in n.targets)]
fake=types.SimpleNamespace(LABELS={'master':'Owner'},WORK_DIR='C:/example-companion')
rem=functions((P/'add_reminder.py'),{'build_prompt'},{'c':fake})['build_prompt']('master','2026-11-07 12:00','example','note')
class Checks(unittest.TestCase):
 def setUp(self):
  self.now=datetime.datetime.fromisoformat('2026-11-08T00:01:00+08:00')
  self.state={}
  c.update(_local_now=lambda:self.now,load_json=lambda *a:self.state,OUTBOUND_STATE_FILE='unused',PROACTIVE_DAILY_LIMIT=4,PROACTIVE_MIN_GAP_SECONDS=300)
 def entry(self,day,stamp,count=1,target='master'):
  self.state.setdefault(target,{})[day]={'last_proactive':stamp,'proactive':count}
 def test_care_templates(self):
  self.assertEqual(len(prompts),2)
  for p in prompts:self.assertTrue(cap['is_synthetic_prompt'](p))
 def test_reminder_template(self):self.assertTrue(cap['is_synthetic_prompt'](rem))
 def test_ordinary_template_mentions(self):
  for t in ('今天想聊上下文关怀','【定时提醒】现在是 我自己写的句子','【上下文关怀】现在是 想聊天'):
   self.assertFalse(cap['is_synthetic_prompt'](t))
 def test_legacy(self):
  for t in ('每日要闻','静默记忆整理任务','主动关心任务','【系统通知】'):
   self.assertTrue(cap['is_synthetic_prompt'](t))
 @unittest.expectedFailure
 def test_known_legacy_false_positive(self):self.assertFalse(cap['is_synthetic_prompt']('我想聊每日要闻的标题'))
 def test_midnight_block(self):
  self.entry('2026-11-07','2026-11-07T23:59:00+08:00')
  self.assertEqual(c['proactive_remaining']('master')[0],0)
 def test_midnight_boundary(self):
  self.entry('2026-11-07','2026-11-07T23:56:00+08:00')
  self.assertEqual(c['proactive_remaining']('master')[0],4)
 def test_today_latest(self):
  self.entry('2026-11-07','2026-11-07T23:50:00+08:00')
  self.entry('2026-11-08','2026-11-08T00:00:30+08:00')
  self.assertEqual(c['proactive_remaining']('master')[0],0)
 def test_daily_cap(self):
  self.entry('2026-11-08','2026-11-07T21:00:00+08:00',4)
  self.assertEqual(c['proactive_remaining']('master')[0],0)
 def test_separate_targets(self):
  self.entry('2026-11-07','2026-11-07T23:59:00+08:00',target='xi')
  self.assertEqual(c['proactive_remaining']('master')[0],4)
 def test_naive_timestamp(self):
  self.entry('2026-11-07','2026-11-07T23:59:00')
  self.assertEqual(c['proactive_remaining']('master')[0],0)
 def test_offset_timestamp(self):
  self.entry('2026-11-07','2026-11-07T15:59:00+00:00')
  self.assertEqual(c['proactive_remaining']('master')[0],0)
 def test_bad_timestamp(self):
  self.entry('2026-11-07',None)
  self.assertEqual(c['proactive_remaining']('master')[0],4)
 def test_future_timestamp(self):
  self.entry('2026-11-08','2026-11-08T00:02:00+08:00')
  self.assertEqual(c['proactive_remaining']('master')[0],0)
 def test_capture_integration(self):
  with tempfile.TemporaryDirectory() as d:
   p=Path(d); session=p/'sessions.json'; state=p/'capture'
   data={'sessions':{'s1':{'id':'s1','history':[]},'s2':{'id':'s2','history':[]}},'user_sessions':{'a':['s1'],'b':['s2']},'active_session':{'a':'s1','b':'s2'}}
   session.write_text(json.dumps(data),encoding='utf-8'); saved=[]
   fake=types.SimpleNamespace(SESSION_FILE=str(session),CAPTURE_STATE_FILE=str(state),CFG={},append_raw=lambda *args:saved.append(args))
   with contextlib.redirect_stdout(io.StringIO()):self.assertEqual(cap['capture'](fake),0)
   data['sessions']['s1']['history']=[{'role':'user','content':rem},{'role':'assistant','content':'NO_REPLY'},{'role':'user','content':'ordinary message'}]
   session.write_text(json.dumps(data),encoding='utf-8')
   with contextlib.redirect_stdout(io.StringIO()):self.assertEqual(cap['capture'](fake),0)
   self.assertEqual([x[1] for x in saved],['ordinary message'])
   with contextlib.redirect_stdout(io.StringIO()):self.assertEqual(cap['capture'](fake),0)
   self.assertEqual(len(saved),1)
if __name__=='__main__':unittest.main(verbosity=2)
