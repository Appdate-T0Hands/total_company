const CHART_STATE_KEY = "total_company_chart_state";

let payload = null;
let currentTab = "bs";
let chartItems = [];
let expandedKeys = new Set();
let autoExpandToken = "";
let chartWindowRef = null;

function fmt(n) {
  if (n === null || n === undefined) return "—";
  return Number(n).toLocaleString("ja-JP");
}

function fmtMonth(m) {
  const [y, mo] = m.split("-");
  return `${y}/${mo}`;
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

function el(id) {
  return document.getElementById(id);
}

function setText(id, text) {
  const node = el(id);
  if (node) node.textContent = text;
}

function saveChartState() {
  const co = getCompany();
  const prev = loadChartState();
  localStorage.setItem(
    CHART_STATE_KEY,
    JSON.stringify({
      ...prev,
      chartItems,
      companyName: co?.company_name || "",
      tab: currentTab,
      updatedAt: Date.now(),
    })
  );
  notifyChartWindow();
}

function loadChartState() {
  try {
    return JSON.parse(localStorage.getItem(CHART_STATE_KEY) || "{}");
  } catch {
    return {};
  }
}

function notifyChartWindow() {
  if (chartWindowRef && !chartWindowRef.closed) {
    chartWindowRef.postMessage({ type: "chart-update" }, location.origin);
  }
}

function openChartWindow() {
  saveChartState();
  const w = Math.max(960, Math.round(window.screen.availWidth * 0.9));
  const h = Math.max(640, Math.round(window.screen.availHeight * 0.9));
  const left = Math.round((window.screen.availWidth - w) / 2);
  const top = Math.round((window.screen.availHeight - h) / 2);
  const spec = [
    `width=${w}`,
    `height=${h}`,
    `left=${left}`,
    `top=${top}`,
    "menubar=no",
    "toolbar=no",
    "location=no",
    "scrollbars=no",
    "resizable=yes",
  ].join(",");
  if (chartWindowRef && !chartWindowRef.closed) {
    chartWindowRef.focus();
    notifyChartWindow();
    return;
  }
  chartWindowRef = window.open("chart.html?v=4", "total_company_chart", spec);
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
  el("rangeSelect")?.addEventListener("change", render);
  el("searchInput")?.addEventListener("input", render);

  window.addEventListener("storage", (e) => {
    if (e.key !== CHART_STATE_KEY) return;
    try {
      const state = JSON.parse(e.newValue || "{}");
      if (Array.isArray(state.chartItems) && !state.chartItems.length) {
        chartItems = [];
        highlightSelectedRows();
      }
    } catch {
      /* ignore */
    }
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
  saveChartState();
  highlightSelectedRows();
  if (chartItems.length) openChartWindow();
}

function highlightSelectedRows() {
  document.querySelectorAll("tr.account").forEach((tr) => {
    tr.classList.toggle("selected", chartItems.some((x) => x.key === tr.dataset.key));
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
  setText("metaInfo", meta);

  const table = document.createElement("table");
  const thead = document.createElement("thead");
  const hr = document.createElement("tr");
  hr.innerHTML =
    `<th class="sticky-col sticky-head">科目</th>` +
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
        return `<th class="sticky-head">${fmtMonth(m)}${badge}</th>`;
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
  const container = document.getElementById("tableContainer");
  container.innerHTML = "";
  container.appendChild(table);

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

  saveChartState();
  highlightSelectedRows();
}

loadData().catch((err) => {
  document.body.innerHTML = `<pre style="padding:2rem;color:red">${err}</pre>`;
});
