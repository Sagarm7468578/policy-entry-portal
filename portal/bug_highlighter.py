import hashlib
import json
import re
import pandas as pd
import streamlit as st
import streamlit.components.v1 as components

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


def _build_highlighter_html(
    rows: list,
    columns: list,
    storage_key: str,
    aligned_debug: list,
    batch_id: str,
    retest_count: int = 0,
) -> str:
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

    return f"""<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8" />
<style>
  * {{ box-sizing: border-box; font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif; }}
  html, body {{
    height: 100%;
    margin: 0;
    padding: 0;
    overflow: hidden;
    background: transparent;
    color: #1e293b;
  }}
  .container {{
    height: 100%;
    display: flex;
    flex-direction: column;
    padding: 2px;
  }}

  .toolbar {{
    flex: 0 0 auto;
    display: flex;
    flex-wrap: wrap;
    align-items: center;
    gap: 8px;
    padding: 8px 10px;
    margin-bottom: 8px;
    background: #f8fafc;
    border: 1px solid #cbd5e1;
    border-radius: 8px;
    font-size: 13px;
  }}
  .tool-group {{ display: flex; flex-wrap: wrap; align-items: center; gap: 6px; }}
  .sep {{ width: 1px; height: 22px; background: #cbd5e1; margin: 0 2px; }}

  .btn {{
    border: 1px solid #cbd5e1;
    background: #ffffff;
    color: #1e293b;
    padding: 5px 10px;
    border-radius: 6px;
    cursor: pointer;
    font-size: 12.5px;
    font-weight: 600;
    transition: all 0.12s ease;
    display: inline-flex;
    align-items: center;
    gap: 5px;
    text-decoration: none;
  }}
  .btn:hover {{ background: #f1f5f9; }}
  .btn.active-red {{ background: #fee2e2; border-color: #dc2626; color: #991b1b; box-shadow: 0 0 0 1px #dc2626; cursor: default; }}
  .btn.active-filter {{ background: #1e40af; border-color: #1e40af; color: #ffffff; }}
  .btn.primary {{ background: #1f4e78; border-color: #1f4e78; color: #ffffff; }}
  .btn.primary:hover {{ background: #163a5a; }}
  .btn.pack {{ background: #0f766e; border-color: #0f766e; color: #ffffff; }}
  .btn.pack:hover {{ background: #115e59; }}
  .btn.clear-green {{ color: #166534; border-color: #86efac; background: #f0fdf4; }}
  .btn.clear-green:hover {{ background: #dcfce7; }}
  .btn.danger {{ color: #b91c1c; border-color: #fca5a5; }}
  .btn.danger:hover {{ background: #fef2f2; }}

  .badge {{
    font-size: 12px;
    font-weight: 700;
    padding: 3px 9px;
    border-radius: 999px;
    background: #e2e8f0;
    color: #334155;
  }}
  .badge.has-bugs {{ background: #fee2e2; color: #991b1b; }}
  .badge.has-fixed {{ background: #dcfce7; color: #166534; border: 1px solid #86efac; }}
  .status-msg {{ font-size: 12px; font-weight: 600; color: #059669; display: none; }}

  .table-wrap {{
    flex: 1 1 auto;
    min-height: 0;
    width: 100%;
    overflow: auto;
    overscroll-behavior: contain;
    border: 1px solid #cbd5e1;
    border-radius: 8px;
    background: #ffffff;
  }}
  table {{
    border-collapse: separate;
    border-spacing: 0;
    width: max-content;
    min-width: 100%;
    font-size: 12.5px;
  }}
  thead th {{
    position: sticky;
    top: 0;
    z-index: 3;
    background: #1f4e78;
    color: #ffffff;
    font-weight: 600;
    text-align: left;
    padding: 8px 10px;
    border-right: 1px solid #2e6496;
    border-bottom: 2px solid #163a5a;
    white-space: nowrap;
    user-select: none;
  }}
  tbody tr:nth-child(even) td {{ background: #f8fafc; }}
  tbody tr:nth-child(odd) td {{ background: #ffffff; }}
  tbody tr:hover td {{ background: #f1f5f9; }}

  td {{
    padding: 7px 10px;
    border-right: 1px solid #e2e8f0;
    border-bottom: 1px solid #e2e8f0;
    white-space: nowrap;
    max-width: 280px;
    overflow: hidden;
    text-overflow: ellipsis;
    cursor: pointer;
    user-select: none;
    transition: background 0.08s ease;
  }}
  td.row-num {{
    position: sticky;
    left: 0;
    z-index: 2;
    background: #f1f5f9 !important;
    color: #475569;
    font-weight: 700;
    text-align: center;
    cursor: default;
    min-width: 38px;
    border-right: 2px solid #cbd5e1;
  }}
  thead th.row-num-hdr {{
    position: sticky;
    left: 0;
    z-index: 5;
    text-align: center;
    min-width: 38px;
  }}
  td.sticky-name {{
    position: sticky;
    left: 38px;
    z-index: 2;
    font-weight: 600;
    border-right: 2px solid #cbd5e1;
  }}
  thead th.sticky-name-hdr {{
    position: sticky;
    left: 38px;
    z-index: 5;
    border-right: 2px solid #2e6496;
  }}
  td.empty-cell {{ color: #94a3b8; font-style: italic; }}

  td.hl-red {{
    background: #fecaca !important;
    color: #7f1d1d !important;
    font-weight: 700;
    box-shadow: inset 0 0 0 2px #dc2626;
  }}
  td.hl-green {{
    background: #dcfce7 !important;
    color: #14532d !important;
    font-weight: 700;
    box-shadow: inset 0 0 0 2px #16a34a;
  }}
</style>
</head>
<body>
<div class="container">
  <div class="toolbar">
    <div class="tool-group">
      <span class="btn active-red">🔴 Bug</span>
    </div>
    <div class="sep"></div>
    <div class="tool-group">
      <span id="bug-count" class="badge">0 Highlighted</span>
      <span id="fixed-count" class="badge has-fixed" style="display:none;">🟢 0 Fixed</span>
      <button id="btn-filter" class="btn" onclick="toggleFilter()">🔎 Highlighted Rows</button>
      <button class="btn pack" onclick="downloadBugPack()">📥 Download Bug Pack + PDF Text (.txt)</button>
      <button class="btn primary" onclick="copyBugList()">📋 Copy Summary</button>
      <button id="btn-clear-green" class="btn clear-green" onclick="clearFixed()" style="display:none;">🧹 Clear Fixed (🟢)</button>
      <button class="btn danger" onclick="clearAll()">🗑️ Clear All</button>
      <span id="status-msg" class="status-msg"></span>
    </div>
  </div>

  <div class="table-wrap">
    <table id="preview-table"></table>
  </div>
</div>

<script>
  const PAYLOAD = {data_json};
  const COLS = PAYLOAD.columns || [];
  const ROWS = PAYLOAD.rows || [];
  const DEBUG_LIST = PAYLOAD.debug || [];
  const STORAGE_KEY = PAYLOAD.storageKey;
  const BATCH_ID = PAYLOAD.batchId || "batch";
  const RETEST_COUNT = PAYLOAD.retestCount || 0;

  const nameColIdx = COLS.findIndex(c => c.trim().toLowerCase() === "client name");
  const compColName = COLS.find(c => c.trim().toLowerCase() === "company name") || "";
  const planColName = COLS.find(c => c.trim().toLowerCase() === "plan name") || "";
  const clientColName = nameColIdx >= 0 ? COLS[nameColIdx] : (COLS[0] || "");

  let onlyHighlighted = false;
  let highlights = {{}};
  let lastBlobUrl = null;

  function getCellVal(rIdx, cIdx) {{
    if (!ROWS[rIdx] || cIdx < 0 || cIdx >= COLS.length) return "";
    return ROWS[rIdx][COLS[cIdx]] || "";
  }}

  function loadHighlights() {{
    try {{
      const saved = window.localStorage.getItem(STORAGE_KEY);
      if (saved) {{
        const parsed = JSON.parse(saved) || {{}};
        const normalized = {{}};
        Object.keys(parsed).forEach(k => {{
          const [rStr, cStr] = k.split("||");
          const rIdx = parseInt(rStr, 10);
          const cIdx = parseInt(cStr, 10);
          if (isNaN(rIdx) || isNaN(cIdx) || rIdx < 0 || rIdx >= ROWS.length || cIdx < 0 || cIdx >= COLS.length) return;
          const v = parsed[k];
          if (typeof v === "string") {{
            normalized[k] = {{ state: v === "green" ? "green" : "red", origVal: getCellVal(rIdx, cIdx) }};
          }} else if (v && typeof v === "object") {{
            normalized[k] = {{
              state: v.state === "green" ? "green" : "red",
              origVal: (v.origVal === undefined || v.origVal === null) ? "" : String(v.origVal),
              fixedVal: (v.fixedVal === undefined || v.fixedVal === null) ? "" : String(v.fixedVal),
            }};
          }}
        }});
        highlights = normalized;
      }}
    }} catch (e) {{}}
  }}

  function saveHighlights() {{
    try {{
      window.localStorage.setItem(STORAGE_KEY, JSON.stringify(highlights));
    }} catch (e) {{}}
  }}

  function reconcileHighlights() {{
    // Automatically turns 🔴 Red cells into 🟢 Green when Re-Test updates their extracted value
    let changed = false;
    let newlyFixed = 0;
    Object.keys(highlights).forEach(k => {{
      const [rStr, cStr] = k.split("||");
      const rIdx = parseInt(rStr, 10);
      const cIdx = parseInt(cStr, 10);
      const currVal = getCellVal(rIdx, cIdx);
      const entry = highlights[k];
      if (!entry) return;

      if (entry.state === "red" && currVal !== entry.origVal) {{
        entry.state = "green";
        entry.fixedVal = currVal;
        changed = true;
        newlyFixed++;
      }} else if (entry.state === "green") {{
        if (currVal === entry.origVal) {{
          entry.state = "red";
          entry.fixedVal = "";
          changed = true;
        }} else if (entry.fixedVal !== currVal) {{
          entry.fixedVal = currVal;
          changed = true;
        }}
      }}
    }});
    if (changed) saveHighlights();
    if (newlyFixed > 0) {{
      showStatus("🎉 " + newlyFixed + " Bug" + (newlyFixed > 1 ? "s" : "") + " Auto-Fixed (🟢)!");
    }}
  }}

  function showStatus(text) {{
    const msg = document.getElementById("status-msg");
    msg.textContent = text;
    msg.style.display = "inline";
    setTimeout(() => {{ msg.style.display = "none"; }}, 3200);
  }}

  function toggleFilter() {{
    onlyHighlighted = !onlyHighlighted;
    const bf = document.getElementById("btn-filter");
    bf.className = "btn" + (onlyHighlighted ? " active-filter" : "");
    bf.textContent = onlyHighlighted ? "📋 Show All Rows" : "🔎 Highlighted Rows";
    renderTable();
  }}

  function toggleCell(rIdx, cIdx, tdEl) {{
    const key = rIdx + "||" + cIdx;
    const currVal = getCellVal(rIdx, cIdx);
    const cur = highlights[key];

    if (!cur) {{
      // Unhighlighted -> 🔴 Red Bug
      highlights[key] = {{ state: "red", origVal: currVal, fixedVal: "" }};
      tdEl.classList.remove("hl-green");
      tdEl.classList.add("hl-red");
      tdEl.title = (currVal || "[BLANK]") + "  (🔴 Marked as Bug — Click to clear)";
    }} else if (cur.state === "green") {{
      // 🟢 Auto-Fixed -> Click once to re-mark 🔴 Red if new value is still wrong
      highlights[key] = {{ state: "red", origVal: currVal, fixedVal: "" }};
      tdEl.classList.remove("hl-green");
      tdEl.classList.add("hl-red");
      tdEl.title = (currVal || "[BLANK]") + "  (🔴 Re-marked as Bug — Click again to clear)";
    }} else {{
      // 🔴 Red -> Unhighlighted
      delete highlights[key];
      tdEl.classList.remove("hl-red", "hl-green");
      tdEl.title = (currVal || "[BLANK]") + "  (Click to highlight)";
    }}

    saveHighlights();
    updateBadge();
    if (onlyHighlighted) renderTable();
  }}

  function clearFixed() {{
    Object.keys(highlights).forEach(k => {{
      if (highlights[k] && highlights[k].state === "green") delete highlights[k];
    }});
    saveHighlights();
    renderTable();
    showStatus("🧹 Cleared fixed (🟢) highlights");
  }}

  function clearAll() {{
    highlights = {{}};
    saveHighlights();
    onlyHighlighted = false;
    const bf = document.getElementById("btn-filter");
    bf.className = "btn";
    bf.textContent = "🔎 Highlighted Rows";
    renderTable();
  }}

  function updateBadge() {{
    let redCnt = 0;
    let greenCnt = 0;
    Object.keys(highlights).forEach(k => {{
      if (highlights[k].state === "green") greenCnt++;
      else redCnt++;
    }});

    const bugBadge = document.getElementById("bug-count");
    const fixedBadge = document.getElementById("fixed-count");
    const clearGreenBtn = document.getElementById("btn-clear-green");

    if (redCnt === 0 && greenCnt === 0) {{
      bugBadge.textContent = "0 Highlighted";
      bugBadge.className = "badge";
    }} else if (redCnt === 0) {{
      bugBadge.textContent = "🔴 0 Pending";
      bugBadge.className = "badge";
    }} else {{
      bugBadge.textContent = "🔴 " + redCnt + (greenCnt > 0 ? " Pending" : " Highlighted");
      bugBadge.className = "badge has-bugs";
    }}

    if (greenCnt > 0) {{
      fixedBadge.textContent = "🟢 " + greenCnt + " Fixed";
      fixedBadge.style.display = "inline-block";
      clearGreenBtn.style.display = "inline-flex";
    }} else {{
      fixedBadge.style.display = "none";
      clearGreenBtn.style.display = "none";
    }}
  }}

  function collectPendingBugsByRow() {{
    // Only exports remaining 🔴 Red bugs (ignores already 🟢 Green auto-fixed cells)
    const byRow = {{}};
    Object.keys(highlights).forEach(k => {{
      const entry = highlights[k];
      if (!entry || entry.state !== "red") return;
      const [rStr, cStr] = k.split("||");
      const rIdx = parseInt(rStr, 10);
      const cIdx = parseInt(cStr, 10);
      if (!byRow[rIdx]) byRow[rIdx] = [];
      byRow[rIdx].push({{ col: COLS[cIdx], val: ROWS[rIdx][COLS[cIdx]] || "[BLANK]" }});
    }});
    const rowIndices = Object.keys(byRow).map(Number).sort((a, b) => a - b);
    return {{ byRow, rowIndices }};
  }}

  function buildSummaryText(byRow, rowIndices) {{
    const out = [];
    rowIndices.forEach((rIdx, i) => {{
      const row = ROWS[rIdx];
      const cname = (clientColName && row[clientColName]) ? row[clientColName] : ("Row #" + (rIdx + 1));
      const comp = compColName && row[compColName] ? row[compColName] : "";
      const plan = planColName && row[planColName] ? row[planColName] : "";
      const meta = [comp, plan].filter(Boolean).join(" | ");
      out.push((i + 1) + ". " + cname + (meta ? " (" + meta + ")" : ""));
      byRow[rIdx].forEach(item => {{
        out.push('   - [BUG] ' + item.col + ': "' + item.val + '"');
      }});
    }});
    return out.join("\\n");
  }}

  function buildFullBugPackText(byRow, rowIndices) {{
    const lines = [];
    const total = rowIndices.length;
    lines.push("================================================================================");
    lines.push("MS.SOFT POLICY MITRA - HIGHLIGHTED BUG PACK (SUMMARY + RAW PDF TEXT)");
    lines.push("Batch ID: " + BATCH_ID + " | Total Highlighted Entries: " + total);
    lines.push("================================================================================");
    lines.push("");
    lines.push("SUMMARY INDEX:");
    lines.push(buildSummaryText(byRow, rowIndices));
    lines.push("");

    rowIndices.forEach((rIdx, i) => {{
      const row = ROWS[rIdx];
      const dbg = DEBUG_LIST[rIdx] || {{}};
      const cname = (clientColName && row[clientColName]) ? row[clientColName] : ("Row #" + (rIdx + 1));
      const comp = compColName && row[compColName] ? row[compColName] : "UNKNOWN";
      const plan = planColName && row[planColName] ? row[planColName] : "UNKNOWN";
      const fname = dbg.file_name || "N/A";
      const rawTxt = dbg.raw_text || "[Raw PDF text not available]";

      lines.push("################################################################################");
      lines.push("BUG ENTRY #" + (i + 1) + " OF " + total);
      lines.push("################################################################################");
      lines.push("CLIENT NAME  : " + cname);
      lines.push("COMPANY NAME : " + comp);
      lines.push("PLAN NAME    : " + plan);
      lines.push("PDF FILE     : " + fname);
      lines.push("HIGHLIGHTED BUGS:");
      byRow[rIdx].forEach(item => {{
        lines.push('  - [BUG] ' + item.col + ': "' + item.val + '"');
      }});
      lines.push("");
      lines.push("EXTRACTED ROW SNAPSHOT:");
      const rowPairs = COLS.map(c => c + "=" + (row[c] || "[BLANK]"));
      lines.push("  " + rowPairs.join(" | "));
      lines.push("");
      lines.push("--- RAW PDF TEXT START (" + fname + ") ---");
      lines.push(rawTxt);
      lines.push("--- RAW PDF TEXT END (" + fname + ") ---");
      lines.push("");
      lines.push("");
    }});

    return lines.join("\\n");
  }}

  function downloadBugPack() {{
    const {{ byRow, rowIndices }} = collectPendingBugsByRow();
    if (rowIndices.length === 0) {{
      const hasGreen = Object.keys(highlights).some(k => highlights[k].state === "green");
      alert(hasGreen
        ? "🎉 Sabhi highlighted bugs auto-fix (🟢 Green) ho chuke hain! Koi pending 🔴 Bug nahi bacha."
        : "Please click at least one cell to highlight a 🔴 bug first.");
      return;
    }}

    const packText = buildFullBugPackText(byRow, rowIndices);
    const filename = "BUG_PACK_" + rowIndices.length + "_ENTRIES_" + BATCH_ID + ".txt";

    if (lastBlobUrl) {{
      try {{ URL.revokeObjectURL(lastBlobUrl); }} catch (e) {{}}
    }}
    const blob = new Blob([packText], {{ type: "text/plain;charset=utf-8" }});
    lastBlobUrl = URL.createObjectURL(blob);

    const a = document.createElement("a");
    a.href = lastBlobUrl;
    a.download = filename;
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);

    showStatus("✅ Downloaded (" + rowIndices.length + " pending entries)");
  }}

  function copyBugList() {{
    const {{ byRow, rowIndices }} = collectPendingBugsByRow();
    if (rowIndices.length === 0) {{
      const hasGreen = Object.keys(highlights).some(k => highlights[k].state === "green");
      alert(hasGreen
        ? "🎉 Sabhi highlighted bugs auto-fix (🟢 Green) ho chuke hain!"
        : "Please click at least one cell to highlight a 🔴 bug first.");
      return;
    }}
    const txt = buildSummaryText(byRow, rowIndices);
    if (navigator.clipboard && navigator.clipboard.writeText) {{
      navigator.clipboard.writeText(txt).then(() => showStatus("✅ Copied!")).catch(() => fallbackCopy(txt));
    }} else {{
      fallbackCopy(txt);
    }}
  }}

  function fallbackCopy(txt) {{
    const ta = document.createElement("textarea");
    ta.value = txt;
    ta.style.position = "fixed";
    ta.style.opacity = "0";
    document.body.appendChild(ta);
    ta.select();
    try {{ document.execCommand("copy"); showStatus("✅ Copied!"); }} catch (e) {{}}
    document.body.removeChild(ta);
  }}

  function rowHasAnyHighlight(rIdx) {{
    const prefix = rIdx + "||";
    return Object.keys(highlights).some(k => k.startsWith(prefix));
  }}

  function renderTable() {{
    const table = document.getElementById("preview-table");
    table.innerHTML = "";

    const thead = document.createElement("thead");
    const htr = document.createElement("tr");

    const thNum = document.createElement("th");
    thNum.textContent = "#";
    thNum.className = "row-num-hdr";
    htr.appendChild(thNum);

    COLS.forEach((col, cIdx) => {{
      const th = document.createElement("th");
      th.textContent = col;
      if (cIdx === nameColIdx) th.className = "sticky-name-hdr";
      htr.appendChild(th);
    }});
    thead.appendChild(htr);
    table.appendChild(thead);

    const tbody = document.createElement("tbody");
    let renderedCount = 0;

    ROWS.forEach((row, rIdx) => {{
      if (onlyHighlighted && !rowHasAnyHighlight(rIdx)) return;
      renderedCount++;

      const tr = document.createElement("tr");
      const tdNum = document.createElement("td");
      tdNum.textContent = String(rIdx + 1);
      tdNum.className = "row-num";
      tr.appendChild(tdNum);

      COLS.forEach((col, cIdx) => {{
        const td = document.createElement("td");
        const val = row[col] || "";
        const entry = highlights[rIdx + "||" + cIdx];
        td.textContent = val || "—";
        if (!val) td.classList.add("empty-cell");
        if (cIdx === nameColIdx) td.classList.add("sticky-name");

        if (entry && entry.state === "green") {{
          td.classList.add("hl-green");
          const beforeTxt = entry.origVal || "[BLANK]";
          const nowTxt = val || "[BLANK]";
          td.title = "✅ Auto-Fixed! Before: " + beforeTxt + " → Now: " + nowTxt + "  (Click to mark 🔴 Bug again if still wrong)";
        }} else if (entry && entry.state === "red") {{
          td.classList.add("hl-red");
          td.title = (val || "[BLANK]") + "  (🔴 Bug — Click to clear)";
        }} else {{
          td.title = (val || "[BLANK]") + "  (Click to highlight 🔴 Bug)";
        }}

        td.addEventListener("click", () => toggleCell(rIdx, cIdx, td));
        tr.appendChild(td);
      }});
      tbody.appendChild(tr);
    }});

    if (renderedCount === 0) {{
      const tr = document.createElement("tr");
      const td = document.createElement("td");
      td.colSpan = COLS.length + 1;
      td.style.textAlign = "center";
      td.style.padding = "20px";
      td.style.color = "#64748b";
      td.textContent = "No highlighted rows yet — click 'Show All Rows' to highlight cells.";
      tr.appendChild(td);
      tbody.appendChild(tr);
    }}

    table.appendChild(tbody);
    updateBadge();
  }}

  loadHighlights();
  reconcileHighlights();
  renderTable();
</script>
</body>
</html>
"""


