"""Explicit UTF-8 JSON input; never reinterpret escapes in decoded text."""
import json
import sys


def read_json_text(*, many=False):
    stream = getattr(sys.stdin, "buffer", sys.stdin)
    try:
        raw = stream.read()
        if isinstance(raw, bytes):
            raw = raw.decode("utf-8-sig")
        value = json.loads(raw)
    except (ValueError, UnicodeError, RecursionError):
        raise ValueError("stdin must contain valid UTF-8 JSON") from None
    if many:
        if not isinstance(value, list) or not value:
            raise ValueError("stdin must be a nonempty JSON string array")
        texts = value
    else:
        texts = [value]
    for text in texts:
        if not isinstance(text, str) or not text.strip():
            raise ValueError("each message must be a nonblank JSON string")
        try:
            text.encode("utf-8")
        except UnicodeError:
            raise ValueError("message contains invalid Unicode") from None
        if "\x00" in text:
            raise ValueError("message must not contain NUL")
    return texts if many else value
