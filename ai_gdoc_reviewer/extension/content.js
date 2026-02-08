// =========================
// Privacy Review Extension
// - Copy-first clipboard read (best effort)
// - Fallback modal paste box (reliable)
// - Backend payload includes: mode, doc_title, doc_text, selection
// - Posts ONE anchored comment thread per selection (manual Cmd+Option+M to open box)
// =========================

// ---------- utils ----------
function sleep(ms) {
  return new Promise((r) => setTimeout(r, ms));
}

function getDocIdFromUrl() {
  // https://docs.google.com/document/d/<DOC_ID>/edit
  const m = window.location.href.match(/\/document\/d\/([^/]+)/);
  return m ? m[1] : null;
}

function getDocTitleBestEffort() {
  // Usually: "<Title> - Google Docs"
  const raw = document.title || "";
  return raw.replace(" - Google Docs", "").trim();
}

// ---------- modal paste UI (clipboard fallback) ----------
function showPasteBox({ title, placeholder }) {
  return new Promise((resolve) => {
    const overlay = document.createElement("div");
    overlay.style.position = "fixed";
    overlay.style.top = "0";
    overlay.style.left = "0";
    overlay.style.width = "100%";
    overlay.style.height = "100%";
    overlay.style.background = "rgba(0,0,0,0.25)";
    overlay.style.zIndex = "9999999";
    overlay.style.display = "flex";
    overlay.style.alignItems = "center";
    overlay.style.justifyContent = "center";

    const modal = document.createElement("div");
    modal.style.width = "520px";
    modal.style.maxWidth = "92vw";
    modal.style.background = "white";
    modal.style.border = "1px solid #ddd";
    modal.style.borderRadius = "14px";
    modal.style.boxShadow = "0 10px 30px rgba(0,0,0,0.25)";
    modal.style.padding = "14px";
    modal.style.fontFamily = "system-ui";

    const h = document.createElement("div");
    h.textContent = title;
    h.style.fontSize = "14px";
    h.style.fontWeight = "600";
    h.style.marginBottom = "6px";

    const p = document.createElement("div");
    p.textContent = "Paste the text here (Cmd+V), then click Run.";
    p.style.fontSize = "12px";
    p.style.color = "#444";
    p.style.marginBottom = "10px";

    const ta = document.createElement("textarea");
    ta.placeholder = placeholder;
    ta.style.width = "100%";
    ta.style.height = "170px";
    ta.style.padding = "10px";
    ta.style.borderRadius = "10px";
    ta.style.border = "1px solid #ccc";
    ta.style.fontSize = "12px";
    ta.style.resize = "vertical";

    const row = document.createElement("div");
    row.style.marginTop = "10px";
    row.style.display = "flex";
    row.style.gap = "8px";
    row.style.justifyContent = "flex-end";

    const cancel = document.createElement("button");
    cancel.textContent = "Cancel";
    cancel.style.padding = "8px 10px";
    cancel.style.borderRadius = "10px";
    cancel.style.border = "1px solid #ddd";
    cancel.style.background = "white";
    cancel.style.cursor = "pointer";

    const run = document.createElement("button");
    run.textContent = "Run";
    run.style.padding = "8px 10px";
    run.style.borderRadius = "10px";
    run.style.border = "1px solid #111";
    run.style.background = "#111";
    run.style.color = "white";
    run.style.cursor = "pointer";

    cancel.onclick = () => {
      overlay.remove();
      resolve(null);
    };

    run.onclick = () => {
      const val = (ta.value || "").trim();
      overlay.remove();
      resolve(val);
    };

    row.appendChild(cancel);
    row.appendChild(run);

    modal.appendChild(h);
    modal.appendChild(p);
    modal.appendChild(ta);
    modal.appendChild(row);

    overlay.appendChild(modal);
    document.body.appendChild(overlay);

    setTimeout(() => ta.focus(), 50);
  });
}

// ---------- clipboard read (best effort) ----------
async function getSelectedTextViaClipboard() {
  try {
    window.focus();
    document.body.focus();
    await sleep(50);
    const text = await navigator.clipboard.readText();
    return text || "";
  } catch (e) {
    console.warn("Clipboard read failed:", e);
    return "";
  }
}

