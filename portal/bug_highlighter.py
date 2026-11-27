import hashlib
import json
import re
from pathlib import Path
import pandas as pd
import streamlit as st
import streamlit.components.v1 as components

_ASSETS_DIR = Path(__file__).resolve().parent / "highlighter_assets"

# Columns hidden ONLY in Preview Window (Excel / Google Sheets export remains 100% untouched)
HIDDEN_PREVIEW_COLS_NORM = {
    "occupation",
    "mailid",
    "healthdatasheet",
    "yes/no/inadequate",
    "remark",
    "mail",
    "print",
    "folder",
}


def _filter_preview_columns(columns: list) -> list:
    visible = [
        c for c in columns
        if re.sub(r"[\s_\-]+", "", str(c or "").strip().lower()) not in HIDDEN_PREVIEW_COLS_NORM
    ]
    return visible if visible else list(columns)


def _align_debug_to_rows(rows: list, columns: list, debug_list: list) -> list:
    """Aligns each Preview Mode row with its corresponding debug item (file_name + raw_text)."""
    if not rows:
        return []
    if not debug_list:
        return [{"file_name": "", "raw_text": ""} for _ in rows]

    if len(debug_list) == len(rows):
        return [
            {
                "file_name": str(d.get("file_name", "") or ""),
                "raw_text": str(d.get("raw_text", "") or ""),
            }
            for d in debug_list
        ]

    filtered = [
        d for d in debug_list
        if d.get("raw_text") and "scanned" not in str(d.get("error_reason", "")).lower()
    ]
    if len(filtered) == len(rows):
        return [
            {
                "file_name": str(d.get("file_name", "") or ""),
                "raw_text": str(d.get("raw_text", "") or ""),
            }
            for d in filtered
        ]

    name_col = next((c for c in columns if c.strip().lower() == "client name"), columns[0] if columns else "")
    used = set()
    aligned = []
    for r in rows:
        r_name = str(r.get(name_col, "") or "").strip().upper()
        matched = None
        for idx, d in enumerate(debug_list):
            if idx in used:
                continue
            d_name = str(d.get("client_name", "") or "").strip().upper()
            if r_name and d_name and r_name == d_name:
                used.add(idx)
                matched = d
                break
        if matched is None:
            for idx, d in enumerate(debug_list):
                if idx not in used:
                    used.add(idx)
                    matched = d
                    break
        aligned.append({
            "file_name": str((matched or {}).get("file_name", "") or ""),
            "raw_text": str((matched or {}).get("raw_text", "") or ""),
        })
    return aligned


def _load_asset(filename: str) -> str:
    path = _ASSETS_DIR / filename
    if not path.exists():
        raise FileNotFoundError(f"Missing preview asset: portal/highlighter_assets/{filename}")
    return path.read_text(encoding="utf-8")


def _load_bundle_js() -> str:
    """Loads modular highlighter JS files (state.js, actions.js, table_ui.js) with legacy script.js fallback."""
    split_files = ("state.js", "actions.js", "table_ui.js")
    if all((_ASSETS_DIR / f).exists() for f in split_files):
        return "\n\n".join(_load_asset(f) for f in split_files)
    return _load_asset("script.js")


