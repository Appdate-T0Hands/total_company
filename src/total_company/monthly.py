"""月次 BS/PL タイムライン（決算月が異なる会社を月単位で比較するため）."""

from __future__ import annotations

import re

from .aggregate import _period_sort_key
from .display import DisplayChart
from .mapping import AccountMapper, normalize_report
from .parser import ParsedReport, dedupe_reports_by_period, report_month_keys

_MONTH_COL = re.compile(r"^\d{4}-\d{2}$")

_SECTION_ORDER_BS = ["流動資産", "固定資産", "流動負債", "固定負債", "純資産"]
_SECTION_ORDER_PL = [
    "売上高",
    "売上原価",
    "販売管理費",
    "営業外",
    "特別損益",
    "損益サマリー",
    "税金・当期利益",
]

# display_chart.yaml の定義順を維持（その他* は末尾付近）
_ACCOUNT_ORDER: dict[str, list[str]] = {
    "販売管理費": [
        "人件費（役員）",
        "人件費（従業員等）",
        "地代家賃",
        "水道光熱費",
        "通信費",
        "支払手数料",
        "減価償却費",
        "租税公課",
        "交際費",
        "消耗品費",
        "修繕費",
        "旅費交通費",
        "広告宣伝費",
        "保険料",
        "会議費",
        "新聞図書費",
        "研修費",
        "業務委託料",
        "雑費",
        "諸会費",
        "その他販管費",
    ],
}


def _sort_account_names(section_name: str, names: list[str]) -> list[str]:
    order = _ACCOUNT_ORDER.get(section_name, [])
    return sorted(names, key=lambda n: (order.index(n) if n in order else 999, n))


def _needs_sub_breakdown(display_name: str, sub_count: int) -> bool:
    return display_name.startswith("その他") or sub_count > 1


def _build_sub_rows(
    sub_map: dict[str, dict[str, float]],
    months: list[str],
) -> list[dict]:
    rows = []
    for name in sorted(sub_map.keys()):
        by_month = sub_map[name]
        values = [by_month.get(m) for m in months]
        if any(v is not None and v != 0 for v in values):
            rows.append({"name": name, "values": values})
    return rows


def _rollup_monthly_reports(
    reports: list[ParsedReport],
    statement: str,
    mapper: AccountMapper,
    chart: DisplayChart,
) -> tuple[
    list[str],
    dict[str, dict[str, dict[str, float]]],
    dict[str, dict[str, dict[str, dict[str, float]]]],
]:
    """section -> display_account -> month -> amount (+ canonical 内訳)."""
    rolled: dict[str, dict[str, dict[str, float]]] = {}
    sub_rolled: dict[str, dict[str, dict[str, dict[str, float]]]] = {}
    months: set[str] = set()

    for report in reports:
        if report.report_type != "monthly" or report.statement != statement:
            continue
        normalized = normalize_report(report, mapper)
        for row in normalized:
            if row.is_section and not row.values:
                continue
            resolved = chart.resolve(row.canonical_name, statement)
            if not resolved:
                continue
            section, display_name = resolved
            canonical = row.canonical_name
            bucket = rolled.setdefault(section, {}).setdefault(display_name, {})
            sub_bucket = (
                sub_rolled.setdefault(section, {})
                .setdefault(display_name, {})
                .setdefault(canonical, {})
            )
            for key, val in row.values.items():
                if not _MONTH_COL.match(key) or val is None:
                    continue
                months.add(key)
                fv = float(val)
                bucket[key] = bucket.get(key, 0.0) + fv
                sub_bucket[key] = sub_bucket.get(key, 0.0) + fv

    ordered_months = sorted(months, key=_period_sort_key)
    return ordered_months, rolled, sub_rolled


def _pack_sections(
    rolled: dict[str, dict[str, dict[str, float]]],
    sub_rolled: dict[str, dict[str, dict[str, dict[str, float]]]],
    months: list[str],
    order: list[str],
) -> list[dict]:
    sections: list[dict] = []
    names = order + [s for s in rolled if s not in order]
    for section_name in names:
        accounts_map = rolled.get(section_name)
        if not accounts_map:
            continue
        rows = []
        for acct_name in _sort_account_names(section_name, list(accounts_map.keys())):
            by_month = accounts_map[acct_name]
            values = [by_month.get(m) for m in months]
            if not any(v is not None and v != 0 for v in values):
                continue

            row: dict = {"name": acct_name, "values": values}
            sub_map = sub_rolled.get(section_name, {}).get(acct_name, {})
            sub_rows = _build_sub_rows(sub_map, months)
            if sub_rows and _needs_sub_breakdown(acct_name, len(sub_rows)):
                row["sub_breakdown"] = sub_rows
            rows.append(row)

        if rows:
            sections.append({"name": section_name, "accounts": rows})
    return sections


