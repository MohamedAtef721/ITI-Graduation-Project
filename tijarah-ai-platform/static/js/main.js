/* static/js/main.js — Global helpers */

// ── Theme (Dark / Light) ─────────────────────────────────────────────
const THEME_KEY = "si_theme";
const THEMES = ["dark", "light"]; // "dark" = default (:root), no extra class
let currentTheme = localStorage.getItem(THEME_KEY) || "dark";

function setTheme(theme) {
  if (!THEMES.includes(theme)) theme = "dark";
  currentTheme = theme;
  localStorage.setItem(THEME_KEY, theme);
  document.body.classList.toggle("theme-light", theme === "light");
  THEMES.forEach(t => document.getElementById(`btn-theme-${t}`)?.classList.toggle("active", t === theme));

  // Swap the logo to match: the cream/light-text logo reads fine on dark
  // backgrounds but disappears on the Light theme's pale background —
  // and vice versa for the dark-text logo.
  const logoImg = document.getElementById("brand-logo-img");
  if (logoImg) {
    const base = logoImg.src.slice(0, logoImg.src.lastIndexOf("/") + 1);
    logoImg.src = base + (theme === "light" ? "logo-full.png" : "logo-full-light.png");
  }
}

// ── Language ──────────────────────────────────────────────────────────
const LANG_KEY = "si_lang";
let currentLang = localStorage.getItem(LANG_KEY) || "en";

function setLang(lang) {
  currentLang = lang;
  localStorage.setItem(LANG_KEY, lang);
  document.body.classList.toggle("rtl", lang === "ar");
  document.querySelectorAll("[data-en]").forEach(el => {
    el.textContent = el.dataset[lang] || el.dataset.en;
  });
  document.getElementById("btn-en")?.classList.toggle("active", lang === "en");
  document.getElementById("btn-ar")?.classList.toggle("active", lang === "ar");
}

// Apply language + theme on load
document.addEventListener("DOMContentLoaded", () => {
  setLang(currentLang);
  setTheme(currentTheme);
  checkStatus();
});

// ── Connection Status ─────────────────────────────────────────────────
async function checkStatus() {
  try {
    const res  = await fetch("/api/status");
    const data = await res.json();
    const dot  = document.getElementById("conn-dot");
    const txt  = document.getElementById("conn-text");
    if (data.connected) {
      dot.className = "conn-dot ok";
      txt.textContent = "Connected";
    } else {
      dot.className = "conn-dot err";
      txt.textContent = "Not Connected";
    }
  } catch {
    document.getElementById("conn-text").textContent = "Offline";
  }
}

// ── Toast ─────────────────────────────────────────────────────────────
function showToast(msg, type = "success") {
  let container = document.getElementById("toast-container");
  if (!container) {
    container = document.createElement("div");
    container.id = "toast-container";
    container.className = "toast-container";
    document.body.appendChild(container);
  }
  const icons = { success: "✅", error: "❌", info: "ℹ️" };
  const toast = document.createElement("div");
  toast.className = `toast ${type}`;
  toast.innerHTML = `<span>${icons[type] || "ℹ️"}</span><span>${msg}</span>`;
  container.appendChild(toast);
  setTimeout(() => toast.remove(), 4000);
}

// ── Format numbers ────────────────────────────────────────────────────
function fmtNum(val, prefix = "", suffix = "") {
  if (val == null) return "N/A";
  const n = parseFloat(val);
  if (isNaN(n)) return "N/A";
  if (Math.abs(n) >= 1_000_000) return prefix + (n / 1_000_000).toFixed(1) + "M" + suffix;
  if (Math.abs(n) >= 1_000)     return prefix + (n / 1_000).toFixed(1)     + "K" + suffix;
  return prefix + n.toFixed(2) + suffix;
}

// ── Chart defaults ────────────────────────────────────────────────────
const CHART_COLORS = [
  "#4f8ef7","#8b5cf6","#10b981","#f59e0b",
  "#ef4444","#06b6d4","#ec4899","#84cc16",
];

// Charts (Chart.js) draw pixels to a canvas — they don't automatically
// follow CSS variable changes the way regular DOM elements do. Reading
// the variables HERE (at the moment each chart is created) means a
// chart built after switching themes will match; a chart already drawn
// before a theme switch won't restyle live, but every page in this app
// reloads its charts from scratch on navigation anyway, so this covers
// the common case without needing to track/rebuild every chart instance
// on every toggle click.
function themeVar(name) {
  return getComputedStyle(document.body).getPropertyValue(name).trim();
}

function chartDefaults() {
  const textMuted = themeVar("--text-muted") || "#64748b";
  const textSec   = themeVar("--text-2")      || "#94a3b8";
  const gridColor = themeVar("--border")      || "#1e2235";
  const cardBg    = themeVar("--bg-card")     || "#1e2235";
  const accent    = themeVar("--accent")      || "#4f8ef7";
  const textMain  = themeVar("--text-1")      || "#e2e8f0";

  return {
    responsive: true,
    maintainAspectRatio: false,
    plugins: {
      legend: { labels: { color: textSec, font: { family: "Inter", size: 12 } } },
      tooltip: {
        backgroundColor: cardBg,
        borderColor: accent,
        borderWidth: 1,
        titleColor: textMain,
        bodyColor: textSec,
      }
    },
    scales: {
      x: {
        ticks: { color: textMuted, font: { family: "Inter", size: 11 } },
        grid:  { color: gridColor },
      },
      y: {
        ticks: { color: textMuted, font: { family: "Inter", size: 11 }, callback: v => fmtNum(v) },
        grid:  { color: gridColor },
      }
    }
  };
}

