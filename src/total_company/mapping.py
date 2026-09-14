"""科目名称の統一マッピング."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

import yaml

from .parser import AccountRow, ParsedReport, StatementType


@dataclass
class MappingRule:
    id: str
    canonical: str
    statements: set[StatementType]
    aliases: set[str] = field(default_factory=set)
    pattern: re.Pattern[str] | None = None
    merge: bool = False


@dataclass
class AccountMapper:
    rules: list[MappingRule]
    section_labels: set[str]

    @classmethod
    def from_yaml(cls, path: Path) -> AccountMapper:
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
        rules: list[MappingRule] = []
        for item in data.get("rules", []):
            pattern = re.compile(item["pattern"]) if item.get("pattern") else None
            rules.append(
                MappingRule(
                    id=item["id"],
                    canonical=item["canonical"],
                    statements=set(item.get("statement", ["pl", "bs"])),
                    aliases=set(item.get("aliases", [])),
                    pattern=pattern,
                    merge=item.get("merge", False),
                )
            )
        section_labels = set(data.get("section_labels", []))
        return cls(rules=rules, section_labels=section_labels)

    def is_section(self, name: str) -> bool:
        if name in self.section_labels:
            return True
        return name.endswith("の部") or name.endswith(" 計")

    def resolve(self, raw_name: str, statement: StatementType) -> tuple[str, str | None, bool]:
        """raw_name -> (canonical_name, rule_id, merge)."""
        if self.is_section(raw_name):
            return raw_name, None, False

        for rule in self.rules:
            if statement not in rule.statements:
                continue
            if raw_name in rule.aliases or raw_name == rule.canonical:
                return rule.canonical, rule.id, rule.merge
            if rule.pattern and rule.pattern.match(raw_name):
                return rule.canonical, rule.id, rule.merge

        return raw_name, None, False


@dataclass
class NormalizedRow:
    canonical_name: str
    raw_names: list[str]
    account_codes: list[str]
    values: dict[str, int | float]
    depth: int
    is_section: bool
    rule_ids: list[str]


def normalize_report(report: ParsedReport, mapper: AccountMapper) -> list[NormalizedRow]:
    merged: dict[str, NormalizedRow] = {}
    order: list[str] = []

    for row in report.rows:
        canonical, rule_id, should_merge = mapper.resolve(row.raw_name, report.statement)

        if canonical in merged:
            existing = merged[canonical]
            if row.raw_name not in existing.raw_names:
                existing.raw_names.append(row.raw_name)
            if row.account_code and row.account_code not in existing.account_codes:
                existing.account_codes.append(row.account_code)
            if rule_id and rule_id not in existing.rule_ids:
                existing.rule_ids.append(rule_id)
            if should_merge:
                for key, val in row.values.items():
                    if val is None:
                        continue
                    existing.values[key] = existing.values.get(key, 0) + val
            else:
                for key, val in row.values.items():
                    if val is None:
                        continue
                    if key not in existing.values:
                        existing.values[key] = val
            continue

        order.append(canonical)
        merged[canonical] = NormalizedRow(
            canonical_name=canonical,
            raw_names=[row.raw_name],
            account_codes=[row.account_code] if row.account_code else [],
            values={
                k: v for k, v in row.values.items() if v is not None
            },
            depth=row.depth,
            is_section=row.is_section or mapper.is_section(canonical),
            rule_ids=[rule_id] if rule_id else [],
        )

    return [merged[k] for k in order]


def collect_raw_accounts(reports: list[ParsedReport]) -> dict[str, set[str]]:
    result: dict[str, set[str]] = {"pl": set(), "bs": set()}
    for report in reports:
        for row in report.rows:
            if row.is_section or mapper_is_section(row.raw_name):
                continue
            result[report.statement].add(row.raw_name)
    return result


def mapper_is_section(name: str) -> bool:
    return name.endswith("の部") or name.endswith(" 計")


def find_mapping_candidates(
    reports_by_company: dict[str, list[ParsedReport]],
    mapper: AccountMapper,
) -> dict[str, list[str]]:
    """各社で canonical 化されなかった科目（= passthrough）を返す."""
    unmapped: dict[str, list[str]] = {}
    for company_id, reports in reports_by_company.items():
        names: set[str] = set()
        for report in reports:
            for row in report.rows:
                if row.is_section or mapper.is_section(row.raw_name):
                    continue
                canonical, rule_id, _ = mapper.resolve(row.raw_name, report.statement)
                if canonical == row.raw_name and rule_id is None:
                    names.add(row.raw_name)
        unmapped[company_id] = sorted(names)
    return unmapped


def find_cross_company_variants(
    reports_by_company: dict[str, list[ParsedReport]],
    mapper: AccountMapper,
) -> list[dict]:
    """会社間で canonical が同じだが raw 名称が異なるものを一覧."""
    bucket: dict[tuple[StatementType, str], dict[str, set[str]]] = {}

    for company_id, reports in reports_by_company.items():
        for report in reports:
            for row in report.rows:
                if row.is_section or mapper.is_section(row.raw_name):
                    continue
                canonical, _, _ = mapper.resolve(row.raw_name, report.statement)
                key = (report.statement, canonical)
                bucket.setdefault(key, {}).setdefault(company_id, set()).add(row.raw_name)

    variants = []
    for (statement, canonical), by_company in sorted(bucket.items()):
        all_raw = set()
        for raw_set in by_company.values():
            all_raw |= raw_set
        if len(all_raw) > 1:
            variants.append(
                {
                    "statement": statement,
                    "canonical": canonical,
                    "by_company": {c: sorted(v) for c, v in by_company.items()},
                }
            )
    return variants
