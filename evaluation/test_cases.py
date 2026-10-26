"""Hand-written detection test cases. Every value here is fake and safe to commit
(example.com addresses, 555 phone numbers, 900-series SSNs, invented names).

A case says: given this text, a detector MUST find every `expect` item and MUST NOT
report anything that overlaps a `forbid` string.
`structured=True` marks cases a regex-only detector is expected to pass.
"""

CASES = [
    # --- e-mail ---------------------------------------------------------
    dict(id="email-plain", text="Contact jane.doe@example.com for access.",
         expect=[("EMAIL", "jane.doe@example.com")], structured=True),
    dict(id="email-plus-subdomain", text="Send to a.b+tag@mail.corp.example.org today",
         expect=[("EMAIL", "a.b+tag@mail.corp.example.org")], structured=True),
    dict(id="email-in-sentence-punct", text="(see k.lee@example.com).",
         expect=[("EMAIL", "k.lee@example.com")], structured=True),
    dict(id="email-not-a-handle", text="Follow us @cadence on the portal",
         expect=[], forbid=["@cadence"], structured=True),
    # --- phone ----------------------------------------------------------
    dict(id="phone-us-brackets", text="Call +1 (212) 555-0147 now",
         expect=[("PHONE", "+1 (212) 555-0147")], structured=True),
    dict(id="phone-uk", text="Office +44 20 7555 0163", expect=[("PHONE", "+44 20 7555 0163")], structured=True),
    dict(id="phone-in", text="Mobile +91 98860 55107", expect=[("PHONE", "+91 98860 55107")], structured=True),
    dict(id="phone-no-country", text="Reach me on (305) 555-0143.", expect=[("PHONE", "(305) 555-0143")], structured=True),
    dict(id="phone-not-a-date", text="Due 31/07/2026 and 2026-0112 reviewed",
         expect=[], forbid=["31/07/2026", "2026-0112"], structured=True),
    # --- ids ------------------------------------------------------------
    dict(id="employee-id", text="Owner: EMP-40522 (Head of Risk)", expect=[("EMPLOYEE_ID", "EMP-40522")], structured=True),
    dict(id="policy-id-is-not-pii", text="See POL-001 and ISS-2026-0004 for scope",
         expect=[], forbid=["POL-001", "ISS-2026-0004"], structured=True),
    dict(id="ssn", text="SSN 900-42-7781 was exposed", expect=[("GOVERNMENT_ID", "900-42-7781")], structured=True),
    dict(id="pan", text="PAN ABCDE1234F on file", expect=[("GOVERNMENT_ID", "ABCDE1234F")], structured=True),
    # --- dates ----------------------------------------------------------
    dict(id="dob-long", text="His DOB 14 July 1991 is recorded", expect=[("DOB", "14 July 1991")], structured=True),
    dict(id="business-date-is-not-dob", text="Review on 15 April 2026 by the committee",
         expect=[], forbid=["15 April 2026"], structured=True),
    # --- address --------------------------------------------------------
    dict(id="address-home", text="lives at 12 Elm Court, Springfield, NJ 07081 now",
         expect=[("ADDRESS", "12 Elm Court, Springfield, NJ 07081")], structured=True),
    # --- names ----------------------------------------------------------
    dict(id="person-full", text="Approved by Ravi Kumar Shetty yesterday", expect=[("PERSON", "Ravi Kumar Shetty")]),
    dict(id="person-initial", text="Owner: R. Shetty", expect=[("PERSON", "R. Shetty")]),
    dict(id="person-middle-initial", text="Chair Anna B. Fontaine (EMP-40001)",
         expect=[("PERSON", "Anna B. Fontaine"), ("EMPLOYEE_ID", "EMP-40001")]),
    dict(id="person-hyphen", text="Contact Lena Okafor-Reed", expect=[("PERSON", "Lena Okafor-Reed")]),
    dict(id="org-is-not-person", text="Hudson Street Capital Limited and Veritrace Services",
         expect=[], forbid=["Hudson Street Capital", "Veritrace Services"]),
    dict(id="role-is-not-person", text="The Chief Risk Officer and the Board Chair approve",
         expect=[], forbid=["Chief Risk Officer", "Board Chair"]),
    # --- mixed ----------------------------------------------------------
    dict(id="mixed-line", text="Anna B. Fontaine, EMP-40001, a.fontaine@example.com, +1 (212) 555-0147",
         expect=[("PERSON", "Anna B. Fontaine"), ("EMPLOYEE_ID", "EMP-40001"),
                 ("EMAIL", "a.fontaine@example.com"), ("PHONE", "+1 (212) 555-0147")]),
    dict(id="no-pii", text="The committee reviewed quarterly metrics and approved the roadmap.", expect=[], structured=True),
]


def structured_cases():
    return [c for c in CASES if c.get("structured")]
