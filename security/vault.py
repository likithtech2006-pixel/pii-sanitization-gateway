"""Restore real values into AI output, on the user's screen only.

The vault (placeholder -> original value) is built by the redactor and lives only in the redaction
result in server memory for the browser session: it is never written to disk, never logged, never put
in reports or certificates, and never sent to the AI. Restoring is a local string substitution on the
AI's answer, done only when the user explicitly asks; the action is audit-logged (without values).
"""
import re
from typing import Dict, List, Tuple

_TOKEN = re.compile(r"\[([A-Z][A-Z_]*?_\d+)\]")


def rehydrate(text: str, vault: Dict[str, str]) -> Tuple[str, int]:
    """Replace known placeholders with their values. Unknown tokens are left untouched."""
    count = 0

    def sub(m):
        nonlocal count
        token = f"[{m.group(1)}]"
        if token in vault:
            count += 1
            return vault[token]
        return token
    return _TOKEN.sub(sub, text), count


def segments(text: str, vault: Dict[str, str]) -> List[Tuple[str, bool]]:
    """(chunk, is_restored_value) pieces, so the UI can highlight restored values."""
    out, pos = [], 0
    for m in _TOKEN.finditer(text):
        token = f"[{m.group(1)}]"
        if token not in vault:
            continue
        if m.start() > pos:
            out.append((text[pos:m.start()], False))
        out.append((vault[token], True))
        pos = m.end()
    if pos < len(text):
        out.append((text[pos:], False))
    return out
