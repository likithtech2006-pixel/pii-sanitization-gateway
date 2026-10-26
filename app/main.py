"""Streamlit UI for the PII sanitization pipeline.

    streamlit run app/main.py

One script, six views selected from the sidebar (Workspace, Findings, Sanitized Text, Compare,
AI Analysis, Reports & Downloads). Uploaded documents are processed once, when they are added in
Workspace, and their results are kept in st.session_state["docs"] for the rest of the browser
session, so switching views never re-runs the pipeline or loses the upload.

Only the AI-analysis view can send data out, and only the sanitized text of a SAFE document
(and only when ANTHROPIC_API_KEY is set; otherwise the analysis is computed offline).
"""
import hashlib
import json
import os
import re
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import pandas as pd  # noqa: E402
import streamlit as st  # noqa: E402

import detection  # noqa: E402
from ai_layer import AnalysisBlocked, analyze  # noqa: E402
from extraction import ocr  # noqa: E402
from pipeline import process  # noqa: E402
from redaction.file_writer import write_redacted_file  # noqa: E402
from redaction.output import report, sanitized_text  # noqa: E402
from security import access, audit, certificate, compliance, keys  # noqa: E402
from security import vault as pii_vault  # noqa: E402

sys.path.insert(0, str(Path(__file__).resolve().parent))
import ui  # noqa: E402

st.set_page_config(page_title="PII Sanitization Gateway", page_icon="🛡️", layout="wide",
                   initial_sidebar_state="auto")
ui.inject()

VIEWS = ["Workspace", "Findings", "Sanitized Text", "Compare", "AI Analysis", "Reports & Downloads", "Security"]
NAV_ICONS = {"Workspace": ":material/upload_file:", "Findings": ":material/policy:",
             "Sanitized Text": ":material/description:", "Compare": ":material/compare_arrows:",
             "AI Analysis": ":material/insights:", "Reports & Downloads": ":material/download:",
             "Security": ":material/verified_user:"}
SESSION_TTL_MIN = int(os.getenv("PII_GATEWAY_SESSION_TTL_MIN", "30"))
# Hosted public demo (e.g. Streamlit Community Cloud): set PII_GATEWAY_PUBLIC_DEMO=1 in the host's secrets.
# Shows a "fictional data only" warning and one-click sample files; the local app is unaffected.
PUBLIC_DEMO = os.getenv("PII_GATEWAY_PUBLIC_DEMO") == "1"
SAMPLE_DIR = ROOT / "sample_test_cases" / "inputs"
DEMO_SAMPLES = [("TC01_access_request.docx", "SAFE · access request"), ("TC07_corrupted.pdf", "BLOCKED · corrupt file"),
                ("TC10_prompt_injection.docx", "Prompt injection"), ("TC11_tracked_changes.docx", "Tracked changes"),
                ("TC02_org_chart.pptx", "PPTX org chart"), ("TC04_scanned_incident.pdf", "Scanned PDF (OCR)")]


class _SampleFile:
    """Minimal stand-in for an uploaded file, for the bundled fictional samples."""
    def __init__(self, path: Path):
        self.name, self._data = path.name, path.read_bytes()

    def getvalue(self) -> bytes:
        return self._data


def _client_id() -> str:
    try:
        return st.context.ip_address or "local"
    except Exception:
        return "local"


def purge_session(reason: str):
    """Drop every document, result, vault and analysis held for this browser session."""
    n = len(st.session_state.get("docs", {}))
    st.session_state.get("docs", {}).clear()
    for k in ("active_doc", "pending_active"):
        st.session_state.pop(k, None)
    if n:
        audit.log("session_purged", detail=reason, count=n)


# ------------------------------------------------------------------ idle timeout (purges data, then re-locks)
_now = time.time()
_last = st.session_state.get("last_seen")
if _last and _now - _last > SESSION_TTL_MIN * 60:
    purge_session("idle timeout")
    st.session_state.pop("authenticated", None)
    st.session_state["expired_notice"] = True
st.session_state["last_seen"] = _now

