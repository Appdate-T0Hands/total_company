"""表示用ロールアップ（標準勘定科目・大項目）."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

import yaml

from .aggregate import CompanyTimeline, _period_sort_key, extract_amount
from .mapping import AccountMapper, normalize_report
from .parser import ParsedReport


@dataclass
class DisplayRule:
    section: str
    name: str
    match: set[str]
    patterns: list[re.Pattern[str]]


@dataclass
class DisplayChart:
    bs_rules: list[DisplayRule]
    pl_rules: list[DisplayRule]

    @classmethod
    def from_yaml(cls, path: Path) -> DisplayChart:
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
        bs_rules: list[DisplayRule] = []
        pl_rules: list[DisplayRule] = []
        for item in data.get("bs", []):
            bs_rules.extend(_load_rules(item))
        for item in data.get("pl", []):
            pl_rules.extend(_load_rules(item))
        return cls(bs_rules=bs_rules, pl_rules=pl_rules)

    def resolve(self, account: str, statement: str) -> tuple[str, str] | None:
        rules = self.bs_rules if statement == "bs" else self.pl_rules
        for rule in rules:
            if account in rule.match:
                return rule.section, rule.name
            for pat in rule.patterns:
                if pat.search(account):
                    return rule.section, rule.name
        return None


def _load_rules(section_item: dict) -> list[DisplayRule]:
    section = section_item["section"]
    rules: list[DisplayRule] = []
    for acct in section_item.get("accounts", []):
        patterns = [re.compile(p) for p in acct.get("patterns", [])]
        rules.append(
            DisplayRule(
                section=section,
                name=acct["name"],
                match=set(acct.get("match", [])),
                patterns=patterns,
            )
        )
    return rules


def _rollup_statement(
    timeline: CompanyTimeline,
    statement: str,
    chart: DisplayChart,
) -> dict[str, dict[str, dict[str, float]]]:
    """section -> display_account -> period_end -> amount."""
    source = timeline.bs if statement == "bs" else timeline.pl
    rolled: dict[str, dict[str, dict[str, float]]] = {}

    for raw_account, by_period in source.items():
        resolved = chart.resolve(raw_account, statement)
        if not resolved:
            continue
        section, display_name = resolved
        bucket = rolled.setdefault(section, {}).setdefault(display_name, {})
        for end, val in by_period.items():
            bucket[end] = bucket.get(end, 0.0) + val

    return rolled


def build_company_display(
    timeline: CompanyTimeline,
    chart: DisplayChart,
) -> dict:
    periods = [p.end for p in timeline.periods]
    bs = _rollup_statement(timeline, "bs", chart)
    pl = _rollup_statement(timeline, "pl", chart)

    section_order_bs = ["流動資産", "固定資産", "流動負債", "固定負債", "純資産"]
    section_order_pl = [
        "売上高",
        "売上原価",
        "販売管理費",
        "営業外",
        "特別損益",
        "税金・当期利益",
    ]

    def pack(
        data: dict[str, dict[str, dict[str, float]]],
        order: list[str],
    ) -> list[dict]:
        sections = []
        names = order + [s for s in data if s not in order]
        for section_name in names:
            accounts = data.get(section_name)
            if not accounts:
                continue
            rows = []
            for acct_name in sorted(accounts.keys()):
                vals = [accounts[acct_name].get(p) for p in periods]
                if any(v is not None and v != 0 for v in vals):
                    rows.append({"name": acct_name, "values": vals})
            if rows:
                sections.append({"name": section_name, "accounts": rows})
        return sections

    return {
        "company_id": timeline.company_id,
        "company_name": timeline.company_name,
        "period_ends": periods,
        "periods": [{"end": p.end, "label": p.label} for p in timeline.periods],
        "bs": pack(bs, section_order_bs),
        "pl": pack(pl, section_order_pl),
    }


def build_grouped_display(companies: list[dict], statement: str) -> list[dict]:
    """全社: 大項目 > 会社 > 科目."""
    section_map: dict[str, dict[str, dict[str, dict[str, float | None]]]] = {}
    all_periods: set[str] = set()

    for co in companies:
        all_periods.update(co["period_ends"])
        for section in co.get(statement, []):
            sec_name = section["name"]
            for acct in section["accounts"]:
                acct_name = acct["name"]
                by_period = {
                    co["period_ends"][i]: acct["values"][i]
                    for i in range(len(co["period_ends"]))
                }
                section_map.setdefault(sec_name, {}).setdefault(co["company_id"], {})[
                    acct_name
                ] = by_period

    periods = sorted(all_periods, key=_period_sort_key)
    result = []
    section_order_bs = ["流動資産", "固定資産", "流動負債", "固定負債", "純資産"]
    section_order_pl = [
        "売上高",
        "売上原価",
        "販売管理費",
        "営業外",
        "特別損益",
        "税金・当期利益",
    ]
    order = section_order_bs if statement == "bs" else section_order_pl

    for sec_name in order + [s for s in section_map if s not in order]:
        if sec_name not in section_map:
            continue
        companies_block = []
        for co in companies:
            cid = co["company_id"]
            if cid not in section_map[sec_name]:
                continue
            accounts = []
            for acct_name, by_period in sorted(section_map[sec_name][cid].items()):
                vals = [by_period.get(p) for p in periods]
                if any(v is not None and v != 0 for v in vals):
                    accounts.append({"name": acct_name, "values": vals})
            if accounts:
                companies_block.append(
                    {
                        "company_id": cid,
                        "company_name": co["company_name"],
                        "accounts": accounts,
                    }
                )
        if companies_block:
            result.append(
                {"name": sec_name, "companies": companies_block, "period_ends": periods}
            )
    return result
