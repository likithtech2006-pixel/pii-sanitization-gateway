"""PII type names used by the evaluation module.

The gold labels use the COARSE types below. Detectors may use their own names
(for example ACCOUNT_ID or SSN); canonical_type() maps those names onto the
coarse types so that scoring does not depend on naming differences.
"""

PERSON = "PERSON"
EMAIL = "EMAIL"
PHONE = "PHONE"
EMPLOYEE_ID = "EMPLOYEE_ID"
GOVERNMENT_ID = "GOVERNMENT_ID"  # SSN, PAN, passport, PESEL, tax id, national id
DOB = "DOB"
ADDRESS = "ADDRESS"
FINANCIAL = "FINANCIAL"  # card numbers, bank account numbers, last-four fragments
IP_ADDRESS = "IP_ADDRESS"
OTHER = "OTHER"

ALL_TYPES = [PERSON, EMAIL, PHONE, EMPLOYEE_ID, GOVERNMENT_ID, DOB,
             ADDRESS, FINANCIAL, IP_ADDRESS, OTHER]

# detector name (upper case, spaces and dashes turned into underscores) -> coarse type
ALIASES = {
    "PERSON_NAME": PERSON, "NAME": PERSON, "PER": PERSON, "FULL_NAME": PERSON,
    "EMAIL_ADDRESS": EMAIL,
    "PHONE_NUMBER": PHONE, "MOBILE": PHONE, "TELEPHONE": PHONE, "MOBILE_NUMBER": PHONE,
    "EMP_ID": EMPLOYEE_ID, "EMPLOYEE": EMPLOYEE_ID, "STAFF_ID": EMPLOYEE_ID,
    "ACCOUNT_ID": EMPLOYEE_ID, "VENDOR_ID": EMPLOYEE_ID, "DIRECTOR_ID": EMPLOYEE_ID,
    "ID": EMPLOYEE_ID,
    "SSN": GOVERNMENT_ID, "US_SSN": GOVERNMENT_ID, "PAN": GOVERNMENT_ID,
    "IN_PAN": GOVERNMENT_ID, "PASSPORT": GOVERNMENT_ID, "PESEL": GOVERNMENT_ID,
    "TAX_ID": GOVERNMENT_ID, "TIN": GOVERNMENT_ID, "NATIONAL_ID": GOVERNMENT_ID,
    "GOVT_ID": GOVERNMENT_ID, "GOVERNMENT_ISSUED_ID": GOVERNMENT_ID,
    "DATE_OF_BIRTH": DOB, "BIRTH_DATE": DOB, "BIRTHDATE": DOB,
    "STREET_ADDRESS": ADDRESS, "HOME_ADDRESS": ADDRESS, "POSTAL_ADDRESS": ADDRESS,
    "CREDIT_CARD": FINANCIAL, "CARD_NUMBER": FINANCIAL, "BANK_ACCOUNT": FINANCIAL,
    "ACCOUNT_NUMBER": FINANCIAL, "IBAN": FINANCIAL,
    "IP": IP_ADDRESS, "IPV4": IP_ADDRESS,
}


def canonical_type(name):
    """Return the coarse type for any detector type name (unknown names are kept)."""
    if name is None:
        return OTHER
    key = str(name).strip().upper().replace(" ", "_").replace("-", "_")
    if key in ALL_TYPES:
        return key
    return ALIASES.get(key, key)
