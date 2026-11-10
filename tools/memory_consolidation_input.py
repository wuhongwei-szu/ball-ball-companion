"""Bounded read-only input for the normal consolidation path. No model or writes."""
import argparse
from contextlib import closing
import datetime as dt
import json
from pathlib import Path
import re
import sqlite3
import sys
import companion_memory as memory
import memory_exclusion as exclusion

ROOT = Path(__file__).resolve().parents[1]
MAX_FILE_BYTES = 512000
MAX_RECORDS = 100
MAX_OUTPUT_BYTES = 48000

def stamp(value):
    parsed = dt.datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError("timezone_required")
    return parsed

def safe(text):
    return isinstance(text, str) and len(text) <= 8000 and not memory.SECRET.search(text) and not memory.PRIVATE.search(text)

def export(root=ROOT, current=None):
    root = Path(root).resolve()
    gate = exclusion.Gate.load(root)  # Fully validate before reading any content.
    current = current or dt.datetime.now(dt.timezone.utc)
    if current.tzinfo is None:
        raise ValueError("timezone_required")
    cutoff = current - dt.timedelta(days=3)
    result = []
    scan_omitted = {}
    skipped_snapshot_files = 0
    path = root / "memory/companion.sqlite3"
    # mode=ro never creates a missing database; no schema bootstrap or PRAGMA writes.
    with closing(sqlite3.connect(path.as_uri() + "?mode=ro", uri=True)) as db:
        db.row_factory = sqlite3.Row
        if db.execute("PRAGMA user_version").fetchone()[0] != 1:
            raise ValueError("unknown_schema")
        # Dates are parsed in Python because older ISO offsets differ lexically.
        # A bounded scan can omit older eligible records; it never implies completeness.
        scan_omitted = {
            "source_rows": max(0, db.execute("SELECT COUNT(*) FROM sources").fetchone()[0]-1000),
            "active_fact_rows": max(0, db.execute("SELECT COUNT(*) FROM facts WHERE active=1").fetchone()[0]-1000)}
        rows = db.execute("SELECT * FROM sources ORDER BY rowid DESC LIMIT 1000").fetchall()
        sources = {}
        for row in rows:
            try:
                recent = cutoff <= stamp(row["at"]) <= current
            except (ValueError, TypeError, AttributeError):
                continue
            if (recent and row["restricted"] == 0 and row["origin"] == "weixin_message"
                    and gate.allowed(row["id"], row["speaker"]) and safe(row["text"])):
                sources[row["id"]] = dict(row)
        # Only facts with a present, eligible ORIGINAL source; orphan/summary facts fail closed.
        facts = db.execute("SELECT * FROM facts WHERE active=1 ORDER BY id DESC LIMIT 1000").fetchall()
        for fact in facts:
            s = db.execute("SELECT * FROM sources WHERE id=?", (fact["source"],)).fetchone()
            if s is not None:
                try:
                    valid_time = stamp(s["at"]) <= current
                except (ValueError, TypeError, AttributeError):
                    valid_time = False
                if not (valid_time and s["restricted"] == 0 and s["origin"] == "weixin_message"
                        and gate.allowed(s["id"], s["speaker"]) and safe(s["text"])):
                    s = None
            if (s and fact["restricted"] == 0 and fact["subject"] in (s["speaker"], "shared")
                    and safe(fact["key"]) and safe(fact["value"]) and safe(fact["quote"])
                    and fact["quote"] and fact["quote"] in s["text"] and fact["value"] in fact["quote"]):
                result.append(dict(kind="current_fact", source=s["id"], speaker=s["speaker"],
                                   at=s["at"], subject=fact["subject"], key=fact["key"], value=fact["value"]))
        for s in sources.values():
            result.append(dict(kind="source_statement", source=s["id"], speaker=s["speaker"], at=s["at"], text=s["text"]))
    # Enumerate ONLY explicitly reviewed snapshot files. Never scan directories or session/history; only reviewed raw blocks may pass.
    # Reviewed snapshots are undated historical evidence, not recent/current assertions.
    for relative in sorted({path for path, digest in gate.reviewed}):
        parts = Path(relative).parts
        if (not exclusion.valid_path(relative)
                or Path(relative).suffix.lower() != ".md"):
            raise ValueError("invalid_snapshot_path")
        file = (root / relative).resolve()
        if not file.is_relative_to(root / "memory"):
            raise ValueError("snapshot_outside_memory")
        if file.stat().st_size > MAX_FILE_BYTES:
            skipped_snapshot_files += 1
            continue
        content = file.read_text(encoding="utf-8")
        blocks = re.split(r"(?m)^##\s+", content) if "raw" in parts else content.splitlines()
        for block in blocks:
            if (block.strip() and safe(block) and (relative, exclusion.block_digest(block)) in gate.reviewed
                    and gate.consolidation_allowed(relative, block)):
                result.append(dict(kind="historical_evidence_not_current_fact", path=relative, text=block))
    kinds = ("current_fact", "source_statement", "historical_evidence_not_current_fact")
    groups = {kind: [r for r in result if r["kind"] == kind] for kind in kinds}
    # Reserve separate record and byte budgets so one class cannot starve another.
    # Unused quota is not borrowed; omissions are explicit, never treated as deletion.
    quotas = dict(zip(kinds, (34, 33, 33)))
    byte_quota = (MAX_OUTPUT_BYTES - 2048) // 3
    chosen = {kind: [] for kind in kinds}
    for kind in kinds:
        used = 0
        for row in groups[kind]:
            size = len(json.dumps(row, ensure_ascii=False).encode("utf-8")) + 2
            if len(chosen[kind]) < quotas[kind] and used + size <= byte_quota:
                chosen[kind].append(row)
                used += size
    selected = []
    for i in range(max((len(v) for v in chosen.values()), default=0)):
        for kind in kinds:
            if i < len(chosen[kind]):
                selected.append(chosen[kind][i])
    omitted = {kind: len(groups[kind])-len(chosen[kind]) for kind in kinds}
    summary = dict(truncated=bool(any(omitted.values()) or any(scan_omitted.values()) or skipped_snapshot_files),
                   emitted={kind: len(chosen[kind]) for kind in kinds}, omitted_eligible=omitted,
                   unscanned_rows=scan_omitted, skipped_snapshot_files=skipped_snapshot_files,
                   completeness="bounded_filtered_view_not_full_history")
    packet = dict(version=1, records=selected, coverage=summary)
    if len(json.dumps(packet, ensure_ascii=False).encode("utf-8")) > MAX_OUTPUT_BYTES:
        raise ValueError("output_budget_exceeded")
    return packet

def main(argv=None):
    parser=argparse.ArgumentParser()
    parser.parse_args(argv)
    try:
        output=json.dumps(export(),ensure_ascii=False,allow_nan=False)
    except Exception:
        print("consolidation_input_status=unavailable",file=sys.stderr)
        return 1
    print(output)
    return 0

if __name__ == "__main__":
    if hasattr(sys.stdout,"reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8",errors="strict")
    raise SystemExit(main())
