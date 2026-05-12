"use strict";

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
      headers: { "Content-Type": "application/json" },
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
   DOMContentLoaded init
   Auto-scrolls the chat on page load if a chat-wrap exists.
   ================================================================ */
document.addEventListener("DOMContentLoaded", () => {
  scrollChatToBottom();
});