def _make_report_token(user_id: str, batch_id: str) -> str:
    """Computes a scoped SHA-256 token for submit_bug_report so SECRET_KEY is NEVER exposed to browser JS."""
    secret = str(st.secrets.get("SECRET_KEY", "") or "")
    if not secret:
        return ""
    raw = f"{secret}|BUG_REPORT|{user_id}|{batch_id}".encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def _build_highlighter_html(
    rows: list,
    columns: list,
    storage_key: str,
    aligned_debug: list,
    batch_id: str,
    retest_count: int = 0,
    ui_mode: str = "admin",
    reporter_meta: dict = None,
) -> str:
    css_code = _load_asset("style.css")
    js_code = _load_bundle_js()

    meta = reporter_meta or {}
    payload = {
        "columns": list(columns),
        "rows": [
            {col: ("" if r.get(col) is None else str(r.get(col))) for col in columns}
            for r in rows
        ],
        "debug": aligned_debug,
        "storageKey": storage_key,
        "batchId": batch_id,
        "retestCount": int(retest_count or 0),
        "uiMode": ui_mode,
        "reporter": {
            "userId": str(meta.get("user_id", "") or ""),
            "userName": str(meta.get("user_name", "") or ""),
            "userEmail": str(meta.get("user_email", "") or ""),
            "modeTag": str(meta.get("mode_tag", "") or ""),
            "endpoint": str(meta.get("endpoint", "") or ""),
            "token": str(meta.get("token", "") or ""),
        },
    }
    data_json = json.dumps(payload, ensure_ascii=False).replace("</", "<\\/")

    if ui_mode == "user_report":
        toolbar_html = (
            "  <div class='toolbar'>"
            "    <div class='tool-group'><span class='btn active-red'>🔴 Click Wrong Cells</span></div>"
            "    <div class='sep'></div>"
            "    <div class='tool-group'>"
            "      <span id='bug-count' class='badge'>0 Selected</span>"
            "      <span id='fixed-count' class='badge has-fixed' style='display:none;'></span>"
            "      <button id='btn-filter' class='btn' onclick='toggleFilter()'>🔎 Selected Rows</button>"
            "      <input id='user-bug-note' class='note-input' type='text' maxlength='250' placeholder='Optional note (e.g. Agency / Premium galat hai)...' />"
            "      <button id='btn-submit-admin' class='btn submit-admin' onclick='submitBugReportToAdmin()'>📨 Submit Bug Report to Admin</button>"
            "      <button id='btn-clear-green' class='btn clear-green' style='display:none;'></button>"
            "      <button class='btn danger' onclick='clearAll()'>🗑️ Clear</button>"
            "      <span id='status-msg' class='status-msg'></span>"
            "    </div>"
            "  </div>"
        )
    else:
        toolbar_html = (
            "  <div class='toolbar'>"
            "    <div class='tool-group'><span class='btn active-red'>🔴 Bug</span></div>"
            "    <div class='sep'></div>"
            "    <div class='tool-group'>"
            "      <span id='bug-count' class='badge'>0 Highlighted</span>"
            "      <span id='fixed-count' class='badge has-fixed' style='display:none;'>🟢 0 Fixed</span>"
            "      <button id='btn-filter' class='btn' onclick='toggleFilter()'>🔎 Highlighted Rows</button>"
            "      <button class='btn pack' onclick='downloadBugPack()'>📥 Download Bug Pack + PDF Text (.txt)</button>"
            "      <button id='btn-clear-green' class='btn clear-green' onclick='clearFixed()' style='display:none;'>🧹 Clear Fixed (🟢)</button>"
            "      <button class='btn danger' onclick='clearAll()'>🗑️ Clear All</button>"
            "      <span id='status-msg' class='status-msg'></span>"
            "    </div>"
            "  </div>"
        )

    return (
        "<!DOCTYPE html><html><head><meta charset='utf-8' />"
        f"<style>{css_code}</style>"
        "</head><body>"
        "<div class='container'>"
        f"{toolbar_html}"
        "  <div class='table-wrap'><table id='preview-table'></table></div>"
        "</div>"
        f"<script>window.POLICY_MITRA_PAYLOAD = {data_json};</script>"
        f"<script>{js_code}</script>"
        "</body></html>"
    )