# ------------------------------------------------------------------ optional access gate
if access.enabled() and not st.session_state.get("authenticated"):
    st.html(ui.login_card())
    _, mid, _ = st.columns([1, 2, 1])
    with mid:
        with st.form("login", clear_on_submit=True):
            pw = st.text_input("Passphrase", type="password", autocomplete="current-password")
            submitted = st.form_submit_button("Unlock", type="primary", use_container_width=True)
        if submitted:
            wait = access.locked_for(_client_id())
            if wait:
                st.error(f"Too many failed attempts. Try again in {wait} seconds.")
            elif access.attempt(_client_id(), pw):
                st.session_state["authenticated"] = True
                audit.log("login", outcome="success")
                st.rerun()
            else:
                audit.log("login", outcome="failure")
                st.error("Incorrect passphrase.")
    st.stop()

# ------------------------------------------------------------------ session state
docs = st.session_state.setdefault("docs", {})          # doc id -> {name, ext, data, result, redacted, analysis, cert}
st.session_state.setdefault("nav", "Workspace")
st.session_state.setdefault("uploader_gen", 0)          # bumped to clear the uploader after files are ingested
if "pending_active" in st.session_state:                 # set by ingest(); applied before the selectbox exists
    st.session_state["active_doc"] = st.session_state.pop("pending_active")
if docs and st.session_state.get("active_doc") not in docs:
    st.session_state["active_doc"] = next(reversed(docs))


def go(view: str):
    st.session_state["nav"] = view


def select(doc_id: str):
    st.session_state["active_doc"] = doc_id


def remove(doc_id: str):
    if docs.pop(doc_id, None) is not None:
        audit.log("document_removed", doc=doc_id[:12])
    if st.session_state.get("active_doc") == doc_id:
        st.session_state.pop("active_doc", None)


def clear_session():
    purge_session("user cleared session")


def is_safe(doc) -> bool:
    return doc["result"].status == "SAFE"


# ------------------------------------------------------------------ sidebar
engines = detection.info()
ocr_ok = ocr.is_available()
with st.sidebar:
    st.html(ui.sidebar_brand())
    st.radio("Navigation", VIEWS, key="nav", format_func=lambda v: f"{NAV_ICONS[v]} {v}",
             label_visibility="collapsed")
    if docs:
        st.html(ui.sidebar_label("Active document"))
        st.selectbox("Active document", list(docs), key="active_doc", label_visibility="collapsed",
                      format_func=lambda i: f"{'SAFE' if is_safe(docs[i]) else 'BLOCKED'} · {docs[i]['name']}")
    st.html(ui.sidebar_label("System"))
    with st.expander("System & settings", icon=":material/tune:"):
        st.html(ui.sidebar_engines([
            ("OCR", "Tesseract ready" if ocr_ok else "Not installed: scans are BLOCKED", not ocr_ok),
            ("Names", engines["ner"], False),
            ("Structured", engines["structured"], False),
            ("AI analysis", "Claude (API key set)" if os.getenv("ANTHROPIC_API_KEY") else "Offline local brief", False),
        ]))
        make_file = st.checkbox("Create redacted PDF/DOCX/PPTX during processing", key="opt_make_file",
                                help="Writes the same redactions into a copy of the original file and verifies it. "
                                     "Scanned PDFs are re-OCR'd at high resolution (takes a few minutes). "
                                     "You can also generate it later in Reports & Downloads.")
        show_original = st.checkbox("Show original text in Compare", key="opt_show_original",
                                    help="Original text contains raw PII. It is shown only on this machine.")


# ------------------------------------------------------------------ processing
@st.cache_resource(show_spinner=False)
def _warm_up():
    detection.detect_text("warm up")      # loads spaCy once
    return True


def safe_name(name: str) -> str:
    """Display/file name without paths, markup or control characters."""
    base = Path(str(name).replace("\\", "/")).name
    return re.sub(r"[^\w.\- ()]", "_", base)[:120] or "document"


