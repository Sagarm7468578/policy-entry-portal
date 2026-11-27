const PAYLOAD = window.POLICY_MITRA_PAYLOAD || {};
const COLS = PAYLOAD.columns || [];
const ROWS = PAYLOAD.rows || [];
const DEBUG_LIST = PAYLOAD.debug || [];
const STORAGE_KEY = PAYLOAD.storageKey;
const FILTER_KEY = STORAGE_KEY ? (STORAGE_KEY + "_filter") : "";
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
    if (!saved) return;
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
  } catch (e) {}
}

function saveHighlights() {
  try {
    window.localStorage.setItem(STORAGE_KEY, JSON.stringify(highlights));
  } catch (e) {}
}

function syncFilterButton() {
  const bf = document.getElementById("btn-filter");
  if (!bf) return;
  bf.className = "btn" + (onlyHighlighted ? " active-filter" : "");
  bf.textContent = onlyHighlighted
    ? "📋 Show All Rows"
    : (IS_USER_REPORT ? "🔎 Selected Rows" : "🔎 Highlighted Rows");
}

function saveFilterState() {
  try {
    if (FILTER_KEY) {
      window.localStorage.setItem(FILTER_KEY, onlyHighlighted ? "1" : "0");
    }
  } catch (e) {}
}

function loadFilterState() {
  try {
    if (FILTER_KEY && window.localStorage.getItem(FILTER_KEY) === "1" && Object.keys(highlights).length > 0) {
      onlyHighlighted = true;
    } else {
      onlyHighlighted = false;
    }
  } catch (e) {
    onlyHighlighted = false;
  }
  syncFilterButton();
}

function getPendingBugRowNumbers() {
  const rowSet = new Set();
  Object.keys(highlights).forEach(k => {
    const entry = highlights[k];
    if (!entry || entry.state !== "red") return;
    const rIdx = parseInt(k.split("||")[0], 10);
    if (!isNaN(rIdx) && rIdx >= 0 && rIdx < ROWS.length) {
      rowSet.add(rIdx + 1);
    }
  });
  return Array.from(rowSet).sort((a, b) => a - b);
}

function getPendingBugRowNumbersText() {
  return getPendingBugRowNumbers().join(", ");
}

function syncPendingRowsToStreamlit(delayMs, pressEnter) {
  if (IS_USER_REPORT) return;
  const rowStr = getPendingBugRowNumbersText();
  const wait = typeof delayMs === "number" ? delayMs : 120;
  const doEnter = pressEnter !== false;
  setTimeout(() => {
    try {
      const pWin = window.parent;
      const pDoc = pWin && pWin.document;
      if (!pDoc) return;
      const inp = pDoc.querySelector('input[aria-label="🎯 Re-Test Rows"]');
      if (!inp || inp.value === rowStr) return;
      const setter = Object.getOwnPropertyDescriptor(pWin.HTMLInputElement.prototype, "value").set;
      setter.call(inp, rowStr);
      inp.dispatchEvent(new pWin.Event("input", { bubbles: true }));
      if (doEnter) {
        setTimeout(() => {
          try {
            inp.dispatchEvent(new pWin.KeyboardEvent("keydown", {
              key: "Enter",
              code: "Enter",
              keyCode: 13,
              which: 13,
              bubbles: true,
              cancelable: true,
            }));
            inp.blur();
          } catch (e) {}
        }, 50);
      } else {
        inp.blur();
      }
    } catch (e) {}
  }, wait);
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
  const retestBtn = document.getElementById("btn-retest-inline");

  if (IS_USER_REPORT) {
    if (bugBadge) {
      bugBadge.textContent = redCnt === 0 ? "0 Selected" : ("🔴 " + redCnt + " Selected");
      bugBadge.className = redCnt === 0 ? "badge" : "badge has-bugs";
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

  if (retestBtn && !retestBtn.disabled) {
    const pendingRows = getPendingBugRowNumbers();
    retestBtn.textContent = pendingRows.length > 0
      ? ("🔄 Re-Test Preview (" + pendingRows.length + " Selected)")
      : ("🔄 Re-Test Preview (All " + ROWS.length + ")");
  }
}

function rowHasAnyHighlight(rIdx) {
  const prefix = rIdx + "||";
  return Object.keys(highlights).some(k => k.startsWith(prefix));
}