// ---------- comment box helpers ----------
function getVisibleTextboxes() {
  const boxes = Array.from(document.querySelectorAll('[role="textbox"]'));
  return boxes.filter((b) => {
    const r = b.getBoundingClientRect();
    return r.width > 20 && r.height > 10;
  });
}

async function waitForCommentTextbox(timeoutMs = 500) {
  const start = Date.now();
  while (Date.now() - start < timeoutMs) {
    const boxes = getVisibleTextboxes();
    if (boxes.length) return boxes[boxes.length - 1];
    await sleep(50);
  }
  return null;
}

async function waitForUserToOpenCommentBox(timeoutMs = 15000) {
  const start = Date.now();
  while (Date.now() - start < timeoutMs) {
    const textbox = await waitForCommentTextbox(250);
    if (textbox) return textbox;
    await sleep(100);
  }
  return null;
}

async function typeIntoTextbox(textbox, text) {
  textbox.focus();
  textbox.click();
  await sleep(100);

  // Insert text using execCommand (more reliable than synthetic key events)
  document.execCommand("insertText", false, text);
  await sleep(150);
}

async function clickSubmitCommentButton() {
  // 1) Try aria-label based matches (most reliable)
  const ariaSelectors = [
    'button[aria-label="Comment"]',
    'div[role="button"][aria-label="Comment"]',
    'button[aria-label="Reply"]',
    'div[role="button"][aria-label="Reply"]',
  ];

  for (const sel of ariaSelectors) {
    const el = document.querySelector(sel);
    if (el) {
      el.click();
      await sleep(700);
      return true;
    }
  }

  // 2) Fallback: scan visible buttons by text content
  const candidates = Array.from(
    document.querySelectorAll("button, div[role='button']")
  );

  for (const el of candidates) {
    const txt = (el.innerText || "").trim();
    if (txt === "Comment" || txt === "Reply") {
      el.click();
      await sleep(700);
      return true;
    }
  }

  return false;
}

async function focusDoc() {
  // Click into doc surface
  document.body.click();
  await sleep(150);

  // more reliable second click
  const evt = new MouseEvent("click", {
    bubbles: true,
    cancelable: true,
    clientX: 300,
    clientY: 300,
  });
  document.dispatchEvent(evt);
  await sleep(150);
}

// ---------- backend calls ----------
const BACKEND_URL = "http://localhost:8000"; // change when deployed
const MCP_HTTP_URL = "http://localhost:3001"; // MCP server Express endpoint
const API_KEY = "dev_secret_key_change_me"; // move to chrome.storage later

async function callMcpGetDoc({ docId }) {
  console.log("Calling MCP server get-doc GET...");
  const res = await fetch(`${MCP_HTTP_URL}/get-doc/${docId}`, {
    method: "GET",
  });

  if (!res.ok) {
    const err = await res.text();
    throw new Error(err);
  }

  return await res.json();
}

async function callGenerateModifications({
  reviewComments,
  parsedComponents,
  parsedDataFlows,
  sessionId,
}) {
  console.log("Calling backend generate-modifications POST...");
  const res = await fetch(`${BACKEND_URL}/generate-modifications`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      "X-API-Key": API_KEY,
    },
    body: JSON.stringify({
      review_comments: reviewComments,
      parsed_components: parsedComponents,
      parsed_data_flows: parsedDataFlows,
      session_id: sessionId,
    }),
  });

  if (!res.ok) {
    const err = await res.text();
    throw new Error(err);
  }

  return await res.json();
}

// ---------- comment posting ----------

/**
 * Group comments that have identical text (after stripping component prefix).
 * Returns array of { comment, severity, components, dataFlows }.
 */
