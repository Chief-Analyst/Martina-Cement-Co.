// Enter sends a chat message; Shift+Enter adds a new line.
document.addEventListener("keydown", function (e) {
  if (e.key !== "Enter" || e.shiftKey || !e.target || e.target.id !== "ai-input") return;
  const btn = document.getElementById("ai-send");
  if (btn && !btn.disabled) {
    e.preventDefault();
    btn.click();
  }
});
