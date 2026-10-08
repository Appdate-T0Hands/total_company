"""決算期（月次 CSV 1ファイル＝1期）ごとの BS/PL 経年表示."""

from __future__ import annotations

import re

from .aggregate import _period_sort_key
from .display import DisplayChart
from .mapping import AccountMapper, normalize_report
from .parser import ParsedReport, dedupe_reports_by_period, report_month_keys

from .monthly import (
    _SECTION_ORDER_BS,
    _SECTION_ORDER_PL,
    _build_sub_rows,
    _needs_sub_breakdown,
    _pack_sections,
    _sort_account_names,
)

_MONTH_COL = re.compile(r"^\d{4}-\d{2}$")


def _period_label(report: ParsedReport) -> str:
    if report.period_label:
        return report.period_label
    if report.period_start and report.period_end:
        sy, sm = report.period_start.split("-")
        ey, em = report.period_end.split("-")
        return f"{sy}年{int(sm)}月～{ey}年{int(em)}月"
    return report.period_end or "?"


def _fiscal_row_amount(row, statement: str, period_end: str) -> float | None:
    month_vals = {
        k: float(v)
        for k, v in row.values.items()
        if _MONTH_COL.match(k) and v is not None
    }
    if not month_vals:
        return None
    if statement == "bs":
        if period_end in month_vals:
            return month_vals[period_end]
        last = max(month_vals.keys(), key=_period_sort_key)
        return month_vals[last]
    return sum(month_vals.values())


def _rollup_fiscal_reports(
    reports: list[ParsedReport],
    statement: str,
    mapper: AccountMapper,
    chart: DisplayChart,
) -> tuple[
    list[str],
    list[dict],
    dict[str, dict[str, dict[str, float]]],
    dict[str, dict[str, dict[str, dict[str, float]]]],
]:
    """period_end -> section -> display_account -> amount."""
    rolled: dict[str, dict[str, dict[str, float]]] = {}
    sub_rolled: dict[str, dict[str, dict[str, dict[str, float]]]] = {}
    period_meta: dict[str, dict] = {}

    for report in reports:
        if report.report_type != "monthly" or report.statement != statement:
            continue
        end = report.period_end
        if not end:
            continue

        months_in_file = sorted(report_month_keys(report), key=_period_sort_key)
        period_meta[end] = {
            "end": end,
            "label": _period_label(report),
            "start": report.period_start,
            "provisional": report.data_status == "provisional",
            "months_in_file": len(months_in_file),
            "source_file": report.source_file,
        }

        normalized = normalize_report(report, mapper)
        for row in normalized:
            if row.is_section:
                continue
            resolved = chart.resolve(row.canonical_name, statement)
            if not resolved:
                continue
            section, display_name = resolved
            amount = _fiscal_row_amount(row, statement, end)
            if amount is None:
                continue
            canonical = row.canonical_name
            sec_map = rolled.setdefault(end, {}).setdefault(section, {})
            sec_map[display_name] = sec_map.get(display_name, 0.0) + amount
            sub_map = (
                sub_rolled.setdefault(end, {})
                .setdefault(section, {})
                .setdefault(display_name, {})
            )
            sub_map[canonical] = sub_map.get(canonical, 0.0) + amount

    ordered_ends = sorted(period_meta.keys(), key=_period_sort_key)
    periods = [period_meta[e] for e in ordered_ends]

    # period_end 軸 → display_chart 構造へ変換
    flat_rolled: dict[str, dict[str, dict[str, float]]] = {}
    flat_sub: dict[str, dict[str, dict[str, dict[str, float]]]] = {}
    for end in ordered_ends:
        for section, accounts in rolled.get(end, {}).items():
            for acct, val in accounts.items():
                flat_rolled.setdefault(section, {}).setdefault(acct, {})[end] = val
                for canon, cval in (
                    sub_rolled.get(end, {}).get(section, {}).get(acct, {}).items()
                ):
                    flat_sub.setdefault(section, {}).setdefault(acct, {}).setdefault(
                        canon, {}
                    )[end] = cval

    return ordered_ends, periods, flat_rolled, flat_sub


def build_fiscal_year_display(
    company_id: str,
    company_name: str,
    reports: list[ParsedReport],
    mapper: AccountMapper,
    chart: DisplayChart,
) -> dict:
    monthly = [r for r in reports if r.report_type == "monthly"]
    active = [
        r
        for r in dedupe_reports_by_period(monthly)
        if r.data_status == "confirmed"
    ]

    bs_ends, bs_periods, bs_rolled, bs_sub = _rollup_fiscal_reports(
        active, "bs", mapper, chart
    )
    pl_ends, pl_periods, pl_rolled, pl_sub = _rollup_fiscal_reports(
        active, "pl", mapper, chart
    )

    all_ends = sorted(set(bs_ends) | set(pl_ends), key=_period_sort_key)
    period_by_end = {p["end"]: p for p in bs_periods + pl_periods if p["end"] in all_ends}
    periods = [period_by_end[e] for e in all_ends if e in period_by_end]

    return {
        "mode": "fiscal",
        "company_id": company_id,
        "company_name": company_name,
        "period_ends": all_ends,
        "periods": periods,
        "provisional_periods": [p["end"] for p in periods if p.get("provisional")],
        "bs": _pack_sections(bs_rolled, bs_sub, all_ends, _SECTION_ORDER_BS),
        "pl": _pack_sections(pl_rolled, pl_sub, all_ends, _SECTION_ORDER_PL),
        "source_files": sorted({r.source_file for r in active}),
    }
