(() => {
  const $ = (s, r = document) => r.querySelector(s);
  const $$ = (s, r = document) => [...r.querySelectorAll(s)];

  // Header toggles (mobile menu, search)
  $$("[data-toggle]").forEach((btn) => {
    btn.addEventListener("click", () => {
      const target = document.getElementById(btn.dataset.toggle);
      if (!target) return;
      const open = target.classList.toggle("open");
      btn.setAttribute("aria-expanded", String(open));
      if (open) target.querySelector("input")?.focus();
    });
  });
  document.addEventListener("keydown", (e) => {
    if (e.key === "Escape") $$(".nav.open,.search-pop.open").forEach((el) => el.classList.remove("open"));
  });

  // Flash messages
  $$("[data-dismiss]").forEach((b) => b.addEventListener("click", () => b.closest(".flash").remove()));
  setTimeout(() => $$(".flash:not(.error)").forEach((f) => f.remove()), 6000);

  // Reveal on scroll
  const items = $$(".reveal");
  if ("IntersectionObserver" in window && !matchMedia("(prefers-reduced-motion: reduce)").matches) {
    const io = new IntersectionObserver((entries) => entries.forEach((en) => {
      if (en.isIntersecting) { en.target.classList.add("in"); io.unobserve(en.target); }
    }), { rootMargin: "0px 0px -40px 0px" });
    items.forEach((el, i) => { el.style.transitionDelay = `${(i % 5) * 60}ms`; io.observe(el); });
  } else items.forEach((el) => el.classList.add("in"));

  // Quantity steppers
  $$(".qty").forEach((q) => {
    const input = $("input", q);
    $$("button", q).forEach((b) => b.addEventListener("click", () => {
      const max = +input.max || 20, min = +input.min || 0;
      input.value = Math.min(max, Math.max(min, (+input.value || 0) + (+b.dataset.step)));
      input.dispatchEvent(new Event("change", { bubbles: true }));
    }));
  });
  $$("[data-autosubmit]").forEach((el) => el.addEventListener("change", () => el.form.requestSubmit()));

  // Product gallery
  const main = $(".pdp-main img");
  $$(".thumbs button").forEach((b) => b.addEventListener("click", () => {
    main.src = b.dataset.src; main.alt = b.dataset.alt || main.alt;
    $$(".thumbs button").forEach((x) => x.classList.toggle("on", x === b));
  }));

  // Copy buttons
  $$("[data-copy]").forEach((b) => b.addEventListener("click", async () => {
    const label = b.querySelector("span");
    try { await navigator.clipboard.writeText(b.dataset.copy); if (label) label.textContent = "کپی شد ✓"; }
    catch { if (label) label.textContent = b.dataset.copy; }
    setTimeout(() => { if (label) label.textContent = "کپی"; }, 2200);
  }));

  // Receipt preview
  const file = $("#receipt");
  if (file) file.addEventListener("change", () => {
    const f = file.files[0], prev = $("#receipt-preview");
    if (!f || !prev) return;
    prev.src = URL.createObjectURL(f); prev.hidden = false;
    $("#receipt-name").textContent = f.name;
  });

  // Confirm dangerous actions
  $$("form[data-confirm]").forEach((f) => f.addEventListener("submit", (e) => {
    if (!window.confirm(f.dataset.confirm)) e.preventDefault();
  }));
})();
