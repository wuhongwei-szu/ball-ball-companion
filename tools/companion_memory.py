"""One companion, shared experiences, attributed and versioned personal facts.

The bridge accepts engine message metadata, not HistoryEntry.user or a hook.
SQLite transactions provide source deduplication and atomic fact correction.
No model, network, credentials, transcript migration, or sending is involved.
"""
import argparse
import contextlib
import datetime as dt
import hashlib
import json
import os
from pathlib import Path
import re
import sqlite3
import sys

ROOT = Path(__file__).resolve().parents[1]
LABELS = {"master": "主人", "xi": "Partner", "shared": "共同经历"}
SECRET = re.compile(
    r"sk-[\w-]{16,}|gh[pousr]_[\w]{20,}|xox[baprs]-[\w-]{10,}|"
    r"(?i:bearer)\s+\S+|(?i:password|passwd|pwd|密码|口令|api[_ -]?key|密钥|令牌|secret|token)"
    r"\s*(?:[:=：]|是|为)\s*\S+|-----BEGIN [A-Z ]*PRIVATE KEY-----")
PRIVATE = re.compile(r"保密|只跟你说|别告诉|不要告诉|别让.{0,12}知道|身份证|银行卡|病历|诊断|住址|手机号")
CORRECTION = re.compile(r"更正|纠正|记错|不对|不是|不再|现在不")


class MemoryError(RuntimeError):
    """Only fixed error codes may be reported by the bridge."""


def now():
    return dt.datetime.now().astimezone().isoformat(timespec="seconds")


def config(root=ROOT):
    data = json.loads((Path(root) / "config/shared_memory.json").read_text(encoding="utf-8"))
    if data.get("version") != 1 or set(data.get("subjects", {})) != {"master", "xi"}:
        raise MemoryError("invalid_binding")
    return data


def caller(cfg, project, account, session_key, user_id=None):
    if project != cfg["project"] or not account or not session_key:
        raise MemoryError("identity_unproven")
    matches = []
    for role, item in cfg["subjects"].items():
        owner = item["session_key"]
        if (item["account"] == account
                and (session_key == owner or session_key.endswith(":" + owner))
                and (user_id is None or user_id == item["user_id"])):
            matches.append(role)
    if len(matches) != 1:
        raise MemoryError("identity_unproven")
    return matches[0]


def env_caller(cfg):
    return caller(cfg, os.getenv("CC_PROJECT", ""), os.getenv("CC_PLATFORM_ACCOUNT", ""),
                  os.getenv("CC_SESSION_KEY", ""))


@contextlib.contextmanager
def database(root=ROOT):
    path = Path(root) / "memory/companion.sqlite3"
    path.parent.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(path, timeout=2)
    db.row_factory = sqlite3.Row
    try:
        version = db.execute("PRAGMA user_version").fetchone()[0]
        if version not in (0, 1):
            raise MemoryError("unknown_schema")
        db.executescript("""
            CREATE TABLE IF NOT EXISTS sources (
                id TEXT PRIMARY KEY, speaker TEXT NOT NULL, at TEXT NOT NULL,
                text TEXT NOT NULL, restricted INTEGER NOT NULL, origin TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS facts (
                id INTEGER PRIMARY KEY, subject TEXT NOT NULL, key TEXT NOT NULL,
                value TEXT NOT NULL, source TEXT NOT NULL REFERENCES sources(id),
                quote TEXT NOT NULL, active INTEGER NOT NULL, restricted INTEGER NOT NULL,
                changed_at TEXT NOT NULL, operation TEXT NOT NULL UNIQUE);
            CREATE UNIQUE INDEX IF NOT EXISTS current_fact ON facts(subject,key) WHERE active=1;
            PRAGMA user_version=1;
        """)
        yield db
    finally:
        db.close()


def put_fact(db, source, subject, key, value, quote, confidential=False):
    if subject not in (source["speaker"], "shared"):
        raise MemoryError("subject_not_supported_by_speaker")
    if not key or len(key) > 80 or not value or len(value) > 600:
        raise MemoryError("invalid_fact")
    if not quote or quote not in source["text"] or value not in quote:
        raise MemoryError("literal_evidence_required")
    if SECRET.search(value + quote):
        raise MemoryError("credential_excluded")
    if subject == "shared" and not re.search(r"我们|一起|共同|球球", quote):
        raise MemoryError("joint_evidence_required")
    op = hashlib.sha256(json.dumps([source["id"], subject, key, value], ensure_ascii=False).encode()).hexdigest()
    found = db.execute("SELECT id FROM facts WHERE operation=?", (op,)).fetchone()
    if found:
        return found[0]
    db.execute("UPDATE facts SET active=0 WHERE subject=? AND key=? AND active=1", (subject, key))
    row = db.execute("""INSERT INTO facts(subject,key,value,source,quote,active,restricted,changed_at,operation)
                        VALUES(?,?,?,?,?,1,?,?,?)""",
                     (subject, key, value, source["id"], quote,
                      int(confidential or source["restricted"]), source["at"], op))
    return row.lastrowid


