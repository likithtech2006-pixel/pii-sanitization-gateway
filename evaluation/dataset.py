"""Ground-truth loading and validation.

File format (JSON, schema_version 1):

{
  "schema_version": 1,
  "documents": {
    "pptx": {
      "source_name": "Cadence_Financial_Group_Organizational_Pack.pptx",
      "source_type": "pptx",
      "items": [ {id, type, subtype, value, variants, location, required,
                  modality, verification, note}, ... ],
      "hard_negatives": [ {text, why, location}, ... ]
    },
    ...
  }
}

required=true  : counts towards recall; a miss is a security miss.
required=false : ambiguous / low-legibility item. Detecting it is not an
                 error (so it is never a false positive); missing it is not
                 penalised.
"""
import json
import os
from dataclasses import dataclass, field

from evaluation import taxonomy as T

SCHEMA_VERSION = 1
MODALITIES = ("native_text", "table", "ocr_text", "ocr_figure", "embedded_image",
              "narrative", "metadata")
VERIFICATIONS = ("text", "visual", "inferred")


@dataclass
class GoldItem:
    id: str
    doc: str
    type: str
    value: str
    location: dict
    required: bool = True
    subtype: str = ""
    variants: list = field(default_factory=list)
    modality: str = "native_text"
    verification: str = "text"
    note: str = ""

    def all_values(self):
        return [self.value] + list(self.variants)


@dataclass
class HardNegative:
    doc: str
    text: str
    why: str = ""
    location: dict = field(default_factory=dict)


@dataclass
class GoldDocument:
    key: str
    source_name: str
    source_type: str
    items: list
    hard_negatives: list

    def required_items(self):
        return [i for i in self.items if i.required]


class GroundTruth:
    def __init__(self, documents):
        self.documents = documents  # key -> GoldDocument

    def get(self, key_or_name):
        """Find a document by its key ('pdf') or by its file name."""
        if key_or_name in self.documents:
            return self.documents[key_or_name]
        base = os.path.basename(str(key_or_name)).lower()
        for doc in self.documents.values():
            if doc.source_name.lower() == base:
                return doc
        raise KeyError("no ground truth for %r" % (key_or_name,))

    def keys(self):
        return list(self.documents)


def validate(gt):
    """Raise ValueError listing every problem found in the ground truth."""
    problems = []
    seen = set()
    for key, doc in gt.documents.items():
        for item in doc.items:
            if item.id in seen:
                problems.append("duplicate id %s" % item.id)
            seen.add(item.id)
            if item.type not in T.ALL_TYPES:
                problems.append("%s: unknown type %r" % (item.id, item.type))
            if not str(item.value).strip():
                problems.append("%s: empty value" % item.id)
            if item.modality not in MODALITIES:
                problems.append("%s: unknown modality %r" % (item.id, item.modality))
            if item.verification not in VERIFICATIONS:
                problems.append("%s: unknown verification %r" % (item.id, item.verification))
            if item.doc != key:
                problems.append("%s: doc field %r != document key %r" % (item.id, item.doc, key))
    if problems:
        raise ValueError("invalid ground truth:\n  " + "\n  ".join(problems))
    return True


def _item_from_dict(doc_key, d):
    return GoldItem(
        id=d["id"], doc=doc_key, type=T.canonical_type(d["type"]), value=d["value"],
        location=d.get("location", {}), required=bool(d.get("required", True)),
        subtype=d.get("subtype", ""), variants=list(d.get("variants", [])),
        modality=d.get("modality", "native_text"),
        verification=d.get("verification", "text"), note=d.get("note", ""))


def load_ground_truth(path):
    """Load one JSON file, or every *.json file in a directory, and validate."""
    paths = []
    if os.path.isdir(path):
        for name in sorted(os.listdir(path)):
            if name.endswith(".json"):
                paths.append(os.path.join(path, name))
    else:
        paths.append(path)
    documents = {}
    for p in paths:
        with open(p, encoding="utf-8") as fh:
            data = json.load(fh)
        if data.get("schema_version") != SCHEMA_VERSION:
            raise ValueError("%s: unsupported schema_version %r" % (p, data.get("schema_version")))
        for key, d in data["documents"].items():
            items = [_item_from_dict(key, i) for i in d.get("items", [])]
            negs = [HardNegative(doc=key, text=n["text"], why=n.get("why", ""),
                                 location=n.get("location", {}))
                    for n in d.get("hard_negatives", [])]
            documents[key] = GoldDocument(key, d["source_name"], d.get("source_type", key), items, negs)
    gt = GroundTruth(documents)
    validate(gt)
    return gt


def save_ground_truth(gt, path):
    """Write a GroundTruth back to JSON (used by the builder tool)."""
    out = {"schema_version": SCHEMA_VERSION, "documents": {}}
    for key, doc in gt.documents.items():
        out["documents"][key] = {
            "source_name": doc.source_name,
            "source_type": doc.source_type,
            "items": [{
                "id": i.id, "type": i.type, "subtype": i.subtype, "value": i.value,
                "variants": i.variants, "location": i.location, "required": i.required,
                "modality": i.modality, "verification": i.verification, "note": i.note,
            } for i in doc.items],
            "hard_negatives": [{"text": n.text, "why": n.why, "location": n.location}
                               for n in doc.hard_negatives],
        }
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(out, fh, indent=1, ensure_ascii=False)
