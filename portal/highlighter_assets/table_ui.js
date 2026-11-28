const _CLIENT_MASTER_COLS = new Set([
  "clientcode", "occupation", "mobile", "mobileno", "mobilenumber",
  "mailid", "email", "emailid", "subagent", "familycode",
]);
const _ACCOUNTS_MASTER_COLS = new Set(["accounts", "account"]);
const _RENEWAL_LIST_COLS = new Set(["pyppremium", "ourrenewal"]);
const _SYSTEM_AUTO_COLS = new Set([
  "dateofentry", "payoutmonth", "share", "share%", "insurancetype",
  "policystatus", "reminderdate", "remark", "mail", "print", "folder",
  "healthdatasheet", "yes/no/inadequate",
]);

function getUserLockReason(colName) {
  if (!IS_USER_REPORT) return "";
  const norm = String(colName || "").toLowerCase().replace(/[\s_\-]+/g, "");
  if (_CLIENT_MASTER_COLS.has(norm)) {
    return "ℹ️ '" + colName + "' aapki Client Master sheet se aata hai (PDF bug nahi hai). Client Master me Client Name check karein — aur kuch batana ho to Note me likh dein.";
  }
  if (_ACCOUNTS_MASTER_COLS.has(norm)) {
    return "ℹ️ '" + colName + "' aapki Accounts Master sheet se aata hai (PDF bug nahi hai). Accounts Master rules check karein ya Note me likh dein.";
  }
  if (_RENEWAL_LIST_COLS.has(norm)) {
    return "ℹ️ '" + colName + "' aapke Renewal List folder se aata hai (PDF bug nahi hai). Koi issue ho to Note me likh dein.";
  }
  if (_SYSTEM_AUTO_COLS.has(norm)) {
    return "ℹ️ '" + colName + "' system/auto-calculated column hai (PDF se direct nahi aata). Agar Premium/DOB/Expiry galat ho to us cell ko select karein ya Note me likh dein.";
  }
  return "";
}

function toggleFilter() {
  onlyHighlighted = !onlyHighlighted;
  saveFilterState();
  syncFilterButton();
  renderTable();
  if (onlyHighlighted) {
    syncPendingRowsToStreamlit(120);
  }
}

function toggleCell(rIdx, cIdx, tdEl) {
  const colName = COLS[cIdx] || "";
  const lockReason = getUserLockReason(colName);
  if (lockReason) {
    showStatus(lockReason, false);
    return;
  }

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
  if (Object.keys(highlights).length === 0 && onlyHighlighted) {
    onlyHighlighted = false;
    saveFilterState();
    syncFilterButton();
  }
  renderTable();
  syncPendingRowsToStreamlit(120);
  showStatus("🧹 Cleared fixed (🟢) highlights");
}

function clearAll() {
  highlights = {};
  saveHighlights();
  onlyHighlighted = false;
  saveFilterState();
  syncFilterButton();
  const btnSub = document.getElementById("btn-submit-admin");
  if (btnSub) {
    btnSub.disabled = false;
    btnSub.className = "btn submit-admin";
    btnSub.textContent = "📨 Submit Bug Report to Admin";
  }
  renderTable();
  syncPendingRowsToStreamlit(120);
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
    const locked = Boolean(getUserLockReason(col));
    th.textContent = locked ? ("🔒 " + col) : col;
    if (cIdx === nameColIdx) th.className = "sticky-name-hdr";
    if (locked) th.title = "Non-PDF / Master column — cannot be ticked as PDF bug";
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
      const lockReason = getUserLockReason(col);
      const entry = highlights[rIdx + "||" + cIdx];
      td.textContent = val || "—";
      if (!val) td.classList.add("empty-cell");
      if (cIdx === nameColIdx) td.classList.add("sticky-name");

      if (lockReason) {
        td.classList.add("locked-cell");
        td.title = lockReason;
      } else if (!IS_USER_REPORT && entry && entry.state === "green") {
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

// Keep mouse-wheel scrolling locked inside the table so outer Streamlit page never jumps
document.addEventListener("wheel", function (e) {
  const wrap = document.querySelector(".table-wrap");
  if (!wrap || !wrap.contains(e.target)) {
    e.preventDefault();
    return;
  }
  const dy = e.deltaY || 0;
  const dx = e.deltaX || 0;
  if (Math.abs(dy) >= Math.abs(dx) && dy !== 0) {
    const atTop = wrap.scrollTop <= 0;
    const atBottom = wrap.scrollTop + wrap.clientHeight >= wrap.scrollHeight - 1;
    if ((dy < 0 && atTop) || (dy > 0 && atBottom)) {
      e.preventDefault();
    }
  }
}, { passive: false });

loadHighlights();
reconcileHighlights();
loadFilterState();
renderTable();