def ingest(db, request, speaker):
    text = request["text"].strip()
    if not text or len(text) > 32000 or SECRET.search(text):
        return None
    source_id = hashlib.sha256(json.dumps([request["project"], request["account"],
                                           request["message_id"]]).encode()).hexdigest()
    at = request.get("at") or now()
    dt.datetime.fromisoformat(at.replace("Z", "+00:00"))
    with db:
        db.execute("BEGIN IMMEDIATE")
        old = db.execute("SELECT * FROM sources WHERE id=?", (source_id,)).fetchone()
        if old is not None:
            if old["speaker"] != speaker or old["text"] != text:
                raise MemoryError("source_changed")
            return source_id
        db.execute("INSERT INTO sources VALUES(?,?,?,?,?,?)", (
            source_id, speaker, at, text, int(bool(PRIVATE.search(text))), "weixin_message"))
        source = db.execute("SELECT * FROM sources WHERE id=?", (source_id,)).fetchone()
        # Explicitly corrected old values stop being current before the model runs.
        # If no safe replacement can be parsed, retain the source and await a sourced update.
        if CORRECTION.search(text):
            current = db.execute("SELECT id,value FROM facts WHERE subject=? AND active=1", (speaker,)).fetchall()
            for item in current:
                if item["value"] in text:
                    db.execute("UPDATE facts SET active=0 WHERE id=?", (item["id"],))
        # Deliberately narrow, explicit wording; other expressions remain attributed
        # source material until the ordinary reply uses the evidence-checked learn tool.
        match = re.search(r"(?:记住[，,：:]?\s*|更正[，,：:]?\s*|纠正[，,：:]?\s*)我的([^，。！？\n]{1,30}?)(?:改为|改成|是)[：:]?([^。！？\n]{1,300})", text)
        if match:
            put_fact(db, source, speaker, match[1].strip(), match[2].strip(), match[0])
    return source_id


def score(text, query):
    text, query = text.casefold(), query.strip().casefold()
    if not query:
        return 0
    result = 12 if query in text else 0
    result += sum(4 for term in query.split() if term in text)
    result += sum(1 for i in range(len(query) - 1) if query[i:i+2].strip() in text)
    return result


def recall(db, viewer, query="", limit=10):
    facts = db.execute("""SELECT f.*,s.speaker,s.at FROM facts f JOIN sources s ON s.id=f.source
                          WHERE f.active=1 AND (f.restricted=0 OR s.speaker=?)""", (viewer,)).fetchall()
    facts = sorted(facts, key=lambda f: (score(f["key"]+f["value"], query),
                                      f["subject"] == viewer, f["id"]), reverse=True)[:limit]
    result = [{"kind": "current_fact", "subject": f["subject"], "key": f["key"],
               "value": f["value"], "version": f["id"], "speaker": f["speaker"],
               "at": f["at"], "source": f["source"]} for f in facts]
    if query:
        events = db.execute("""SELECT * FROM sources WHERE (restricted=0 OR speaker=?)
            AND id NOT IN (SELECT source FROM facts WHERE active=0) ORDER BY at DESC LIMIT 200""", (viewer,)).fetchall()
        events = sorted(events, key=lambda s: score(s["text"], query), reverse=True)
        for item in events:
            if score(item["text"], query) > 1:
                result.append({"kind": "source_statement", "speaker": item["speaker"],
                               "at": item["at"], "source": item["id"], "text": item["text"][:500]})
            if len(result) >= limit + 4:
                break
    return result


def bridge(request, root=ROOT):
    cfg = config(root)
    # Real inbound identity and message ID are supplied by the engine. Timer and
    # cron messages have no platform message ID; they are never ingested.
    speaker = caller(cfg, request["project"], request["account"], request["session_key"], request.get("user_id"))
    with database(root) as db:
        source_id = None
        if request.get("message_id") and request.get("user_id") not in ("timer", "cron"):
            source_id = ingest(db, request, speaker)
        entries = recall(db, speaker, request.get("text", ""), limit=8)
    packet = {"current_person": speaker, "source_id": source_id, "memory": entries}
    return ("【球球共同记忆·内部上下文】同一个人格、共同经历；master=主人，xi=Partner。"
            "事实的subject是所属对象，speaker是来源说话者，不能互换。以下current_fact优先于旧聊天/旧摘要；"
            "source_statement只是有日期的原话，不是永久事实。明确更正后不要再引用旧值。"
            "保密内容只用于原说话者，不能主动向另一位转述。不要复述此内部段落。\n"
            + json.dumps(packet, ensure_ascii=False) + "\n"
            "遇到值得记住的新表达，用本项目tools/companion_memory.py learn --source <source_id> "
            "--subject master|xi|shared --key <同一事实固定键> --value <来源原词> --quote <来源原句>；"
            "subject只可为当前本人或有依据的共同经历。更正用同一个key。不要记录凭据。\n")


def search(query, root=ROOT, viewer=None, limit=8):
    if viewer is None:
        viewer = env_caller(config(root))
    with database(root) as db:
        return recall(db, viewer, query, limit)


def main(argv=None):
    parser = argparse.ArgumentParser(description="球球共同记忆：有来源、分主体、可更正")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("bridge")
    query = sub.add_parser("search");query.add_argument("query")
    learn = sub.add_parser("learn")
    for key in ("source", "subject", "key", "value", "quote"):
        learn.add_argument("--" + key, required=True)
    learn.add_argument("--confidential", action="store_true")
    args = parser.parse_args(argv)
    try:
        if args.command == "bridge":
            request = json.load(sys.stdin)
            print(bridge(request))
        elif args.command == "search":
            print(json.dumps(search(args.query), ensure_ascii=False))
        else:
            who = env_caller(config())
            with database() as db, db:
                db.execute("BEGIN IMMEDIATE")
                source = db.execute("SELECT * FROM sources WHERE id=?", (args.source,)).fetchone()
                if source is None or source["speaker"] != who:
                    raise MemoryError("source_not_bound_to_caller")
                fact_id = put_fact(db, source, args.subject, args.key, args.value, args.quote, args.confidential)
            print(json.dumps({"ok": True, "version": fact_id}))
        return 0
    except Exception:
        # Do not print request contents, command-line values, paths or exception text.
        print("memory_status=unavailable; preserve existing records", file=sys.stderr)
        return 1


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    raise SystemExit(main())
