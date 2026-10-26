"""Run the hand-written detection cases against a detector.

The structured cases also run against the regex baseline, which proves the cases themselves
are consistent. Every case runs against the team detector (detection.detect_text); to test
another detector set

    EVAL_DETECTOR=module:function

where the callable takes text and returns findings (dicts or objects with type/text).
"""
import importlib
import os

import pytest

from evaluation import baseline, taxonomy, test_cases
from evaluation.adapters import get_field


def _load_team():
    spec = os.environ.get("EVAL_DETECTOR", "detection:detect_text")
    module, _, func = spec.partition(":")
    return getattr(importlib.import_module(module), func)


def _baseline_detect(text):
    return baseline.detect_units([({}, text, "x")])


def _run(detect, case):
    found = detect(case["text"])
    got = {(taxonomy.canonical_type(get_field(f, "type")), str(get_field(f, "text", "value"))) for f in found}
    missing = [e for e in case["expect"] if (taxonomy.canonical_type(e[0]), e[1]) not in got]
    leaked = [g for g in got if any(fb in g[1] or g[1] in fb for fb in case.get("forbid", []))]
    return missing, leaked


@pytest.mark.parametrize("case", test_cases.structured_cases(), ids=lambda c: c["id"])
def test_cases_pass_on_baseline(case):
    missing, leaked = _run(_baseline_detect, case)
    assert not missing and not leaked


@pytest.mark.parametrize("case", test_cases.CASES, ids=lambda c: c["id"])
def test_team_detector(case):
    detect = _load_team()
    missing, leaked = _run(detect, case)
    assert not missing, "missed %s" % missing
    assert not leaked, "reported non-PII %s" % leaked
