(() => {
  document.querySelectorAll("[data-toggle]").forEach((b) => b.addEventListener("click", () =>
    document.getElementById(b.dataset.toggle)?.classList.toggle("open")));
  document.querySelectorAll("form[data-confirm]").forEach((f) => f.addEventListener("submit", (e) => {
    if (!window.confirm(f.dataset.confirm)) e.preventDefault();
  }));
  document.querySelectorAll('button[value="delete"][form^="img"]').forEach((b) => b.addEventListener("click", (e) => {
    if (!window.confirm("این تصویر حذف شود؟")) e.preventDefault();
  }));
  const up = document.getElementById("imgup");
  if (up) up.addEventListener("change", () => {
    document.getElementById("imgup-names").textContent = [...up.files].map((f) => f.name).join("، ") || "";
  });
})();
