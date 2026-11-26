import hashlib
import json
import pandas as pd
import streamlit as st
import streamlit.components.v1 as components


def _build_highlighter_html(rows: list, columns: list, storage_key: str) -> str:
    payload = {
        "columns": list(columns),
        "rows": [
            {col: ("" if r.get(col) is None else str(r.get(col))) for col in columns}
            for r in rows
        ],
        "storageKey": storage_key,
    }
    data_json = json.dumps(payload, ensure_ascii=False).replace("</", "<\\/")

    return f"""<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8" />
<style>
  * {{ box-sizing: border-box; font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif; }}
  body {{ margin: 0; padding: 4px 2px; background: transparent; color: #1e293b; }}

  .toolbar {{
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
  .tool-group {{ display: flex; align-items: center; gap: 6px; }}
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
  }}
  .btn:hover {{ background: #f1f5f9; }}
  .btn.active-red {{ background: #fee2e2; border-color: #dc2626; color: #991b1b; box-shadow: 0 0 0 1px #dc2626; }}
  .btn.active-yellow {{ background: #fef3c7; border-color: #d97706; color: #92400e; box-shadow: 0 0 0 1px #d97706; }}
  .btn.active-green {{ background: #d1fae5; border-color: #059669; color: #065f46; box-shadow: 0 0 0 1px #059669; }}
  .btn.active-filter {{ background: #1e40af; border-color: #1e40af; color: #ffffff; }}
  .btn.primary {{ background: #1f4e78; border-color: #1f4e78; color: #ffffff; }}
  .btn.primary:hover {{ background: #163a5a; }}
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
  .copy-msg {{ font-size: 12px; font-weight: 600; color: #059669; display: none; }}

  .table-wrap {{
    width: 100%;
    max-height: 490px;
    overflow: auto;
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

  /* Highlight Colors */
  td.hl-red {{
    background: #fecaca !important;
    color: #7f1d1d !important;
    font-weight: 700;
    box-shadow: inset 0 0 0 2px #dc2626;
  }}
  td.hl-yellow {{
    background: #fde68a !important;
    color: #78350f !important;
    font-weight: 700;
    box-shadow: inset 0 0 0 2px #d97706;
  }}
  td.hl-green {{
    background: #a7f3d0 !important;
    color: #064e3b !important;
    font-weight: 700;
    box-shadow: inset 0 0 0 2px #059669;
  }}

  .summary-box {{
    margin-top: 8px;
    display: none;
    background: #fffbeb;
    border: 1px solid #f59e0b;
    border-radius: 8px;
    padding: 8px 10px;
  }}
  .summary-box textarea {{
    width: 100%;
    height: 110px;
    margin-top: 6px;
    font-family: ui-monospace, SFMono-Regular, Menlo, monospace;
    font-size: 12px;
    padding: 6px;
    border: 1px solid #cbd5e1;
    border-radius: 6px;
    resize: vertical;
  }}
</style>
</head>
<body>
  <div class="toolbar">
    <div class="tool-group">
      <span style="font-weight:700;color:#475569;">Brush:</span>
      <button id="btn-red" class="btn active-red" onclick="setColor('red')">🔴 Bug</button>
      <button id="btn-yellow" class="btn" onclick="setColor('yellow')">🟡 Recheck</button>
      <button id="btn-green" class="btn" onclick="setColor('green')">🟢 Fixed</button>
    </div>
    <div class="sep"></div>
    <div class="tool-group">
      <span id="bug-count" class="badge">0 Highlighted</span>
      <button id="btn-filter" class="btn" onclick="toggleFilter()">🔎 Only Highlighted Rows</button>
      <button class="btn primary" onclick="copyBugList()">📋 Copy Highlighted Bugs</button>
      <button class="btn danger" onclick="clearAll()">🗑️ Clear All</button>
      <span id="copy-msg" class="copy-msg">✅ Copied!</span>
    </div>
  </div>

  <div class="table-wrap">
    <table id="preview-table"></table>
  </div>

  <div id="summary-box" class="summary-box">
    <div style="display:flex;justify-content:space-between;align-items:center;">
      <strong style="font-size:12.5px;color:#92400e;">Highlighted Bugs Summary (Ready to paste in chat):</strong>
      <button class="btn" onclick="document.getElementById('summary-box').style.display='none'">✖ Close</button>
    </div>
    <textarea id="summary-text" readonly></textarea>
  </div>

<script>
  const PAYLOAD = {data_json};
  const COLS = PAYLOAD.columns || [];
  const ROWS = PAYLOAD.rows || [];
  const STORAGE_KEY = PAYLOAD.storageKey;

  const nameColIdx = COLS.findIndex(c => c.trim().toLowerCase() === "client name");
  const compColName = COLS.find(c => c.trim().toLowerCase() === "company name") || "";
  const planColName = COLS.find(c => c.trim().toLowerCase() === "plan name") || "";
  const clientColName = nameColIdx >= 0 ? COLS[nameColIdx] : (COLS[0] || "");

  let activeColor = "red";
  let onlyHighlighted = false;
  let highlights = {{}};

  function loadHighlights() {{
    try {{
      const saved = window.localStorage.getItem(STORAGE_KEY);
      if (saved) highlights = JSON.parse(saved) || {{}};
    }} catch (e) {{}}
  }}

  function saveHighlights() {{
    try {{
      window.localStorage.setItem(STORAGE_KEY, JSON.stringify(highlights));
    }} catch (e) {{}}
  }}

  function setColor(c) {{
    activeColor = c;
    ["red", "yellow", "green"].forEach(k => {{
      const b = document.getElementById("btn-" + k);
      b.className = "btn" + (k === c ? " active-" + k : "");
    }});
  }}

  function toggleFilter() {{
    onlyHighlighted = !onlyHighlighted;
    const bf = document.getElementById("btn-filter");
    bf.className = "btn" + (onlyHighlighted ? " active-filter" : "");
    bf.textContent = onlyHighlighted ? "📋 Show All Rows" : "🔎 Only Highlighted Rows";
    renderTable();
  }}

  function toggleCell(rIdx, cIdx, tdEl) {{
    const key = rIdx + "||" + cIdx;
    if (highlights[key] === activeColor) {{
      delete highlights[key];
      tdEl.classList.remove("hl-red", "hl-yellow", "hl-green");
    }} else {{
      highlights[key] = activeColor;
      tdEl.classList.remove("hl-red", "hl-yellow", "hl-green");
      tdEl.classList.add("hl-" + activeColor);
    }}
    saveHighlights();
    updateBadge();
    if (onlyHighlighted) renderTable();
  }}

  function clearAll() {{
    highlights = {{}};
    saveHighlights();
    onlyHighlighted = false;
    const bf = document.getElementById("btn-filter");
    bf.className = "btn";
    bf.textContent = "🔎 Only Highlighted Rows";
    document.getElementById("summary-box").style.display = "none";
    renderTable();
  }}

  function updateBadge() {{
    const keys = Object.keys(highlights);
    const redCnt = keys.filter(k => highlights[k] === "red").length;
    const yelCnt = keys.filter(k => highlights[k] === "yellow").length;
    const grnCnt = keys.filter(k => highlights[k] === "green").length;
    const badge = document.getElementById("bug-count");
    if (keys.length === 0) {{
      badge.textContent = "0 Highlighted";
      badge.className = "badge";
    }} else {{
      const parts = [];
      if (redCnt) parts.push("🔴 " + redCnt);
      if (yelCnt) parts.push("🟡 " + yelCnt);
      if (grnCnt) parts.push("🟢 " + grnCnt);
      badge.textContent = parts.join(" | ");
      badge.className = "badge" + (redCnt ? " has-bugs" : "");
    }}
  }}

  function buildBugReportText() {{
    const byRow = {{}};
    Object.keys(highlights).forEach(k => {{
      const color = highlights[k];
      if (color === "green") return;
      const [rStr, cStr] = k.split("||");
      const rIdx = parseInt(rStr, 10);
      const cIdx = parseInt(cStr, 10);
      if (!byRow[rIdx]) byRow[rIdx] = [];
      byRow[rIdx].push({{ col: COLS[cIdx], val: ROWS[rIdx][COLS[cIdx]] || "[BLANK]", color }});
    }});

    const rowIndices = Object.keys(byRow).map(Number).sort((a, b) => a - b);
    if (rowIndices.length === 0) return "";

    const out = [];
    rowIndices.forEach((rIdx, i) => {{
      const row = ROWS[rIdx];
      const cname = (clientColName && row[clientColName]) ? row[clientColName] : ("Row #" + (rIdx + 1));
      const comp = compColName && row[compColName] ? row[compColName] : "";
      const plan = planColName && row[planColName] ? row[planColName] : "";
      const meta = [comp, plan].filter(Boolean).join(" | ");
      out.push((i + 1) + ". " + cname + (meta ? " (" + meta + ")" : ""));
      byRow[rIdx].forEach(item => {{
        const tag = item.color === "red" ? "BUG" : "CHECK";
        out.push("   - [" + tag + "] " + item.col + ': "' + item.val + '"');
      }});
    }});
    return out.join("\\n");
  }}

  function copyBugList() {{
    const txt = buildBugReportText();
    if (!txt) {{
      alert("Please click at least one cell with 🔴 Bug or 🟡 Recheck first.");
      return;
    }}
    const box = document.getElementById("summary-box");
    const ta = document.getElementById("summary-text");
    ta.value = txt;
    box.style.display = "block";

    const showCopied = () => {{
      const msg = document.getElementById("copy-msg");
      msg.style.display = "inline";
      setTimeout(() => {{ msg.style.display = "none"; }}, 2200);
    }};

    if (navigator.clipboard && navigator.clipboard.writeText) {{
      navigator.clipboard.writeText(txt).then(showCopied).catch(() => {{
        ta.select();
        try {{ document.execCommand("copy"); showCopied(); }} catch (e) {{}}
      }});
    }} else {{
      ta.select();
      try {{ document.execCommand("copy"); showCopied(); }} catch (e) {{}}
    }}
  }}

  function rowHasHighlight(rIdx) {{
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
      if (onlyHighlighted && !rowHasHighlight(rIdx)) return;
      renderedCount++;

      const tr = document.createElement("tr");
      const tdNum = document.createElement("td");
      tdNum.textContent = String(rIdx + 1);
      tdNum.className = "row-num";
      tr.appendChild(tdNum);

      COLS.forEach((col, cIdx) => {{
        const td = document.createElement("td");
        const val = row[col] || "";
        td.textContent = val || "—";
        td.title = (val || "[BLANK]") + "  (Click to highlight)";
        if (!val) td.classList.add("empty-cell");
        if (cIdx === nameColIdx) td.classList.add("sticky-name");

        const hl = highlights[rIdx + "||" + cIdx];
        if (hl) td.classList.add("hl-" + hl);

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
  renderTable();
</script>
</body>
</html>
"""


