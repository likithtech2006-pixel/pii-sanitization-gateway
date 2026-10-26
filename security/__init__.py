"""Security services for the PII Sanitization Gateway.

    keys          Ed25519 signing key (certificates, audit log), stored with owner-only permissions
    xmlsafe       XML parser hardened against XXE / entity expansion (no DTDs, no network)
    upload_guard  file validation before parsing: size, magic bytes, ZIP-bomb and path checks, encryption
    inspector     hidden-content and prompt-injection inspection
    compliance    PII type -> regulation mapping (informational)
    certificate   signed, verifiable sanitization certificates
    vault         session-only placeholder -> value map for restoring names on the user's screen
    audit         append-only, hash-chained, signed audit log (never raw PII)
    access        optional passphrase gate (scrypt) with lockout
"""
