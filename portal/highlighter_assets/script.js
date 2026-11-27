const PAYLOAD = window.POLICY_MITRA_PAYLOAD || {};
const COLS = PAYLOAD.columns || [];
const ROWS = PAYLOAD.rows || [];
const DEBUG_LIST = PAYLOAD.debug || [];
const STORAGE_KEY = PAYLOAD.storageKey;
const BATCH_ID = PAYLOAD.batchId || "batch";
const UI_MODE = PAYLOAD.uiMode || "admin";
const REPORTER = PAYLOAD.reporter || {};
const IS_USER_REPORT = UI_MODE === "user_report";

const nameColIdx = COLS.findIndex(c => c.trim().toLowerCase() === "client name");
const compColName = COLS.find(c => c.trim().toLowerCase() === "company name") || "";
const planColName = COLS.find(c => c.trim().toLowerCase() === "plan name") || "";
const clientColName = nameColIdx >= 0 ? COLS[nameColIdx] : (COLS[0] || "");

let onlyHighlighted = false;
let highlights = {};
let lastBlobUrl = null;
let isSubmitting = false;

function getCellVal(rIdx, cIdx) {
  if (!ROWS[rIdx] || cIdx < 0 || cIdx >= COLS.length) return "";
  return ROWS[rIdx][COLS[cIdx]] || "";
}

function loadHighlights() {
  try {
    const saved = window.localStorage.getItem(STORAGE_KEY);
    if (saved) {
      const parsed = JSON.parse(saved) || {};
      const normalized = {};
      Object.keys(parsed).forEach(k => {
        const [rStr, cStr] = k.split("||");
        const rIdx = parseInt(rStr, 10);
        const cIdx = parseInt(cStr, 10);
        if (isNaN(rIdx) || isNaN(cIdx) || rIdx < 0 || rIdx >= ROWS.length || cIdx < 0 || cIdx >= COLS.length) return;
        const v = parsed[k];
        if (typeof v === "string") {
          normalized[k] = { state: v === "green" ? "green" : "red", origVal: getCellVal(rIdx, cIdx), fixedVal: "" };
        } else if (v && typeof v === "object") {
          normalized[k] = {
            state: v.state === "green" ? "green" : "red",
            origVal: (v.origVal === undefined || v.origVal === null) ? "" : String(v.origVal),
            fixedVal: (v.fixedVal === undefined || v.fixedVal === null) ? "" : String(v.fixedVal),
          };
        }
      });
      highlights = normalized;
    }
  } catch (e) {}
}

function saveHighlights() {
  try {
    window.localStorage.setItem(STORAGE_KEY, JSON.stringify(highlights));
  } catch (e) {}
}

function reconcileHighlights() {
  if (IS_USER_REPORT) return;
  let changed = false;
  let newlyFixed = 0;
  Object.keys(highlights).forEach(k => {
    const [rStr, cStr] = k.split("||");
    const rIdx = parseInt(rStr, 10);
    const cIdx = parseInt(cStr, 10);
    const currVal = getCellVal(rIdx, cIdx);
    const entry = highlights[k];
    if (!entry) return;

    if (entry.state === "red" && currVal !== entry.origVal) {
      entry.state = "green";
      entry.fixedVal = currVal;
      changed = true;
      newlyFixed++;
    } else if (entry.state === "green") {
      if (currVal === entry.origVal) {
        entry.state = "red";
        entry.fixedVal = "";
        changed = true;
      } else if (entry.fixedVal !== currVal) {
        entry.fixedVal = currVal;
        changed = true;
      }
    }
  });
  if (changed) saveHighlights();
  if (newlyFixed > 0) {
    showStatus("🎉 " + newlyFixed + " Bug" + (newlyFixed > 1 ? "s" : "") + " Auto-Fixed (🟢)!");
  }
}

function showStatus(text, isErr) {
  const msg = document.getElementById("status-msg");
  if (!msg) return;
  msg.textContent = text;
  msg.className = "status-msg" + (isErr ? " err-msg" : "");
  msg.style.display = "inline";
  if (!isErr) {
    setTimeout(() => { msg.style.display = "none"; }, 4500);
  }
}

function toggleFilter() {
  onlyHighlighted = !onlyHighlighted;
  const bf = document.getElementById("btn-filter");
  if (bf) {
    bf.className = "btn" + (onlyHighlighted ? " active-filter" : "");
    bf.textContent = onlyHighlighted
      ? "📋 Show All Rows"
      : (IS_USER_REPORT ? "🔎 Selected Rows" : "🔎 Highlighted Rows");
  }
  renderTable();
}