def render_preview_table(rows: list, columns: list, batch_id: str, enable_highlighter: bool = False):
    """
    Renders Preview Mode table.
    - Admin users get an interactive click-to-highlight cell table (Red/Yellow/Green) + Filter + Copy Bug List.
    - Regular users see the clean standard Streamlit dataframe.
    """
    if not rows:
        return

    if not enable_highlighter:
        st.dataframe(pd.DataFrame(rows, columns=columns), use_container_width=True, hide_index=True)
        return

    h_col1, h_col2 = st.columns([3, 1])
    with h_col1:
        st.caption("🖍️ **Bug Highlight Mode:** Click any cell to highlight it (🔴 Bug / 🟡 Recheck / 🟢 Fixed). Click again to remove.")
    with h_col2:
        use_highlight_mode = st.toggle("🖍️ Cell Highlighter", value=True, key=f"toggle_hl_{batch_id}")

    if not use_highlight_mode:
        st.dataframe(pd.DataFrame(rows, columns=columns), use_container_width=True, hide_index=True)
        return

    sig = hashlib.md5(f"{batch_id}|{len(rows)}|{','.join(columns)}".encode("utf-8")).hexdigest()[:12]
    storage_key = f"ms_policy_mitra_hl_{sig}"
    html_str = _build_highlighter_html(rows, columns, storage_key)
    iframe_height = min(max(320, 185 + len(rows) * 35), 650)
    components.html(html_str, height=iframe_height, scrolling=True)
