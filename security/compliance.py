"""PII type -> regulations that typically govern it (informational, not legal advice).

Applicability depends on the data subject, jurisdiction and processing purpose. The mapping is
deliberately conservative: every identifier is personal data under DPDP and GDPR; specific regimes
are added only where the identifier is named or clearly covered by them.
"""
from typing import Dict, List

REGULATIONS: Dict[str, Dict[str, str]] = {
    "DPDP": {"name": "Digital Personal Data Protection Act, 2023", "jurisdiction": "India",
             "reference": "s. 2(t) personal data"},
    "GDPR": {"name": "General Data Protection Regulation", "jurisdiction": "EU / EEA",
             "reference": "Art. 4(1) personal data"},
    "GDPR-87": {"name": "GDPR: national identification numbers", "jurisdiction": "EU / EEA",
                "reference": "Art. 87"},
    "AADHAAR": {"name": "Aadhaar Act, 2016", "jurisdiction": "India",
                "reference": "s. 29 restrictions on sharing identity information"},
    "PCI-DSS": {"name": "PCI DSS v4.0", "jurisdiction": "Payment card industry",
                "reference": "Req. 3: protect stored account data (PAN)"},
    "GLBA": {"name": "Gramm-Leach-Bliley Act", "jurisdiction": "United States",
             "reference": "Nonpublic personal information (financial institutions)"},
    "CPRA": {"name": "California Consumer Privacy Act (as amended by CPRA)", "jurisdiction": "California, US",
             "reference": "Sensitive personal information, Cal. Civ. Code §1798.140(ae)"},
}

_BASE = ["DPDP", "GDPR"]
_EXTRA = {
    "CREDIT_CARD": ["PCI-DSS", "GLBA"],
    "IBAN": ["GLBA"], "BANK_ACCOUNT": ["GLBA"], "FINANCIAL": ["GLBA"],
    "SSN": ["GLBA", "CPRA"],
    "AADHAAR": ["AADHAAR"],
    "PASSPORT": ["GDPR-87", "CPRA"], "NATIONAL_ID": ["GDPR-87", "CPRA"],
}

DISCLAIMER = ("Regulation mapping is informational and not legal advice; applicability depends on the data "
              "subject, jurisdiction and purpose of processing.")


def regulations_for(pii_type: str) -> List[str]:
    return _BASE + _EXTRA.get(pii_type.upper(), [])


def summary(counts_by_type: Dict[str, int]) -> List[Dict[str, object]]:
    """One row per regulation touched by the document, with the PII types and occurrences behind it."""
    rows: Dict[str, Dict[str, object]] = {}
    for pii_type, count in counts_by_type.items():
        for reg in regulations_for(pii_type):
            row = rows.setdefault(reg, {"id": reg, **REGULATIONS[reg], "types": [], "occurrences": 0})
            row["types"].append(pii_type)
            row["occurrences"] += count
    order = list(REGULATIONS)
    return sorted(rows.values(), key=lambda r: order.index(r["id"]))
