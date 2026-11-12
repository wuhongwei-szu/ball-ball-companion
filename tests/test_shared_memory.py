import contextlib
import importlib.util
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

HERE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(HERE / "tools"))
import companion_memory as m
import memory_search as search


class SharedMemoryTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(dir=HERE, prefix="synthetic-")
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        (self.root / "config").mkdir()
        self.cfg = {"version": 1, "project": "fixture", "subjects": {
            role: {"account": role+"-bot", "session_key": "weixin:dm:"+role,
                   "user_id": role} for role in ("master", "xi")}}
        (self.root / "config/shared_memory.json").write_text(json.dumps(self.cfg), encoding="utf-8")

    def req(self, role="master", text="fixture", msg="1"):
        return {"project": "fixture", "account": role+"-bot", "session_key": "weixin:dm:"+role,
                "user_id": role, "message_id": msg, "text": text,
                "at": "2026-11-05T18:00:00+08:00"}

    def add(self, role, text, key, value, subject=None, msg="1", **kwargs):
        with m.database(self.root) as db:
            sid = m.ingest(db, self.req(role, text, msg), role)
            source = db.execute("SELECT * FROM sources WHERE id=?", (sid,)).fetchone()
            with db:
                m.put_fact(db, source, subject or role, key, value, text, **kwargs)
            return sid

    def test_distinct_personal_preferences_shared_companion(self):
        self.add("master", "我喜欢红茶", "饮料", "红茶")
        self.add("xi", "我喜欢乌龙茶", "饮料", "乌龙茶")
        # Viewer-first: a normal query only injects the current person's own
        # facts, so the other person's unrelated preference does not leak in.
        master_facts = m.search("饮料", self.root, "master")
        self.assertEqual({(f["subject"], f["value"]) for f in master_facts if f["kind"]=="current_fact"},
                         {("master","红茶")})
        self.assertEqual(master_facts[0]["subject"], "master")
        xi_facts = m.search("饮料", self.root, "xi")
        self.assertEqual({(f["subject"], f["value"]) for f in xi_facts if f["kind"]=="current_fact"},
                         {("xi","乌龙茶")})
        self.assertEqual(xi_facts[0]["subject"], "xi")
        # Cross-person facts are available when the query explicitly mentions
        # the other person, or uses a shared "we/together" context.
        cross = m.search("茜茜喜欢什么饮料", self.root, "master")
        self.assertIn(("xi","乌龙茶"),
                      {(f["subject"], f["value"]) for f in cross if f["kind"]=="current_fact"})
        shared = m.search("我们的饮料偏好", self.root, "xi")
        self.assertIn(("master","红茶"),
                      {(f["subject"], f["value"]) for f in shared if f["kind"]=="current_fact"})

    def test_joint_experience_visible_in_both_entrances(self):
        self.add("master", "我们一起去看了海", "一起出游", "看了海", "shared")
        for who in ("master","xi"):
            self.assertEqual(m.search("出游",self.root,who)[0]["subject"], "shared")

    def test_expired_fact_is_not_current(self):
        self.add("master", "我喜欢红茶", "饮料", "红茶", valid_until="2000-01-01")
        facts = m.search("饮料", self.root, "master")
        self.assertNotIn(("master", "红茶"),
                         {(f["subject"], f["value"]) for f in facts if f["kind"] == "current_fact"})
        self.add("master", "我喜欢绿茶", "饮料2", "绿茶", msg="2", valid_until="2999-01-01")
        facts = m.search("绿茶", self.root, "master")
        self.assertIn(("master", "绿茶"),
                      {(f["subject"], f["value"]) for f in facts if f["kind"] == "current_fact"})

    def test_access_count_and_importance(self):
        self.add("master", "我喜欢红茶", "饮料", "红茶", importance=0.9)
        with m.database(self.root) as db:
            m.recall(db, "master", "饮料", record_access=True)
            row = db.execute(
                "SELECT importance, access_count, last_accessed FROM facts WHERE key='饮料'"
            ).fetchone()
            self.assertAlmostEqual(row["importance"], 0.9)
            self.assertGreaterEqual(row["access_count"], 1)
            self.assertTrue(row["last_accessed"])

    def test_one_explicit_correction_immediately_replaces_old_value(self):
        m.bridge(self.req(text="记住我的饮料偏好是红茶"),self.root)
        packet=m.bridge(self.req(text="更正，我的饮料偏好是乌龙茶",msg="2"),self.root)
        self.assertIn("乌龙茶",packet);self.assertNotIn('"value": "红茶"',packet)
        with m.database(self.root) as db:
            self.assertEqual(db.execute("SELECT value FROM facts WHERE active=1").fetchall()[0][0],"乌龙茶")
            self.assertEqual(db.execute("SELECT count(*) FROM facts").fetchone()[0],2)

    def test_correction_without_replacement_withdraws_old_current_fact(self):
        self.add("master","我喜欢红茶","饮料","红茶")
        m.bridge(self.req(text="记错了，我现在不喜欢红茶",msg="2"),self.root)
        self.assertFalse([f for f in m.search("饮料",self.root,"master") if f["kind"]=="current_fact"])

    def test_same_platform_message_deduplicated(self):
        request=self.req(text="记住我的饮料是红茶")
        m.bridge(request,self.root);m.bridge(request,self.root)
        with m.database(self.root) as db:
            self.assertEqual(db.execute("SELECT count(*) FROM sources").fetchone()[0],1)
            self.assertEqual(db.execute("SELECT count(*) FROM facts").fetchone()[0],1)

    def test_confidential_source_stays_with_speaker(self):
        self.add("xi","保密，我喜欢绿茶","饮料","绿茶")
        self.assertTrue(m.search("绿茶",self.root,"xi"))
        self.assertFalse(m.search("绿茶",self.root,"master"))

    def test_credentials_never_persist(self):
        for index,text in enumerate(("密码：fixture-secret-value", "我的密码是fixture-secret-value", "API key为fixture-secret-value")):
            m.bridge(self.req(text=text,msg=str(index)),self.root)
        with m.database(self.root) as db:
            self.assertEqual(db.execute("SELECT count(*) FROM sources").fetchone()[0],0)
        self.assertNotIn(b"fixture-secret-value",(self.root/"memory/companion.sqlite3").read_bytes())

    def test_ambiguous_identity_rejected(self):
        request=self.req();request["account"]="xi-bot"
        with self.assertRaises(m.MemoryError):m.bridge(request,self.root)

    def test_synthetic_prompt_not_source(self):
        request=self.req(text="【上下文关怀】",msg="")
        m.bridge(request,self.root)
        with m.database(self.root) as db:
            self.assertEqual(db.execute("SELECT count(*) FROM sources").fetchone()[0],0)

    def test_fact_requires_literal_source_and_correct_subject(self):
        with m.database(self.root) as db:
            sid=m.ingest(db,self.req(text="我喜欢红茶"),"master")
            source=db.execute("SELECT * FROM sources WHERE id=?",(sid,)).fetchone()
            for subject,value,quote in [("xi","红茶","我喜欢红茶"),("master","绿茶","我喜欢红茶")]:
                with self.assertRaises(m.MemoryError):m.put_fact(db,source,subject,"饮料",value,quote)

    def test_env_identity_survives_account_namespace(self):
        with patch.dict(os.environ,{"CC_PROJECT":"fixture","CC_PLATFORM_ACCOUNT":"xi-bot",
                                    "CC_SESSION_KEY":"account:xi-bot:weixin:dm:xi"}):
            self.assertEqual(m.env_caller(self.cfg),"xi")

    def test_actual_tool_entry_learns_and_searches_with_caller_env(self):
        tools=self.root/"tools";tools.mkdir()
        shutil.copy2(HERE/"tools/companion_memory.py",tools)
        shutil.copy2(HERE/"tools/memory_search.py",tools)
        request=self.req("xi","我喜欢桂花茶")
        env={**os.environ,"CC_PROJECT":"fixture","CC_PLATFORM_ACCOUNT":"xi-bot",
             "CC_SESSION_KEY":"weixin:dm:xi"}
        cmd=[sys.executable,"-X","utf8",str(tools/"companion_memory.py")]
        first=subprocess.run(cmd+["bridge"],input=json.dumps(request),env=env,capture_output=True,text=True,encoding="utf-8")
        self.assertEqual(first.returncode,0,first.stderr)
        with m.database(self.root) as db:sid=db.execute("SELECT id FROM sources").fetchone()[0]
        second=subprocess.run(cmd+["learn","--source",sid,"--subject","xi","--key","茶偏好",
                                   "--value","桂花茶","--quote","我喜欢桂花茶"],env=env,capture_output=True,text=True,encoding="utf-8")
        self.assertEqual(second.returncode,0,second.stderr)
        third=subprocess.run([sys.executable,"-X","utf8",str(tools/"memory_search.py"),"茶偏好"],env=env,capture_output=True,text=True,encoding="utf-8")
        self.assertEqual(third.returncode,0,third.stderr)
        self.assertIn('"subject": "xi"',third.stdout);self.assertIn("桂花茶",third.stdout)

    def test_legacy_attribution_and_superseded_value_filter(self):
        p=self.root/"memory/raw/s2/2026-11-04.md";p.parent.mkdir(parents=True)
        p.write_text("## 12:00 user\n喜欢红茶\n## 13:00 user\n一起看海",encoding="utf-8")
        self.add("xi","我喜欢红茶","饮料","红茶")
        self.add("xi","我喜欢绿茶","饮料","绿茶",msg="2")
        self.assertFalse(search.legacy("红茶","master",self.root))
        self.assertEqual(search.legacy("看海","master",self.root)[0]["subject"],"xi")


if __name__=="__main__":unittest.main(verbosity=2)
