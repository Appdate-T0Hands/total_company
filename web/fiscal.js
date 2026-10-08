/** 決算期（1 CSV = 1 期）ビュー */

/** ヘッダーに期別合計（内訳の足し算）を出す大項目 */
const SECTION_SUM_TOTALS = new Set([
  "売上高",
  "売上原価",
  "販売管理費",
  "営業外",
  "特別損益",
  "流動資産",
  "固定資産",
  "流動負債",
  "固定負債",
  "純資産",
]);

const SUMMARY_METRICS = [
  { section: "売上高", name: "売上高", tab: "pl" },
  { section: "損益サマリー", name: "営業損益", tab: "pl" },
  { section: "損益サマリー", name: "経常損益", tab: "pl" },
  { section: "損益サマリー", name: "当期純利益", tab: "pl" },
  { section: "流動資産", name: "現金及び預金", tab: "bs" },
  { section: "純資産", name: "純資産", tab: "bs" },
];

let payload = null;
let currentTab = "pl";
let summaryCharts = [];
let expandedKeys = new Set();

function fmt(n) {
  if (n === null || n === undefined) return "—";
  return Number(n).toLocaleString("ja-JP");
}

function periodHeader(p) {
  const end = p.end || p;
  const [y, m] = end.split("-");
  const short = `${y}/${m}期`;
  if (typeof p === "object" && p.provisional) {
    return `${short}<span class="cov prov">未確定</span>`;
  }
  return short;
}

function findAccount(sections, sectionName, acctName) {
  const sec = sections.find((s) => s.name === sectionName);
  if (!sec) return null;
  return sec.accounts.find((a) => a.name === acctName) || null;
}

function el(id) {
  return document.getElementById(id);
}

async function loadData() {
  const res = await fetch("data.json");
  payload = await res.json();
  el("pageTitle").textContent = `${payload.company_name} — 決算期推移`;
  document.title = payload.company_name + " — 決算期";

  document.querySelectorAll(".tab").forEach((btn) => {
    btn.addEventListener("click", () => {
      document.querySelectorAll(".tab").forEach((b) => b.classList.remove("active"));
      btn.classList.add("active");
      currentTab = btn.dataset.tab;
      render();
    });
  });

  render();
}

function destroySummaryCharts() {
  summaryCharts.forEach((c) => c.destroy());
  summaryCharts = [];
}

function renderSummaryCharts() {
  destroySummaryCharts();
  const wrap = el("summaryCharts");
  wrap.innerHTML = "";
  const periods = payload.periods || [];
  const labels = periods.map((p) => {
    const lbl = p.label || p.end;
    return lbl.replace(/年/g, "/").replace(/月/g, "").replace(/～/g, "–");
  });

  for (const metric of SUMMARY_METRICS) {
    if (metric.tab !== currentTab) continue;
    const acct = findAccount(payload[currentTab] || [], metric.section, metric.name);
    if (!acct) continue;
    const values = acct.values.map((v) => (v == null ? null : Number(v)));
    if (!values.some((v) => v !== null && v !== 0)) continue;

    const card = document.createElement("div");
    card.className = "summary-card";
    card.innerHTML = `<h3>${metric.name}</h3><canvas></canvas>`;
    wrap.appendChild(card);
    const canvas = card.querySelector("canvas");
    const chart = new Chart(canvas, {
      type: "bar",
      data: {
        labels,
        datasets: [
          {
            label: metric.name,
            data: values,
            backgroundColor: "rgba(37, 99, 235, 0.65)",
            borderRadius: 4,
          },
        ],
      },
      options: {
        responsive: true,
        plugins: {
          legend: { display: false },
          tooltip: {
            callbacks: {
              label: (ctx) => fmt(ctx.parsed.y),
            },
          },
        },
        scales: {
          y: {
            ticks: {
              callback: (v) => (Math.abs(v) >= 1e6 ? `${v / 1e6}M` : v),
            },
          },
        },
      },
    });
    summaryCharts.push(chart);
  }
}

function itemKey(section, name) {
  return `${section}::${name}`;
}

