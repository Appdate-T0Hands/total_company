let payload = null;
let currentTab = "bs";
let chart = null;
let chartItems = [];
let expandedKeys = new Set();
let autoExpandToken = "";

const COLORS = [
  "rgba(29, 78, 216, 0.9)",
  "rgba(220, 38, 38, 0.9)",
  "rgba(5, 150, 105, 0.9)",
  "rgba(234, 88, 12, 0.9)",
  "rgba(124, 58, 237, 0.9)",
  "rgba(8, 145, 178, 0.9)",
];

function fmt(n) {
  if (n === null || n === undefined) return "—";
  return Number(n).toLocaleString("ja-JP");
}

function fmtMonth(m) {
  const [y, mo] = m.split("-");
  return `${y}/${mo}`;
}

function fmtMonthShort(m) {
  const [y, mo] = m.split("-");
  return `${y.slice(2)}/${mo}`;
}

function itemKey(section, name) {
  return `${section}::${name}`;
}

function shouldAutoExpand(name) {
  return name.startsWith("その他");
}

function ensureAutoExpand(co, sections) {
  const token = `${co.company_id}:${currentTab}`;
  if (autoExpandToken === token) return;
  autoExpandToken = token;
  for (const section of sections) {
    for (const acct of section.accounts) {
      if (shouldAutoExpand(acct.name)) {
        expandedKeys.add(itemKey(section.name, acct.name));
      }
    }
  }
}

async function loadData() {
  const res = await fetch("data.json");
  payload = await res.json();

  const sel = document.getElementById("companySelect");
  sel.innerHTML = "";
  for (const c of payload.company_list) {
    const opt = document.createElement("option");
    opt.value = c.id;
    opt.textContent = c.name;
    sel.appendChild(opt);
  }
  if (payload.default_company_id) {
    sel.value = payload.default_company_id;
  }

  sel.addEventListener("change", () => {
    chartItems = [];
    expandedKeys = new Set();
    autoExpandToken = "";
    render();
  });
  document.getElementById("rangeSelect").addEventListener("change", render);
  document.getElementById("searchInput").addEventListener("input", render);
  document.getElementById("chartMode").addEventListener("change", updateChart);
  document.getElementById("clearChartBtn").addEventListener("click", () => {
    chartItems = [];
    render();
  });

  document.querySelectorAll(".tab").forEach((btn) => {
    btn.addEventListener("click", () => {
      document.querySelectorAll(".tab").forEach((b) => b.classList.remove("active"));
      btn.classList.add("active");
      currentTab = btn.dataset.tab;
      chartItems = [];
      expandedKeys = new Set();
      autoExpandToken = "";
      render();
    });
  });

  const params = new URLSearchParams(location.search);
  if (params.get("company")) sel.value = params.get("company");
  if (params.get("q")) document.getElementById("searchInput").value = params.get("q");
  render();
}

function visibleMonths(allMonths) {
  const range = document.getElementById("rangeSelect").value;
  if (range === "all") return allMonths;
  return allMonths.slice(-Number(range));
}

function getCompany() {
  const cid = document.getElementById("companySelect").value;
  return payload.companies.find((c) => c.company_id === cid);
}

function toggleChartItem(section, acct, co) {
  const key = itemKey(section.name, acct.name);
  const idx = chartItems.findIndex((x) => x.key === key);
  if (idx >= 0) {
    chartItems.splice(idx, 1);
  } else {
    const months = visibleMonths(co.months);
    const monthIndex = co.months.map((m, i) => ({ m, i })).filter(({ m }) => months.includes(m));
    const series = monthIndex.map(({ m, i }) => ({ m, v: acct.values[i] }));
    chartItems.push({
      key,
      label: `${section.name} — ${acct.name}`,
      series,
    });
  }
  renderSelection();
  updateChart();
  highlightSelectedRows();
}

function renderSelection() {
  const el = document.getElementById("chartSelection");
  if (!chartItems.length) {
    el.innerHTML = "";
    return;
  }
  el.innerHTML = chartItems
    .map(
      (item, i) =>
        `<span class="chip" style="border-color:${COLORS[i % COLORS.length]}">${item.label} <button type="button" data-key="${item.key}">×</button></span>`
    )
    .join("");
  el.querySelectorAll("button").forEach((btn) => {
    btn.addEventListener("click", () => {
      chartItems = chartItems.filter((x) => x.key !== btn.dataset.key);
      renderSelection();
      updateChart();
      highlightSelectedRows();
    });
  });
}