def _write_redacted(name: str, data: bytes, result):
    """Redacted copy in the original format; returns (outcome, bytes or None). SAFE results only."""
    ext = Path(safe_name(name)).suffix.lower()
    with tempfile.TemporaryDirectory() as tmp:          # fixed names: an uploaded name never becomes a path
        src = Path(tmp) / f"input{ext}"
        src.write_bytes(data)
        out = Path(tmp) / f"redacted{ext}"
        outcome = write_redacted_file(str(src), result.original, result.gate, str(out))
        return outcome, (out.read_bytes() if outcome.ok else None)


def ingest(files, make_file: bool):
    """Process newly added files once, reporting each pipeline stage as it actually finishes."""
    last = None
    for f in files:
        data = f.getvalue()
        name = safe_name(f.name)
        doc_id = hashlib.sha256(data).hexdigest()[:16]
        last = doc_id
        if doc_id in docs:                      # same content already processed in this session
            continue
        with st.status(f"Processing {name}", expanded=True) as status:
            _warm_up()

            def on_stage(stage, info, status=status):
                if stage == "extract":
                    if info["status"] == "error":
                        status.write("Extraction failed: the file could not be read.")
                    else:
                        status.write(f"Extracted {info['blocks']} text blocks"
                                     f"{' with OCR' if info['ocr_used'] else ''} ({info['seconds']} s)")
                elif stage == "detect":
                    status.write(f"Detected {info['findings']} PII findings ({info['seconds']} s)")
                elif stage == "verify":
                    status.write(f"Redacted {info['redacted']} values · verification: "
                                 f"{info['status']} ({info['reason'].replace('_', ' ')}) ({info['seconds']} s)")
                elif stage == "inspect":
                    status.write(f"Hidden-content and prompt-injection inspection: {info['findings']} finding(s)"
                                 f"{' · AI analysis disabled (possible prompt injection)' if info['ai_blocked'] else ''}")

            result = process(data, filename=name, on_stage=on_stage)
            redacted = None
            if make_file and result.status == "SAFE":
                status.write("Writing the redacted copy and verifying it…")
                redacted = _write_redacted(name, data, result)
                status.write("Redacted copy verified." if redacted[0].ok else f"Redacted copy not produced: {redacted[0].reason}")
            safe = result.status == "SAFE"
            status.update(label=f"{name}: {'SAFE' if safe else 'BLOCKED'}", state="complete" if safe else "error",
                          expanded=False)
        sm = result.summary()
        audit.log("document_processed", doc=doc_id[:12], file_type=Path(name).suffix.lower().lstrip("."),
                  status=result.status, reason=result.gate.reason, findings=sm["findings"], redacted=sm["redacted"],
                  risk=sm["content_risk"])
        docs[doc_id] = {"name": name, "ext": Path(name).suffix.lower(), "data": data, "result": result,
                        "redacted": redacted, "analysis": None, "cert": None}
    if last:
        st.session_state["pending_active"] = last
        st.session_state["uploader_gen"] += 1     # new uploader key: the dropzone is cleared for the next file
        st.rerun()


def _findings_table(result) -> pd.DataFrame:
    return pd.DataFrame([{"Type": f.pii_type, "Value (masked)": f.masked_value(), "Source": f.source,
                          "Confidence": round(f.confidence, 2), "Method": f.detection_method,
                          "Regulations": ", ".join(compliance.regulations_for(f.pii_type)),
                          "Validated": f.validated} for f in result.findings])


def log_download(doc_id: str, kind: str):
    audit.log("download", doc=doc_id[:12], kind=kind)


def active_doc():
    return docs.get(st.session_state.get("active_doc"))


def view_header(kicker: str, title: str, subtitle: str, empty_text: str):
    """Title + active-document context. Returns the document, or None (empty state shown)."""
    st.html(ui.view_title(kicker, title, subtitle))
    doc = active_doc()
    if doc is None:
        st.html(ui.empty("No document yet", empty_text))
        st.button("Go to Workspace", icon=":material/upload_file:", on_click=go, args=("Workspace",))
        st.html(ui.footer())
        return None
    st.html(ui.doc_context(doc["name"], doc["ext"], is_safe(doc), doc["result"].gate.reason))
    return doc


