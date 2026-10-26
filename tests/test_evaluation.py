"""Unit tests for the evaluation module. All data here is synthetic and safe to commit."""
import json

import pytest

from evaluation import adapters, baseline, dataset, metrics, normalize, run_evaluation, taxonomy
from evaluation.dataset import GoldDocument, GoldItem, HardNegative, load_ground_truth


def item(i, typ, value, page=1, required=True, **kw):
    return GoldItem(id="d-%d" % i, doc="d", type=typ, value=value, location={"page": page},
                    required=required, **kw)


def finding(typ, text, page=1, status="valid"):
    return adapters.EvalFinding(type=typ, text=text, location={"page": page}, validation_status=status)


def gold_doc(items, negs=()):
    return GoldDocument("d", "d.pdf", "pdf", list(items), list(negs))


# ---------------------------------------------------------------- taxonomy
def test_canonical_types():
    assert taxonomy.canonical_type("ssn") == "GOVERNMENT_ID"
    assert taxonomy.canonical_type("Account_ID") == "EMPLOYEE_ID"
    assert taxonomy.canonical_type("DATE_OF_BIRTH") == "DOB"


# --------------------------------------------------------------- normalize
@pytest.mark.parametrize("typ,a,b", [
    ("EMAIL", "Jane.Doe@Example.com", "jane.doe@example.com"),
    ("PHONE", "+1 (212) 555-0147", "12125550147"),
    ("EMPLOYEE_ID", "emp-40522", "EMP-40522"),
    ("DOB", "14 July 1991", "14/07/1991"),
])
def test_normalize_equivalents(typ, a, b):
    assert normalize.normalize(typ, a) == normalize.normalize(typ, b)


def test_values_match_phone_suffix_and_person_initial():
    assert normalize.values_match("PHONE", "212 555-0147", ["+1 (212) 555-0147"])[0]
    assert normalize.values_match("PERSON", "Ravi Shetty", ["Ravi Shetty"])[0]
    assert not normalize.values_match("PERSON", "Ravi Shetty", ["Anna Fontaine"])[0]
    assert not normalize.values_match("EMAIL", "a@example.com", ["b@example.com"])[0]


# ---------------------------------------------------------------- adapters
def test_parse_location_variants():
    assert adapters.parse_location("Slide 2 / table 1 row 3") == {"slide": 2, "table": 1, "row": 3}
    assert adapters.parse_location({"page": 4}) == {"page": 4}
    assert adapters.parse_location(None) == {}


def test_locations_agree_only_on_page_or_slide():
    assert adapters.locations_agree({"page": 2}, {"page": 2, "block": 9}) is True
    assert adapters.locations_agree({"page": 2}, {"page": 3}) is False
    assert adapters.locations_agree({"page": 2}, {}) is None


def test_finding_text_cut_from_block_span_and_alt_field_names():
    doc = {"content_blocks": [{"block_id": "b1", "text": "mail jane@example.com now", "location": {"page": 1}}]}
    f = {"type": "EMAIL", "block_id": "b1", "location": {"start": 5, "end": 21}}
    idx = adapters.block_index(doc)
    assert adapters.finding_text({"block_id": "b1", "span": [5, 21]}, idx) == "jane@example.com"
    assert adapters.to_eval_findings([f], doc)[0].type == "EMAIL"


# ---------------------------------------------------------------- matching
def test_perfect_detection():
    gd = gold_doc([item(1, "EMAIL", "a@example.com"), item(2, "PHONE", "+1 (212) 555-0147")])
    r = metrics.evaluate_document(gd, [finding("EMAIL", "a@example.com"), finding("PHONE", "212 555-0147")])
    d = r["detection"]
    assert (d["tp"], d["fn"], d["fp"]) == (2, 0, 0)
    assert d["recall"] == 1 and d["precision"] == 1


def test_missed_required_and_false_positive():
    gd = gold_doc([item(1, "EMAIL", "a@example.com"), item(2, "EMAIL", "b@example.com")])
    r = metrics.evaluate_document(gd, [finding("EMAIL", "a@example.com"), finding("EMAIL", "zzz@example.com")])
    d = r["detection"]
    assert (d["tp"], d["fn"], d["fp"]) == (1, 1, 1)
    assert d["recall"] == 0.5
    assert d["precision"] == 0.5


def test_optional_item_is_never_a_false_positive_or_a_miss():
    gd = gold_doc([item(1, "PERSON", "Ravi Shetty", required=False)])
    hit = metrics.evaluate_document(gd, [finding("PERSON", "Ravi Shetty")])["detection"]
    miss = metrics.evaluate_document(gd, [])["detection"]
    assert hit["fp"] == 0 and hit["fn"] == 0
    assert miss["fn"] == 0 and miss["recall"] is None