def render_preview_table(
    rows: list,
    columns: list,
    batch_id: str,
    enable_highlighter: bool = False,
    debug_list: list = None,
    retest_count: int = 0,
    allow_user_report: bool = True,
    mode_tag: str = "",
):
    """
    Renders Preview Mode table for the current round only (non-essential columns hidden in Preview only).
    - Admin Bugging Mode (`enable_highlighter=True`): Click-to-highlight 🔴 Bug + 📥 Bug Pack + 🟢 Auto-Fix on Re-Test.
    - Production Modes (Mode 1, 2, 3): Clean Preview table + 1-click '🐞 Report Wrong Data' button.
    """
    if not rows:
        return

    visible_cols = _filter_preview_columns(columns)

    # 1. Admin Bugging Mode UI
    if enable_highlighter:
        _, h_col2 = st.columns([3, 1])
        with h_col2:
            use_highlight_mode = st.toggle("🖍️ Cell Highlighter", value=True, key=f"toggle_hl_{batch_id}")

        if not use_highlight_mode:
            st.dataframe(pd.DataFrame(rows, columns=visible_cols), use_container_width=True, hide_index=True, height=620)
            return

        try:
            aligned_debug = _align_debug_to_rows(rows, visible_cols, debug_list or [])
            sig = hashlib.md5(f"{batch_id}|{len(rows)}|{','.join(visible_cols)}".encode("utf-8")).hexdigest()[:12]
            storage_key = f"ms_policy_mitra_hl_{sig}"
            html_str = _build_highlighter_html(
                rows, visible_cols, storage_key, aligned_debug, batch_id,
                retest_count=retest_count, ui_mode="admin",
            )
            iframe_height = min(max(360, 120 + len(rows) * 33), 630)
            components.html(html_str, height=iframe_height, scrolling=False)
        except FileNotFoundError as e:
            st.warning(f"⚠️ {e} — Showing standard table fallback.")
            st.dataframe(pd.DataFrame(rows, columns=visible_cols), use_container_width=True, hide_index=True, height=620)
        return

    # 2. Production Modes (Mode 1, Mode 2, Mode 3) — Clean Preview + '🐞 Report Wrong Data' Toggle
    if not allow_user_report:
        st.dataframe(pd.DataFrame(rows, columns=visible_cols), use_container_width=True, hide_index=True, height=620)
        return

    report_key = f"user_report_open_{batch_id}"
    is_reporting = bool(st.session_state.get(report_key, False))

    r_col1, r_col2 = st.columns([3.2, 1.3])
    with r_col1:
        if is_reporting:
            st.info("🐞 **Report Wrong Data Active:** Neeche galat cells par click karke 🔴 select karein, fir **📨 Submit Bug Report to Admin** dabayein.")
        else:
            st.caption("Koi value galat ya blank aayi ho to right side me **🐞 Report Wrong Data** par click karke seedha Admin ko bhej sakte hain.")
    with r_col2:
        btn_label = "✖️ Close Bug Reporter" if is_reporting else "🐞 Report Wrong Data"
        if st.button(btn_label, use_container_width=True, key=f"btn_toggle_report_{batch_id}"):
            st.session_state[report_key] = not is_reporting
            st.rerun()

    if not is_reporting:
        st.dataframe(pd.DataFrame(rows, columns=visible_cols), use_container_width=True, hide_index=True, height=620)
        return

    try:
        aligned_debug = _align_debug_to_rows(rows, visible_cols, debug_list or [])
        sig = hashlib.md5(f"UREP|{batch_id}|{len(rows)}|{','.join(visible_cols)}".encode("utf-8")).hexdigest()[:12]
        storage_key = f"ms_policy_mitra_urep_{sig}"
        uid = str(st.session_state.get("user_id", "") or "")
        reporter_meta = {
            "user_id": uid,
            "user_name": str(st.session_state.get("user_name", "") or uid),
            "user_email": str(st.session_state.get("user_email", "") or ""),
            "mode_tag": mode_tag or "Policy Mitra",
            "endpoint": str(st.secrets.get("WEB_APP_URL", "") or ""),
            "token": _make_report_token(uid, batch_id),
        }
        html_str = _build_highlighter_html(
            rows, visible_cols, storage_key, aligned_debug, batch_id,
            retest_count=0, ui_mode="user_report", reporter_meta=reporter_meta,
        )
        iframe_height = min(max(380, 130 + len(rows) * 33), 640)
        components.html(html_str, height=iframe_height, scrolling=False)
    except FileNotFoundError as e:
        st.warning(f"⚠️ {e} — Showing standard table fallback.")
        st.dataframe(pd.DataFrame(rows, columns=visible_cols), use_container_width=True, hide_index=True, height=620)
