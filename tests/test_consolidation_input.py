import contextlib
import datetime as dt
import hashlib
import io
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'tools'))
import companion_memory as m
import memory_exclusion as e
import memory_consolidation_input as x

class ExportTests(unittest.TestCase):
    def setUp(self):
        self.t=tempfile.TemporaryDirectory(dir=Path(__file__).parent)
        self.root=Path(self.t.name);(self.root/'config').mkdir();(self.root/'memory').mkdir()
        self.data=dict(version=1,excluded=[],legacy=[],reviewed=[],quarantine_paths=[])
        self.save(); self.now=dt.datetime(2026,1,5,tzinfo=dt.timezone.utc)
    def tearDown(self): self.t.cleanup()
    def save(self): (self.root/'config/memory_exclusions.json').write_text(json.dumps(self.data),encoding='utf-8')
    def seed(self,id='a',text='synthetic ordinary value',restricted=0,at='2026-01-04T00:00:00+00:00',speaker='master'):
        sid=hashlib.sha256(id.encode()).hexdigest()
        with m.database(self.root) as db,db:
            db.execute('INSERT INTO sources VALUES(?,?,?,?,?,?)',(sid,speaker,at,text,restricted,'weixin_message'))
        return sid
    def test_excluded_then_same_text_new_id_and_readonly(self):
        old=self.seed('old');new=self.seed('new');self.data['excluded']=[dict(id=old,speaker='master')];self.save()
        path=self.root/'memory/companion.sqlite3';before=path.read_bytes()
        result=x.export(self.root,self.now);ids=[r.get('source') for r in result['records']]
        self.assertNotIn(old,ids);self.assertIn(new,ids);self.assertEqual(path.read_bytes(),before)
        self.assertEqual(json.loads(json.dumps(result)),result)
    def test_private_secret_stale_future_and_missing_fact_source(self):
        self.seed('private',restricted=1);self.seed('privateword',text='保密 synthetic')
        self.seed('secret',text='password=synthetic-secret')
        self.seed('old',at='2025-01-01T00:00:00+00:00');self.seed('future',at='2027-01-01T00:00:00+00:00')
        self.seed('badtime',at='2026-01-04T00:00:00')
        with m.database(self.root) as db,db:
            db.execute("INSERT INTO facts VALUES(1,'master','key','value',?,'value',1,0,'2026-01-04','fake')",('f'*64,))
        self.assertEqual(x.export(self.root,self.now)['records'],[])
    def test_current_fact_and_source(self):
        sid=self.seed()
        with m.database(self.root) as db,db:
            s=db.execute('SELECT * FROM sources WHERE id=?',(sid,)).fetchone()
            m.put_fact(db,s,'master','key','value','ordinary value')
        records=x.export(self.root,self.now)['records']
        self.assertEqual({r['kind'] for r in records},{'current_fact','source_statement'})
    def test_unknown_md_never_read_and_reviewed_hash_only(self):
        with m.database(self.root): pass
        (self.root/'memory/STATE.md').write_text('synthetic approved\nsynthetic unknown',encoding='utf-8')
        self.assertEqual(x.export(self.root,self.now)['records'],[])
        self.data['reviewed']=[dict(path='memory/STATE.md',sha256=e.block_digest('synthetic approved'))];self.save()
        records=x.export(self.root,self.now)['records'];self.assertEqual(len(records),1)
        self.assertEqual(records[0]['text'],'synthetic approved');self.assertEqual(records[0]['kind'],'historical_evidence_not_current_fact')
    def test_error_no_partial_body_and_cli_valid_json(self):
        self.seed()
        stdout=io.StringIO();stderr=io.StringIO()
        original=x.export
        with patch.object(x,'export',side_effect=lambda: original(self.root,self.now)),contextlib.redirect_stdout(stdout):
            self.assertEqual(x.main([]),0)
        self.assertTrue(json.loads(stdout.getvalue())['records'])
        self.data['excluded']=[dict(id='bad',speaker='master')];self.save()
        stdout=io.StringIO()
        with patch.object(x,'export',side_effect=lambda: original(self.root,self.now)),contextlib.redirect_stdout(stdout),contextlib.redirect_stderr(stderr):
            self.assertEqual(x.main([]),1)
        self.assertEqual(stdout.getvalue(),'');self.assertEqual(stderr.getvalue(),'consolidation_input_status=unavailable\n')
    def test_missing_db_is_not_created(self):
        with self.assertRaises(Exception): x.export(self.root,self.now)
        self.assertFalse((self.root/'memory/companion.sqlite3').exists())

    def test_old_active_fact_without_recent_source_statement(self):
        sid=self.seed('oldactive',at='2020-01-01T00:00:00+00:00')
        with m.database(self.root) as db,db:
            source=db.execute('SELECT * FROM sources WHERE id=?',(sid,)).fetchone()
            m.put_fact(db,source,'master','oldkey','value','ordinary value')
        result=x.export(self.root,self.now)
        self.assertEqual(len(result['records']),1)
        self.assertEqual(result['records'][0]['kind'],'current_fact')
    def test_three_full_classes_have_separate_budgets(self):
        lines=[]
        for i in range(110):
            sid=self.seed(str(i))
            with m.database(self.root) as db,db:
                source=db.execute('SELECT * FROM sources WHERE id=?',(sid,)).fetchone()
                m.put_fact(db,source,'master','key'+str(i),'value','ordinary value')
            line='synthetic reviewed '+str(i);lines.append(line)
            self.data['reviewed'].append(dict(path='memory/STATE.md',sha256=e.block_digest(line)))
        (self.root/'memory/STATE.md').write_text('\n'.join(lines),encoding='utf-8');self.save()
        result=x.export(self.root,self.now)
        counts=result['coverage']['emitted']
        self.assertEqual(counts,dict(current_fact=34,source_statement=33,historical_evidence_not_current_fact=33))
        self.assertTrue(result['coverage']['truncated'])
        self.assertEqual(sum(result['coverage']['omitted_eligible'].values()),230)
        self.assertLessEqual(len(json.dumps(result,ensure_ascii=False).encode()),x.MAX_OUTPUT_BYTES)
        self.assertEqual(result,x.export(self.root,self.now))
    def test_manifest_path_validation_all_lists(self):
        for path in ['memory/../outside.md','memory/dir\\outside.md','memory/file.md:stream','/memory/x.md','C:/memory/x.md','memory//x.md']:
            for field in ['reviewed','legacy','quarantine_paths']:
                data=dict(version=1,excluded=[],legacy=[],reviewed=[],quarantine_paths=[])
                row=dict(path=path,sha256='a'*64)
                if field=='legacy': row['sources']=[dict(id='a'*64,speaker='master')]
                data[field]=[path if field=='quarantine_paths' else row]
                with self.subTest(path=path,field=field),self.assertRaises(e.ExclusionError): e.Gate(data)

if __name__=='__main__': unittest.main(verbosity=2)