def restricted(doc, what: str):
    reason = doc["result"].gate.reason.replace("_", " ")
    st.html(ui.empty(f"{what} is not available for a BLOCKED document",
                     f"This document was blocked ({reason}), so nothing from it is released. "
                     "The masked findings and the audit report remain available for diagnosis.", "bad"))
    c1, c2, _ = st.columns([1, 1, 3])
    c1.button("Review findings", icon=":material/policy:", on_click=go, args=("Findings",), key=f"rf-{what}",
              use_container_width=True)
    c2.button("Audit report", icon=":material/download:", on_click=go, args=("Reports & Downloads",), key=f"ar-{what}",
              use_container_width=True)
    st.html(ui.footer())


# ------------------------------------------------------------------ views
def view_workspace():
    st.html(ui.hero())
    if PUBLIC_DEMO:
        st.html(ui.warning("Public demo: use the fictional sample files below. Do not upload real or confidential "
                           "documents. Files are processed in this server's memory only and discarded when the session "
                           "ends or after 30 minutes of inactivity. Nothing is sent to an AI provider."))
        st.html(ui.label("Try a fictional sample"))
        cols = st.columns(3)
        for i, (fname, label_) in enumerate(DEMO_SAMPLES):
            if (SAMPLE_DIR / fname).exists() and cols[i % 3].button(label_, key=f"sample-{fname}",
                                                                    use_container_width=True):
                ingest([_SampleFile(SAMPLE_DIR / fname)], make_file)
    files = st.file_uploader("Documents", type=["pdf", "docx", "pptx"], accept_multiple_files=True,
                             key=f"uploader_{st.session_state['uploader_gen']}")
    if files:
        ingest(files, make_file)

    if not docs:
        st.html(ui.landing())
        st.html(ui.footer())
        return

    if len(docs) > 1:
        head, clear = st.columns([5, 1], vertical_alignment="bottom")
        head.html(ui.label(f"Session documents ({len(docs)})"))
        clear.button("Clear all", type="tertiary", on_click=clear_session, use_container_width=True)
        with st.container(border=True):
            for doc_id, d in docs.items():
                active = doc_id == st.session_state.get("active_doc")
                c1, c2, c3 = st.columns([6, 1, 1], vertical_alignment="center")
                c1.html(ui.doc_row(d["name"], d["ext"], is_safe(d), len(d["result"].findings), active))
                c2.button("Inspect", key=f"sel-{doc_id}", on_click=select, args=(doc_id,), disabled=active,
                          use_container_width=True)
                c3.button("Remove", key=f"rm-{doc_id}", type="tertiary", on_click=remove, args=(doc_id,),
                          use_container_width=True)

    doc = active_doc()
    res = doc["result"]
    s = res.summary()
    safe = is_safe(doc)
    message = (f"{s['redacted']} PII occurrences replaced, verified by a second independent scan." if safe
               else "Nothing is released for this document.")
    st.html(ui.doc_header(doc["name"], doc["ext"], safe, res.gate.reason, s, message))
    st.html(ui.stepper(safe, res.gate.reason, s, res.gate.passes))
    st.html(ui.metrics(s))
    if s["warnings"]:
        st.html(ui.warning(s["warnings"]))
    risk = res.content_risk
    if risk and risk.findings:
        st.html(ui.label("Hidden content & AI safety"))
        if risk.ai_blocked:
            st.html(ui.warning("Possible prompt injection found: text in this document tries to instruct an AI model. "
                               "AI analysis is disabled for this document; downloads remain available."))
        st.html(ui.risk_panel(risk.findings))

    st.html(ui.label("Next steps"))
    actions = ([("Review findings", "Findings", ":material/policy:"),
                ("Sanitized text", "Sanitized Text", ":material/description:"),
                ("Analyse with AI", "AI Analysis", ":material/insights:"),
                ("Downloads", "Reports & Downloads", ":material/download:")] if safe else
               [("Review findings", "Findings", ":material/policy:"),
                ("Audit report", "Reports & Downloads", ":material/download:")])
    cols = st.columns(len(actions) + 2)
    for col, (text, view, ic) in zip(cols, actions):
        col.button(text, icon=ic, on_click=go, args=(view,), key=f"go-{view}", use_container_width=True,
                   type="primary" if view == actions[0][1] else "secondary")
    if len(docs) == 1:
        cols[len(actions)].button("Remove", type="tertiary", icon=":material/close:", on_click=remove,
                                  args=(st.session_state["active_doc"],), key="rm-single", use_container_width=True)
    st.html(ui.footer())