function toggleCell(rIdx, cIdx, tdEl) {
  const key = rIdx + "||" + cIdx;
  const currVal = getCellVal(rIdx, cIdx);
  const cur = highlights[key];

  if (!cur) {
    highlights[key] = { state: "red", origVal: currVal, fixedVal: "" };
    tdEl.classList.remove("hl-green");
    tdEl.classList.add("hl-red");
    tdEl.title = (currVal || "[BLANK]") + "  (🔴 Marked as Bug — Click to clear)";
  } else if (cur.state === "green") {
    highlights[key] = { state: "red", origVal: currVal, fixedVal: "" };
    tdEl.classList.remove("hl-green");
    tdEl.classList.add("hl-red");
    tdEl.title = (currVal || "[BLANK]") + "  (🔴 Re-marked as Bug — Click again to clear)";
  } else {
    delete highlights[key];
    tdEl.classList.remove("hl-red", "hl-green");
    tdEl.title = (currVal || "[BLANK]") + "  (Click to highlight 🔴 Bug)";
  }

  saveHighlights();
  updateBadge();
  if (onlyHighlighted) renderTable();
}

function clearFixed() {
  Object.keys(highlights).forEach(k => {
    if (highlights[k] && highlights[k].state === "green") delete highlights[k];
  });
  saveHighlights();
  renderTable();
  showStatus("🧹 Cleared fixed (🟢) highlights");
}

function clearAll() {
  highlights = {};
  saveHighlights();
  onlyHighlighted = false;
  const bf = document.getElementById("btn-filter");
  if (bf) {
    bf.className = "btn";
    bf.textContent = IS_USER_REPORT ? "🔎 Selected Rows" : "🔎 Highlighted Rows";
  }
  const btnSub = document.getElementById("btn-submit-admin");
  if (btnSub) {
    btnSub.disabled = false;
    btnSub.className = "btn submit-admin";
    btnSub.textContent = "📨 Submit Bug Report to Admin";
  }
  renderTable();
}

function updateBadge() {
  let redCnt = 0;
  let greenCnt = 0;
  Object.keys(highlights).forEach(k => {
    if (highlights[k].state === "green") greenCnt++;
    else redCnt++;
  });

  const bugBadge = document.getElementById("bug-count");
  const fixedBadge = document.getElementById("fixed-count");
  const clearGreenBtn = document.getElementById("btn-clear-green");

  if (IS_USER_REPORT) {
    if (bugBadge) {
      if (redCnt === 0) {
        bugBadge.textContent = "0 Selected";
        bugBadge.className = "badge";
      } else {
        bugBadge.textContent = "🔴 " + redCnt + " Selected";
        bugBadge.className = "badge has-bugs";
      }
    }
    if (fixedBadge) fixedBadge.style.display = "none";
    if (clearGreenBtn) clearGreenBtn.style.display = "none";
    return;
  }

  if (bugBadge) {
    if (redCnt === 0 && greenCnt === 0) {
      bugBadge.textContent = "0 Highlighted";
      bugBadge.className = "badge";
    } else if (redCnt === 0) {
      bugBadge.textContent = "🔴 0 Pending";
      bugBadge.className = "badge";
    } else {
      bugBadge.textContent = "🔴 " + redCnt + (greenCnt > 0 ? " Pending" : " Highlighted");
      bugBadge.className = "badge has-bugs";
    }
  }

  if (fixedBadge && clearGreenBtn) {
    if (greenCnt > 0) {
      fixedBadge.textContent = "🟢 " + greenCnt + " Fixed";
      fixedBadge.style.display = "inline-block";
      clearGreenBtn.style.display = "inline-flex";
    } else {
      fixedBadge.style.display = "none";
      clearGreenBtn.style.display = "none";
    }
  }
}

function collectPendingBugsByRow() {
  const byRow = {};
  let totalCells = 0;
  Object.keys(highlights).forEach(k => {
    const entry = highlights[k];
    if (!entry || entry.state !== "red") return;
    const [rStr, cStr] = k.split("||");
    const rIdx = parseInt(rStr, 10);
    const cIdx = parseInt(cStr, 10);
    if (!byRow[rIdx]) byRow[rIdx] = [];
    byRow[rIdx].push({ col: COLS[cIdx], val: ROWS[rIdx][COLS[cIdx]] || "[BLANK]" });
    totalCells++;
  });
  const rowIndices = Object.keys(byRow).map(Number).sort((a, b) => a - b);
  return { byRow, rowIndices, totalCells };
}

