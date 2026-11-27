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

  // Auto-switch to Highlighted Rows view & sync bug row numbers to hidden Streamlit Re-Test bridge
  onlyHighlighted = true;
  saveFilterState();
  syncFilterButton();
  renderTable();
  syncPendingRowsToStreamlit(350, false);

  showStatus("✅ Downloaded (" + rowIndices.length + " pending entries)");
}

function triggerRetestPreview() {
  if (IS_USER_REPORT) return;
  const retestBtn = document.getElementById("btn-retest-inline");
  if (retestBtn) {
    retestBtn.disabled = true;
    retestBtn.textContent = "⏳ Re-Testing...";
  }
  try {
    const pWin = window.parent;
    const pDoc = pWin && pWin.document;
    if (!pDoc) return;

    const rowStr = getPendingBugRowNumbersText();
    const inp = pDoc.querySelector('input[aria-label="🎯 Re-Test Rows"]');
    if (inp && inp.value !== rowStr) {
      const setter = Object.getOwnPropertyDescriptor(pWin.HTMLInputElement.prototype, "value").set;
      setter.call(inp, rowStr);
      inp.dispatchEvent(new pWin.Event("input", { bubbles: true }));
      inp.blur();
    }

    setTimeout(() => {
      const buttons = pDoc.querySelectorAll("button");
      for (let i = 0; i < buttons.length; i++) {
        if ((buttons[i].textContent || "").indexOf("PM_HIDDEN_RETEST_TRIGGER") !== -1) {
          buttons[i].click();
          return;
        }
      }
      if (retestBtn) {
        retestBtn.disabled = false;
        updateBadge();
      }
      showStatus("⚠️ Re-Test trigger not ready — please refresh once.", true);
    }, 90);
  } catch (e) {
    if (retestBtn) {
      retestBtn.disabled = false;
      updateBadge();
    }
  }
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
