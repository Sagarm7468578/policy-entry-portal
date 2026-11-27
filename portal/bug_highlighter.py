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


def _build_highlighter_html(
    rows: list,
    columns: list,
    storage_key: str,
    aligned_debug: list,
    batch_id: str,
    retest_count: int = 0,
) -> str:
    css_code = _load_asset("style.css")
    js_code = _load_asset("script.js")

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
    }
    data_json = json.dumps(payload, ensure_ascii=False).replace("</", "<\\/")

    return (
        "<!DOCTYPE html><html><head><meta charset='utf-8' />"
        f"<style>{css_code}</style>"
        "</head><body>"
        "<div class='container'>"
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
):
    """
    Renders Preview Mode table for the current round only (non-essential columns hidden in Preview only).
    - Admin users get click-to-highlight 🔴 Bug cells that auto-turn 🟢 Green on 1-click Re-Test.
    - Excel / Google Sheet saving continues to include ALL columns untouched.
    """
    if not rows:
        return

    visible_cols = _filter_preview_columns(columns)

    if not enable_highlighter:
        st.dataframe(pd.DataFrame(rows, columns=visible_cols), use_container_width=True, hide_index=True, height=900)
        return

    h_col1, h_col2 = st.columns([3, 1])
    with h_col1:
        st.caption(
            "🖍️ **Bug Highlight Mode:** Click wrong cells to mark 🔴 Bug → update code → click **🔄 Re-Test Preview** to auto-turn fixed cells 🟢 Green."
        )
    with h_col2:
        use_highlight_mode = st.toggle("🖍️ Cell Highlighter", value=True, key=f"toggle_hl_{batch_id}")

    if not use_highlight_mode:
        st.dataframe(pd.DataFrame(rows, columns=visible_cols), use_container_width=True, hide_index=True, height=900)
        return

    try:
        aligned_debug = _align_debug_to_rows(rows, visible_cols, debug_list or [])
        sig = hashlib.md5(f"{batch_id}|{len(rows)}|{','.join(visible_cols)}".encode("utf-8")).hexdigest()[:12]
        storage_key = f"ms_policy_mitra_hl_{sig}"
        html_str = _build_highlighter_html(rows, visible_cols, storage_key, aligned_debug, batch_id, retest_count=retest_count)
        iframe_height = min(max(680, 140 + len(rows) * 36), 960)
        components.html(html_str, height=iframe_height, scrolling=False)
    except FileNotFoundError as e:
        st.warning(f"⚠️ {e} — Showing standard table fallback.")
        st.dataframe(pd.DataFrame(rows, columns=visible_cols), use_container_width=True, hide_index=True, height=900)