def view_findings():
    doc = view_header("Findings", "Detected personal data",
                      "Where each value was found, how it was detected, and how confident the detector was.",
                      "Upload a document in Workspace to inspect its detected findings.")
    if not doc:
        return
    res = doc["result"]
    s = res.summary()
    if not is_safe(doc):
        st.html(ui.warning("Diagnostic view: this document was blocked and nothing was released. Values are masked."))
    if not res.findings:
        st.html(ui.empty("No personal data detected", "The detector found no PII in this document."))
    else:
        bars = ui.type_bars(s["counts_by_type"])
        if bars:
            st.html(ui.label("Redacted by type"))
            st.html(bars)
        st.html(ui.label(f"Findings ({len(res.findings)})"))
        st.dataframe(_findings_table(res), hide_index=True, use_container_width=True, column_config={
            "Type": st.column_config.TextColumn(width="medium"),
            "Value (masked)": st.column_config.TextColumn(width="medium"),
            "Source": st.column_config.TextColumn(width="medium"),
            "Confidence": st.column_config.NumberColumn(format="%.2f", width="small"),
            "Method": st.column_config.TextColumn(width="large"),
            "Regulations": st.column_config.TextColumn(width="medium"),
            "Validated": st.column_config.CheckboxColumn(width="small"),
        })
    review = [x for x in report(res.gate)["skipped"] if x.get("reason") == "below_threshold"]
    if review:
        st.html(ui.label(f"Needs review ({len(review)})"))
        st.caption("Low-confidence candidates that were not redacted automatically.")
        st.dataframe(pd.DataFrame([{"Type": x["type"], "Value (masked)": x.get("safe_reference", ""),
                                    "Source": x["source"]} for x in review]), hide_index=True, use_container_width=True)
    if s["counts_by_type"]:
        st.html(ui.label("Regulations in scope"))
        st.html(ui.compliance_panel(compliance.summary(s["counts_by_type"]), compliance.DISCLAIMER))
    residuals = res.gate.verification.safe_residuals() if res.gate.verification else []
    if residuals:
        st.html(ui.label(f"Residual findings after the last scan ({len(residuals)})"))
        st.dataframe(pd.DataFrame(residuals), hide_index=True, use_container_width=True)
    st.html(ui.footer())


def view_sanitized():
    doc = view_header("Sanitized text", "The document as it may be released",
                      "Every value replaced with a typed placeholder; every block labelled with its source.",
                      "Upload a document in Workspace to view its sanitized text.")
    if not doc:
        return
    if not is_safe(doc):
        restricted(doc, "Sanitized text")
        return
    res = doc["result"]
    st.download_button("Download .txt", sanitized_text(res.gate), f"{Path(doc['name']).stem}.sanitized.txt",
                       icon=":material/download:", on_click=log_download,
                       args=(st.session_state["active_doc"], "sanitized_text"), key="dl-txt-view")
    st.html(ui.sanitized_view(res.gate.document.content, res.gate.redaction.redacted_count))
    st.html(ui.footer())


