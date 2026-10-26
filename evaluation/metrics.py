"""Evaluation metrics for the PII gateway.

Everything here is plain Python with no third-party packages.

Main entry point: evaluate_document(...), which returns one dict of metrics.
aggregate(...) combines several documents (micro-average: counts are summed,
then precision / recall are recomputed).

Definitions (see docs/evaluation.md for the long version)
---------------------------------------------------------
gold item        one PII occurrence in the ground truth (required or optional)
match            a finding paired one-to-one with a gold item
recall           matched REQUIRED gold items / all REQUIRED gold items
precision        matched findings / all findings (matches to optional items
                 count as correct, so ambiguous items never hurt precision)
false positive   a finding that matched no gold item
residual PII     a required gold value still present in the sanitized text,
                 found by an independent text search (NOT by the team's own
                 verifier, so it can catch a verifier that says SAFE wrongly)
"""
import re
from collections import Counter

from evaluation import taxonomy as T
from evaluation.adapters import locations_agree
from evaluation.normalize import normalize, parse_date, ratio, squash, values_match

TRACE_KEYS = ("page", "slide", "paragraph", "table", "block", "image", "row", "cell", "line")


# --------------------------------------------------------------------------
# small helpers
# --------------------------------------------------------------------------
def safe_div(a, b):
    """a / b, or None when b is zero (so 'no data' is not reported as 0%)."""
    return None if not b else a / b


def masked(value):
    """Display-safe version of a value for reports (never prints the full value)."""
    s = str(value)
    if "@" in s:
        local, _, domain = s.partition("@")
        return local[:1] + "***@" + domain
    if len(s) <= 4:
        return "*" * len(s)
    return s[:2] + "*" * (len(s) - 4) + s[-2:]


def tokenize(text):
    return re.findall(r"[a-z0-9]+", str(text).lower())


# --------------------------------------------------------------------------
# matching findings to gold items
# --------------------------------------------------------------------------
class Match:
    def __init__(self, gold, finding, score):
        self.gold = gold
        self.finding = finding
        self.score = score
        self.type_ok = (finding.type == gold.type)


class MatchResult:
    def __init__(self):
        self.matches = []             # Match objects (required and optional gold)
        self.missed_required = []     # GoldItem
        self.missed_optional = []     # GoldItem
        self.false_positives = []     # EvalFinding
        self.ignored = []             # EvalFinding with status 'rejected'
        self.misplaced = []           # false positives whose value matches gold on ANOTHER page/slide
        self.unresolved = []          # findings whose text could not be read


def match_findings(gold_items, findings, threshold=0.85, ignore_statuses=("rejected",)):
    """Pair findings with gold items one-to-one (best score first)."""
    result = MatchResult()
    active = []
    for f in findings:
        if f.validation_status in ignore_statuses:
            result.ignored.append(f)
        else:
            active.append(f)

    candidates = []  # (score, is_required, finding_index, gold_index)
    for fi, f in enumerate(active):
        if not f.text:
            continue
        for gi, g in enumerate(gold_items):
            if locations_agree(g.location, f.location) is False:
                continue
            ok, score = values_match(g.type, f.text, g.all_values(), threshold)
            if ok:
                candidates.append((score, 1 if g.required else 0, fi, gi))
    # best score first; on a tie prefer a required gold item
    candidates.sort(key=lambda c: (-c[0], -c[1], c[2], c[3]))

    used_findings, used_gold = set(), set()
    for score, _req, fi, gi in candidates:
        if fi in used_findings or gi in used_gold:
            continue
        used_findings.add(fi)
        used_gold.add(gi)
        result.matches.append(Match(gold_items[gi], active[fi], score))

    for gi, g in enumerate(gold_items):
        if gi not in used_gold:
            (result.missed_required if g.required else result.missed_optional).append(g)
    for fi, f in enumerate(active):
        if fi in used_findings:
            continue
        result.false_positives.append(f)
        if not f.text:
            result.unresolved.append(f)
            continue
        # right value, wrong page/slide?
        for g in gold_items:
            if locations_agree(g.location, f.location) is False:
                ok, _ = values_match(g.type, f.text, g.all_values(), threshold)
                if ok:
                    result.misplaced.append(f)
                    break
    return result


# --------------------------------------------------------------------------
# detection metrics
# --------------------------------------------------------------------------
def _prf(tp, fp, fn):
    precision = safe_div(tp, tp + fp)
    recall = safe_div(tp, tp + fn)
    f1 = None
    if precision is not None and recall is not None and (precision + recall) > 0:
        f1 = 2 * precision * recall / (precision + recall)
    return precision, recall, f1


def has_traceable_location(loc):
    return any(k in loc for k in TRACE_KEYS)