function groupSimilarComments(comments) {
  const groups = new Map();

  for (const c of comments) {
    // Extract component prefix if present: "[Component Name]: rest of comment"
    const match = c.comment?.match(/^\[([^\]]+)\]:\s*/);
    const componentFromPrefix = match ? match[1] : null;
    const commentWithoutPrefix = match ? c.comment.slice(match[0].length) : c.comment;

    // Collect all components/flows for this comment
    const allItems = new Set(c.related_components || []);
    if (componentFromPrefix) {
      allItems.add(componentFromPrefix);
    }

    // Separate components from data flows (data flows contain "→" or "->")
    const components = new Set();
    const dataFlows = new Set();
    for (const item of allItems) {
      if (item.includes("→") || item.includes("->")) {
        dataFlows.add(item);
      } else {
        components.add(item);
      }
    }

    // Use the comment text (without prefix) as the grouping key
    const key = `${c.severity}:${commentWithoutPrefix}`;

    if (groups.has(key)) {
      const existing = groups.get(key);
      // Merge components and data flows
      for (const comp of components) {
        existing.components.add(comp);
      }
      for (const flow of dataFlows) {
        existing.dataFlows.add(flow);
      }
    } else {
      groups.set(key, {
        comment: commentWithoutPrefix,
        severity: c.severity || "medium",
        components: components,
        dataFlows: dataFlows,
      });
    }
  }

  // Convert to array and sort by severity
  const severityOrder = { high: 0, medium: 1, low: 2 };
  return Array.from(groups.values())
    .sort((a, b) => (severityOrder[a.severity] || 1) - (severityOrder[b.severity] || 1));
}

async function postSingleAnchoredCommentPrivacy(inlineComments) {
  if (!inlineComments || inlineComments.length === 0) return 0;

  // Group similar comments together
  const grouped = groupSimilarComments(inlineComments.slice(0, 8));

  let body = "🤖 AI Privacy Review\n";
  body += "----------------------------------\n";

  grouped.forEach((g, i) => {
    const severity = String(g.severity).toUpperCase();

    // Build affected items line with clear labels
    let affectedItems = "";
    if (g.components.size > 0) {
      affectedItems += `🔧 ${Array.from(g.components).join(", ")}`;
    }
    if (g.dataFlows.size > 0) {
      if (affectedItems) affectedItems += "\n     ";
      affectedItems += `🔀 ${Array.from(g.dataFlows).join(", ")}`;
    }

    body += `\n${i + 1}) [${severity}]`;
    if (affectedItems) {
      body += `\n     ${affectedItems}`;
    }
    body += `\n${g.comment}\n`;
  });

  await focusDoc();

  alert(
    "✅ Privacy review ready.\n\nNow press Cmd+Option+M to open the Google Docs comment box on your selection.\n\n(Once it opens, I will auto-fill + submit.)"
  );

  const textbox = await waitForUserToOpenCommentBox(20000);
  if (!textbox) {
    alert(
      "Comment box did not open.\n\nTry again: select text, then press Cmd+Option+M."
    );
    return 0;
  }

  await typeIntoTextbox(textbox, body);

  const submitted = await clickSubmitCommentButton();
  if (!submitted) {
    alert(
      "Could not find the Comment button.\n\nYou may need to click 'Comment' manually."
    );
    return 0;
  }

  return 1;
}

// ---------- state: last review results ----------
let lastReviewComments = null; // stored after a successful privacy review
let lastReviewSelection = null; // the selection text that was reviewed
let lastParsedComponents = null; // pre-parsed components from review (avoids re-parsing in apply)
let lastParsedDataFlows = null; // pre-parsed data flows from review (avoids re-parsing in apply)

// ---------- Status Panel ----------
let statusPanel = null;
let statusEventSource = null;
let currentSessionId = null;

function createStatusPanel() {
  if (statusPanel) return statusPanel;

  const panel = document.createElement("div");
  panel.id = "ai-status-panel";
  panel.style.position = "fixed";
  panel.style.right = "20px";
  panel.style.top = "80px";
  panel.style.width = "320px";
  panel.style.maxHeight = "400px";
  panel.style.background = "#1a1a2e";
  panel.style.border = "1px solid #333";
  panel.style.borderRadius = "12px";
  panel.style.boxShadow = "0 4px 20px rgba(0,0,0,0.3)";
  panel.style.fontFamily = "ui-monospace, SFMono-Regular, Menlo, Monaco, monospace";
  panel.style.fontSize = "12px";
  panel.style.color = "#e0e0e0";
  panel.style.zIndex = "999998";
  panel.style.display = "none";
  panel.style.flexDirection = "column";
  panel.style.overflow = "hidden";

  // Header
  const header = document.createElement("div");
  header.style.padding = "10px 12px";
  header.style.borderBottom = "1px solid #333";
  header.style.display = "flex";
  header.style.justifyContent = "space-between";
  header.style.alignItems = "center";
  header.style.background = "#16213e";
  header.style.borderRadius = "12px 12px 0 0";

  const title = document.createElement("span");
  title.textContent = "🤖 Agent Thinking";
  title.style.fontWeight = "600";
  title.style.color = "#fff";

  const closeBtn = document.createElement("button");
  closeBtn.textContent = "×";
  closeBtn.style.background = "none";
  closeBtn.style.border = "none";
  closeBtn.style.color = "#888";
  closeBtn.style.fontSize = "18px";
  closeBtn.style.cursor = "pointer";
  closeBtn.style.padding = "0 4px";
  closeBtn.onclick = () => hideStatusPanel();

  header.appendChild(title);
  header.appendChild(closeBtn);

  // Content area
  const content = document.createElement("div");
  content.id = "ai-status-content";
  content.style.padding = "8px 12px";
  content.style.overflowY = "auto";
  content.style.flex = "1";
  content.style.maxHeight = "340px";

  panel.appendChild(header);
  panel.appendChild(content);
  document.body.appendChild(panel);

  statusPanel = panel;
  return panel;
}

