"""Value normalization and matching rules.

Two strings are compared AFTER being normalized with the rule for the gold
item's type. The rules are deliberately simple and explicit.
"""
import re
from difflib import SequenceMatcher

from evaluation import taxonomy as T

MONTHS = {
    "jan": 1, "feb": 2, "mar": 3, "apr": 4, "may": 5, "jun": 6,
    "jul": 7, "aug": 8, "sep": 9, "oct": 10, "nov": 11, "dec": 12,
}
TITLES = ("mr", "mrs", "ms", "miss", "dr", "prof")


def ratio(a, b):
    """Similarity between two strings, 0.0 to 1.0."""
    if not a and not b:
        return 1.0
    return SequenceMatcher(None, a, b).ratio()


def parse_date(text):
    """Turn '14/07/1991', '14 July 1991', '3 August 1996' into 'YYYY-MM-DD'.

    Slash dates are read day/month/year because the supplied documents use
    that order everywhere (for example 31/05/2026). Returns None if no date
    can be read.
    """
    t = str(text)
    m = re.search(r"(\d{1,2})[/.\-](\d{1,2})[/.\-](\d{4})", t)
    if m:
        day, month, year = int(m.group(1)), int(m.group(2)), int(m.group(3))
        return "%04d-%02d-%02d" % (year, month, day)
    m = re.search(r"(\d{1,2})\s+([A-Za-z]{3,9})\.?,?\s+(\d{4})", t)
    if m and m.group(2)[:3].lower() in MONTHS:
        return "%04d-%02d-%02d" % (int(m.group(3)), MONTHS[m.group(2)[:3].lower()], int(m.group(1)))
    return None


def normalize(type_name, text):
    """Normalize a value according to its (coarse) type."""
    t = T.canonical_type(type_name)
    s = "" if text is None else str(text)
    if t == T.EMAIL:
        return re.sub(r"\s+", "", s).lower().strip(".,;:()<>[]\"'|!")   # OCR: "l." read as "|."
    if t == T.PHONE:
        return re.sub(r"\D", "", s)
    if t in (T.EMPLOYEE_ID, T.GOVERNMENT_ID, T.FINANCIAL):
        return re.sub(r"[^A-Z0-9X]", "", s.upper())
    if t == T.DOB:
        d = parse_date(s)
        return d if d else re.sub(r"[^a-z0-9]", "", s.lower())
    if t == T.IP_ADDRESS:
        return re.sub(r"[^0-9.]", "", s)
    if t == T.PERSON:
        s = s.lower().replace(".", " ")
        s = re.sub(r"[^a-z0-9\- ]", " ", s)
        words = [w for w in s.split() if w]
        while words and words[0] in TITLES:
            words = words[1:]
        return " ".join(words)
    # ADDRESS and anything else
    return " ".join(re.sub(r"[^a-z0-9 ]", " ", s.lower()).split())


def squash(text):
    """Lower-case letters and digits only (used for residual-PII search)."""
    return re.sub(r"[^a-z0-9]", "", str(text).lower())


def values_match(type_name, finding_text, gold_values, threshold=0.85):
    """Does a finding's text match a gold value (or one of its OCR variants)?

    gold_values is a list: the true value first, then known OCR variants.
    Returns (matched, score). Both sides are normalized with the GOLD type.
    """
    if finding_text is None:
        return False, 0.0
    t = T.canonical_type(type_name)
    f = normalize(t, finding_text)
    if not f:
        return False, 0.0
    best = 0.0
    for gv in gold_values:
        g = normalize(t, gv)
        if not g:
            continue
        if f == g:
            return True, 1.0
        score = ratio(f, g)
        if t == T.EMAIL:
            # OCR may damage the domain, but a different local part is a different person
            fl, _, fd = f.partition("@")
            gl, _, gd = g.partition("@")
            local_ok = fl == gl or (len(gl) >= 8 and ratio(fl, gl) >= 0.92)
            score = (0.5 * ratio(fl, gl) + 0.5 * ratio(fd, gd)) if (local_ok and ratio(fd, gd) >= threshold) else 0.0
        elif t in (T.PHONE, T.EMPLOYEE_ID, T.GOVERNMENT_ID, T.FINANCIAL, T.DOB):
            score = 0.0          # digits matter: one wrong digit is another number
        elif t == T.PERSON:
            if ratio(f.split(" ")[-1], g.split(" ")[-1]) < 0.9:
                score = 0.0      # surname must agree
        if t == T.PHONE:
            # '+1 (212) 555-0147' vs '(212) 555-0147': one ends with the other
            shorter, longer = (f, g) if len(f) <= len(g) else (g, f)
            if len(shorter) >= 7 and longer.endswith(shorter):
                score = max(score, 0.95)
        elif t in (T.PERSON, T.ADDRESS):
            # the gold value inside a slightly longer finding is still a match,
            # but a finding that swallows a lot of extra text is not
            if g in f and len(f) <= 1.6 * len(g) + 2:
                score = max(score, 0.9)
        elif t in (T.GOVERNMENT_ID, T.EMPLOYEE_ID, T.FINANCIAL):
            # a label such as 'SSN ' or 'Passport ' in front of the value is ok
            if g in f and len(f) - len(g) <= 8:
                score = max(score, 0.9)
        best = max(best, score)
    return best >= threshold, best