function buildSummaryText(byRow, rowIndices) {
  const out = [];
  rowIndices.forEach((rIdx, i) => {
    const row = ROWS[rIdx];
    const cname = (clientColName && row[clientColName]) ? row[clientColName] : ("Row #" + (rIdx + 1));
    const comp = compColName && row[compColName] ? row[compColName] : "";
    const plan = planColName && row[planColName] ? row[planColName] : "";
    const meta = [comp, plan].filter(Boolean).join(" | ");
    out.push((i + 1) + ". " + cname + (meta ? " (" + meta + ")" : ""));
    byRow[rIdx].forEach(item => {
      out.push('   - [BUG] ' + item.col + ': "' + item.val + '"');
    });
  });
  return out.join("\n");
}

function buildFullBugPackText(byRow, rowIndices, userNote) {
  const lines = [];
  const total = rowIndices.length;
  lines.push("================================================================================");
  lines.push("MS.SOFT POLICY MITRA - HIGHLIGHTED BUG PACK (SUMMARY + RAW PDF TEXT)");
  lines.push("Batch ID: " + BATCH_ID + " | Total Highlighted Entries: " + total);
  if (IS_USER_REPORT) {
    lines.push(
      "Reported By: " + (REPORTER.userName || REPORTER.userId || "User")
      + (REPORTER.userEmail ? " (" + REPORTER.userEmail + ")" : "")
      + " | Mode: " + (REPORTER.modeTag || "Policy Mitra")
    );
    if (userNote) lines.push("User Note  : " + userNote);
  }
  lines.push("================================================================================");
  lines.push("");
  lines.push("SUMMARY INDEX:");
  lines.push(buildSummaryText(byRow, rowIndices));
  lines.push("");

  rowIndices.forEach((rIdx, i) => {
    const row = ROWS[rIdx];
    const dbg = DEBUG_LIST[rIdx] || {};
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
    byRow[rIdx].forEach(item => {
      lines.push('  - [BUG] ' + item.col + ': "' + item.val + '"');
    });
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
  });

  return lines.join("\n");
}

function downloadBugPack() {
  const { byRow, rowIndices } = collectPendingBugsByRow();
  if (rowIndices.length === 0) {
    const hasGreen = Object.keys(highlights).some(k => highlights[k].state === "green");
    alert(hasGreen
      ? "🎉 Sabhi highlighted bugs auto-fix (🟢 Green) ho chuke hain! Koi pending 🔴 Bug nahi bacha."
      : "Please click at least one cell to highlight a 🔴 bug first.");
    return;
  }

  const packText = buildFullBugPackText(byRow, rowIndices, "");
  const filename = "BUG_PACK_" + rowIndices.length + "_ENTRIES_" + BATCH_ID + ".txt";

  if (lastBlobUrl) {
    try { URL.revokeObjectURL(lastBlobUrl); } catch (e) {}
  }
  const blob = new Blob([packText], { type: "text/plain;charset=utf-8" });
  lastBlobUrl = URL.createObjectURL(blob);

  const a = document.createElement("a");
  a.href = lastBlobUrl;
  a.download = filename;
  document.body.appendChild(a);
  a.click();
  document.body.removeChild(a);

  showStatus("✅ Downloaded (" + rowIndices.length + " pending entries)");
}

