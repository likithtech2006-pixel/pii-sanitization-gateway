"""Usage: python scripts/dump_json.py path/to/file.pdf [more files...]
Writes output/<name>.extracted.json (the NormalizedDocument) for debugging.
NOTE: the output contains the RAW text, including PII. output/ is gitignored;
share it privately and never commit it."""
import dataclasses
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from extraction import extract  # noqa: E402


def main(paths):
    if not paths:
        print(__doc__)
        return 2
    out_dir = Path("output")
    out_dir.mkdir(exist_ok=True)
    for p in paths:
        doc = extract(p)
        out = out_dir / (Path(p).stem + ".extracted.json")
        out.write_text(json.dumps(dataclasses.asdict(doc), indent=2, ensure_ascii=False), encoding="utf-8")
        md = doc.metadata
        print(f"{p}: {len(doc.content)} blocks | status={md.get('status')} | "
              f"ocr_used={md.get('ocr_used')} | warnings={md.get('warnings') or '-'} -> {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