def hard_negative_hits(false_positives, hard_negatives):
    """False positives that landed on a known trap (a hard negative)."""
    hits = []
    for f in false_positives:
        if not f.text:
            continue
        ft = " ".join(re.sub(r"[^a-z0-9 ]", " ", f.text.lower()).split())
        for hn in hard_negatives:
            ht = " ".join(re.sub(r"[^a-z0-9 ]", " ", hn.text.lower()).split())
            if not ht or not ft:
                continue
            if ft == ht or ratio(ft, ht) >= 0.9 or (len(ht) >= 5 and (ht in ft or ft in ht)):
                hits.append((f, hn))
                break
    return hits


def detection_metrics(gold_doc, result, active_findings_count):
    """Counts and rates for one document. Counts are kept so they can be summed."""
    required = [g for g in gold_doc.items if g.required]
    matched_required = [m for m in result.matches if m.gold.required]
    matched_optional = [m for m in result.matches if not m.gold.required]
    tp = len(matched_required)
    fn = len(result.missed_required)
    fp = len(result.false_positives)
    correct_findings = len(result.matches)
    precision = safe_div(correct_findings, correct_findings + fp)
    recall = safe_div(tp, len(required))
    f1 = None
    if precision is not None and recall is not None and (precision + recall) > 0:
        f1 = 2 * precision * recall / (precision + recall)

    by_type = {}
    for t in T.ALL_TYPES:
        gold_t = [g for g in required if g.type == t]
        tp_t = len([m for m in matched_required if m.gold.type == t])
        found_t = [f for f in (m.finding for m in result.matches) if f.type == t]
        fp_t = len([f for f in result.false_positives if f.type == t])
        if gold_t or found_t or fp_t:
            by_type[t] = {"gold": len(gold_t), "tp": tp_t, "fn": len(gold_t) - tp_t,
                          "recall": safe_div(tp_t, len(gold_t)), "false_positives": fp_t}

    by_modality = {}
    for g in required:
        d = by_modality.setdefault(g.modality, {"gold": 0, "tp": 0})
        d["gold"] += 1
    for m in matched_required:
        by_modality[m.gold.modality]["tp"] += 1
    for d in by_modality.values():
        d["recall"] = safe_div(d["tp"], d["gold"])

    type_ok = len([m for m in result.matches if m.type_ok])
    traceable = 0
    for m in result.matches:
        if has_traceable_location(m.finding.location):
            traceable += 1
    for f in result.false_positives:
        if has_traceable_location(f.location):
            traceable += 1
    hn_hits = hard_negative_hits(result.false_positives, gold_doc.hard_negatives)
    over_broad = 0
    for m in result.matches:
        gl = len(normalize(m.gold.type, m.gold.value))
        fl = len(normalize(m.gold.type, m.finding.text))
        if gl and fl > 1.3 * gl:
            over_broad += 1

    return {
        "gold_required": len(required),
        "gold_optional": len(gold_doc.items) - len(required),
        "findings": active_findings_count,
        "ignored_rejected": len(result.ignored),
        "tp": tp, "fn": fn, "fp": fp,
        "matched_optional": len(matched_optional),
        "precision": precision, "recall": recall, "f1": f1,
        "by_type": by_type,
        "by_modality": by_modality,
        "classification_correct": type_ok,
        "classification_total": len(result.matches),
        "classification_accuracy": safe_div(type_ok, len(result.matches)),
        "traceable_findings": traceable,
        "traceability": safe_div(traceable, active_findings_count),
        "misplaced_findings": len(result.misplaced),
        "unresolved_findings": len(result.unresolved),
        "hard_negative_hits": len(hn_hits),
        "over_broad_matches": over_broad,
    }


# --------------------------------------------------------------------------
# residual PII after redaction (independent text search)
# --------------------------------------------------------------------------
def find_dates(text):
    """Every date in the text, as ISO strings."""
    found = set()
    for m in re.finditer(r"\d{1,2}[/.\-]\d{1,2}[/.\-]\d{4}", text):
        d = parse_date(m.group(0))
        if d:
            found.add(d)
    for m in re.finditer(r"\d{1,2}\s+[A-Za-z]{3,9}\.?,?\s+\d{4}", text):
        d = parse_date(m.group(0))
        if d:
            found.add(d)
    return found


def count_value_in_unit(gold, unit_text):
    """How many times does this gold value still appear in one text unit?"""
    t = gold.type
    value_forms = gold.all_values()
    n = 0
    low = unit_text.lower()
    if t == T.DOB:
        iso = normalize(T.DOB, gold.value)
        return 1 if iso in find_dates(unit_text) else 0
    if t == T.PHONE:
        digits = re.sub(r"\D", "", unit_text)
        for v in value_forms[:1]:
            needle = normalize(T.PHONE, v)
            needle = needle[-10:] if len(needle) > 10 else needle
            if len(needle) >= 7:
                n += digits.count(needle)
        return n
    if t == T.IP_ADDRESS:
        needle = normalize(T.IP_ADDRESS, gold.value)
        return low.count(needle) if needle else 0
    sq = squash(unit_text)
    for v in value_forms[:1]:
        needle = squash(v)
        if t == T.PERSON and len(needle) < 8:
            continue  # short initial-forms are checked by surname below
        if len(needle) >= 6:
            n += sq.count(needle)
    return n