function highlightSelectedRows() {
  document.querySelectorAll("tr.account").forEach((tr) => {
    tr.classList.toggle("selected", chartItems.some((x) => x.key === tr.dataset.key));
  });
}

function buildTimelineDatasets() {
  return chartItems.map((item, i) => ({
    label: item.label,
    data: item.series.map(({ v }) => (v == null ? null : v)),
    borderColor: COLORS[i % COLORS.length],
    backgroundColor: COLORS[i % COLORS.length].replace("0.9", "0.15"),
    spanGaps: false,
    tension: 0.2,
    pointRadius: 2,
  }));
}

function buildYoYDatasets() {
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
      datasets.push({
        label: `${item.label} (${year}年)`,
        data: monthLabels.map((mo) => byYear[year][mo] ?? null),
        borderColor: color,
        backgroundColor: color.replace("0.9", "0.15"),
        spanGaps: false,
        tension: 0.2,
        pointRadius: 2,
      });
    }
  });
  return datasets;
}

function updateChart() {
  const mode = document.getElementById("chartMode").value;
  const titleEl = document.getElementById("chartTitle");

  if (!chartItems.length) {
    titleEl.textContent = "科目をクリックするとグラフに追加されます";
    if (chart) {
      chart.destroy();
      chart = null;
    }
    return;
  }

  titleEl.textContent =
    mode === "yoy"
      ? "同月比較 — 横軸は1月～12月、線は年度別"
      : "月次推移 — クリックした科目を重ね表示";

  const labels =
    mode === "yoy"
      ? ["1", "2", "3", "4", "5", "6", "7", "8", "9", "10", "11", "12"]
      : chartItems[0].series.map(({ m }) => fmtMonthShort(m));

  const datasets = mode === "yoy" ? buildYoYDatasets() : buildTimelineDatasets();

  if (chart) chart.destroy();
  chart = new Chart(document.getElementById("trendChart"), {
    type: "line",
    data: { labels, datasets },
    options: {
      maintainAspectRatio: false,
      plugins: {
        legend: { display: datasets.length > 1, labels: { boxWidth: 10, font: { size: 11 } } },
        tooltip: { callbacks: { label: (c) => `${c.dataset.label}: ${fmt(c.parsed.y)} 円` } },
      },
      layout: { padding: { left: 4, right: 4 } },
      scales: {
        y: { ticks: { callback: (v) => Number(v).toLocaleString("ja-JP"), font: { size: 9 }, maxTicksLimit: 5 } },
        x: {
          ticks: { font: { size: 9 }, maxRotation: 0, autoSkip: true, maxTicksLimit: 8 },
          grid: { display: false },
        },
      },
    },
  });
}

function valueCells(monthIndex, values) {
  return monthIndex
    .map(({ i }) => {
      const v = values[i];
      return v == null
        ? '<td class="num empty">—</td>'
        : `<td class="num">${fmt(v)}</td>`;
    })
    .join("");
}

