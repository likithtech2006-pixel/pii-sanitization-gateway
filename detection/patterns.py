"""Structured PII recognizers: regular expressions plus checksum/context validators.

Each recognizer is (type, compiled pattern, confidence, validator or None).
A pattern with a named group "v" reports only that group; the rest of the match
is required context (for example the word "passport" before the number).

Design rules
  * Precision comes from validators (Luhn, mod-97, Verhoeff, octet ranges) and
    from requiring a label for values that look like ordinary numbers or dates.
  * Business identifiers (POL-001, ISS-2026-0112, RSK-4488, CTL-IAM-04...) are
    deliberately NOT matched; tests/test_detection.py pins that.
"""
import re
from typing import Callable, List, Optional, Pattern, Tuple

Recognizer = Tuple[str, Pattern, float, Optional[Callable[[str], bool]]]


# ------------------------------------------------------------------ validators
def digits(value: str) -> str:
    return re.sub(r"\D", "", value)


def luhn_ok(value: str) -> bool:
    ds = [int(c) for c in digits(value)]
    if not 13 <= len(ds) <= 19 or len(set(ds)) == 1:
        return False
    total = 0
    for i, d in enumerate(reversed(ds)):
        if i % 2:
            d *= 2
            if d > 9:
                d -= 9
        total += d
    return total % 10 == 0


def iban_ok(value: str) -> bool:
    compact = re.sub(r"\s", "", value).upper()
    if not 15 <= len(compact) <= 34:
        return False
    rearranged = compact[4:] + compact[:4]
    try:
        return int("".join(str(int(c, 36)) for c in rearranged)) % 97 == 1
    except ValueError:
        return False


_VERHOEFF_D = [[0, 1, 2, 3, 4, 5, 6, 7, 8, 9], [1, 2, 3, 4, 0, 6, 7, 8, 9, 5],
               [2, 3, 4, 0, 1, 7, 8, 9, 5, 6], [3, 4, 0, 1, 2, 8, 9, 5, 6, 7],
               [4, 0, 1, 2, 3, 9, 5, 6, 7, 8], [5, 9, 8, 7, 6, 0, 4, 3, 2, 1],
               [6, 5, 9, 8, 7, 1, 0, 4, 3, 2], [7, 6, 5, 9, 8, 2, 1, 0, 4, 3],
               [8, 7, 6, 5, 9, 3, 2, 1, 0, 4], [9, 8, 7, 6, 5, 4, 3, 2, 1, 0]]
_VERHOEFF_P = [[0, 1, 2, 3, 4, 5, 6, 7, 8, 9], [1, 5, 7, 6, 2, 8, 3, 0, 9, 4],
               [5, 8, 0, 3, 7, 9, 6, 1, 4, 2], [8, 9, 1, 6, 0, 4, 3, 5, 2, 7],
               [9, 4, 5, 3, 1, 2, 6, 8, 7, 0], [4, 2, 8, 6, 5, 7, 3, 9, 0, 1],
               [2, 7, 9, 3, 8, 0, 6, 4, 1, 5], [7, 0, 4, 6, 9, 1, 3, 2, 5, 8]]


def aadhaar_ok(value: str) -> bool:
    ds = digits(value)
    if len(ds) != 12 or ds[0] in "01":
        return False
    c = 0
    for i, d in enumerate(reversed(ds)):
        c = _VERHOEFF_D[c][_VERHOEFF_P[i % 8][int(d)]]
    return c == 0


def ssn_ok(value: str) -> bool:
    ds = digits(value)
    area, group, serial = ds[:3], ds[3:5], ds[5:]
    # 9xx is kept on purpose: ITINs and test SSNs are still personal identifiers.
    return len(ds) == 9 and area not in ("000", "666") and group != "00" and serial != "0000"


def phone_ok(value: str) -> bool:
    ds = digits(value)
    if not 7 <= len(ds) <= 15 or len(set(ds)) == 1:
        return False
    # A bare run of 4-digit years ("2025 2026") is not a phone number.
    return not all(re.fullmatch(r"(?:19|20)\d\d", part) for part in re.findall(r"\d+", value))


def ipv4_ok(value: str) -> bool:
    parts = value.split(".")
    return len(parts) == 4 and all(p.isdigit() and int(p) <= 255 for p in parts) \
        and not all(int(p) < 10 for p in parts)       # 1.2.3.4-style section numbers


def has_digit(value: str) -> bool:
    return any(c.isdigit() for c in value)


# --------------------------------------------------------------------- pieces
_DATE = (r"\d{1,2}[/.-]\d{1,2}[/.-]\d{2,4}|\d{4}-\d{2}-\d{2}|"
         r"\d{1,2}(?:st|nd|rd|th)? (?:of )?[A-Z][a-z]{2,8}\.?,? \d{4}|[A-Z][a-z]{2,8}\.? \d{1,2}(?:st|nd|rd|th)?,? \d{4}")