def partial_person_leak(gold, unit_text):
    """A PERSON's surname (last word, 4+ letters) still present as a whole word."""
    words = normalize(T.PERSON, gold.value).split()
    if not words:
        return 0
    surname = words[-1]
    if len(surname) < 4:
        return 0
    return len(re.findall(r"(?<![a-z0-9])%s(?![a-z0-9])" % re.escape(surname), unit_text.lower()))


def residual_pii(gold_doc, sanitized_units):
    """Search the sanitized text for required gold values.

    Values are counted once per distinct (type, normalized value). A value is
    'residual' if it is still present anywhere in the sanitized document.
    Surnames that survive redaction are reported separately as partial leaks.
    """
    distinct = {}
    for g in gold_doc.required_items():
        key = (g.type, normalize(g.type, g.value))
        distinct.setdefault(key, g)
    residual_values, partial_values = [], []
    residual_occurrences = 0
    for key, g in distinct.items():
        remaining = sum(count_value_in_unit(g, u) for u in sanitized_units)
        if remaining:
            residual_values.append((g, remaining))
            residual_occurrences += remaining
        elif g.type == T.PERSON:
            leaks = sum(partial_person_leak(g, u) for u in sanitized_units)
            if leaks:
                partial_values.append((g, leaks))
    return {
        "distinct_required_values": len(distinct),
        "residual_value_count": len(residual_values),
        "residual_occurrences": residual_occurrences,
        "partial_person_leaks": len(partial_values),
        "residual_values": [{"id": g.id, "type": g.type, "ref": masked(g.value), "remaining": r}
                            for g, r in residual_values],
        "partial_leaks": [{"id": g.id, "ref": masked(g.value), "remaining": r}
                          for g, r in partial_values],
    }


def verifier_consistency(verification_status, residual_value_count):
    """Compare the team verifier's verdict with the independent residual check.

    FALSE_SAFE is the dangerous case: verifier says SAFE but PII is still there.
    """
    if verification_status is None:
        return None
    says_safe = str(verification_status).strip().lower() in ("safe", "passed", "pass", "ok", "verified", "clean")
    if says_safe and residual_value_count > 0:
        return "FALSE_SAFE"
    if (not says_safe) and residual_value_count == 0:
        return "BLOCKED_BUT_CLEAN"
    return "CONSISTENT"


# --------------------------------------------------------------------------
# context retention and structure retention
# --------------------------------------------------------------------------
def context_retention(original_units, sanitized_units, gold_doc):
    """Share of NON-PII words that survive redaction (measures over-redaction).

    The words that belong to required PII values are removed from the original
    word count first, so removing PII is not counted as lost context.
    """
    original = Counter()
    for u in original_units:
        original.update(tokenize(u))
    for g in gold_doc.required_items():
        for tok in tokenize(g.value):
            if original[tok] > 0:
                original[tok] -= 1
    sanitized = Counter()
    for u in sanitized_units:
        sanitized.update(tokenize(u))
    total = sum(v for v in original.values() if v > 0)
    kept = sum(min(v, sanitized[t]) for t, v in original.items() if v > 0)
    return {"non_pii_words": total, "kept_words": kept, "retention": safe_div(kept, total)}


def distinct_units(blocks_locations, key):
    return set(loc[key] for loc in blocks_locations if key in loc and isinstance(loc[key], int))


def unit_coverage(reference_locs, extracted_locs, key):
    """Fraction of reference units (pages / slides / tables) found in the extraction.

    Numbering may start at 0 or 1 depending on the extractor, so offsets of
    -1, 0 and +1 are tried and the best one is used.
    """
    ref = distinct_units(reference_locs, key)
    ext = distinct_units(extracted_locs, key)
    if not ref:
        return None
    best = 0
    for offset in (-1, 0, 1):
        shifted = set(x + offset for x in ext)
        best = max(best, len(ref & shifted))
    return best / len(ref)