function render() {
  const co = getCompany();
  if (!co) return;

  const sections = co[currentTab] || [];
  const months = visibleMonths(co.months);
  const search = document.getElementById("searchInput").value.trim().toLowerCase();
  const isConsolidated = co.display_type === "consolidated";
  const monthIndex = co.months.map((m, i) => ({ m, i })).filter(({ m }) => months.includes(m));

  let meta = `${co.company_name} — ${currentTab.toUpperCase()} — ${months.length}ヶ月（${fmtMonth(months[0])} ～ ${fmtMonth(months[months.length - 1])}）`;
  if (co.display_type === "consolidated") {
    meta += ` — ${co.member_names.join(" + ")} の合算`;
  }
  const prov = (co.provisional_months || []).filter((m) => months.includes(m));
  if (prov.length) {
    meta += ` — 未確定: ${prov.map(fmtMonth).join(", ")}`;
  }
  document.getElementById("metaInfo").textContent = meta;

  const table = document.createElement("table");
  const thead = document.createElement("thead");
  const hr = document.createElement("tr");
  hr.innerHTML =
    `<th class="sticky-col">科目</th>` +
    months
      .map((m) => {
        const cov = isConsolidated && co.month_coverage ? co.month_coverage[m] : null;
        const badges = [];
        if (cov != null && cov < co.members.length) {
          badges.push(`<span class="cov warn">${cov}/${co.members.length}社</span>`);
        } else if (cov != null) {
          badges.push(`<span class="cov">${cov}社</span>`);
        }
        if (co.provisional_months?.includes(m)) {
          badges.push(`<span class="cov prov">未確定</span>`);
        }
        const badge = badges.join("");
        return `<th>${fmtMonth(m)}${badge}</th>`;
      })
      .join("");
  thead.appendChild(hr);
  table.appendChild(thead);

  ensureAutoExpand(co, sections);

  const tbody = document.createElement("tbody");
  for (const section of sections) {
    const sr = document.createElement("tr");
    sr.className = "section";
    sr.innerHTML = `<td class="sticky-col" colspan="${months.length + 1}">${section.name}</td>`;
    tbody.appendChild(sr);

    for (const acct of section.accounts) {
      if (search && !acct.name.toLowerCase().includes(search)) continue;

      const key = itemKey(section.name, acct.name);
      const hasSub = acct.sub_breakdown?.length;
      const hasCo = isConsolidated && acct.breakdown?.length;
      const canExpand = hasSub || hasCo;
      const isExpanded = expandedKeys.has(key);

      const tr = document.createElement("tr");
      tr.className = "account" + (search ? " match" : "");
      tr.dataset.key = key;

      const toggleBtn = canExpand
        ? `<button type="button" class="expand-btn" aria-label="内訳を${isExpanded ? "閉じる" : "開く"}">${isExpanded ? "▼" : "▶"}</button>`
        : `<span class="expand-placeholder"></span>`;

      tr.innerHTML =
        `<td class="sticky-col account-label">${toggleBtn}<span>${acct.name}</span></td>` +
        valueCells(monthIndex, acct.values);

      if (canExpand) {
        const btn = tr.querySelector(".expand-btn");
        btn.addEventListener("click", (e) => {
          e.stopPropagation();
          if (expandedKeys.has(key)) expandedKeys.delete(key);
          else expandedKeys.add(key);
          render();
        });
      }

      tr.addEventListener("click", () => toggleChartItem(section, acct, co));
      tbody.appendChild(tr);

      if (canExpand && isExpanded) {
        if (hasSub) {
          for (const sub of acct.sub_breakdown) {
            const sr = document.createElement("tr");
            sr.className = "account-sub";
            sr.innerHTML =
              `<td class="sticky-col">▸ ${sub.name}</td>` +
              valueCells(monthIndex, sub.values);
            sr.addEventListener("click", (e) => {
              e.stopPropagation();
              toggleChartItem(
                section,
                { name: `${acct.name} › ${sub.name}`, values: sub.values },
                co
              );
            });
            tbody.appendChild(sr);
          }
        }
        if (hasCo) {
          for (const line of acct.breakdown) {
            const dr = document.createElement("tr");
            dr.className = "account-detail";
            dr.innerHTML =
              `<td class="sticky-col">└ ${line.company_name}</td>` +
              valueCells(monthIndex, line.values);
            dr.addEventListener("click", (e) => {
              e.stopPropagation();
              toggleChartItem(
                section,
                { name: `${acct.name}（${line.company_name}）`, values: line.values },
                co
              );
            });
            tbody.appendChild(dr);
          }
        }
      }
    }
  }

  table.appendChild(tbody);
  document.getElementById("tableContainer").innerHTML = "";
  document.getElementById("tableContainer").appendChild(table);

  chartItems = chartItems.map((item) => {
    for (const section of sections) {
      const acct = section.accounts.find((a) => itemKey(section.name, a.name) === item.key);
      if (acct) {
        const monthIndex = co.months.map((m, i) => ({ m, i })).filter(({ m }) => months.includes(m));
        return {
          ...item,
          series: monthIndex.map(({ m, i }) => ({ m, v: acct.values[i] })),
        };
      }
    }
    return item;
  });

  renderSelection();
  updateChart();
  highlightSelectedRows();
}

loadData().catch((err) => {
  document.body.innerHTML = `<pre style="padding:2rem;color:red">${err}</pre>`;
});