async function submitBugReportToAdmin() {
  if (isSubmitting) return;
  const { byRow, rowIndices, totalCells } = collectPendingBugsByRow();
  if (rowIndices.length === 0) {
    alert("Please click at least one wrong cell (🔴) before submitting the bug report.");
    return;
  }
  if (!REPORTER.endpoint || !REPORTER.token) {
    showStatus("❌ Reporting service not configured.", true);
    return;
  }

  const noteEl = document.getElementById("user-bug-note");
  const userNote = noteEl ? noteEl.value.trim() : "";
  const summaryText = buildSummaryText(byRow, rowIndices);
  const packText = buildFullBugPackText(byRow, rowIndices, userNote);
  const safeUser = (REPORTER.userId || "USER").replace(/[^A-Za-z0-9_\-]/g, "_").slice(0, 20);
  const fileName = "USER_BUG_PACK_" + safeUser + "_" + rowIndices.length + "_ENTRIES_" + BATCH_ID + ".txt";

  const btnSub = document.getElementById("btn-submit-admin");
  isSubmitting = true;
  if (btnSub) {
    btnSub.disabled = true;
    btnSub.textContent = "⏳ Sending to Admin...";
  }
  showStatus("⏳ Sending bug report to Admin...");

  try {
    // Use text/plain to keep it a simple CORS request (no preflight) for Google Apps Script Web App
    const resp = await fetch(REPORTER.endpoint, {
      method: "POST",
      headers: { "Content-Type": "text/plain;charset=utf-8" },
      redirect: "follow",
      body: JSON.stringify({
        action: "submit_bug_report",
        report_token: REPORTER.token,
        user_id: REPORTER.userId || "",
        user_name: REPORTER.userName || "",
        user_email: REPORTER.userEmail || "",
        mode_tag: REPORTER.modeTag || "",
        batch_id: BATCH_ID,
        entry_count: rowIndices.length,
        bug_count: totalCells,
        user_note: userNote,
        summary_text: summaryText,
        bug_pack_text: packText,
        file_name: fileName,
      }),
    });
    const resJson = await resp.json();
    if (resJson && resJson.success) {
      if (btnSub) {
        btnSub.className = "btn submit-admin sent-ok";
        btnSub.textContent = "✅ Sent to Admin!";
      }
      if (noteEl) noteEl.value = "";
      showStatus("✅ Bug Report Admin ke mail par bhej diya gaya hai! (" + rowIndices.length + " entries)");
    } else {
      throw new Error((resJson && resJson.message) ? resJson.message : "Server returned an error.");
    }
  } catch (err) {
    if (btnSub) {
      btnSub.disabled = false;
      btnSub.textContent = "📨 Retry Submit Bug Report";
    }
    showStatus("❌ Send failed: " + (err && err.message ? err.message : String(err)), true);
  } finally {
    isSubmitting = false;
  }
}

function rowHasAnyHighlight(rIdx) {
  const prefix = rIdx + "||";
  return Object.keys(highlights).some(k => k.startsWith(prefix));
}

function renderTable() {
  const table = document.getElementById("preview-table");
  table.innerHTML = "";

  const thead = document.createElement("thead");
  const htr = document.createElement("tr");

  const thNum = document.createElement("th");
  thNum.textContent = "#";
  thNum.className = "row-num-hdr";
  htr.appendChild(thNum);

  COLS.forEach((col, cIdx) => {
    const th = document.createElement("th");
    th.textContent = col;
    if (cIdx === nameColIdx) th.className = "sticky-name-hdr";
    htr.appendChild(th);
  });
  thead.appendChild(htr);
  table.appendChild(thead);

  const tbody = document.createElement("tbody");
  let renderedCount = 0;

  ROWS.forEach((row, rIdx) => {
    if (onlyHighlighted && !rowHasAnyHighlight(rIdx)) return;
    renderedCount++;

    const tr = document.createElement("tr");
    const tdNum = document.createElement("td");
    tdNum.textContent = String(rIdx + 1);
    tdNum.className = "row-num";
    tr.appendChild(tdNum);

    COLS.forEach((col, cIdx) => {
      const td = document.createElement("td");
      const val = row[col] || "";
      const entry = highlights[rIdx + "||" + cIdx];
      td.textContent = val || "—";
      if (!val) td.classList.add("empty-cell");
      if (cIdx === nameColIdx) td.classList.add("sticky-name");

      if (!IS_USER_REPORT && entry && entry.state === "green") {
        td.classList.add("hl-green");
        const beforeTxt = entry.origVal || "[BLANK]";
        const nowTxt = val || "[BLANK]";
        td.title = "✅ Auto-Fixed! Before: " + beforeTxt + " → Now: " + nowTxt + "  (Click to mark 🔴 Bug again if still wrong)";
      } else if (entry && entry.state === "red") {
        td.classList.add("hl-red");
        td.title = (val || "[BLANK]") + "  (🔴 Selected — Click to clear)";
      } else {
        td.title = (val || "[BLANK]") + "  (Click to mark 🔴 wrong value)";
      }

      td.addEventListener("click", () => toggleCell(rIdx, cIdx, td));
      tr.appendChild(td);
    });
    tbody.appendChild(tr);
  });

  if (renderedCount === 0) {
    const tr = document.createElement("tr");
    const td = document.createElement("td");
    td.colSpan = COLS.length + 1;
    td.style.textAlign = "center";
    td.style.padding = "20px";
    td.style.color = "#64748b";
    td.textContent = "No selected rows yet — click 'Show All Rows' to select wrong cells.";
    tr.appendChild(td);
    tbody.appendChild(tr);
  }

  table.appendChild(tbody);
  updateBadge();
}

loadHighlights();
reconcileHighlights();
renderTable();