def test_one_to_one_matching_repeated_value():
    gd = gold_doc([item(1, "EMAIL", "a@example.com"), item(2, "EMAIL", "a@example.com")])
    one = metrics.evaluate_document(gd, [finding("EMAIL", "a@example.com")])["detection"]
    two = metrics.evaluate_document(gd, [finding("EMAIL", "a@example.com")] * 2)["detection"]
    assert (one["tp"], one["fn"]) == (1, 1)
    assert (two["tp"], two["fn"]) == (2, 0)


def test_wrong_page_is_not_a_match_and_is_reported_as_misplaced():
    gd = gold_doc([item(1, "EMAIL", "a@example.com", page=1)])
    r = metrics.evaluate_document(gd, [finding("EMAIL", "a@example.com", page=5)])
    assert r["detection"]["tp"] == 0 and r["detection"]["fp"] == 1
    assert len(r["_result"].misplaced) == 1


def test_wrong_type_still_matches_but_hurts_classification_accuracy():
    gd = gold_doc([item(1, "GOVERNMENT_ID", "900-42-7781")])
    d = metrics.evaluate_document(gd, [finding("EMPLOYEE_ID", "900-42-7781")])["detection"]
    assert d["tp"] == 1
    assert d["classification_accuracy"] == 0


def test_rejected_findings_are_ignored_not_counted():
    gd = gold_doc([item(1, "EMAIL", "a@example.com")])
    d = metrics.evaluate_document(gd, [finding("EMAIL", "a@example.com"),
                                       finding("EMAIL", "junk@example.com", status="rejected")])["detection"]
    assert d["fp"] == 0 and d["ignored_rejected"] == 1


def test_fuzzy_ocr_noise_still_matches_but_other_value_does_not():
    gd = gold_doc([item(1, "EMAIL", "m.achebe@cadencefg.com")])
    ok = metrics.evaluate_document(gd, [finding("EMAIL", "m.achebe@cadencefy.com")])["detection"]
    bad = metrics.evaluate_document(gd, [finding("EMAIL", "p.raghavan@cadencefg.com")])["detection"]
    assert ok["tp"] == 1 and bad["tp"] == 0


def test_hard_negative_hit_counted():
    gd = gold_doc([], [HardNegative("d", "POL-001")])
    d = metrics.evaluate_document(gd, [finding("EMPLOYEE_ID", "POL-001")])["detection"]
    assert d["fp"] == 1 and d["hard_negative_hits"] == 1


def test_traceability_counts_findings_with_location():
    gd = gold_doc([item(1, "EMAIL", "a@example.com")])
    f = adapters.EvalFinding(type="EMAIL", text="a@example.com", location={})
    d = metrics.evaluate_document(gd, [f])["detection"]
    assert d["traceability"] == 0


# ---------------------------------------------------------------- residual
def test_residual_detects_leftovers_and_false_safe():
    gd = gold_doc([item(1, "EMAIL", "a@example.com"), item(2, "PHONE", "+1 (212) 555-0147")])
    r = metrics.evaluate_document(gd, [], ["Contact a@example.com or [REDACTED]"],
                                  ["Contact a@example.com or +1 (212) 555-0147"], "SAFE")
    assert r["residual"]["residual_value_count"] == 1
    assert r["residual"]["verifier"] == "FALSE_SAFE"


def test_residual_clean_output_and_consistent_verifier():
    gd = gold_doc([item(1, "EMAIL", "a@example.com")])
    r = metrics.evaluate_document(gd, [], ["Contact [REDACTED]"], ["Contact a@example.com"], "SAFE")
    assert r["residual"]["residual_value_count"] == 0
    assert r["residual"]["verifier"] == "CONSISTENT"


def test_residual_finds_value_with_different_formatting():
    gd = gold_doc([item(1, "PHONE", "+1 (212) 555-0147")])
    r = metrics.residual_pii(gd, ["call 212-555-0147 please"])
    assert r["residual_value_count"] == 1


def test_partial_person_leak_reported():
    gd = gold_doc([item(1, "PERSON", "Ravi Shetty")])
    r = metrics.residual_pii(gd, ["Approved by [REDACTED] Shetty"])
    assert r["residual_value_count"] == 0 and r["partial_person_leaks"] == 1


def test_verifier_blocked_but_clean():
    assert metrics.verifier_consistency("UNSAFE", 0) == "BLOCKED_BUT_CLEAN"
    assert metrics.verifier_consistency(None, 3) is None


