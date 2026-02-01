// =========================
// Phase 1 MVP: Privacy mode
// - Copy-first clipboard read (best effort)
// - Fallback modal paste box (reliable)
// - Optional "Set Context" per-doc (stored in chrome.storage.local)
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

function storageKeyForContext(docId) {
  return `ai_review_context::${docId || "unknown_doc"}`;
}

async function saveContextForDoc(docId, text) {
  const key = storageKeyForContext(docId);
  await chrome.storage.local.set({ [key]: text });
}

async function loadContextForDoc(docId) {
  const key = storageKeyForContext(docId);
  const data = await chrome.storage.local.get([key]);
  return data[key] || "";
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

// ---------- backend call ----------
async function callBackendReview({ selection, mode, docTitle, docText }) {
  const backendUrl = "http://localhost:8000/review"; // change when deployed
  const apiKey = "dev_secret_key_change_me"; // move to chrome.storage later

  console.log("Calling backend review POST...");
  const res = await fetch(backendUrl, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      "X-API-Key": apiKey,
    },
    body: JSON.stringify({
      selection,
      mode,
      doc_title: docTitle,
      doc_text: docText,
    }),
  });

  if (!res.ok) {
    const err = await res.text();
    throw new Error(err);
  }

  return await res.json();
}

// ---------- comment posting ----------
async function postSingleAnchoredCommentPrivacy(inlineComments) {
  if (!inlineComments || inlineComments.length === 0) return 0;

  let body = "🤖 AI Privacy Review\n";
  body += "----------------------------------\n";

  inlineComments.slice(0, 8).forEach((c, i) => {
    body += `\n${i + 1}) [PRIVACY | ${String(c.severity || "medium").toUpperCase()}]\n`;
    body += `${c.comment}\n`;
    if (c.rewrite_suggestion) {
      body += `Suggested rewrite: ${c.rewrite_suggestion}\n`;
    }
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

  // Button 1: Set context (copy-first + fallback paste box)
  const setCtxBtn = document.createElement("button");
  setCtxBtn.id = "ai-set-context-btn";
  setCtxBtn.textContent = "📌 Set AI Context";
  baseBtnStyle(setCtxBtn);

  setCtxBtn.onclick = async () => {
    try {
      setCtxBtn.textContent = "Saving...";

      const docId = getDocIdFromUrl();

      let ctxText = (await getSelectedTextViaClipboard()).trim();
      if (ctxText.length < 80) {
        ctxText = await showPasteBox({
          title: "📌 Set AI Context",
          placeholder:
            "Paste a doc overview / system context section here (>= ~80 chars).",
        });
      }

      if (!ctxText || ctxText.length < 80) {
        alert("Context too short. Paste a larger doc overview section.");
        setCtxBtn.textContent = "📌 Set AI Context";
        return;
      }

      await saveContextForDoc(docId, ctxText);
      alert("✅ Saved doc context for this document.");
    } catch (e) {
      alert("Error saving context: " + e);
    } finally {
      setCtxBtn.textContent = "📌 Set AI Context";
    }
  };

  // Button 2: Review selection (privacy mode) (copy-first + fallback paste box)
  const reviewBtn = document.createElement("button");
  reviewBtn.id = "ai-review-btn";
  reviewBtn.textContent = "🤖 Privacy Review";
  baseBtnStyle(reviewBtn);

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

      const docId = getDocIdFromUrl();
      const docTitle = getDocTitleBestEffort();

      // Load stored context if any (recommended)
      const storedContext = await loadContextForDoc(docId);

      // Phase 1 MVP: doc_text is optional. If missing, backend still runs privacy mode,
      // but context-aware framework selection will be weaker.
      const review = await callBackendReview({
        selection,
        mode: "privacy",
        docTitle,
        docText: storedContext || "",
      });

      console.log("Inline comments:", review.inline_comments);

      const posted = await postSingleAnchoredCommentPrivacy(
        review.inline_comments || []
      );

      alert(`✅ Posted ${posted} comment thread(s)`);
    } catch (e) {
      alert("Error: " + e);
    } finally {
      reviewBtn.textContent = "🤖 Privacy Review";
    }
  };

  wrap.appendChild(setCtxBtn);
  wrap.appendChild(reviewBtn);
  document.body.appendChild(wrap);
}

// auto-inject
injectFloatingButtons();