def view_compare():
    doc = view_header("Compare", "Before and after redaction",
                      "Each block that redaction changed, side by side. The original stays hidden unless you enable it.",
                      "Upload a document in Workspace to compare original and sanitized blocks.")
    if not doc:
        return
    if not is_safe(doc):
        restricted(doc, "Comparison")
        return
    res = doc["result"]
    changed = [(o, n) for o, n in zip(res.original.content, res.gate.document.content) if o.text != n.text]
    if not changed:
        st.html(ui.empty("No changes", "No block was changed, because no personal data was found."))
        st.html(ui.footer())
        return
    labels = [f"{i + 1}. {o.source}" for i, (o, _) in enumerate(changed)]
    pick = st.selectbox(f"Changed block ({len(changed)} of {len(res.original.content)} blocks changed)",
                        range(len(changed)), format_func=lambda i: labels[i], key=f"cmp-{st.session_state['active_doc']}")
    o, n = changed[pick]
    st.html(ui.compare(o.text if show_original else None, n.text))
    st.html(ui.footer())


def view_ai():
    doc = view_header("AI analysis", "Analyse the sanitized document",
                      "A brief of the sanitized text, or an answer to your question about it.",
                      "Upload a document in Workspace to analyse its sanitized text.")
    if not doc:
        return
    if not is_safe(doc):
        restricted(doc, "AI analysis")
        return
    if doc["result"].content_risk and doc["result"].content_risk.ai_blocked:
        st.html(ui.empty("AI analysis is disabled for this document",
                         "The document contains text that tries to instruct an AI model (possible prompt injection). "
                         "The AI layer refuses it. Review the flagged locations in Workspace; the sanitized text and "
                         "reports are still available.", "bad"))
        st.html(ui.footer())
        return
    if os.getenv("ANTHROPIC_API_KEY"):
        st.caption("Provider: Claude. Only the sanitized text of this SAFE document is sent, after an egress re-scan.")
    else:
        st.caption("Provider: offline local brief (no external AI call). Set ANTHROPIC_API_KEY to use Claude; "
                   "only sanitized text would be sent.")
    doc_id = st.session_state["active_doc"]
    q = st.text_input("Question (optional)", key=f"q-{doc_id}", persist_state="session",
                      placeholder="e.g. Who approves risk acceptance for critical risks?")
    if st.button("Run analysis on sanitized text", type="primary", icon=":material/insights:", key=f"ai-{doc_id}"):
        try:
            with st.spinner("Analysing sanitized text…"):
                analysis = analyze(doc["result"].gate, q or None)
                doc["analysis"] = {"question": q, "md": analysis.to_markdown(), "provider": analysis.provider}
            audit.log("ai_analysis", doc=doc_id[:12], provider=analysis.provider, outcome="completed")
        except AnalysisBlocked as e:
            doc["analysis"] = {"question": q, "error": str(e)}
            audit.log("ai_analysis", doc=doc_id[:12], outcome="blocked")
    a = doc.get("analysis")
    if a:
        if a.get("error"):
            st.error(f"Blocked: {a['error']}")
        else:
            with st.container(border=True):
                # demote headings so the brief sits under the page title
                st.markdown(re.sub(r"(?m)^(#{1,2}) ", lambda m: "#" * (len(m.group(1)) + 2) + " ", a["md"]))
            st.html(ui.label("Restore real names on this screen"))
            st.caption("The AI only ever received placeholders. Restoring swaps them back locally, using the vault held "
                       "in this session's memory. Nothing is sent anywhere; the action is recorded in the audit log "
                       "without any values.")
            if st.toggle("Show real values in this answer", key=f"reveal-{doc_id}"):
                vault = doc["result"].gate.redaction.vault
                plain = re.sub(r"(?m)^#{1,6}\s*", "", a["md"]).replace("_Provider:", "Provider:").replace(")._", ").")
                segs = pii_vault.segments(plain, vault)
                restored = sum(1 for _, r in segs if r)
                if not a.get("revealed"):
                    audit.log("values_revealed", doc=doc_id[:12], count=restored)
                    a["revealed"] = True
                st.html(ui.restored_view(segs))
    st.html(ui.footer())


