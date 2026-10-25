/* HealthTracker v5 — app_v5.js */
"use strict";

// ─── Chart defaults ──────────────────────────────────────────
if (typeof Chart !== "undefined") {
  Chart.defaults.color = "#a8a094";
  Chart.defaults.borderColor = "rgba(242,236,224,0.08)";
  Chart.defaults.font.family = "'Outfit', sans-serif";
  Chart.defaults.font.size = 11;
}

// ─── Helpers ─────────────────────────────────────────────────
function toggleExpand(btn) {
  const body = btn.nextElementSibling;
  if (!body) return;
  body.classList.toggle("open");
  const arrow = btn.querySelector("svg");
  if (arrow) arrow.style.transform = body.classList.contains("open") ? "rotate(180deg)" : "";
}

function animateProgressBars() {
  document.querySelectorAll(".prog-fill[data-target], .risk-gauge-fill[data-target]").forEach(el => {
    const target = parseFloat(el.getAttribute("data-target")) || 0;
    setTimeout(() => { el.style.width = Math.min(100, Math.max(0, target)) + "%"; }, 120);
  });
}

// ─── Toast auto-dismiss ───────────────────────────────────────
function initToasts() {
  document.querySelectorAll(".toast").forEach(t => {
    setTimeout(() => { t.style.opacity = "0"; t.style.transition = "opacity 0.4s"; setTimeout(() => t.remove(), 400); }, 4000);
  });
}

// ─── Mobile nav ───────────────────────────────────────────────
function initNav() {
  const btn = document.getElementById("navToggle");
  const nav = document.querySelector(".nav");
  if (btn && nav) {
    btn.addEventListener("click", () => nav.classList.toggle("open"));
  }
}

// ─── File drop zone ───────────────────────────────────────────
function updateDropLabel(input) {
  const lbl = document.getElementById("dropLabel");
  if (lbl && input.files[0]) lbl.textContent = "📄 " + input.files[0].name;
}

function initDropZone() {
  const zone = document.getElementById("dropZone");
  const fileInput = document.getElementById("csvFile");
  if (!zone || !fileInput) return;
  zone.addEventListener("dragover", e => { e.preventDefault(); zone.style.borderColor = "var(--teal)"; });
  zone.addEventListener("dragleave", () => { zone.style.borderColor = ""; });
  zone.addEventListener("drop", e => {
    e.preventDefault(); zone.style.borderColor = "";
    const file = e.dataTransfer.files[0];
    if (file) { const dt = new DataTransfer(); dt.items.add(file); fileInput.files = dt.files; updateDropLabel(fileInput); }
  });
}

// ─── Watch sync ───────────────────────────────────────────────
function initSyncBtn() {
  const btn = document.getElementById("syncBtn");
  if (!btn) return;
  btn.addEventListener("click", async () => {
    btn.disabled = true;
    const orig = btn.innerHTML;
    btn.innerHTML = `<svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" style="animation:spin 1s linear infinite"><polyline points="23 4 23 10 17 10"/><polyline points="1 20 1 14 7 14"/><path d="M3.51 9a9 9 0 0 1 14.85-3.36L23 10M1 14l4.64 4.36A9 9 0 0 0 20.49 15"/></svg> Syncing…`;

    try {
      const res = await fetch("/api/sync_watch");
      const data = await res.json();
      if (data.ok) {
        showToast(`Synced: ${data.synced.steps ? data.synced.steps.toLocaleString() + ' steps' : ''} ${data.synced.sleep ? data.synced.sleep + 'h sleep' : ''}`, "success");
        setTimeout(() => location.reload(), 1200);
      } else {
        showToast(data.error || data.note || "No data synced.", "error");
      }
    } catch (e) {
      showToast("Sync request failed. Check your connection.", "error");
    } finally {
      btn.disabled = false;
      btn.innerHTML = orig;
    }
  });
}

function showToast(msg, type = "info") {
  let stack = document.getElementById("toastStack");
  if (!stack) {
    stack = document.createElement("div");
    stack.id = "toastStack";
    stack.className = "toast-stack";
    document.body.appendChild(stack);
  }
  const t = document.createElement("div");
  t.className = `toast toast-${type}`;
  t.innerHTML = `<span>${msg}</span><button class="toast-close" onclick="this.parentElement.remove()">×</button>`;
  stack.appendChild(t);
  setTimeout(() => { t.style.opacity = "0"; t.style.transition = "opacity 0.4s"; setTimeout(() => t.remove(), 400); }, 4000);
}

// Add CSS spin animation
const spinStyle = document.createElement("style");
spinStyle.textContent = "@keyframes spin { from { transform: rotate(0deg); } to { transform: rotate(360deg); } }";
document.head.appendChild(spinStyle);

