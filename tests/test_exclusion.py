import json
import hashlib
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
from types import SimpleNamespace
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
import memory_exclusion as e
import companion_memory as m
import memory_search as search
import capture_runtime as c

A = "a" * 64
B = "b" * 64
def manifest():
    return dict(version=1, excluded=[], legacy=[], reviewed=[], quarantine_paths=[])
def ref(id=A, speaker="master"):
    return dict(id=id, speaker=speaker)

class GateTests(unittest.TestCase):
    def test_exact_scope_and_later_input(self):
        data=manifest(); data["excluded"]=[ref()]; g=e.Gate(data)
        self.assertFalse(g.allowed(A,"master"))
        self.assertTrue(g.allowed(A,"xi"))
        self.assertTrue(g.allowed(B,"master"))
        self.assertFalse(g.allowed(None,"master"))
    def test_invalid_and_missing_fail_closed(self):
        with self.assertRaises(e.ExclusionError): e.Gate({})
        with self.assertRaises(e.ExclusionError): e.Gate.load(Path(__file__).parent/'not-present')
        data=manifest(); data['excluded']=[dict(id='*',speaker='master')]
        with self.assertRaises(e.ExclusionError): e.Gate(data)
    def test_legacy_scoping(self):
        data=manifest(); g=e.Gate(data)
        self.assertTrue(g.legacy_allowed('memory/STATE.md','synthetic'))
        self.assertEqual(g.consolidation([dict(path='memory/STATE.md',text='synthetic')]),[])
        data['excluded']=[ref()]
        data['legacy']=[dict(path='memory/raw/s1/day.md',sha256=e.block_digest('synthetic'),sources=[ref()])]
        data['quarantine_paths']=['memory/notes/s1/review.md']
        g=e.Gate(data)
        self.assertFalse(g.legacy_allowed('memory/raw/s1/day.md','synthetic'))
        self.assertTrue(g.legacy_allowed('memory/raw/s2/day.md','synthetic'))
        self.assertFalse(g.legacy_allowed('memory/notes/s1/review.md','synthetic'))
        self.assertTrue(g.legacy_allowed('memory/STATE.md','other'))
    def test_reviewed_snapshot_no_promotion_or_hash_bypass(self):
        data=manifest(); data['reviewed']=[dict(path='memory/STATE.md',sha256=e.block_digest('safe'))]
        data['quarantine_paths']=['memory/STATE.md'];g=e.Gate(data)
        records=[dict(path='memory/STATE.md',text='safe',kind='current_fact')]
        self.assertEqual(g.consolidation(records)[0]['kind'],'historical_evidence_not_current_fact')
        self.assertFalse(g.consolidation_allowed('memory/STATE.md','changed'))
        data['legacy']=[dict(path='memory/STATE.md',sha256=e.block_digest('safe'),sources=[ref()])]
        data['excluded']=[ref()];self.assertFalse(e.Gate(data).consolidation_allowed('memory/STATE.md','safe'))
    def test_capture_stable_separate_event_ids(self):
        self.assertEqual(e.capture_id('session',2),e.capture_id('session',2))
        self.assertNotEqual(e.capture_id('session',2),e.capture_id('session',3))
        self.assertNotEqual(e.capture_id('session',2),e.capture_id('new',2))

class IntegrationTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(dir=Path(__file__).parent)
        self.root=Path(self.temp.name); (self.root/'config').mkdir()
        self.data=manifest(); self.save()
    def tearDown(self): self.temp.cleanup()
    def save(self):
        (self.root/'config/memory_exclusions.json').write_text(json.dumps(self.data),encoding='utf-8')
    def request(self,id='one'):
        return dict(text='synthetic evidence value', project='fake',account='fake',message_id=id,at='2026-01-01T00:00:00+00:00')
    def test_ingest_learn_recall_and_retention(self):
        with m.database(self.root) as db:
            sid=m.ingest(db,self.request(),'master')
            source=db.execute('select * from sources where id=?',(sid,)).fetchone()
            with db: m.put_fact(db,source,'master','key','value','evidence value')
            self.assertTrue(m.recall(db,'master'))
            self.data['excluded']=[ref(sid)]; self.save()
            self.assertIsNone(m.ingest(db,self.request(),'master'))
            with self.assertRaises(e.ExclusionError): m.put_fact(db,source,'master','key','value','evidence value')
            self.assertEqual(m.recall(db,'master','synthetic'),[])
            self.assertEqual(db.execute('select count(*) from sources').fetchone()[0],1)
            self.assertEqual(db.execute('select count(*) from facts').fetchone()[0],1)
            self.assertIsNotNone(m.ingest(db,self.request('new'),'master'))
    def test_legacy_actual_search(self):
        (self.root/'memory').mkdir(); path=self.root/'memory/STATE.md'; path.write_text('synthetic evidence',encoding='utf-8')
        self.assertTrue(search.legacy('synthetic','master',self.root))
        self.data['legacy']=[dict(path='memory/STATE.md',sha256=e.block_digest('synthetic evidence'),sources=[ref()])]
        self.data['excluded']=[ref()]; self.save()
        self.assertEqual(search.legacy('synthetic','master',self.root),[])
        self.assertEqual(path.read_text(encoding='utf-8'),'synthetic evidence')
    def test_capture_filtered_cursor_and_no_source_change(self):
        session=self.root/'session.json'; state=self.root/'capture'
        data=dict(sessions={'s1':dict(id='s1',history=[]),'s2':dict(id='s2',history=[])},user_sessions={'o1':['s1'],'o2':['s2']},active_session={'o1':'s1','o2':'s2'})
        session.write_text(json.dumps(data),encoding='utf-8'); appended=[]
        common=SimpleNamespace(SESSION_FILE=str(session),CAPTURE_STATE_FILE=str(state),CFG={},append_raw=lambda *args:appended.append(args))
        self.data['excluded']=[ref(e.capture_id('s1',0))];gate=e.Gate(self.data)
        with patch.object(e.Gate,'load',return_value=gate):
            c.capture(common)
            data['sessions']['s1']['history']=[dict(role='user',content='synthetic excluded',timestamp='2026-01-01T00:00:00+00:00'),dict(role='user',content='synthetic later',timestamp='2026-01-01T00:01:00+00:00')]
            session.write_text(json.dumps(data),encoding='utf-8'); before=session.read_bytes()
            c.capture(common); c.capture(common)
        self.assertEqual(len(appended),1);self.assertEqual(appended[0][1],'synthetic later')
        self.assertEqual(session.read_bytes(),before)
        checkpoint=json.loads(Path(str(state)+'.v2').read_text())
        self.assertEqual(checkpoint['channels']['s1']['sessions']['s1']['cursor'],2)

if __name__=='__main__': unittest.main(verbosity=2)