def render_preview_table(
    rows: list,
    columns: list,
    batch_id: str,
    enable_highlighter: bool = False,
    debug_list: list = None,
    retest_count: int = 0,
):
    """
    Renders Preview Mode table for the current round only (with non-essential columns hidden in Preview only).
    - Admin users get click-to-highlight 🔴 Bug cells that auto-turn 🟢 Green on 1-click Re-Test.
    - Excel / Google Sheet saving continues to include ALL columns untouched.
    """
    if not rows:
        return

    visible_cols = _filter_preview_columns(columns)

    if not enable_highlighter:
        st.dataframe(pd.DataFrame(rows, columns=visible_cols), use_container_width=True, hide_index=True, height=560)
        return

    h_col1, h_col2 = st.columns([3, 1])
    with h_col1:
        st.caption(
            "🖍️ **Bug Highlight Mode:** Click wrong cells to mark 🔴 Bug → update code → click **🔄 Re-Test Preview** to auto-turn fixed cells 🟢 Green."
        )
    with h_col2:
        use_highlight_mode = st.toggle("🖍️ Cell Highlighter", value=True, key=f"toggle_hl_{batch_id}")

    if not use_highlight_mode:
        st.dataframe(pd.DataFrame(rows, columns=visible_cols), use_container_width=True, hide_index=True, height=560)
        return

    aligned_debug = _align_debug_to_rows(rows, visible_cols, debug_list or [])
    sig = hashlib.md5(f"{batch_id}|{len(rows)}|{','.join(visible_cols)}".encode("utf-8")).hexdigest()[:12]
    storage_key = f"ms_policy_mitra_hl_{sig}"
    html_str = _build_highlighter_html(rows, visible_cols, storage_key, aligned_debug, batch_id, retest_count=retest_count)
    iframe_height = min(max(280, 120 + len(rows) * 34), 560)
    components.html(html_str, height=iframe_height, scrolling=False)
