"""複数年度の BS/PL 集計."""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from .mapping import AccountMapper, NormalizedRow, normalize_report
from .parser import ParsedReport


@dataclass
class FiscalYear:
    end: str
    label: str
    start: str | None
    source_file: str


def _period_sort_key(end: str) -> tuple[int, int]:
    m = re.match(r"(\d{4})-(\d{2})", end)
    if m:
        return int(m.group(1)), int(m.group(2))
    return 0, 0


def _pick_period_end(report: ParsedReport) -> str | None:
    if report.period_end:
        return report.period_end
    for row in report.rows:
        for key in row.values:
            m = re.search(r"(\d{4})-(\d{2})", key)
            if m and ("期末" in key or "月" in key):
                return f"{m.group(1)}-{m.group(2)}"
    return None


def extract_amount(values: dict[str, int | float | None], statement: str) -> float | None:
    if not values:
        return None

    for key in values:
        if "期末" in key:
            val = values[key]
            if val is not None:
                return float(val)

    for key in sorted(values.keys(), key=_period_sort_key):
        m = re.match(r"(\d{4})年-(\d{2})月", key)
        if m:
            val = values[key]
            if val is not None:
                return float(val)

    range_keys = sorted(
        [k for k in values if re.match(r"\d{4}-\d{2}\s+\d{4}-\d{2}", k.strip())],
        key=lambda k: _period_sort_key(k.split()[-1]),
    )
    if range_keys:
        val = values[range_keys[-1]]
        if val is not None:
            return float(val)

    dated = sorted(
        [k for k in values if re.match(r"\d{4}-\d{2}期末", k)],
        key=_period_sort_key,
    )
    if dated:
        val = values[dated[-1]]
        if val is not None:
            return float(val)

    for key in sorted(values.keys(), reverse=True):
        m = re.search(r"(\d{4})-(\d{2})", key)
        if m and "構成" not in key and "前年比" not in key:
            val = values[key]
            if val is not None:
                return float(val)

    if statement == "pl":
        for key in ("借方", "期間借方金額"):
            if values.get(key) is not None:
                return float(values[key])

    if statement == "bs":
        for key in ("貸方", "借方"):
            if values.get(key) is not None:
                return float(values[key])

    nums = [float(v) for v in values.values() if v is not None and v != 0]
    if len(nums) == 1:
        return nums[0]
    return None


@dataclass
class CompanyTimeline:
    company_id: str
    company_name: str
    periods: list[FiscalYear] = field(default_factory=list)
    pl: dict[str, dict[str, float]] = field(default_factory=dict)
    bs: dict[str, dict[str, float]] = field(default_factory=dict)

    def pl_series(self, account: str) -> list[tuple[str, float]]:
        data = self.pl.get(account, {})
        return [(p.end, data[p.end]) for p in self.periods if p.end in data]

    def bs_series(self, account: str) -> list[tuple[str, float]]:
        data = self.bs.get(account, {})
        return [(p.end, data[p.end]) for p in self.periods if p.end in data]


def _merge_rows(rows: list[NormalizedRow], statement: str) -> dict[str, float]:
    out: dict[str, float] = {}
    for row in rows:
        if row.is_section:
            continue
        amount = extract_amount(row.values, statement)
        if amount is None:
            continue
        out[row.canonical_name] = out.get(row.canonical_name, 0) + amount
    return out


def build_timeline(
    company_id: str,
    company_name: str,
    reports: list[ParsedReport],
    mapper: AccountMapper,
) -> CompanyTimeline:
    timeline = CompanyTimeline(company_id=company_id, company_name=company_name)
    by_end: dict[str, tuple[FiscalYear, dict[str, float], dict[str, float]]] = {}

    for report in reports:
        end = _pick_period_end(report)
        if not end:
            continue
        normalized = normalize_report(report, mapper)
        fy = FiscalYear(
            end=end,
            label=report.period_label or end,
            start=report.period_start,
            source_file=report.source_file,
        )
        pl_data = _merge_rows(normalized, "pl") if report.statement == "pl" else {}
        bs_data = _merge_rows(normalized, "bs") if report.statement == "bs" else {}

        if end not in by_end:
            by_end[end] = (fy, {}, {})
        existing_fy, pl_acc, bs_acc = by_end[end]
        if report.period_label and len(report.period_label) > len(existing_fy.label):
            existing_fy = fy
        pl_acc.update(pl_data)
        bs_acc.update(bs_data)
        by_end[end] = (existing_fy, pl_acc, bs_acc)

    for end in sorted(by_end.keys(), key=_period_sort_key):
        fy, pl_acc, bs_acc = by_end[end]
        timeline.periods.append(fy)
        for acct, val in pl_acc.items():
            timeline.pl.setdefault(acct, {})[end] = val
        for acct, val in bs_acc.items():
            timeline.bs.setdefault(acct, {})[end] = val

    return timeline