def view_reports():
    doc = view_header("Reports & downloads", "Audit report and released outputs",
                      "Only outputs this document is allowed to release are offered.",
                      "Upload a document in Workspace to get its report and downloads.")
    if not doc:
        return
    res = doc["result"]
    safe = is_safe(doc)
    stem, ext = Path(doc["name"]).stem, doc["ext"]
    rep = report(res.gate)
    rep["pipeline"] = res.summary()

    doc_id = st.session_state["active_doc"]
    st.html(ui.label("Outputs"))
    rows = st.container(border=True)
    c1, c2 = rows.columns([4, 1], vertical_alignment="center")
    c1.html(ui.output_row("Sanitized text (.txt)", "Every block with its source label and placeholders." if safe
                          else "Withheld because the document is BLOCKED.", safe))
    if safe:
        c2.download_button("Download", sanitized_text(res.gate), f"{stem}.sanitized.txt", key="dl-txt",
                           on_click=log_download, args=(doc_id, "sanitized_text"), use_container_width=True)

    c1, c2 = rows.columns([4, 1], vertical_alignment="center")
    c1.html(ui.output_row("Audit report (.json)", "Status, reason, counts and masked values. Contains no raw PII.", True))
    c2.download_button("Download", json.dumps(rep, indent=2, default=str), f"{stem}.report.json", key="dl-json",
                       on_click=log_download, args=(doc_id, "audit_report"), use_container_width=True)

    c1, c2 = rows.columns([4, 1], vertical_alignment="center")
    c1.html(ui.output_row("Sanitization certificate (.json)",
                          "Ed25519-signed record of the verdict, content hashes, rule set, risks and regulations. "
                          "No file name, text or PII. Verify it in Security.", True))
    if doc.get("cert") is None:
        doc["cert"] = certificate.issue(doc["data"], ext.lstrip("."), res, sanitized_text(res.gate), res.content_risk)
        audit.log("certificate_issued", doc=doc_id[:12], certificate_id=doc["cert"]["certificate_id"], status=res.status)
    c2.download_button("Download", json.dumps(doc["cert"], indent=2), f"{stem}.certificate.json", key="dl-cert",
                       on_click=log_download, args=(doc_id, "certificate"), use_container_width=True)

    c1, c2 = rows.columns([4, 1], vertical_alignment="center")
    kind = ext[1:].upper()
    red = doc.get("redacted")
    if not safe:
        c1.html(ui.output_row(f"Redacted {kind}", "Not available for a BLOCKED document.", False))
    elif red and red[0].ok:
        c1.html(ui.output_row(f"Redacted {kind}", "Same redactions inside the original format, verified after writing.", True))
        c2.download_button("Download", red[1], f"{stem}.redacted{ext}", key="dl-red", on_click=log_download,
                           args=(doc_id, "redacted_file"), use_container_width=True)
    else:
        desc = (f"Could not be produced: {red[0].reason}" if red else
                "Not generated yet. Writing and verifying the copy can take minutes for scanned PDFs.")
        c1.html(ui.output_row(f"Redacted {kind}", desc, False))
        if c2.button("Generate", key="gen-red", use_container_width=True):
            with st.spinner(f"Writing and verifying the redacted {kind}…"):
                doc["redacted"] = _write_redacted(doc["name"], doc["data"], res)
            st.rerun()

    if res.gate.redaction.counts_by_type():
        st.html(ui.label("Regulations in scope"))
        st.html(ui.compliance_panel(compliance.summary(res.gate.redaction.counts_by_type()), compliance.DISCLAIMER))
    st.html(ui.label("Audit report"))
    st.json(rep, expanded=False)
    st.html(ui.footer())