function sectionColumnTotals(section, colCount) {
  if (!SECTION_SUM_TOTALS.has(section.name) || !section.accounts?.length) {
    return null;
  }
  const totals = Array(colCount).fill(null);
  let any = false;
  for (const acct of section.accounts) {
    acct.values.forEach((v, i) => {
      if (v == null || i >= colCount) return;
      any = true;
      totals[i] = (totals[i] ?? 0) + Number(v);
    });
  }
  return any ? totals : null;
}

function stripeClass(index) {
  return index % 2 === 0 ? "stripe-a" : "stripe-b";
}

function renderTable() {
  const sections = payload[currentTab] || [];
  const periods = payload.periods || [];
  const ends = payload.period_ends || periods.map((p) => p.end);

  let meta = `${payload.company_name} — ${currentTab.toUpperCase()} — ${periods.length}期`;
  if (payload.provisional_periods?.length) {
    meta += ` — 未確定期: ${payload.provisional_periods.join(", ")}`;
  }
  el("metaInfo").textContent = meta;

  const table = document.createElement("table");
  const thead = document.createElement("thead");
  const hr = document.createElement("tr");
  hr.innerHTML =
    `<th class="sticky-col sticky-head">科目</th>` +
    periods
      .map((p) => `<th class="sticky-head">${periodHeader(p)}</th>`)
      .join("");
  thead.appendChild(hr);
  table.appendChild(thead);

  const tbody = document.createElement("tbody");
  let stripeIndex = 0;

  for (const section of sections) {
    const totals = sectionColumnTotals(section, ends.length);
    const sr = document.createElement("tr");
    sr.className = "section";
    const totalCells = totals
      ? totals
          .map((v) =>
            v == null
              ? '<td class="section-total empty">—</td>'
              : `<td class="num section-total">${fmt(v)}</td>`
          )
          .join("")
      : ends.map(() => '<td class="section-total"></td>').join("");
    sr.innerHTML =
      `<td class="sticky-col section-name">${section.name}</td>` + totalCells;
    tbody.appendChild(sr);

    for (const acct of section.accounts) {
      const key = itemKey(section.name, acct.name);
      const hasSub = acct.sub_breakdown?.length;
      const isExpanded = expandedKeys.has(key);

      const tr = document.createElement("tr");
      tr.className = `account data-row ${stripeClass(stripeIndex)}`;
      stripeIndex += 1;
      const toggleBtn = hasSub
        ? `<button type="button" class="expand-btn">${isExpanded ? "▼" : "▶"}</button>`
        : `<span class="expand-placeholder"></span>`;
      tr.innerHTML =
        `<td class="sticky-col account-name">${toggleBtn}${acct.name}</td>` +
        acct.values
          .map((v) =>
            v == null
              ? '<td class="num empty">—</td>'
              : `<td class="num">${fmt(v)}</td>`
          )
          .join("");

      if (hasSub) {
        tr.querySelector(".expand-btn")?.addEventListener("click", () => {
          if (expandedKeys.has(key)) expandedKeys.delete(key);
          else expandedKeys.add(key);
          renderTable();
        });
      }
      tbody.appendChild(tr);

      if (hasSub && isExpanded) {
        for (const sub of acct.sub_breakdown) {
          const subTr = document.createElement("tr");
          subTr.className = `sub-account data-row sub-row ${stripeClass(stripeIndex)}`;
          stripeIndex += 1;
          subTr.innerHTML =
            `<td class="sticky-col sub-name">↳ ${sub.name}</td>` +
            sub.values
              .map((v) =>
                v == null
                  ? '<td class="num empty">—</td>'
                  : `<td class="num">${fmt(v)}</td>`
              )
              .join("");
          tbody.appendChild(subTr);
        }
      }
    }
  }
  table.appendChild(tbody);
  const container = el("tableContainer");
  container.innerHTML = "";
  container.appendChild(table);
}

function render() {
  renderSummaryCharts();
  renderTable();
}

loadData().catch((err) => {
  el("metaInfo").textContent = "data.json の読み込みに失敗しました: " + err;
});