function showStatusPanel() {
  const panel = createStatusPanel();
  panel.style.display = "flex";
  clearStatusPanel();
}

function hideStatusPanel() {
  if (statusPanel) {
    statusPanel.style.display = "none";
  }
  disconnectStatusStream();
}

function clearStatusPanel() {
  const content = document.getElementById("ai-status-content");
  if (content) {
    content.innerHTML = "";
  }
}

function addStatusEntry(update) {
  const content = document.getElementById("ai-status-content");
  if (!content) return;

  const entry = document.createElement("div");
  entry.style.marginBottom = "8px";
  entry.style.lineHeight = "1.4";

  const typeColors = {
    step: "#58a6ff",     // Blue for major steps
    info: "#8b949e",     // Gray for info
    detail: "#6e7681",   // Darker gray for details
    success: "#3fb950",  // Green for success
    warning: "#d29922",  // Yellow for warnings
    error: "#f85149",    // Red for errors
    complete: "#a371f7", // Purple for completion
  };

  const typeIcons = {
    step: "▸",
    info: "  •",
    detail: "    ◦",
    success: "✓",
    warning: "⚠",
    error: "✗",
    complete: "★",
  };

  const type = update.type || "info";
  const icon = typeIcons[type] || "•";
  const color = typeColors[type] || "#8b949e";

  entry.style.color = color;

  if (type === "step") {
    entry.style.fontWeight = "600";
    entry.style.marginTop = "12px";
  } else if (type === "detail") {
    entry.style.fontSize = "11px";
  }

  entry.textContent = `${icon} ${update.message}`;

  content.appendChild(entry);
  content.scrollTop = content.scrollHeight;
}

// ---------- Guided Modifications UI ----------

let currentModificationIndex = 0;
let currentModifications = [];
let onModificationComplete = null;

function showGuidedModifications(modifications, onComplete) {
  console.log("showGuidedModifications called with", modifications.length, "modifications");

  currentModifications = modifications;
  currentModificationIndex = 0;
  onModificationComplete = onComplete;

  if (modifications.length === 0) {
    addStatusEntry({ type: "warning", message: "No modifications to apply" });
    return;
  }

  // Ensure panel is visible and has correct display style
  const panel = createStatusPanel();
  panel.style.display = "flex";

  // Update panel header
  updatePanelHeader(`📋 Modifications (${modifications.length})`);

  // Show first modification
  showCurrentModification();

  console.log("Guided modifications panel should now be visible");
}

function updatePanelHeader(text) {
  const panel = statusPanel || createStatusPanel();
  const header = panel.querySelector("div > span");
  if (header) {
    header.textContent = text;
  }
}