def _pack_sections_consolidated(
    rolled: dict[str, dict[str, dict[str, float]]],
    by_company: dict[str, dict[str, dict[str, dict[str, float]]]],
    sub_rolled: dict[str, dict[str, dict[str, dict[str, float]]]],
    members: list[dict],
    months: list[str],
    order: list[str],
) -> list[dict]:
    sections: list[dict] = []
    names = order + [s for s in rolled if s not in order]
    co_by_id = {co["company_id"]: co for co in members}

    for section_name in names:
        accounts_map = rolled.get(section_name)
        if not accounts_map:
            continue
        rows = []
        for acct_name in _sort_account_names(section_name, list(accounts_map.keys())):
            by_month = accounts_map[acct_name]
            values = [by_month.get(m) for m in months]
            if not any(v is not None and v != 0 for v in values):
                continue

            breakdown = []
            for cid in [co["company_id"] for co in members]:
                co_vals_map = (
                    by_company.get(section_name, {})
                    .get(acct_name, {})
                    .get(cid, {})
                )
                co_values = [co_vals_map.get(m) for m in months]
                if any(v is not None and v != 0 for v in co_values):
                    breakdown.append(
                        {
                            "company_id": cid,
                            "company_name": co_by_id[cid]["company_name"],
                            "values": co_values,
                        }
                    )

            row: dict = {"name": acct_name, "values": values}
            sub_map = sub_rolled.get(section_name, {}).get(acct_name, {})
            sub_rows = _build_sub_rows(sub_map, months)
            if sub_rows and _needs_sub_breakdown(acct_name, len(sub_rows)):
                row["sub_breakdown"] = sub_rows
            if breakdown:
                row["breakdown"] = breakdown
            rows.append(row)

        if rows:
            sections.append({"name": section_name, "accounts": rows})
    return sections


def build_consolidated_monthly_display(
    group_id: str,
    group_name: str,
    members: list[dict],
) -> dict:
    """複数社を暦月（YYYY-MM）で合算。各月はデータがある会社のみ足し込む。"""
    all_months = sorted(
        {m for co in members for m in co["months"]},
        key=_period_sort_key,
    )
    member_ids = [co["company_id"] for co in members]
    month_coverage: dict[str, int] = {}

    def sum_statement(stmt: str, order: list[str]) -> list[dict]:
        rolled: dict[str, dict[str, dict[str, float]]] = {}
        by_company: dict[str, dict[str, dict[str, dict[str, float]]]] = {}
        sub_rolled: dict[str, dict[str, dict[str, dict[str, float]]]] = {}

        for co in members:
            month_idx = {m: i for i, m in enumerate(co["months"])}
            cid = co["company_id"]
            for section in co.get(stmt, []):
                sec_name = section["name"]
                for acct in section["accounts"]:
                    acct_name = acct["name"]
                    bucket = rolled.setdefault(sec_name, {}).setdefault(acct_name, {})
                    co_bucket = (
                        by_company.setdefault(sec_name, {})
                        .setdefault(acct_name, {})
                        .setdefault(cid, {})
                    )
                    for m in all_months:
                        idx = month_idx.get(m)
                        if idx is None:
                            continue
                        v = acct["values"][idx]
                        if v is None:
                            continue
                        fv = float(v)
                        bucket[m] = bucket.get(m, 0.0) + fv
                        co_bucket[m] = fv

                    for sub in acct.get("sub_breakdown", []):
                        sub_name = sub["name"]
                        sub_bucket = (
                            sub_rolled.setdefault(sec_name, {})
                            .setdefault(acct_name, {})
                            .setdefault(sub_name, {})
                        )
                        for m in all_months:
                            idx = month_idx.get(m)
                            if idx is None:
                                continue
                            v = sub["values"][idx]
                            if v is None:
                                continue
                            sub_bucket[m] = sub_bucket.get(m, 0.0) + float(v)

        return _pack_sections_consolidated(
            rolled, by_company, sub_rolled, members, all_months, order
        )

    for m in all_months:
        month_coverage[m] = sum(1 for co in members if m in co["months"])

    prov_months = sorted(
        {m for co in members for m in co.get("provisional_months", [])},
        key=_period_sort_key,
    )

    return {
        "mode": "monthly",
        "company_id": f"_group_{group_id}",
        "company_name": group_name,
        "display_type": "consolidated",
        "members": member_ids,
        "member_names": [co["company_name"] for co in members],
        "months": all_months,
        "month_coverage": month_coverage,
        "provisional_months": prov_months,
        "bs": sum_statement("bs", _SECTION_ORDER_BS),
        "pl": sum_statement("pl", _SECTION_ORDER_PL),
    }


def _active_monthly_reports(reports: list[ParsedReport]) -> list[ParsedReport]:
    monthly = [r for r in reports if r.report_type == "monthly"]
    return dedupe_reports_by_period(monthly)


def _provisional_months(active: list[ParsedReport]) -> list[str]:
    months: set[str] = set()
    for report in active:
        if report.data_status == "provisional":
            months.update(report_month_keys(report))
    return sorted(months, key=_period_sort_key)


def build_monthly_display(
    company_id: str,
    company_name: str,
    reports: list[ParsedReport],
    mapper: AccountMapper,
    chart: DisplayChart,
) -> dict:
    active = _active_monthly_reports(reports)
    bs_months, bs_rolled, bs_sub = _rollup_monthly_reports(active, "bs", mapper, chart)
    pl_months, pl_rolled, pl_sub = _rollup_monthly_reports(active, "pl", mapper, chart)
    all_months = sorted(set(bs_months) | set(pl_months), key=_period_sort_key)
    prov_months = _provisional_months(active)

    return {
        "mode": "monthly",
        "company_id": company_id,
        "company_name": company_name,
        "display_type": "single",
        "months": all_months,
        "provisional_months": prov_months,
        "bs": _pack_sections(bs_rolled, bs_sub, all_months, _SECTION_ORDER_BS),
        "pl": _pack_sections(pl_rolled, pl_sub, all_months, _SECTION_ORDER_PL),
        "source_files": sorted({r.source_file for r in active}),
    }