// ─── Dashboard charts ─────────────────────────────────────────
function makeChartOptions(yLabel, y2Label) {
  return {
    responsive: true,
    maintainAspectRatio: false,
    interaction: { mode: "index", intersect: false },
    plugins: {
      legend: { position: "top", labels: { usePointStyle: true, pointStyleWidth: 10, padding: 16 } },
      tooltip: {
        backgroundColor: "rgba(12,18,32,0.95)",
        borderColor: "rgba(255,255,255,0.08)",
        borderWidth: 1,
        padding: 12,
        titleFont: { family: "'IBM Plex Mono', monospace", size: 11 },
        bodyFont: { family: "'DM Sans', sans-serif", size: 13 },
      }
    },
    scales: {
      x: { grid: { color: "rgba(255,255,255,0.03)" }, ticks: { maxTicksLimit: 8 } },
      y: { beginAtZero: true, grid: { color: "rgba(255,255,255,0.04)" }, title: { display: !!yLabel, text: yLabel } },
      ...(y2Label ? { y2: { position: "right", grid: { display: false }, title: { display: true, text: y2Label }, beginAtZero: true } } : {})
    }
  };
}

function initDashboardCharts() {
  if (typeof CHART_DATA === "undefined") return;

  const labels = CHART_DATA.dates || [];
  if (!labels.length) return;

  // Main chart: sleep + steps
  const mainCtx = document.getElementById("mainChart");
  if (mainCtx) {
    new Chart(mainCtx, {
      type: "line",
      data: {
        labels,
        datasets: [
          {
            label: "Sleep (hrs)", data: CHART_DATA.sleep,
            borderColor: "#8fa3b0", backgroundColor: "rgba(143,163,176,0.08)",
            tension: 0.35, pointRadius: 2.5, pointHoverRadius: 5, yAxisID: "y"
          },
          {
            label: "Steps", data: CHART_DATA.steps,
            borderColor: "#d4b896", backgroundColor: "rgba(212,184,150,0.08)",
            tension: 0.35, pointRadius: 2.5, pointHoverRadius: 5, yAxisID: "y2"
          },
          {
            label: "Active min", data: CHART_DATA.active,
            borderColor: "#8fad8a", backgroundColor: "rgba(143,173,138,0.08)",
            tension: 0.35, pointRadius: 2.5, pointHoverRadius: 5, yAxisID: "y"
          }
        ]
      },
      options: makeChartOptions("hrs / min", "steps")
    });
  }

  // Stress chart
  const stressCtx = document.getElementById("stressChart");
  if (stressCtx) {
    new Chart(stressCtx, {
      type: "bar",
      data: {
        labels,
        datasets: [{
          label: "Stress level",
          data: CHART_DATA.stress,
          backgroundColor: CHART_DATA.stress.map(v =>
            v === null ? "transparent" : v >= 7 ? "rgba(192,112,112,0.55)" : v >= 5 ? "rgba(196,138,90,0.5)" : "rgba(143,173,138,0.5)"
          ),
          borderRadius: 2
        }]
      },
      options: { ...makeChartOptions("0–10"), scales: { ...makeChartOptions("0–10").scales, y: { min: 0, max: 10, grid: { color: "rgba(242,236,224,0.05)" } } } }
    });
  }

  // Chart toggle
  document.querySelectorAll(".chart-toggle-btn").forEach(btn => {
    btn.addEventListener("click", () => {
      document.querySelectorAll(".chart-toggle-btn").forEach(b => b.classList.remove("active"));
      btn.classList.add("active");
      const which = btn.getAttribute("data-chart");
      const mainWrap = document.getElementById("mainChart")?.parentElement;
      const stressWrap = document.getElementById("stressChartWrap");
      if (mainWrap) mainWrap.style.display  = which === "main"   ? "block" : "none";
      if (stressWrap) stressWrap.style.display = which === "stress" ? "block" : "none";
    });
  });
}