function showCurrentModification() {
  console.log("showCurrentModification called, index:", currentModificationIndex);

  const content = document.getElementById("ai-status-content");
  if (!content) {
    console.error("Could not find ai-status-content element!");
    return;
  }

  const mod = currentModifications[currentModificationIndex];
  if (!mod) {
    console.error("No modification at index", currentModificationIndex);
    return;
  }

  console.log("Showing modification:", mod);

  const total = currentModifications.length;
  const current = currentModificationIndex + 1;

  content.innerHTML = "";

  // Progress indicator
  const progress = document.createElement("div");
  progress.style.marginBottom = "12px";
  progress.style.padding = "8px 10px";
  progress.style.background = "#16213e";
  progress.style.borderRadius = "8px";
  progress.style.display = "flex";
  progress.style.justifyContent = "space-between";
  progress.style.alignItems = "center";

  const progressText = document.createElement("span");
  progressText.textContent = `Modification ${current} of ${total}`;
  progressText.style.fontWeight = "600";
  progressText.style.color = "#58a6ff";

  const severityBadge = document.createElement("span");
  const severityColors = { low: "#3fb950", medium: "#d29922", high: "#f85149" };
  severityBadge.textContent = mod.severity.toUpperCase();
  severityBadge.style.fontSize = "10px";
  severityBadge.style.padding = "2px 6px";
  severityBadge.style.borderRadius = "4px";
  severityBadge.style.background = severityColors[mod.severity] || "#d29922";
  severityBadge.style.color = "#000";
  severityBadge.style.fontWeight = "600";

  progress.appendChild(progressText);
  progress.appendChild(severityBadge);
  content.appendChild(progress);

  // Target Component/Data Flow
  const targetBox = document.createElement("div");
  targetBox.style.marginBottom = "12px";
  targetBox.style.padding = "10px";
  targetBox.style.background = "#1a1a2e";
  targetBox.style.borderRadius = "8px";
  targetBox.style.borderLeft = "3px solid #58a6ff";

  const targetLabel = document.createElement("div");
  const isDataFlow = mod.target?.target_type === "data_flow";
  targetLabel.textContent = isDataFlow ? "🔀 Data Flow" : "🔧 Component";
  targetLabel.style.fontSize = "10px";
  targetLabel.style.color = "#8b949e";
  targetLabel.style.marginBottom = "4px";
  targetLabel.style.textTransform = "uppercase";
  targetLabel.style.letterSpacing = "0.5px";

  const targetName = document.createElement("div");
  targetName.textContent = mod.target?.name || "Unknown";
  targetName.style.fontWeight = "600";
  targetName.style.color = isDataFlow ? "#a371f7" : "#fff";

  targetBox.appendChild(targetLabel);
  targetBox.appendChild(targetName);
  content.appendChild(targetBox);

  // Modification Description
  const modBox = document.createElement("div");
  modBox.style.marginBottom = "12px";
  modBox.style.padding = "10px";
  modBox.style.background = "#1a1a2e";
  modBox.style.borderRadius = "8px";
  modBox.style.borderLeft = "3px solid #3fb950";

  const modLabel = document.createElement("div");
  modLabel.textContent = "✏️ Required Changes";
  modLabel.style.fontSize = "10px";
  modLabel.style.color = "#8b949e";
  modLabel.style.marginBottom = "6px";
  modLabel.style.textTransform = "uppercase";
  modLabel.style.letterSpacing = "0.5px";

  const modificationText = mod.modification || "";
  const modText = document.createElement("div");
  modText.style.fontSize = "11px";
  modText.style.lineHeight = "1.5";
  modText.style.color = "#e0e0e0";
  modText.style.whiteSpace = "pre-wrap";
  modText.style.maxHeight = "120px";
  modText.style.overflowY = "auto";
  // Show first 500 chars with ellipsis
  const displayText = modificationText.length > 500
    ? modificationText.substring(0, 500) + "..."
    : modificationText;
  modText.textContent = displayText;

  // Copy button
  const copyBtn = document.createElement("button");
  copyBtn.textContent = "📋 Copy to Clipboard";
  copyBtn.style.marginTop = "8px";
  copyBtn.style.padding = "6px 10px";
  copyBtn.style.fontSize = "11px";
  copyBtn.style.borderRadius = "6px";
  copyBtn.style.border = "1px solid #3fb950";
  copyBtn.style.background = "transparent";
  copyBtn.style.color = "#3fb950";
  copyBtn.style.cursor = "pointer";
  copyBtn.onclick = async () => {
    try {
      await navigator.clipboard.writeText(modificationText);
      copyBtn.textContent = "✓ Copied!";
      copyBtn.style.background = "#3fb950";
      copyBtn.style.color = "#000";
      setTimeout(() => {
        copyBtn.textContent = "📋 Copy to Clipboard";
        copyBtn.style.background = "transparent";
        copyBtn.style.color = "#3fb950";
      }, 2000);
    } catch (e) {
      copyBtn.textContent = "Copy failed";
    }
  };

  modBox.appendChild(modLabel);
  modBox.appendChild(modText);
  modBox.appendChild(copyBtn);
  content.appendChild(modBox);

  // Issue Reference
  const issueBox = document.createElement("div");
  issueBox.style.marginBottom = "12px";
  issueBox.style.padding = "10px";
  issueBox.style.background = "#1a1a2e";
  issueBox.style.borderRadius = "8px";
  issueBox.style.borderLeft = "3px solid #d29922";

  const issueLabel = document.createElement("div");
  issueLabel.textContent = "📌 Addresses Issue";
  issueLabel.style.fontSize = "10px";
  issueLabel.style.color = "#8b949e";
  issueLabel.style.marginBottom = "4px";
  issueLabel.style.textTransform = "uppercase";
  issueLabel.style.letterSpacing = "0.5px";

  const issueText = document.createElement("div");
  issueText.style.fontSize = "11px";
  issueText.style.color = "#d29922";
  issueText.style.fontStyle = "italic";
  issueText.style.lineHeight = "1.4";
  // Show first 200 chars
  const issuePreview = mod.issue_reference.length > 200
    ? mod.issue_reference.substring(0, 200) + "..."
    : mod.issue_reference;
  issueText.textContent = `"${issuePreview}"`;

  issueBox.appendChild(issueLabel);
  issueBox.appendChild(issueText);
  content.appendChild(issueBox);

  // Navigation buttons
  const navRow = document.createElement("div");
  navRow.style.display = "flex";
  navRow.style.gap = "8px";
  navRow.style.marginTop = "8px";

  if (currentModificationIndex > 0) {
    const prevBtn = document.createElement("button");
    prevBtn.textContent = "← Previous";
    prevBtn.style.flex = "1";
    prevBtn.style.padding = "10px";
    prevBtn.style.borderRadius = "8px";
    prevBtn.style.border = "1px solid #444";
    prevBtn.style.background = "transparent";
    prevBtn.style.color = "#e0e0e0";
    prevBtn.style.cursor = "pointer";
    prevBtn.style.fontSize = "12px";
    prevBtn.onclick = () => {
      currentModificationIndex--;
      showCurrentModification();
    };
    navRow.appendChild(prevBtn);
  }

  const nextBtn = document.createElement("button");
  const isLast = currentModificationIndex >= total - 1;
  nextBtn.textContent = isLast ? "✓ Done" : "Next →";
  nextBtn.style.flex = "1";
  nextBtn.style.padding = "10px";
  nextBtn.style.borderRadius = "8px";
  nextBtn.style.border = "none";
  nextBtn.style.background = isLast ? "#3fb950" : "#58a6ff";
  nextBtn.style.color = "#000";
  nextBtn.style.cursor = "pointer";
  nextBtn.style.fontWeight = "600";
  nextBtn.style.fontSize = "12px";
  nextBtn.onclick = () => {
    if (isLast) {
      // All done
      if (onModificationComplete) {
        onModificationComplete();
      }
    } else {
      currentModificationIndex++;
      showCurrentModification();
    }
  };
  navRow.appendChild(nextBtn);

  content.appendChild(navRow);
}

