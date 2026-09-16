const CHART_STATE_KEY = "total_company_chart_state";

const COLORS = [
  "rgba(29, 78, 216, 0.85)",
  "rgba(220, 38, 38, 0.85)",
  "rgba(5, 150, 105, 0.85)",
  "rgba(234, 88, 12, 0.85)",
  "rgba(124, 58, 237, 0.85)",
  "rgba(8, 145, 178, 0.85)",
  "rgba(190, 24, 93, 0.85)",
  "rgba(101, 163, 13, 0.85)",
];

let chart = null;

function fmt(n) {
  if (n === null || n === undefined) return "—";
  return Number(n).toLocaleString("ja-JP");
}

function fmtMonthShort(m) {
  const [y, mo] = m.split("-");
  return `${y.slice(2)}/${mo}`;
}

function loadState() {
  try {
    return JSON.parse(localStorage.getItem(CHART_STATE_KEY) || "{}");
  } catch {
    return {};
  }
}

function saveState(state) {
  localStorage.setItem(
    CHART_STATE_KEY,
    JSON.stringify({ ...state, updatedAt: Date.now() })
  );
}

function styleDataset(base, chartType) {
  if (chartType === "line") {
    return {
      ...base,
      backgroundColor: base.borderColor.replace("1)", "0.12)"),
      fill: false,
      tension: 0.2,
      pointRadius: 3,
      pointHoverRadius: 5,
    };
  }
  return base;
}

function buildTimelineDatasets(chartItems, chartType) {
  return chartItems.map((item, i) => {
    const color = COLORS[i % COLORS.length];
    return styleDataset(
      {
        label: item.label,
        data: item.series.map(({ v }) => (v == null ? null : v)),
        backgroundColor: color,
        borderColor: color.replace("0.85", "1"),
        borderWidth: chartType === "line" ? 2 : 1,
        spanGaps: false,
      },
      chartType
    );
  });
}

function buildYoYDatasets(chartItems, chartType) {
  const monthLabels = ["01", "02", "03", "04", "05", "06", "07", "08", "09", "10", "11", "12"];
  const datasets = [];

  chartItems.forEach((item, itemIdx) => {
    const byYear = {};
    for (const { m, v } of item.series) {
      if (v == null) continue;
      const [y, mo] = m.split("-");
      if (!byYear[y]) byYear[y] = {};
      byYear[y][mo] = v;
    }
    for (const year of Object.keys(byYear).sort()) {
      const color = COLORS[(itemIdx + Object.keys(byYear).indexOf(year)) % COLORS.length];
      datasets.push(
        styleDataset(
          {
            label: `${item.label} (${year}年)`,
            data: monthLabels.map((mo) => byYear[year][mo] ?? null),
            backgroundColor: color,
            borderColor: color.replace("0.85", "1"),
            borderWidth: chartType === "line" ? 2 : 1,
            spanGaps: false,
          },
          chartType
        )
      );
    }
  });
  return datasets;
}

function chartEl(id) {
  return document.getElementById(id);
}

function renderSelection(chartItems) {
  const box = chartEl("chartSelection");
  if (!box) return;
  if (!chartItems.length) {
    box.innerHTML = "";
    return;
  }
  box.innerHTML = chartItems
    .map(
      (item, i) =>
        `<span class="chip" style="border-color:${COLORS[i % COLORS.length]}">${item.label}</span>`
    )
    .join("");
}

function renderChart() {
  const state = loadState();
  const chartItems = state.chartItems || [];
  const mode = state.chartMode || "timeline";
  const chartType = state.chartType || "bar";
  const titleEl = chartEl("chartTitle");
  const metaEl = chartEl("chartMeta");
  const modeSelect = chartEl("chartMode");
  const typeSelect = chartEl("chartType");
  if (modeSelect) modeSelect.value = mode;
  if (typeSelect) typeSelect.value = chartType;

  const tabLabel = state.tab ? state.tab.toUpperCase() : "";
  if (metaEl) {
    metaEl.textContent = [state.companyName, tabLabel].filter(Boolean).join(" — ");
  }

  renderSelection(chartItems);

  if (!chartItems.length) {
    if (titleEl) titleEl.textContent = "メイン画面で科目をクリックするとここに表示されます";
    if (chart) {
      chart.destroy();
      chart = null;
    }
    return;
  }

  const typeLabel = chartType === "line" ? "折れ線" : "棒";
  if (titleEl) {
    titleEl.textContent =
      mode === "yoy"
        ? `同月比較（${typeLabel}）— 横軸は1月～12月`
        : `月次推移（${typeLabel}）— クリックした科目を重ね表示`;
  }

  const labels =
    mode === "yoy"
      ? ["1", "2", "3", "4", "5", "6", "7", "8", "9", "10", "11", "12"]
      : chartItems[0].series.map(({ m }) => fmtMonthShort(m));

  const datasets =
    mode === "yoy"
      ? buildYoYDatasets(chartItems, chartType)
      : buildTimelineDatasets(chartItems, chartType);

  const canvas = chartEl("trendChart");
  if (!canvas) return;

  if (chart) chart.destroy();
  chart = new Chart(canvas, {
    type: chartType,
    data: { labels, datasets },
    options: {
      maintainAspectRatio: false,
      plugins: {
        legend: {
          display: datasets.length > 1,
          position: "top",
          align: "start",
          labels: { boxWidth: 12, font: { size: 11 }, padding: 8 },
        },
        tooltip: {
          callbacks: { label: (c) => `${c.dataset.label}: ${fmt(c.parsed.y)} 円` },
        },
      },
      layout: { padding: { left: 8, right: 8, top: 4 } },
      scales: {
        y: {
          ticks: {
            callback: (v) => Number(v).toLocaleString("ja-JP"),
            font: { size: 12 },
            maxTicksLimit: 8,
          },
          grid: { color: "rgba(0,0,0,0.06)" },
        },
        x: {
          ticks: { font: { size: 12 }, maxRotation: 45, minRotation: 0, autoSkip: true },
          grid: { display: false },
        },
      },
      datasets: {
        bar: {
          maxBarThickness: mode === "yoy" ? 28 : 36,
        },
      },
    },
  });
  requestAnimationFrame(() => chart?.resize());
}

function resizeChart() {
  chart?.resize();
}

function clearChart() {
  const state = loadState();
  saveState({ ...state, chartItems: [] });
  renderChart();
}

function initChartPage() {
  chartEl("chartMode")?.addEventListener("change", (e) => {
    const state = loadState();
    saveState({ ...state, chartMode: e.target.value });
    renderChart();
  });

  chartEl("chartType")?.addEventListener("change", (e) => {
    const state = loadState();
    saveState({ ...state, chartType: e.target.value });
    renderChart();
  });

  chartEl("clearChartBtn")?.addEventListener("click", clearChart);

  window.addEventListener("storage", (e) => {
    if (e.key === CHART_STATE_KEY) renderChart();
  });

  window.addEventListener("message", (e) => {
    if (e.origin === location.origin && e.data?.type === "chart-update") {
      renderChart();
    }
  });

  let resizeTimer = null;
  window.addEventListener("resize", () => {
    if (resizeTimer) clearTimeout(resizeTimer);
    resizeTimer = setTimeout(resizeChart, 80);
  });

  const state = loadState();
  if (!state.chartType) {
    saveState({ ...state, chartType: "bar", chartMode: state.chartMode || "timeline" });
  }

  renderChart();
}

if (document.readyState === "loading") {
  document.addEventListener("DOMContentLoaded", initChartPage);
} else {
  initChartPage();
}