def view_security():
    st.html(ui.view_title("Security", "Security posture and verification",
                          "Live status of the controls protecting this session, the audit trail, and certificate checks."))
    ok_chain, n_events, problem = audit.verify()
    addr = st.get_option("server.address") or ""
    rows = [
        ((None if PUBLIC_DEMO else addr in ("127.0.0.1", "localhost", "::1")), "Local-only listener",
         "Hosted public demo: fictional data only. Run locally for real documents." if PUBLIC_DEMO
         else "The server accepts connections from this machine only.", "hosted demo" if PUBLIC_DEMO else (addr or "all interfaces")),
        (bool(st.get_option("server.enableXsrfProtection")), "XSRF protection", "Cross-site requests are rejected.",
         "on" if st.get_option("server.enableXsrfProtection") else "off"),
        (st.get_option("client.showErrorDetails") in ("none", "type"), "Error details hidden",
         "Exceptions never show document content in the browser.", str(st.get_option("client.showErrorDetails"))),
        (not st.get_option("browser.gatherUsageStats"), "No telemetry", "Usage statistics are disabled.", "off"),
        (True, "Upload guard", "Magic-byte type check, size and page limits, ZIP-bomb and path checks, encrypted files rejected.",
         f"≤ {st.get_option('server.maxUploadSize')} MB"),
        (True, "Hardened XML parsing", "DTDs and entities rejected (XXE, billion laughs).", "lxml, no network"),
        (True, "Fail-closed release gate", "Independent second scan; anything unverifiable is BLOCKED.", "max 2 scans"),
        (True, "AI egress guard + injection lock", "Only SAFE sanitized text leaves; prompt-injected documents are refused.",
         "Claude" if os.getenv("ANTHROPIC_API_KEY") else "offline"),
        (True if access.enabled() else None, "Access gate",
         "Passphrase with scrypt and lockout." if access.enabled() else "Off. Set PII_GATEWAY_PASSPHRASE_HASH to require a passphrase.",
         "on" if access.enabled() else "off"),
        (True, "Session data lifetime", "Documents, results and the vault live only in this session's memory and are "
         "purged after inactivity.", f"{SESSION_TTL_MIN} min idle"),
        (ok_chain, "Audit trail integrity", problem or "Hash-chained, Ed25519-signed, no PII.", f"{n_events} events"),
        (True, "Signing key", "Certificates and audit entries are signed; key file is owner-only.", keys.key_id()),
    ]
    st.html(ui.posture(rows))

    c1, c2 = st.columns(2)
    c1.download_button("Download public key (.pem)", keys.public_key_pem(), "pii-gateway-public-key.pem",
                       icon=":material/key:", on_click="ignore", use_container_width=True)
    c2.button("Purge this session now", icon=":material/delete_forever:", on_click=purge_session,
              args=("user purge",), use_container_width=True, disabled=not docs)

    st.html(ui.label("Verify a certificate"))
    st.caption("Checks the Ed25519 signature and, optionally, that a file matches the certificate's content hash.")
    v1, v2 = st.columns(2)
    cert_file = v1.file_uploader("Certificate (.json)", type=["json"], key="verify-cert")
    orig = v2.file_uploader("Original document (optional)", type=["pdf", "docx", "pptx"], key="verify-orig")
    if cert_file is not None:
        try:
            cert = json.loads(cert_file.getvalue()[:1_000_000])
            ok, notes = certificate.verify(cert, input_bytes=orig.getvalue() if orig is not None else None)
        except (ValueError, UnicodeDecodeError):
            ok, notes = False, ["not a valid certificate file"]
        audit.log("certificate_verified", ok=ok)
        (st.success if ok else st.error)(" · ".join(notes))
        if ok:
            v = cert.get("verdict", {})
            st.caption(f"Verdict: {v.get('status')} ({v.get('reason')}) · issued {cert.get('issued_at')} · "
                       f"certificate {cert.get('certificate_id')}")

    st.html(ui.label("Recent audit events"))
    recent = audit.recent(15)
    if recent:
        st.html(ui.events([" ".join(f"{k}={v}" for k, v in e.items() if k != "hash") for e in recent]))
    else:
        st.caption("No events yet.")
    st.html(ui.footer())


if st.session_state.pop("expired_notice", False):
    st.toast("Session data was purged after inactivity.", icon=":material/timer_off:")

{"Workspace": view_workspace, "Findings": view_findings, "Sanitized Text": view_sanitized, "Compare": view_compare,
 "AI Analysis": view_ai, "Reports & Downloads": view_reports, "Security": view_security}[st.session_state["nav"]]()