function generateSessionId() {
  return "session-" + Math.random().toString(36).substring(2, 15);
}

function connectStatusStream(sessionId) {
  disconnectStatusStream();

  currentSessionId = sessionId;
  const url = `${BACKEND_URL}/status/${sessionId}`;

  console.log("Connecting to status stream:", url);

  statusEventSource = new EventSource(url);

  statusEventSource.onmessage = (event) => {
    try {
      const data = JSON.parse(event.data);
      if (data.type === "done" || data.type === "timeout") {
        disconnectStatusStream();
      } else {
        addStatusEntry(data);
      }
    } catch (e) {
      console.warn("Failed to parse status event:", e);
    }
  };

  statusEventSource.onerror = (e) => {
    console.warn("Status stream error:", e);
    disconnectStatusStream();
  };
}

function disconnectStatusStream() {
  if (statusEventSource) {
    statusEventSource.close();
    statusEventSource = null;
  }
  currentSessionId = null;
}

// Modified backend call functions that include session ID
async function callBackendReviewWithStatus({ selection, mode, docTitle, docText, googleDocId, sessionId }) {
  console.log("Calling backend review POST with session:", sessionId);
  const res = await fetch(`${BACKEND_URL}/review`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      "X-API-Key": API_KEY,
    },
    body: JSON.stringify({
      selection,
      mode,
      doc_title: docTitle,
      doc_text: docText,
      google_doc_id: googleDocId,
      session_id: sessionId,
    }),
  });

  if (!res.ok) {
    const err = await res.text();
    throw new Error(err);
  }

  return await res.json();
}