def structure_retention(reference_blocks, extracted_blocks):
    """Compare an extractor's output with an independent reference extraction.

    reference_blocks / extracted_blocks: lists of {'text': str, 'location': dict}.
    Returns unit coverage per page/slide/table and word-level text retention.
    """
    ref_locs = [b["location"] for b in reference_blocks if str(b["text"]).strip()]
    ext_locs = [b["location"] for b in extracted_blocks if str(b["text"]).strip()]
    coverage = {}
    for key in ("page", "slide", "table"):
        c = unit_coverage(ref_locs, ext_locs, key)
        if c is not None:
            coverage[key] = c
    ref_words = Counter()
    for b in reference_blocks:
        ref_words.update(tokenize(b["text"]))
    ext_words = Counter()
    for b in extracted_blocks:
        ext_words.update(tokenize(b["text"]))
    total = sum(ref_words.values())
    kept = sum(min(v, ext_words[t]) for t, v in ref_words.items())
    return {
        "unit_coverage": coverage,
        "reference_words": total,
        "retained_words": kept,
        "text_retention": safe_div(kept, total),
        "reference_blocks": len(reference_blocks),
        "extracted_blocks": len(extracted_blocks),
    }


# --------------------------------------------------------------------------
# one document, and many documents
# --------------------------------------------------------------------------
def evaluate_document(gold_doc, findings, sanitized_units=None, original_units=None,
                      verification_status=None, reference_blocks=None,
                      extracted_blocks=None, seconds=None, threshold=0.85):
    """Compute every metric that the supplied inputs allow.

    findings         list of EvalFinding (see adapters.to_eval_findings)
    sanitized_units  list of text strings of the SANITIZED output (optional)
    original_units   list of text strings of the extracted ORIGINAL (optional)
    """
    result = match_findings(gold_doc.items, findings, threshold)
    active = len(findings) - len(result.ignored)
    out = {
        "document": gold_doc.key,
        "source_name": gold_doc.source_name,
        "detection": detection_metrics(gold_doc, result, active),
        "seconds": seconds,
        "_result": result,  # kept for report details; removed before saving JSON
    }
    if sanitized_units is not None:
        residual = residual_pii(gold_doc, sanitized_units)
        residual["verifier"] = verifier_consistency(verification_status, residual["residual_value_count"])
        out["residual"] = residual
        if original_units is not None:
            out["context"] = context_retention(original_units, sanitized_units, gold_doc)
    if reference_blocks is not None and extracted_blocks is not None:
        out["structure"] = structure_retention(reference_blocks, extracted_blocks)
    return out


SUM_KEYS = ("gold_required", "gold_optional", "findings", "ignored_rejected", "tp", "fn", "fp",
            "matched_optional", "classification_correct", "classification_total",
            "traceable_findings", "misplaced_findings", "unresolved_findings",
            "hard_negative_hits", "over_broad_matches")


def aggregate(doc_results):
    """Micro-average over documents: sum the counts, recompute the rates."""
    total = {k: 0 for k in SUM_KEYS}
    by_type, by_modality = {}, {}
    residual_values = residual_occurrences = distinct_values = partial = 0
    any_residual = False
    false_safe = 0
    total_seconds = 0.0
    for r in doc_results:
        d = r["detection"]
        for k in SUM_KEYS:
            total[k] += d[k]
        for t, v in d["by_type"].items():
            a = by_type.setdefault(t, {"gold": 0, "tp": 0, "false_positives": 0})
            a["gold"] += v["gold"]
            a["tp"] += v["tp"]
            a["false_positives"] += v["false_positives"]
        for m, v in d["by_modality"].items():
            a = by_modality.setdefault(m, {"gold": 0, "tp": 0})
            a["gold"] += v["gold"]
            a["tp"] += v["tp"]
        if "residual" in r:
            any_residual = True
            residual_values += r["residual"]["residual_value_count"]
            residual_occurrences += r["residual"]["residual_occurrences"]
            distinct_values += r["residual"]["distinct_required_values"]
            partial += r["residual"]["partial_person_leaks"]
            if r["residual"].get("verifier") == "FALSE_SAFE":
                false_safe += 1
        if r.get("seconds"):
            total_seconds += r["seconds"]
    correct = total["tp"] + total["matched_optional"]
    precision = safe_div(correct, correct + total["fp"])
    recall = safe_div(total["tp"], total["gold_required"])
    f1 = None
    if precision is not None and recall is not None and (precision + recall) > 0:
        f1 = 2 * precision * recall / (precision + recall)
    for a in by_type.values():
        a["recall"] = safe_div(a["tp"], a["gold"])
    for a in by_modality.values():
        a["recall"] = safe_div(a["tp"], a["gold"])
    out = dict(total)
    out.update({
        "precision": precision, "recall": recall, "f1": f1,
        "classification_accuracy": safe_div(total["classification_correct"], total["classification_total"]),
        "traceability": safe_div(total["traceable_findings"], total["findings"]),
        "by_type": by_type, "by_modality": by_modality,
        "seconds": total_seconds or None,
    })
    if any_residual:
        out["residual"] = {"residual_value_count": residual_values,
                           "residual_occurrences": residual_occurrences,
                           "distinct_required_values": distinct_values,
                           "partial_person_leaks": partial,
                           "documents_false_safe": false_safe}
    return out