function lineChart(ctx, labels, datasets) {
  return new Chart(ctx, {
    type: "line",
    data: {
      labels,
      datasets: datasets.map((d, i) => ({
        label: d.label,
        data: d.data,
        borderColor: CHART_COLORS[i],
        backgroundColor: CHART_COLORS[i] + "18",
        borderWidth: 2,
        pointRadius: 3,
        fill: i === 0,
        tension: 0.3,
        ...d,
      }))
    },
    options: chartDefaults()
  });
}

function barChart(ctx, labels, data, color = "#4f8ef7", horizontal = false) {
  // Axis-aware scales: the "value" axis (numbers) gets fmtNum formatting,
  // the "category" axis (labels) must NOT be run through fmtNum — doing
  // so on a horizontal bar chart turns product names into their raw
  // tick index (0.00, 1.00, 2.00...) because indexAxis:"y" makes Y the
  // category axis and X the value axis — the opposite of a vertical chart.
  const base = chartDefaults();
  const valueAxisTicks    = base.scales.y.ticks; // already has the fmtNum callback + theme colors
  const categoryAxisTicks = { color: base.scales.x.ticks.color, font: base.scales.x.ticks.font };
  const gridStyle         = base.scales.y.grid;

  const scales = horizontal
    ? {
        x: { ticks: valueAxisTicks,    grid: gridStyle },
        y: { ticks: categoryAxisTicks, grid: { display: false } },
      }
    : {
        x: { ticks: categoryAxisTicks, grid: { display: false } },
        y: { ticks: valueAxisTicks,    grid: gridStyle },
      };

  return new Chart(ctx, {
    type: "bar",
    data: {
      labels,
      datasets: [{
        data,
        backgroundColor: labels.map((_, i) => CHART_COLORS[i % CHART_COLORS.length] + "cc"),
        borderColor:      labels.map((_, i) => CHART_COLORS[i % CHART_COLORS.length]),
        borderWidth: 1,
        borderRadius: 6,
      }]
    },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      indexAxis: horizontal ? "y" : "x",
      plugins: {
        legend: { display: false },
        tooltip: base.plugins.tooltip,
      },
      scales,
    }
  });
}

function doughnutChart(ctx, labels, data) {
  const base = chartDefaults();
  return new Chart(ctx, {
    type: "doughnut",
    data: {
      labels,
      datasets: [{
        data,
        backgroundColor: CHART_COLORS.map(c => c + "cc"),
        borderColor: themeVar("--bg-primary") || "#0f1117",
        borderWidth: 2,
        hoverOffset: 6,
      }]
    },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      cutout: "58%",
      plugins: {
        legend: { position: "right", labels: base.plugins.legend.labels },
        tooltip: base.plugins.tooltip,
      }
    }
  });
}

// ── Build HTML table from array of objects ────────────────────────────
// Columns that should always be displayed as text (never formatted as numbers)
const TEXT_COLUMNS = ["name","product","customer","supplier","employee","category",
  "color","brand","method","type","period","month","quarter","continent",
  "city","state","country","description","label","status","group"];

function isTextColumn(colName) {
  const lower = colName.toLowerCase();
  return TEXT_COLUMNS.some(t => lower.includes(t));
}

function buildTable(rows, container) {
  if (!rows || !rows.length) {
    container.innerHTML = '<p style="color:#64748b;font-size:13px">No data available.</p>';
    return;
  }
  const keys = Object.keys(rows[0]);
  const ths  = keys.map(k => `<th>${k}</th>`).join("");
  const trs  = rows.map(r =>
    "<tr>" + keys.map(k => {
      const v = r[k];
      if (v === null || v === undefined) return `<td>—</td>`;
      // If column name suggests text, display as-is
      if (isTextColumn(k)) return `<td>${v}</td>`;
      // Otherwise try numeric formatting
      const n = parseFloat(v);
      return `<td>${(!isNaN(n) && isFinite(n)) ? fmtNum(n) : v}</td>`;
    }).join("") + "</tr>"
  ).join("");
  container.innerHTML = `<table class="data-table"><thead><tr>${ths}</tr></thead><tbody>${trs}</tbody></table>`;
}

// ── Loading helper ────────────────────────────────────────────────────
function showLoading(id, show) {
  const el = document.getElementById(id);
  if (el) el.classList.toggle("show", show);
}

// ── Page-data cache (survives navigation between pages, cleared when
//    the browser tab is closed) ─────────────────────────────────────
// Since this is a traditional multi-page Flask app (not an SPA), every
// navigation is a full page reload — all JS state and charts get torn
// down and rebuilt from scratch, which shows an empty/"—" flash while
// the API is re-fetched. cachedFetch() renders the last-known data for
// this page immediately (from sessionStorage), then fetches fresh data
// in the background and re-renders only if it's different — so the
// page looks instantly "already loaded" on every visit.
//
// Usage pattern (replace a plain `await fetch(url)` with this):
//   cachedFetch("home:kpis", "/api/kpis", renderKpis);
// `render(data)` is called once immediately with cached data (if any),
// and again once fresh data arrives.
async function cachedFetch(cacheKey, url, render) {
  const cached = sessionStorage.getItem(cacheKey);
  if (cached) {
    try { render(JSON.parse(cached)); } catch {}
  }
  try {
    const res  = await fetch(url);
    const data = await res.json();
    sessionStorage.setItem(cacheKey, JSON.stringify(data));
    render(data);
  } catch (e) {
    if (!cached) throw e; // only surface the error if we had nothing to show
  }
}