// ─── Lab page charts ──────────────────────────────────────────
function initLabCharts() {
  if (typeof LAB_TIMELINE === "undefined") return;
  const { dates, total_cholesterol, ldl_cholesterol, hdl_cholesterol, fasting_glucose, hba1c, hs_crp } = LAB_TIMELINE;
  if (!dates || dates.length < 2) return;

  const cholCtx = document.getElementById("cholChart");
  if (cholCtx) {
    new Chart(cholCtx, {
      type: "line",
      data: {
        labels: dates,
        datasets: [
          { label: "Total", data: total_cholesterol, borderColor: "#c9a05a", backgroundColor: "rgba(201,160,90,0.08)", tension: 0.35, pointRadius: 3 },
          { label: "LDL",   data: ldl_cholesterol,   borderColor: "#c07070", backgroundColor: "rgba(192,112,112,0.08)", tension: 0.35, pointRadius: 3 },
          { label: "HDL",   data: hdl_cholesterol,   borderColor: "#8fad8a", backgroundColor: "rgba(143,173,138,0.08)", tension: 0.35, pointRadius: 3 },
        ]
      },
      options: makeChartOptions("mg/dL")
    });
  }

  const glucCtx = document.getElementById("glucChart");
  if (glucCtx) {
    new Chart(glucCtx, {
      type: "line",
      data: {
        labels: dates,
        datasets: [
          { label: "Fasting glucose", data: fasting_glucose, borderColor: "#d4b896", backgroundColor: "rgba(212,184,150,0.08)", tension: 0.35, pointRadius: 3, yAxisID: "y" },
          { label: "HbA1c %",         data: hba1c,            borderColor: "#8fa3b0", backgroundColor: "rgba(143,163,176,0.08)", tension: 0.35, pointRadius: 3, yAxisID: "y2" },
        ]
      },
      options: makeChartOptions("mg/dL", "%")
    });
  }

  const crpHasData = hs_crp && hs_crp.some(v => v !== null);
  const crpCtx = document.getElementById("crpChart");
  if (crpCtx && crpHasData) {
    new Chart(crpCtx, {
      type: "line",
      data: {
        labels: dates,
        datasets: [{ label: "hs-CRP", data: hs_crp, borderColor: "#f43f5e", backgroundColor: "rgba(244,63,94,0.06)", tension: 0.35, pointRadius: 3, fill: true }]
      },
      options: makeChartOptions("mg/L")
    });
  }
}

// ─── Profile BMI live calc ────────────────────────────────────
function initBmiCalc() {
  const h = document.querySelector("[name=height]");
  const w = document.querySelector("[name=weight]");
  if (!h || !w) return;
  function update() {
    const hv = parseFloat(h.value); const wv = parseFloat(w.value);
    if (hv > 0 && wv > 0) {
      const bmi = (wv / ((hv/100)**2)).toFixed(1);
      let existing = document.getElementById("liveBmi");
      if (!existing) {
        existing = document.createElement("div");
        existing.id = "liveBmi";
        existing.style.cssText = "font-size:12px;color:var(--text-2);margin-top:4px;font-family:var(--font-mono,monospace);";
        w.parentElement.appendChild(existing);
      }
      const cat = bmi < 18.5 ? "Underweight" : bmi < 25 ? "Normal" : bmi < 30 ? "Overweight" : "Obese";
      const col = bmi < 18.5 || bmi >= 30 ? "var(--orange)" : bmi < 25 ? "var(--green)" : "var(--yellow)";
      existing.innerHTML = `BMI: <span style="color:${col};font-weight:600;">${bmi}</span> — ${cat}`;
    }
  }
  h.addEventListener("input", update); w.addEventListener("input", update);
}

// ─── Stress slider colour ─────────────────────────────────────
function initStressInput() {
  const el = document.getElementById("stressInput");
  if (!el) return;
  el.addEventListener("input", () => {
    const v = parseFloat(el.value);
    el.style.borderColor = v >= 7 ? "var(--red)" : v >= 5 ? "var(--orange)" : "var(--green)";
  });
}

// ─── Gender identity ↔ equation sex sync ──────────────────────
function initSexSync() {
  const identity = document.querySelector("[data-sync-equation-sex]");
  const equation = document.getElementById("sex_for_equation");
  const note = document.getElementById("sexSyncNote");
  if (!identity || !equation) return;

  const MSG_MATCH =
    "Choosing Male or Female for gender identity fills equation sex to match. You can still override equation sex if needed.";
  const MSG_SEPARATE =
    "Gender identity and equation sex are separate here. PREVENT/PCE need a binary male/female coefficient — pick the category your clinician uses, or leave unset and we refuse a CVD number.";

  const sync = () => {
    const v = identity.value;
    if (v === "male" || v === "female") {
      equation.value = v;
      if (note) note.textContent = MSG_MATCH;
    } else if (note) {
      note.textContent = MSG_SEPARATE;
    }
  };
  identity.addEventListener("change", sync);
  sync();
}

function initRegionNote() {
  const sel = document.querySelector("[data-region-select]");
  const note = document.getElementById("regionNote");
  if (!sel || !note) return;
  const update = () => {
    const opt = sel.options[sel.selectedIndex];
    note.textContent = (opt && opt.getAttribute("data-note")) || "";
  };
  sel.addEventListener("change", update);
  update();
}

// ─── Init ─────────────────────────────────────────────────────
document.addEventListener("DOMContentLoaded", () => {
  animateProgressBars();
  initToasts();
  initNav();
  initDropZone();
  initSyncBtn();
  initDashboardCharts();
  initLabCharts();
  initBmiCalc();
  initStressInput();
  initSexSync();
  initRegionNote();
});