// ---------- UI injection ----------
function injectFloatingButtons() {
  if (document.getElementById("ai-review-wrap")) return;

  const wrap = document.createElement("div");
  wrap.id = "ai-review-wrap";
  wrap.style.position = "fixed";
  wrap.style.bottom = "20px";
  wrap.style.right = "20px";
  wrap.style.zIndex = "999999";
  wrap.style.display = "flex";
  wrap.style.gap = "8px";

  const baseBtnStyle = (btn) => {
    btn.style.padding = "10px 12px";
    btn.style.borderRadius = "12px";
    btn.style.border = "1px solid #ddd";
    btn.style.background = "white";
    btn.style.cursor = "pointer";
    btn.style.boxShadow = "0 2px 12px rgba(0,0,0,0.15)";
    btn.style.fontSize = "13px";
  };

  // Privacy Review button (copy-first + fallback paste box)
  const reviewBtn = document.createElement("button");
  reviewBtn.id = "ai-review-btn";
  reviewBtn.textContent = "🤖 Privacy Review";
  baseBtnStyle(reviewBtn);

  // Apply Suggestions button (hidden until a review is run)
  const applyBtn = document.createElement("button");
  applyBtn.id = "ai-apply-btn";
  applyBtn.textContent = "✏️ Apply Suggestions";
  baseBtnStyle(applyBtn);
  applyBtn.style.display = "none"; // hidden until review completes
  applyBtn.style.background = "#e8f5e9";
  applyBtn.style.border = "1px solid #81c784";

  reviewBtn.onclick = async () => {
    try {
      reviewBtn.textContent = "Running...";

      let selection = (await getSelectedTextViaClipboard()).trim();
      if (selection.length < 30) {
        selection = await showPasteBox({
          title: "🤖 Privacy Review Selection",
          placeholder: "Paste the selected text here (>= ~30 chars)...",
        });
      }

      if (!selection || selection.length < 30) {
        alert("Selection too short. Paste a larger section and try again.");
        reviewBtn.textContent = "🤖 Privacy Review";
        return;
      }

      // Show status panel and connect to stream
      const sessionId = generateSessionId();
      showStatusPanel();
      connectStatusStream(sessionId);
      addStatusEntry({ type: "step", message: "Starting privacy review..." });

      const docId = getDocIdFromUrl();
      let docTitle = getDocTitleBestEffort();

      // Fetch full document via MCP for complete architectural context
      reviewBtn.textContent = "Fetching doc...";
      addStatusEntry({ type: "info", message: "Fetching document content..." });
      let fullDocText = "";
      try {
        const docData = await callMcpGetDoc({ docId });
        fullDocText = docData.content || "";
        docTitle = docData.title || docTitle;
        addStatusEntry({ type: "info", message: `Fetched ${docData.contentLength} characters` });
      } catch (mcpErr) {
        console.warn("Failed to fetch full doc via MCP:", mcpErr);
        addStatusEntry({ type: "warning", message: "Could not fetch full doc, using selection only" });
      }

      reviewBtn.textContent = "Analyzing...";
      addStatusEntry({ type: "step", message: "Sending to AI reviewer..." });

      const review = await callBackendReviewWithStatus({
        selection,
        mode: "privacy",
        docTitle,
        docText: fullDocText,
        googleDocId: docId,
        sessionId,
      });

      console.log("Inline comments:", review.inline_comments);

      // Hide status panel after a short delay
      setTimeout(() => hideStatusPanel(), 2000);

      const posted = await postSingleAnchoredCommentPrivacy(
        review.inline_comments || []
      );

      // Store results for "Apply Suggestions"
      const commentsWithSuggestions = (review.inline_comments || []).filter(
        (c) => c.comment
      );
      if (commentsWithSuggestions.length > 0) {
        lastReviewComments = commentsWithSuggestions;
        lastReviewSelection = selection;
        lastParsedComponents = review.parsed_components || null;
        lastParsedDataFlows = review.parsed_data_flows || null;
        console.log("Stored pre-parsed structure:", {
          components: lastParsedComponents?.length || 0,
          dataFlows: lastParsedDataFlows?.length || 0,
        });
        applyBtn.style.display = "inline-block";
      }

      alert(`✅ Posted ${posted} comment thread(s)`);
    } catch (e) {
      addStatusEntry({ type: "error", message: `Error: ${e.message || e}` });
      setTimeout(() => hideStatusPanel(), 3000);
      alert("Error: " + e);
    } finally {
      reviewBtn.textContent = "🤖 Privacy Review";
    }
  };

  applyBtn.onclick = async () => {
    if (!lastReviewComments || !lastReviewSelection) {
      alert("No review suggestions available. Run a Privacy Review first.");
      return;
    }

    // Check we have parsed components or data flows
    if (!lastParsedComponents && !lastParsedDataFlows) {
      alert("No components or data flows found from the review. Run a Privacy Review on a document with technical components.");
      return;
    }

    // Show status panel and connect to stream
    const sessionId = generateSessionId();
    showStatusPanel();
    connectStatusStream(sessionId);
    addStatusEntry({ type: "step", message: "Generating modification suggestions..." });

    try {
      applyBtn.textContent = "Analyzing...";

      // Format comments for the endpoint (include related_components for filtering)
      const commentsPayload = lastReviewComments.map((c) => ({
        target_quote: c.target_quote,
        comment: c.comment,
        severity: c.severity || "medium",
        related_components: c.related_components || [],
      }));

      addStatusEntry({
        type: "info",
        message: `Analyzing ${commentsPayload.length} compliance issues against ${(lastParsedComponents || []).length} components`
      });

      console.log("Calling generate-modifications...");
      console.log("  - Comments:", commentsPayload.length);
      console.log("  - Components:", (lastParsedComponents || []).length);
      console.log("  - Data flows:", (lastParsedDataFlows || []).length);

      const result = await callGenerateModifications({
        reviewComments: commentsPayload,
        parsedComponents: lastParsedComponents || [],
        parsedDataFlows: lastParsedDataFlows || [],
        sessionId,
      });

      if (result.error) {
        addStatusEntry({ type: "error", message: `Error: ${result.error}` });
        setTimeout(() => hideStatusPanel(), 3000);
        alert("Error generating modifications: " + result.error);
        applyBtn.textContent = "✏️ Apply Suggestions";
        return;
      }

      console.log("Modification result:", result);
      console.log("  - Modifications:", result.modifications?.length);

      const modifications = result.modifications || [];
      console.log("Modifications from generator:", modifications);
      console.log("Number of modifications:", modifications.length);

      if (modifications.length === 0) {
        addStatusEntry({ type: "complete", message: "No modifications needed" });
        setTimeout(() => hideStatusPanel(), 2000);
        alert(
          `✅ Analysis complete.\n\n` +
          `No specific modifications were generated. ` +
          `The document may already address the compliance issues, or the issues may require manual review.`
        );
        applyBtn.textContent = "✏️ Apply Suggestions";
        return;
      }

      addStatusEntry({ type: "success", message: `Generated ${modifications.length} modifications` });

      // Show guided modifications in the status panel
      showGuidedModifications(modifications, () => {
        // Called when user clicks "Done" on last modification
        addStatusEntry({ type: "complete", message: "All modifications reviewed!" });

        // Clear stored review
        lastReviewComments = null;
        lastReviewSelection = null;
        lastParsedComponents = null;
        lastParsedDataFlows = null;
        applyBtn.style.display = "none";

        setTimeout(() => {
          hideStatusPanel();
          alert(
            `✅ Reviewed ${modifications.length} modification(s).\n\n` +
            `Update the relevant components/data flows in your design document based on these suggestions.`
          );
        }, 1500);
      });

      applyBtn.textContent = "✏️ Apply Suggestions";
    } catch (e) {
      addStatusEntry({ type: "error", message: `Error: ${e.message || e}` });
      setTimeout(() => hideStatusPanel(), 3000);
      alert("Error applying suggestions: " + e);
    } finally {
      applyBtn.textContent = "✏️ Apply Suggestions";
    }
  };

  wrap.appendChild(reviewBtn);
  wrap.appendChild(applyBtn);
  document.body.appendChild(wrap);
}

// auto-inject
injectFloatingButtons();