# ------------------------------------------------------- context/structure
def test_context_retention_ignores_removed_pii_but_penalises_over_redaction():
    gd = gold_doc([item(1, "EMAIL", "a@example.com")])
    orig = ["Please email a@example.com about the quarterly budget review"]
    good = metrics.context_retention(orig, ["Please email [REDACTED] about the quarterly budget review"], gd)
    over = metrics.context_retention(orig, ["[REDACTED] [REDACTED]"], gd)
    assert good["retention"] == 1.0
    assert over["retention"] < 0.5


def test_structure_retention_detects_dropped_page():
    ref = [{"text": "alpha beta", "location": {"page": p}} for p in (1, 2, 3, 4)]
    ext = [{"text": "alpha beta", "location": {"page": p}} for p in (1, 2, 3)]
    s = metrics.structure_retention(ref, ext)
    assert s["unit_coverage"]["page"] == pytest.approx(0.75)
    assert s["text_retention"] == pytest.approx(0.75)


# ---------------------------------------------------------------- aggregate
def test_aggregate_is_micro_average():
    a = metrics.evaluate_document(gold_doc([item(i, "EMAIL", "a%d@example.com" % i) for i in range(1, 5)]),
                                  [finding("EMAIL", "a1@example.com")])
    b = metrics.evaluate_document(gold_doc([item(1, "EMAIL", "z@example.com")]),
                                  [finding("EMAIL", "z@example.com")])
    agg = metrics.aggregate([a, b])
    assert agg["gold_required"] == 5 and agg["tp"] == 2
    assert agg["recall"] == pytest.approx(0.4)


# ---------------------------------------------------------------- dataset
def _write_gold(path, items):
    path.write_text(json.dumps({"schema_version": 1, "documents": {"d": {
        "source_name": "d.pdf", "source_type": "pdf", "items": items, "hard_negatives": []}}}))


def test_load_ground_truth_roundtrip(tmp_path):
    p = tmp_path / "g.json"
    _write_gold(p, [{"id": "d-1", "type": "SSN", "value": "900-42-7781", "location": {"page": 1}}])
    gt = load_ground_truth(str(p))
    assert gt.get("d.pdf").items[0].type == "GOVERNMENT_ID"
    out = tmp_path / "o.json"
    dataset.save_ground_truth(gt, str(out))
    assert load_ground_truth(str(out)).get("d").items[0].value == "900-42-7781"


def test_validate_rejects_duplicates_and_bad_type(tmp_path):
    p = tmp_path / "g.json"
    _write_gold(p, [{"id": "d-1", "type": "EMAIL", "value": "a@example.com"},
                    {"id": "d-1", "type": "EMAIL", "value": "b@example.com"}])
    with pytest.raises(ValueError):
        load_ground_truth(str(p))


# ------------------------------------------------- baseline + full runner
def test_baseline_on_synthetic_deck_end_to_end(tmp_path):
    pptx = pytest.importorskip("pptx")
    prs = pptx.Presentation()
    s = prs.slides.add_slide(prs.slide_layouts[5])
    box = s.shapes.add_textbox(0, 0, 4000000, 1000000)
    box.text_frame.text = "Anna Fontaine: mail a.fontaine@example.com or call +1 (212) 555-0147. Ref POL-001."
    path = tmp_path / "deck.pptx"
    prs.save(str(path))
    gold = tmp_path / "g.json"
    gold.write_text(json.dumps({"schema_version": 1, "documents": {"deck": {
        "source_name": "deck.pptx", "source_type": "pptx",
        "items": [
            {"id": "deck-1", "type": "EMAIL", "value": "a.fontaine@example.com", "location": {"slide": 1}},
            {"id": "deck-2", "type": "PHONE", "value": "+1 (212) 555-0147", "location": {"slide": 1}},
            {"id": "deck-3", "type": "PERSON", "value": "Anna Fontaine", "location": {"slide": 1}}],
        "hard_negatives": [{"text": "POL-001"}]}}}))
    out = tmp_path / "rep"
    code = run_evaluation.main(["--gold", str(gold), "--samples", str(tmp_path), "--out", str(out)])
    data = json.loads((out / "last.json").read_text())
    s = data["summary"]
    assert (s["tp"], s["fn"], s["fp"]) == (2, 1, 0)       # regex baseline cannot find the name
    assert s["residual"]["residual_value_count"] == 1      # the name is still there
    assert "a.fontaine" not in (out / "last.md").read_text() + (out / "last.json").read_text()
    assert code == 0


def test_regression_compare_flags_drop_and_residual_rise():
    prev = {"recall": 0.9, "precision": 0.9, "residual": {"residual_value_count": 2}}
    worse = {"recall": 0.8, "precision": 0.9, "residual": {"residual_value_count": 5}}
    assert len(run_evaluation.compare(worse, prev)) == 2
    assert run_evaluation.compare(prev, prev) == []