_MONTH = r"(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Sept|Oct|Nov|Dec)[a-z]*\b"
_STREET = (r"Street|St|Avenue|Ave|Road|Rd|Lane|Ln|Drive|Dr|Boulevard|Blvd|Way|Court|Ct|Place|Pl|"
           r"Terrace|Close|Crescent|Cres|Parkway|Pkwy|Circle|Cir|Square|Sq|Highway|Hwy|Row|Grove|Gardens|Marg|Nagar")

RECOGNIZERS: List[Recognizer] = [
    # ---- e-mail (incl. OCR damage: spaces around "@") ----
    # An OCR'd "l." / "I." at the start may come out as "|." or "!." - it is kept inside the match.
    ("EMAIL", re.compile(r"(?<![A-Za-z0-9+-])(?:[|!]\.)?[A-Za-z0-9][A-Za-z0-9._%+-]*@[A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)*\.[A-Za-z]{2,}(?![\w-])"), 0.99, None),
    ("EMAIL", re.compile(r"(?<![A-Za-z0-9+-])(?:[|!]\.)?[A-Za-z0-9][A-Za-z0-9._%+-]* ?@ ?[A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)*\.[A-Za-z]{2,}(?![\w-])"), 0.9, None),
    # OCR split the local part at a space: "thomas brown@acmecorp.con" (not "contact bob@...")
    ("EMAIL", re.compile(r"(?<![\w.@])(?!(?:e-?mail|mail|contact|at|to|from|cc|bcc|or|and|via|is|write|reach|send)\b)"
                         r"[a-z]{2,12}\.? [a-z][a-z0-9_%+-]*@[A-Za-z0-9-]{3,}(?:\.[A-Za-z0-9-]+)*(?![\w@-])"), 0.8, None),
    # truncated by OCR or a column edge: "vist@cade"
    ("EMAIL", re.compile(r"(?<![A-Za-z0-9+-])[A-Za-z0-9._%+-]{2,}@[A-Za-z0-9-]{3,}(?![\w.@-])"), 0.75, None),

    # ---- government identifiers ----
    ("SSN", re.compile(r"(?<![\d-])\d{3}-\d{2}-\d{4}(?![\d-])"), 0.95, ssn_ok),
    ("SSN", re.compile(r"\b(?:SSN|social security(?: number| no\.?)?)[ :#]*(?P<v>\d{3}[-. ]?\d{2}[-. ]?\d{4})(?![\d-])", re.I), 0.95, ssn_ok),
    # partial SSN: "social security number (4821)", "SSN ending 4821"
    ("SSN", re.compile(r"\b(?:SSN|social security number)(?: ending(?: in)?)?[ :#(]*(?P<v>\d{4})\)?(?!\d)", re.I), 0.8, None),
    ("PAN", re.compile(r"\b[A-Z]{3}[ABCFGHLJPT][A-Z]\d{4}[A-Z]\b"), 0.9, None),
    ("PAN", re.compile(r"\bPAN(?: (?:no\.?|number|card))?[ :#]*(?P<v>[A-Z]{5}\d{4}[A-Z])\b"), 0.95, None),
    ("AADHAAR", re.compile(r"(?<!\d)\d{4}[ -]\d{4}[ -]\d{4}(?![\d-])"), 0.9, aadhaar_ok),
    ("NATIONAL_ID", re.compile(r"\b(?:NI(?:NO)?|National Insurance(?: number| no\.?)?)[ :#]*"
                               r"(?P<v>[A-CEGHJ-PR-TW-Z]{2} ?\d{2} ?\d{2} ?\d{2} ?[A-D])\b", re.I), 0.95, None),
    ("NATIONAL_ID", re.compile(r"\b(?:PESEL|national id(?:entity)?(?: number| no\.?)?|tax id|TIN)[ :#]*(?P<v>[A-Z0-9-]{6,15})\b", re.I),
     0.9, has_digit),
    ("PASSPORT", re.compile(r"\bpassport(?: (?:no\.?|number|#))?[ :#]*(?P<v>[A-Z0-9]{6,9})\b", re.I), 0.95, has_digit),
    ("PASSPORT", re.compile(r"\b[A-Z]{2}\d{7}\b"), 0.75, None),

    # ---- financial ----
    ("CREDIT_CARD", re.compile(r"(?<![\d-])(?:\d[ -]?){12,18}\d(?![\d-])"), 0.95, luhn_ok),
    ("IBAN", re.compile(r"\b[A-Z]{2}\d{2}(?: ?[A-Z0-9]{4}){2,7}(?: ?[A-Z0-9]{1,4})?\b"), 0.95, iban_ok),
    ("BANK_ACCOUNT", re.compile(r"\b(?:account|acct|a/c)(?: (?:no\.?|number|#))?[ :#]*(?P<v>\d{6,17})\b", re.I), 0.85, None),
    # last-four fragments: "card ending 4421", "account ending in 0093"
    ("FINANCIAL", re.compile(r"\b(?:card|account|acct)(?: number)? ending(?: in| with)?[ :]*(?P<v>\d{4})\b", re.I), 0.8, None),

    # ---- phone numbers ----
    # international: +CC then groups; first group may be bracketed: +1 (555) 0114, +91 80 4555 0182
    ("PHONE", re.compile(r"(?<![\w+])\+\d{1,3}[ .-]?(?:\(\d{1,5}\)[ .-]?)?\d{1,5}(?:[ .-]?\d{3,5}){0,4}(?![\w/-])"), 0.95, phone_ok),
    # North-American style: (212) 555-0147, 212-555-0147, 212.555.0147
    ("PHONE", re.compile(r"(?<![\w+(-])(?:\(\d{3}\) ?|\d{3}[ .-])\d{3}[ .-]\d{4}(?![\w-])"), 0.9, phone_ok),
    # labelled numbers in any format: "Tel: 020 7946 0001", "Mobile 98860 55107", "M 0114"
    ("PHONE", re.compile(r"\b(?:tel|telephone|phone|mobile|mob|cell|fax|whatsapp)\.?[ :#]*(?P<v>\(?\+?\d[\d ()-]{5,18}\d)(?![\w-])", re.I),
     0.9, phone_ok),

    # Fragments: OCR of table columns splits numbers across lines - "+1 (212)" ... "555-0174".
    ("PHONE", re.compile(r"(?<![\w+])\+\d{1,3} ?\(\d{2,5}\)(?![ .-]?\d)"), 0.8, None),
    # "+44 20" / "+1 212" left at the end of a cell, followed by other text or a line break
    ("PHONE", re.compile(r"(?<![\w+])\+\d{1,3}[ .-]?\d{1,4}(?=[ \t]*$|[ \t]+(?!" + _MONTH + r")[^\d\s])", re.M), 0.8, None),
    # a bare "+44" before a line break, a dash, or a date in the next column
    ("PHONE", re.compile(r"(?<![\w+])\+\d{1,3}(?=[ \t]*$|[ \t]*[\u2014\u2013-]|[ \t]+\d{1,2}[ \t]+" + _MONTH + r")", re.M), 0.75, None),
    ("PHONE", re.compile(r"(?<![\w./-])\d{3}-\d{4}(?![\w/-])"), 0.7, None),
    ("PHONE", re.compile(r"(?<![\w./-])(?<!\d )(?<!\d\. )(?:\d{1,3} )?\d{4} \d{4}(?![\w./-])(?! \d)(?! ?[AaPp]\.?[Mm]\b)"), 0.7, phone_ok),

    # ---- dates of birth (only when labelled; ordinary dates are not PII) ----
    ("DOB", re.compile(r"\b(?:DOB|D\.O\.B\.?|date of birth|birth ?date|born(?: on)?)[ :,]*(?P<v>" + _DATE + r")", re.I), 0.95, None),

    # ---- addresses ----
    ("ADDRESS", re.compile(r"\b\d{1,5}[A-Z]? (?:[A-Z][a-z]+ ){1,3}(?:" + _STREET + r")\b\.?"
                           r"(?:,? (?:Apartment|Apt|Suite|Unit|Flat|Floor) ?#?[A-Z0-9]{1,5}\b)?"
                           r"(?:, [A-Z][a-z]+(?: [A-Z][a-z]+)?(?:, [A-Z]{2})?(?: \d{5}(?:-\d{4})?)?)?"), 0.85, None),
    ("ADDRESS", re.compile(r"\b[A-Z][a-z]+(?: [A-Z][a-z]+)?, [A-Z]{2} \d{5}(?:-\d{4})?\b"), 0.8, None),
    # UK postcode
    ("ADDRESS", re.compile(r"\b[A-Z]{1,2}\d[A-Z\d]? \d[ABD-HJLNP-UW-Z]{2}\b"), 0.75, None),
    # Indian PIN when labelled
    ("ADDRESS", re.compile(r"\b(?:PIN|pincode|pin code)[ :#-]*(?P<v>\d{6})\b", re.I), 0.8, None),

    # ---- network ----
    ("IP_ADDRESS", re.compile(r"(?<![\w.])(?:\d{1,3}\.){3}\d{1,3}(?![\w.])"), 0.85, ipv4_ok),

    # ---- organisation-issued personal identifiers ----
    # Staff / contractor / director numbers: EMP-41077, MER-IN-4471, DIR-0058, CTR-20931.
    # OCR may add "_" or split the digits ("EMP-39 4"), so the end is "no further digit".
    ("EMPLOYEE_ID", re.compile(r"\b(?:EMP|EMPL|MER|CTR|CON|STF|USR|DIR)[- ]{0,2}(?:[A-Z]{2}-)?\d{3,6}(?!\d)"), 0.95, None),
    ("EMPLOYEE_ID", re.compile(r"\bEMP[- ]{0,2}\d{1,3} \d{1,3}(?!\d)"), 0.8, None),
    ("EMPLOYEE_ID", re.compile(r"\b(?:employee|staff|personnel|badge)(?: (?:id|no\.?|number|#))[ :#]*(?P<v>[A-Z0-9][A-Z0-9-]{3,11})\b", re.I),
     0.9, has_digit),
]
