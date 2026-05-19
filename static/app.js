"use strict";

/* ================================================================
   CSRF token helper
   Reads the token from the <meta name="csrf-token"> tag injected
   by base.html so all fetch POST calls can include it as a header.
   ================================================================ */
function getCsrfToken() {
  return document.querySelector('meta[name="csrf-token"]')?.content || '';
}

/* ================================================================
   Typing indicator
   Shows / hides the three-dot bounce animation in the chat while
   waiting for an AI response.
   ================================================================ */
function showTypingIndicator() {
  const el = document.getElementById("typing-indicator");
  if (el) el.classList.add("visible");
  scrollChatToBottom();
}

function hideTypingIndicator() {
  const el = document.getElementById("typing-indicator");
  if (el) el.classList.remove("visible");
}

/* ================================================================
   Chat auto-scroll
   Scrolls the chat-wrap container to the bottom so the latest
   message is always visible.
   ================================================================ */
function scrollChatToBottom() {
  const wrap = document.getElementById("chat-wrap");
  if (wrap) wrap.scrollTop = wrap.scrollHeight;
}

/* ================================================================
   Modality selector
   Toggles the .selected class on modality cards and syncs the
   hidden input value used by the save handler.
   ================================================================ */
function selectModality(card) {
  document.querySelectorAll(".modality-card").forEach((c) =>
    c.classList.remove("selected")
  );
  card.classList.add("selected");
  const input = document.getElementById("selected-modality");
  if (input) input.value = card.dataset.modality;
}

/* ================================================================
   Assessment tab switcher
   Swaps active state on both the .tab buttons and .tab-panel
   divs without a page reload.
   ================================================================ */
function switchTab(name, el) {
  document.querySelectorAll(".tab").forEach((t) => t.classList.remove("active"));
  document.querySelectorAll(".tab-panel").forEach((p) =>
    p.classList.remove("active")
  );
  el.classList.add("active");
  const panel = document.getElementById("tab-" + name);
  if (panel) panel.classList.add("active");
}

/* ================================================================
   Reflection form submission
   Posts all three answers via fetch(), shows a success banner,
   and disables the submit button after a successful save so the
   student knows the form has been recorded.
   ================================================================ */
async function submitReflectionForm(postUrl) {
  const q1 = (document.getElementById("q1") || {}).value?.trim();
  const q2 = (document.getElementById("q2") || {}).value?.trim();
  const q3 = (document.getElementById("q3") || {}).value?.trim();
  const btn = document.getElementById("submit-btn");
  const errorEl = document.getElementById("reflection-error");
  const banner = document.getElementById("success-banner");

  if (!errorEl || !banner || !btn) return;

  errorEl.style.display = "none";
  banner.classList.remove("visible");

  if (!q1 || !q2 || !q3) {
    errorEl.textContent = "Please answer all three questions before submitting.";
    errorEl.style.display = "block";
    return;
  }

  btn.disabled = true;
  btn.textContent = "Saving…";

  try {
    const resp = await fetch(postUrl, {
      method: "POST",
      headers: { "Content-Type": "application/json", "X-CSRFToken": getCsrfToken() },
      body: JSON.stringify({ question_1: q1, question_2: q2, question_3: q3 }),
    });
    const data = await resp.json();

    if (!resp.ok) throw new Error(data.error || "Submission failed");

    banner.classList.add("visible");
    btn.textContent = "Update reflection";
    btn.disabled = false;
    banner.scrollIntoView({ behavior: "smooth", block: "nearest" });
  } catch (err) {
    errorEl.textContent = err.message;
    errorEl.style.display = "block";
    btn.disabled = false;
    btn.textContent = "Submit reflection";
  }
}

/* ================================================================
   Paste / cut restriction (students only)
   Blocks paste and cut on all student-facing text inputs and
   textareas. Instructors and dev accounts are unaffected because
   USER_ROLE will not equal 'student' for those roles.
   ================================================================ */
function showPasteRestrictionMessage(field) {
  // If the field lives inside a flex row (e.g. the chat input), insert the
  // message after the row rather than inside it.
  const anchor = field.closest(".chat-input-row") || field;

  // Remove any existing restriction message attached to this anchor.
  const existing = anchor.parentNode.querySelector(".paste-block-msg");
  if (existing) {
    clearTimeout(existing._hideTimer);
    existing.remove();
  }

  const msg = document.createElement("div");
  msg.className = "paste-block-msg";
  msg.textContent = "Please type your response in your own words.";
  msg.style.cssText =
    "font-size:12px;color:var(--text-tertiary);margin-top:4px;opacity:1;transition:opacity .3s;";
  anchor.insertAdjacentElement("afterend", msg);

  msg._hideTimer = setTimeout(() => {
    msg.style.opacity = "0";
    setTimeout(() => msg.remove(), 300);
  }, 2000);
}

function restrictPasteForStudents() {
  if (typeof USER_ROLE === "undefined" || USER_ROLE !== "student") return;

  // These fields on the login / registration page are always exempt.
  const EXEMPT_IDS = new Set([
    "code-input",
    "first-name",
    "last-initial",
    "ret-first-name",
    "ret-last-initial",
  ]);

  document
    .querySelectorAll('input[type="text"], textarea')
    .forEach((el) => {
      if (EXEMPT_IDS.has(el.id) || el.dataset.pasteRestricted) return;
      el.dataset.pasteRestricted = "1";
      ["paste", "cut"].forEach((type) => {
        el.addEventListener(type, (e) => {
          e.preventDefault();
          showPasteRestrictionMessage(el);
        });
      });
    });
}

/* ================================================================
   DOMContentLoaded init
   Auto-scrolls the chat on page load if a chat-wrap exists, and
   applies paste/cut restrictions for student accounts.
   ================================================================ */
document.addEventListener("DOMContentLoaded", () => {
  scrollChatToBottom();
  restrictPasteForStudents();
});
