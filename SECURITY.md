# Security model: PII Sanitization Gateway

This application handles documents full of personal data, so it is built to **fail closed**: when it
cannot prove a document is clean, nothing is released. This file lists every control, what it defends
against, where it lives in the code, and the test that proves it. It also lists what must be added for a
multi-user production deployment.

## 1. Assets and threats

| Asset | Threats considered |
|---|---|
| Raw documents and their PII | Leak to an AI model or third party; disclosure to other network users; residue on disk; display to the wrong person |
| Placeholder vault (tag → real value) | Leak through reports, logs, certificates or the AI |
| Verdicts and audit trail | Forged "SAFE" claims; tampered or deleted audit entries |
| The host machine | Malicious uploads: XXE file disclosure, ZIP or image decompression bombs, path traversal, disguised file types, crafted names |
| AI integration | Prompt injection hidden in documents; hidden text the reviewer never saw |

## 2. Controls

| # | Control | Defends against | Code | Proof |
|---|---|---|---|---|
| 1 | **Local-only listener**: server binds to `127.0.0.1` | Other machines on the network opening the app (the Streamlit default listens on every interface) | `.streamlit/config.toml` | `lsof` shows `127.0.0.1:8501` |
| 2 | **XSRF + CORS protection** on, **usage telemetry off** | Cross-site upload/form requests; data leaving via telemetry | `.streamlit/config.toml` | Security view |
| 3 | **No error details or error links in the browser** | Exception text (which may contain document content) shown on screen or sent to Google/ChatGPT via "search this error" links | `client.showErrorDetails="none"`, `showErrorLinks=false` | Security view |
| 4 | **Upload guard** before any parser: size limit, real type by magic bytes, password-protected/legacy Office rejected, ZIP-bomb limits (entries, total and per-entry expansion), unsafe member names, required package parts, encrypted PDF and page limit | Disguised files, decompression bombs, path traversal, unparseable inputs passing as "clean" | `security/upload_guard.py`, `extraction/__init__.py` | `test_upload_guard_rejects_disguised_and_malicious_files`, `test_rejected_upload_is_blocked_fail_closed` |
| 5 | **Hardened XML parsing**: DTD/ENTITY declarations rejected; no entity resolution, DTD loading or network | XXE (local file disclosure), "billion laughs" | `security/xmlsafe.py` (extractor + redacted-file writer) | `test_xml_rejects_xxe_and_entity_expansion` |
| 6 | **Image decompression limit** (120 MP) | Image bombs exhausting memory during OCR | `extraction/images.py` | — |
| 7 | **Safe file names**: uploaded names are stripped of paths/markup; temporary files use fixed names in private temp dirs | Path traversal via a crafted upload name; markdown/HTML injection in labels | `app/main.py` (`safe_name`, `_write_redacted`) | — |
| 8 | **Tracked changes extracted**: `<w:ins>` and `<w:del>` text (skipped by python-docx) is now detected and redacted | PII surviving in tracked changes of a "redacted" Word file | `extraction/docx_extractor.py` | `test_pii_in_tracked_changes_is_detected_and_redacted`, sample case TC11 |
| 9 | **Hidden-content inspection**: hidden/white/tiny text, tracked changes, hidden slides, off-slide shapes, invisible/transparent/off-page PDF text, macros, embedded files, PDF JavaScript, external links | Content a reviewer never saw but an AI or recipient would | `security/inspector.py` | `test_hidden_text_is_flagged`, TC10 |
| 10 | **Prompt-injection lock** enforced at the AI boundary (not just in the UI) | Documents that instruct the AI to reveal data or ignore its rules | `security/inspector.py`, `ai_layer/__init__.py` | `test_prompt_injection_blocks_ai_analysis`, `test_ordinary_text_is_not_injection`, TC10 |
| 11 | **Fail-closed release gate**: independent second scan, remediation, BLOCKED on any doubt | Detector misses; partial extraction treated as clean | `redaction/gate.py` | existing gate tests |
| 12 | **AI egress guard**: SAFE-only, outgoing text re-scanned | Raw PII sent to an AI provider | `ai_layer/__init__.py` | existing AI-layer tests |
| 13 | **Vault isolation**: real values only in session memory; never in reports, certificates, logs, `repr` or AI input; restoring is local, opt-in and audit-logged without values | Re-identification data leaking | `redaction/redactor.py`, `security/vault.py` | `test_vault_restores_on_screen_and_never_reaches_reports` |
| 14 | **Signed sanitization certificates** (Ed25519): input hash, output hash, verdict, rule-set hash, risks, regulations; no file name, text or PII | Forged or altered "SAFE" claims; proving which file was approved under which rules | `security/certificate.py` | `test_certificate_signs_verifies_and_detects_tampering` |
| 15 | **Tamper-evident audit log**: append-only, hash-chained, every entry Ed25519-signed, field whitelist (no names, no values), `0600` file, file lock | Silent edits, deletions or insertions in the audit trail; PII in logs | `security/audit.py` | `test_audit_chain_detects_tampering_and_drops_unsafe_fields`, `test_audit_detects_deleted_line` |
| 16 | **Key protection**: private key in `~/.pii_gateway/keys` (dir `0700`, file `0600`, created with `O_EXCL`); optional encryption at rest via `PII_GATEWAY_KEY_PASSPHRASE` | Key theft by other local users | `security/keys.py` | — |
| 17 | **Optional access gate**: scrypt passphrase hash, constant-time compare, per-client exponential lockout | Unauthorised use of an unattended workstation; brute force | `security/access.py`, `app/main.py` | `test_access_gate_hash_and_lockout`; UI tested |
| 18 | **Session lifetime**: documents, results and vault are purged after 30 min of inactivity (and re-locked); manual purge in the Security view | Data lingering in memory | `app/main.py` (`PII_GATEWAY_SESSION_TTL_MIN`) | — |
| 19 | **Original text hidden by default**; masked values everywhere else | Shoulder-surfing and screen sharing | `app/main.py` | — |
| 20 | **HTML escaping** of every document-derived string in the UI | Script/markup injection from document content | `app/ui.py` | — |

