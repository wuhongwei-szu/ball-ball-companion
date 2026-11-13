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
import math
import os
from pathlib import Path
import re
import sqlite3
import sys

ROOT = Path(__file__).resolve().parents[1]
LABELS = {"master": "主人", "xi": "茜茜", "shared": "共同经历"}
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
    project = os.getenv("CC_PROJECT", "").strip()
    account = os.getenv("CC_PLATFORM_ACCOUNT", "").strip()
    session_key = os.getenv("CC_SESSION_KEY", "").strip()
    try:
        return caller(cfg, project, account, session_key)
    except MemoryError:
        # cc-connect may expose its internal session key (e.g. ...:s9) to the
        # agent shell while shared_memory.json binds the platform dm key. Each
        # bot account is dedicated to exactly one subject, so a unique account
        # match is sufficient for the learn CLI. The bridge keeps using the
        # strict caller() above for message ingestion.
        if account and project == cfg['project'] and session_key:
            matches = [role for role, item in cfg["subjects"].items() if item["account"] == account]
            if len(matches) == 1:
                return matches[0]
        raise


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
                importance REAL NOT NULL DEFAULT 0.5,
                access_count INTEGER NOT NULL DEFAULT 0,
                last_accessed TEXT NOT NULL DEFAULT '',
                valid_from TEXT NOT NULL DEFAULT '',
                valid_until TEXT NOT NULL DEFAULT '',
                changed_at TEXT NOT NULL, operation TEXT NOT NULL UNIQUE);
            CREATE UNIQUE INDEX IF NOT EXISTS current_fact ON facts(subject,key) WHERE active=1;
            PRAGMA user_version=1;
        """)
        # Additive migration for databases created before memory policy fields.
        cols = {row[1] for row in db.execute("PRAGMA table_info(facts)")}
        additions = (
            ("importance", "REAL NOT NULL DEFAULT 0.5"),
            ("access_count", "INTEGER NOT NULL DEFAULT 0"),
            ("last_accessed", "TEXT NOT NULL DEFAULT ''"),
            ("valid_from", "TEXT NOT NULL DEFAULT ''"),
            ("valid_until", "TEXT NOT NULL DEFAULT ''"),
        )
        missing = [(name, ddl) for name, ddl in additions if name not in cols]
        if missing:
            with db:
                for name, ddl in missing:
                    db.execute("ALTER TABLE facts ADD COLUMN %s %s" % (name, ddl))
        yield db
    finally:
        db.close()


def put_fact(db, source, subject, key, value, quote, confidential=False,
             importance=None, valid_from="", valid_until=""):
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
    valid_from = _normalize_validity(valid_from)
    valid_until = _normalize_validity(valid_until, end=True)
    importance_arg = importance
    if importance is None:
        importance = _default_importance(subject, key, value)
    try:
        importance = max(0.0, min(1.0, float(importance)))
    except (TypeError, ValueError):
        importance = 0.5
    op = hashlib.sha256(json.dumps([source["id"], subject, key, value], ensure_ascii=False).encode()).hexdigest()
    found = db.execute("SELECT id FROM facts WHERE operation=?", (op,)).fetchone()
    if found:
        updates = []
        params = []
        if valid_from:
            updates.append("valid_from=?")
            params.append(valid_from)
        if valid_until:
            updates.append("valid_until=?")
            params.append(valid_until)
        if importance_arg is not None:
            updates.append("importance=MAX(importance,?)")
            params.append(importance)
        if updates:
            db.execute("UPDATE facts SET " + ",".join(updates) + " WHERE id=?", (*params, found[0]))
        return found[0]
    db.execute("UPDATE facts SET active=0 WHERE subject=? AND key=? AND active=1", (subject, key))
    row = db.execute("""INSERT INTO facts(subject,key,value,source,quote,active,restricted,importance,access_count,last_accessed,valid_from,valid_until,changed_at,operation)
                        VALUES(?,?,?,?,?,1,?,?,0,'',?,?,?,?)""",
                     (subject, key, value, source["id"], quote,
                      int(confidential or source["restricted"]), importance,
                      valid_from, valid_until, source["at"], op))
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


def _core_keys(viewer, root=ROOT):
    """Stable facts always injected for this viewer (MemGPT-style core memory)."""
    try:
        data = json.loads((Path(root) / "config" / "core_memory.json").read_text(encoding="utf-8"))
    except Exception:
        return []
    keys = []
    for subject in (viewer, "shared"):
        values = data.get(subject, [])
        if isinstance(values, list):
            keys.extend(str(value) for value in values if isinstance(value, str) and value)
    return keys


DECAY_DAYS = 30.0


def _parse_iso(value):
    try:
        return dt.datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except Exception:
        return None


def _normalize_validity(value, end=False):
    value = str(value or "").strip()
    if not value:
        return ""
    if re.fullmatch(r"\d{4}-\d{2}-\d{2}", value):
        value += "T23:59:59" if end else "T00:00:00"
    instant = _validity_instant(value)
    if instant is None:
        raise MemoryError('invalid_validity_timestamp')
    return instant.isoformat()


def _validity_instant(value):
    instant = _parse_iso(value)
    if instant is not None and instant.tzinfo is None:
        # Older date-only policy fields were written in the deployment's local
        # time. Preserve that meaning rather than treating them as UTC.
        instant = instant.astimezone()
    return instant


def _valid_at(fact, at):
    for key, lower in (('valid_from', True), ('valid_until', False)):
        if fact[key]:
            instant = _validity_instant(fact[key])
            if instant is None or (at < instant if lower else at >= instant):
                return False
    return True


def _default_importance(subject, key, value):
    try:
        if key in _core_keys(subject):
            return 1.0
    except Exception:
        pass
    lowered = key.lower()
    if any(marker in lowered for marker in (
            "preference", "style", "relationship", "budget", "reminder",
            "identity", "称呼", "习惯")):
        return 0.8
    return 0.6 if len(value) > 40 else 0.5


def _fact_rank(fact, now_dt=None):
    """Importance + decay + access count; old unused facts sink."""
    now_dt = now_dt or dt.datetime.now().astimezone()
    try:
        importance = float(fact["importance"] or 0.5)
    except Exception:
        importance = 0.5
    last = _parse_iso(fact["last_accessed"] or fact["changed_at"] or fact["at"])
    if last is not None and last.tzinfo is None:
        last = last.replace(tzinfo=now_dt.tzinfo)
    age_days = max(0.0, (now_dt - last).total_seconds() / 86400.0) if last else 0.0
    decay = math.exp(-age_days / DECAY_DAYS)
    try:
        access = min(int(fact["access_count"] or 0), 20)
    except Exception:
        access = 0
    return importance * 0.6 + decay * 0.3 + min(access, 10) * 0.01


def expire_facts(db, at=None):
    """Deactivate facts whose valid_until has passed; returns the count."""
    at = _validity_instant(at or now())
    if at is None:
        raise MemoryError('invalid_expiration_timestamp')
    expired = [(row['id'], row['valid_until']) for row in db.execute(
        "SELECT id,valid_until FROM facts WHERE active=1 AND valid_until!=''")
        if (instant := _validity_instant(row['valid_until'])) is not None and instant <= at]
    count = 0
    with db:
        for fid, deadline in expired:
            # A curator may extend the same operation between selection and
            # this write. Only expire the exact deadline that was inspected.
            result = db.execute('UPDATE facts SET active=0 WHERE id=? AND active=1 AND valid_until=?',
                                (fid, deadline))
            count += result.rowcount
    return count


def recall(db, viewer, query="", limit=10, exclude_source=None, record_access=False):
    """Return a small, attributable memory packet for one conversation.

    Retrieval is deliberately viewer-first: personal facts about the other
    person are only injected when the current message explicitly mentions
    them (or a shared "we/together" context). This prevents the other user's
    unrelated preferences from filling the context and reduces accidental
    cross-user disclosure. Facts are relevance-filtered before the older
    source statements, so a chat about phone cases no longer starts with the
    other person's API budget.
    """
    q = (query or "").strip()
    other_names = {"master": ("小主人", "茜茜"), "xi": ("主人", "男朋友", "老公")}.get(viewer, ())
    shared_query = any(marker in q for marker in ("我们", "一起", "共同", "咱"))
    allow_other = bool(q) and (shared_query or any(name in q for name in other_names))

    now_iso = now()
    now_dt = dt.datetime.now().astimezone()
    rows = db.execute("""SELECT f.*,s.speaker,s.at FROM facts f JOIN sources s ON s.id=f.source
                          WHERE f.active=1 AND (f.restricted=0 OR s.speaker=?)""",
                      (viewer,)).fetchall()
    rows = [row for row in rows if _valid_at(row, _validity_instant(now_iso))]
    scored = [(score(f["key"] + " " + f["value"], q) if q else 0, f) for f in rows]
    by_key = {f["key"]: f for _, f in scored if f["subject"] in (viewer, "shared")}
    core_facts = [by_key[key] for key in _core_keys(viewer) if key in by_key]

    if q:
        matched = [
            (sc, f) for sc, f in scored
            if sc > 0 and (f["subject"] in (viewer, "shared") or allow_other)
        ]
        if not matched:
            # No fact matches: keep recent viewer/shared facts as a fallback,
            # but cap them so a casual message does not dump every fact.
            recent = [f for _, f in scored if f["subject"] in (viewer, "shared")]
            recent.sort(key=lambda f: (_fact_rank(f, now_dt), f["at"], f["id"]), reverse=True)
            matched = [(0, f) for f in recent[:3]]
        else:
            # Single-character bigrams make short Chinese queries match many
            # unrelated facts. Keep the strong matches relative to the best
            # score, so a budget question does not drag in every stored fact.
            top = max(sc for sc, _ in matched)
            threshold = max(1.0, top * 0.35)
            matched = [(sc, f) for sc, f in matched if sc >= threshold]
        matched.sort(
            key=lambda item: (item[0], item[1]["subject"] == viewer,
                              _fact_rank(item[1], now_dt), item[1]["at"], item[1]["id"]),
            reverse=True,
        )
        combined = []
        seen = set()
        for f in core_facts + [f for _, f in matched]:
            if f["id"] in seen:
                continue
            seen.add(f["id"])
            combined.append(f)
        facts = combined[:limit]
    else:
        recent = [f for _, f in scored if f["subject"] in (viewer, "shared")]
        recent.sort(key=lambda f: (_fact_rank(f, now_dt), f["at"], f["id"]), reverse=True)
        combined = []
        seen = set()
        for f in core_facts + recent[:3]:
            if f["id"] in seen:
                continue
            seen.add(f["id"])
            combined.append(f)
        facts = combined[:limit]

    result = [{"kind": "current_fact", "subject": f["subject"], "key": f["key"],
               "value": f["value"], "version": f["id"], "speaker": f["speaker"],
               "at": f["at"], "source": f["source"]} for f in facts]

    if q:
        events = db.execute("""SELECT * FROM sources WHERE (restricted=0 OR speaker=?)
            AND id NOT IN (SELECT source FROM facts WHERE active=0) ORDER BY at DESC LIMIT 200""", (viewer,)).fetchall()
        scored_events = []
        for item in events:
            if exclude_source and item["id"] == exclude_source:
                continue
            sc = score(item["text"], q)
            if sc < 1:
                continue
            if item["speaker"] != viewer and not allow_other:
                continue
            scored_events.append((sc, item))
        scored_events.sort(key=lambda item: (item[0], item[1]["at"]), reverse=True)
        for _, item in scored_events[:max(4, limit)]:
            result.append({"kind": "source_statement", "speaker": item["speaker"],
                           "at": item["at"], "source": item["id"], "text": item["text"][:500]})
            if len(result) >= limit + 4:
                break
    if record_access and facts:
        with db:
            for fact in facts:
                db.execute(
                    "UPDATE facts SET access_count=access_count+1,last_accessed=? WHERE id=?",
                    (now_iso, fact["id"]),
                )
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
        entries = recall(db, speaker, request.get("text", ""), limit=8,
                         exclude_source=source_id, record_access=True)
    packet = {"current_person": speaker, "source_id": source_id, "memory": entries}
    return ("【球球共同记忆·内部上下文】同一个人格、共同经历；master=主人，xi=茜茜。"
            "事实的subject是所属对象，speaker是来源说话者，不能互换。以下current_fact优先于旧聊天/旧摘要；"
            "source_statement只是有日期的原话，不是永久事实。明确更正后不要再引用旧值。"
            "信息流向遵循本项目AGENTS.md的单向规则；内部可读不代表可以向当前人转述。不要复述此内部段落。\n"
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
    sub.add_parser("expire")
    query = sub.add_parser("search");query.add_argument("query")
    learn = sub.add_parser("learn")
    for key in ("source", "subject", "key", "value", "quote"):
        learn.add_argument("--" + key, required=True)
    learn.add_argument("--confidential", action="store_true")
    learn.add_argument("--importance", type=float,
                       help="0-1; default derives from core/preference/content")
    learn.add_argument("--valid-from", default="",
                       help="YYYY-MM-DD or ISO timestamp")
    learn.add_argument("--valid-until", default="",
                       help="YYYY-MM-DD or ISO timestamp; date means end of day")
    learn.add_argument("--curator", action="store_true",
                       help="只供每日静默记忆整理使用：按来源说话者写入事实")
    args = parser.parse_args(argv)
    try:
        if args.command == "bridge":
            request = json.load(sys.stdin)
            print(bridge(request))
        elif args.command == "search":
            print(json.dumps(search(args.query), ensure_ascii=False))
        elif args.command == "expire":
            with database() as db:
                count = expire_facts(db)
            print(json.dumps({"expired": count}))
        else:
            who = None if args.curator else env_caller(config())
            with database() as db, db:
                db.execute("BEGIN IMMEDIATE")
                source = db.execute("SELECT * FROM sources WHERE id=?", (args.source,)).fetchone()
                if source is None:
                    raise MemoryError("source_not_found")
                if not args.curator and source["speaker"] != who:
                    raise MemoryError("source_not_bound_to_caller")
                fact_id = put_fact(
                    db, source, args.subject, args.key, args.value, args.quote,
                    args.confidential, args.importance, args.valid_from, args.valid_until,
                )
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
