"""Read-only, exact source exclusion. No transcript deletion or semantic matching."""
import hashlib
import json
from pathlib import Path
import re

class ExclusionError(RuntimeError):
    pass

def canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()

def block_digest(text):
    return hashlib.sha256(text.encode("utf-8")).hexdigest()

def capture_id(session, index):
    return hashlib.sha256(canonical(["capture-v1", session, index])).hexdigest()

def valid_ref(ref):
    return (isinstance(ref, dict) and set(ref) == {"id", "speaker"}
            and ref["speaker"] in {"master", "xi"}
            and isinstance(ref["id"], str) and re.fullmatch(r"[0-9a-f]{64}", ref["id"]))

def valid_path(value):
    return (isinstance(value, str) and value.startswith("memory/")
            and "\\" not in value and ":" not in value
            and all(part not in ("", ".", "..") for part in value.split("/"))
            and not any(ord(ch) < 32 for ch in value))

class Gate:
    def __init__(self, data):
        if (not isinstance(data, dict) or set(data) != {"version", "excluded", "legacy", "reviewed", "quarantine_paths"}
                or data["version"] != 1 or not isinstance(data["excluded"], list)
                or not isinstance(data["legacy"], list)):
            raise ExclusionError("invalid_exclusion_manifest")
        if any(not valid_ref(ref) for ref in data["excluded"]):
            raise ExclusionError("invalid_exclusion_ref")
        self.excluded = {(ref["speaker"], ref["id"]) for ref in data["excluded"]}
        if (not isinstance(data["reviewed"], list) or not isinstance(data["quarantine_paths"], list)
                or any(not valid_path(p) for p in data["quarantine_paths"])):
            raise ExclusionError("invalid_scope")
        self.quarantine_paths = set(data["quarantine_paths"])
        self.reviewed = set()
        for row in data["reviewed"]:
            if (not isinstance(row, dict) or set(row) != {"path", "sha256"}
                    or not valid_path(row["path"])
                    or not isinstance(row["sha256"], str) or not re.fullmatch(r"[0-9a-f]{64}", row["sha256"])):
                raise ExclusionError("invalid_reviewed_snapshot")
            self.reviewed.add((row["path"], row["sha256"]))
        self.legacy = {}
        for row in data["legacy"]:
            if (not isinstance(row, dict) or set(row) != {"path", "sha256", "sources"}
                    or not valid_path(row["path"])
                    or not isinstance(row["sha256"], str) or not re.fullmatch(r"[0-9a-f]{64}", row["sha256"])
                    or not isinstance(row["sources"], list) or not row["sources"]
                    or any(not valid_ref(ref) for ref in row["sources"])):
                raise ExclusionError("invalid_legacy_provenance")
            key = (row["path"], row["sha256"])
            if key in self.legacy:
                raise ExclusionError("duplicate_legacy_provenance")
            self.legacy[key] = row["sources"]

    @classmethod
    def load(cls, root):
        try:
            return cls(json.loads((Path(root)/"config/memory_exclusions.json").read_text(encoding="utf-8")))
        except (OSError, ValueError, TypeError):
            raise ExclusionError("exclusion_manifest_unavailable") from None

    def allowed(self, source_id, speaker):
        ref = {"id": source_id, "speaker": speaker}
        return bool(valid_ref(ref)) and (speaker, source_id) not in self.excluded

    def require(self, source_id, speaker):
        if not self.allowed(source_id, speaker):
            raise ExclusionError("source_excluded_or_unproven")

    def legacy_allowed(self, path, block):
        key = (path, block_digest(block))
        refs = self.legacy.get(key)
        if refs is not None:
            return all(self.allowed(ref["id"], ref["speaker"]) for ref in refs)
        return key in self.reviewed or path not in self.quarantine_paths

    def consolidation_allowed(self, path, block):
        key = (path, block_digest(block))
        if key in self.legacy:
            return self.legacy_allowed(path, block)
        return key in self.reviewed

    def consolidation(self, records):
        """Only metadata-bound blocks; outputs evidence, NEVER current facts.
        Caller supplies vetted visibility/restriction filtering separately.
        Unknown or changed blocks are withheld rather than grandfathered in.
        """
        return [{**r, "kind": "historical_evidence_not_current_fact"}
                for r in records if self.consolidation_allowed(r["path"], r["text"])]

def for_database(db):
    filename = next(row[2] for row in db.execute("PRAGMA database_list") if row[1] == "main")
    if not filename:
        raise ExclusionError("database_root_unproven")
    return Gate.load(Path(filename).parent.parent)