## 3. Data lifecycle

1. **Upload** → bytes held in session memory; a temporary copy (mode `0600`) is written for parsing and deleted immediately.
2. **Processing** → results, sanitized copy and the vault stay in memory for this browser session only. Nothing is written to a database.
3. **Release** → only SAFE output: sanitized text, a verified redacted file, a JSON report with masked values, and a signed certificate.
4. **AI** → only SAFE, non-injected, egress-checked sanitized text, and only if `ANTHROPIC_API_KEY` is set. Otherwise the analysis is computed offline.
5. **End** → purge on idle timeout, "Clear all", "Purge this session now", or when the browser session ends.
6. **Persistent on disk**: only the signing key and the audit log in `~/.pii_gateway/`. Neither contains PII.

## 4. Configuration

| Variable | Purpose |
|---|---|
| `PII_GATEWAY_PASSPHRASE_HASH` | Turns on the access gate. Generate it with `.venv/bin/python -m security.access` |
| `PII_GATEWAY_SESSION_TTL_MIN` | Idle minutes before session data is purged (default 30) |
| `PII_GATEWAY_MAX_UPLOAD_MB` / `PII_GATEWAY_MAX_PAGES` | Upload limits (default 50 MB / 500 pages; keep `server.maxUploadSize` in step) |
| `PII_GATEWAY_HOME` | Location of the key and audit log (default `~/.pii_gateway`) |
| `PII_GATEWAY_KEY_PASSPHRASE` | Encrypts the signing key at rest |
| `ANTHROPIC_API_KEY` | Enables Claude for analysis of SAFE sanitized text. Keep it in the environment or a secrets manager, never in code |

## 5. Production deployment checklist (multi-user)

The app is hardened for single-user, on-device use. Before serving it to a team, add:

- [ ] **TLS-terminating reverse proxy** (nginx/Envoy) in front; keep Streamlit on `127.0.0.1`.
- [ ] **SSO** (OIDC/SAML) enforced at the proxy or via Streamlit's `st.login`; replace the shared passphrase.
- [ ] **Security headers** at the proxy: `Content-Security-Policy`, `Strict-Transport-Security`, `X-Content-Type-Options: nosniff`, `Referrer-Policy: no-referrer`, `frame-ancestors 'none'`.
- [ ] **Signing key in a KMS/HSM**, with key rotation and the public key published for verifiers.
- [ ] **Audit log shipped** to a write-once store or SIEM, with chain verification scheduled.
- [ ] **Container hardening**: non-root user, read-only root filesystem, tmpfs for temporary files, no outbound network except the approved AI endpoint.
- [ ] **Dependency pinning and scanning** (`pip freeze` lock file with hashes, `pip-audit` in CI), plus the existing test suite and the evaluation harness as release gates.
- [ ] **Rate limiting** per user at the proxy; upload quotas.
- [ ] **AI provider review**: data-processing agreement, zero-retention settings, region.
- [ ] **Penetration test** before go-live.

## 6. Known limits (stated honestly)

- **Memory is not encrypted.** Python cannot reliably wipe or encrypt process memory, so the session holds raw document bytes while processing. This is mitigated by local-only binding, idle purge and no persistence.
- **Pattern-based detectors.** Prompt-injection and hidden-content detection catch the known patterns listed in `security/inspector.py`. A novel phrasing may pass, so the AI egress guard and the PII gate remain the primary controls.
- **Not legal advice.** The regulation mapping is informational.
- **SAFE is not a proof.** It means two independent scans found no PII. The two known detection gaps are in `sample_test_cases/README.md`.
