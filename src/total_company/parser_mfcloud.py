"""マネーフォワード クラウド（残高試算表）CSV パーサ."""

from __future__ import annotations

import csv
import re
from pathlib import Path

from .parser import (
    AccountRow,
    ParsedReport,
    StatementType,
    _parse_amount,
)

_TOP_SECTIONS = frozenset({"資産の部", "負債の部", "純資産の部", "負債及び純資産の部"})
_MAJOR_BS = frozenset(
    {"流動資産", "固定資産", "流動負債", "固定負債", "株主資本", "評価・換算差額等", "新株予約権"}
)
_MAJOR_PL = frozenset(
    {
        "売上高",
        "売上原価",
        "売上総利益",
        "販売費及び一般管理費",
        "営業外収益",
        "営業外費用",
        "特別利益",
        "特別損失",
    }
)


def _read_csv_rows(path: Path) -> list[list[str]]:
    data = path.read_bytes()
    for enc in ("cp932", "utf-8-sig", "utf-8"):
        try:
            return list(csv.reader(data.decode(enc).splitlines()))
        except UnicodeDecodeError:
            continue
    raise ValueError(f"文字コードを判定できません: {path}")


def _extract_mf_period(header: list[str]) -> tuple[str, str | None, str | None]:
    start = end = None
    for cell in header:
        c = cell.strip()
        m = re.match(r"開始月:(\d{4}-\d{2}-\d{2})", c)
        if m:
            start = m.group(1)[:7]
        m = re.match(r"終了月:(\d{4}-\d{2}-\d{2})", c)
        if m:
            end = m.group(1)[:7]
    if start and end:
        return f"{start}～{end}", start, end
    return "", None, None


def _parse_mf_header(header: list[str]) -> dict[str, int]:
    value_cols: dict[str, int] = {}
    for i, cell in enumerate(header):
        c = cell.strip()
        if re.match(r"開始月:\d{4}-\d{2}-\d{2}", c):
            value_cols["期首"] = i
        elif c == "期間借方金額":
            value_cols["借方"] = i
        elif c == "期間貸方金額":
            value_cols["貸方"] = i
        elif re.match(r"終了月:\d{4}-\d{2}-\d{2}", c):
            m = re.match(r"終了月:(\d{4}-\d{2}-\d{2})", c)
            key = f"{m.group(1)[:7]}期末" if m else "期末"
            value_cols[key] = i
    return value_cols


def _has_col2_children(rows: list[list[str]], idx: int) -> bool:
    for j in range(idx + 1, min(idx + 20, len(rows))):
        nxt = rows[j]
        col0 = nxt[0].strip() if nxt else ""
        col1 = nxt[1].strip() if len(nxt) > 1 else ""
        col2 = nxt[2].strip() if len(nxt) > 2 else ""
        if col0 and not col0.endswith("合計"):
            break
        if col2:
            return True
        if col1 and not _has_col2_children(rows, j):
            break
    return False


def _update_section_stack(stack: list[str], name: str, statement: StatementType) -> None:
    if name.endswith("合計"):
        return
    if name in _TOP_SECTIONS:
        stack.clear()
        stack.append(name)
        return
    major = _MAJOR_BS if statement == "bs" else _MAJOR_PL
    if name in major:
        if stack and stack[0] in _TOP_SECTIONS:
            stack[:] = stack[:1] + [name]
        else:
            stack[:] = [name]
        return
    if stack:
        if len(stack) >= 2:
            stack[:] = stack[:2] + [name]
        else:
            stack.append(name)


_MF_MONTH = re.compile(r"^(\d{1,2})月$")
_SKIP_MF_MONTHLY = frozenset({"決算整理", "合計"})


def _extract_mf_fiscal_year(filename: str) -> int | None:
    m = re.match(r"^(\d{4})_", filename)
    if m:
        return int(m.group(1))
    # 例: 損益計算書_月次推移_20260914_2246.csv（export 日時から会計年度を推定）
    m = re.search(r"(\d{4})(\d{2})(\d{2})", filename)
    if m:
        year, month = int(m.group(1)), int(m.group(2))
        return year if month >= 10 else year - 1
    return None


def _mf_month_to_key(fiscal_year_end: int, month: int, fiscal_year_shift: int = 0) -> str:
    year = fiscal_year_end - 1 if month >= 10 else fiscal_year_end
    year += fiscal_year_shift
    return f"{year}-{month:02d}"


def _parse_mf_monthly_header(
    header: list[str], fiscal_year_end: int, fiscal_year_shift: int = 0
) -> dict[str, int]:
    value_cols: dict[str, int] = {}
    for i, cell in enumerate(header):
        c = cell.strip()
        if c in _SKIP_MF_MONTHLY:
            continue
        m = _MF_MONTH.match(c)
        if m:
            key = _mf_month_to_key(fiscal_year_end, int(m.group(1)), fiscal_year_shift)
            value_cols[key] = i
    return value_cols


def parse_mfcloud_monthly_csv(
    path: Path,
    company_id: str,
    statement: StatementType,
    fiscal_year_shift: int = 0,
) -> ParsedReport:
    raw_rows = _read_csv_rows(path)
    if not raw_rows:
        raise ValueError(f"空の CSV です: {path}")

    fiscal_year_end = _extract_mf_fiscal_year(path.name)
    if not fiscal_year_end:
        raise ValueError(f"会計年度をファイル名から判定できません: {path.name}")

    start_year = fiscal_year_end - 1 + fiscal_year_shift
    end_year = fiscal_year_end + fiscal_year_shift
    period_start = f"{start_year}-10"
    period_end = f"{end_year}-09"
    period_label = f"{period_start}～{period_end}"

    header = raw_rows[0]
    value_cols = _parse_mf_monthly_header(header, fiscal_year_end, fiscal_year_shift)

    report = ParsedReport(
        company_id=company_id,
        statement=statement,
        report_type="monthly",
        period_label=period_label,
        period_start=period_start,
        period_end=period_end,
        source_file=path.name,
    )

    section_stack: list[str] = []

    for row in raw_rows[1:]:
        if not any(cell.strip() for cell in row):
            continue

        col0 = row[0].strip() if row else ""
        col1 = row[1].strip() if len(row) > 1 else ""
        col2 = row[2].strip() if len(row) > 2 else ""

        if col0 and not col1 and not col2:
            values: dict[str, int | float | None] = {}
            for label, col_idx in value_cols.items():
                if col_idx < len(row):
                    val = _parse_amount(row[col_idx])
                    if val is not None:
                        values[label] = val

            if values:
                report.rows.append(
                    AccountRow(
                        raw_name=col0,
                        account_code=None,
                        values=values,
                        depth=len(section_stack),
                        is_section=False,
                    )
                )
                continue

            _update_section_stack(section_stack, col0, statement)
            if not col0.endswith("合計"):
                report.rows.append(
                    AccountRow(
                        raw_name=col0,
                        account_code=None,
                        values={},
                        depth=len(section_stack),
                        is_section=True,
                    )
                )
            continue

        if col2:
            continue

        if not col1 or col1.endswith("合計"):
            continue

        values = {}
        for label, col_idx in value_cols.items():
            if col_idx < len(row):
                val = _parse_amount(row[col_idx])
                if val is not None:
                    values[label] = val

        if not values:
            continue

        report.rows.append(
            AccountRow(
                raw_name=col1,
                account_code=None,
                values=values,
                depth=len(section_stack),
                is_section=False,
            )
        )

    return report


def parse_mfcloud_csv(path: Path, company_id: str, statement: StatementType) -> ParsedReport:
    raw_rows = _read_csv_rows(path)
    if not raw_rows:
        raise ValueError(f"空の CSV です: {path}")

    header = raw_rows[0]
    period_label, period_start, period_end = _extract_mf_period(header)
    value_cols = _parse_mf_header(header)

    report = ParsedReport(
        company_id=company_id,
        statement=statement,
        report_type="trial",
        period_label=period_label,
        period_start=period_start,
        period_end=period_end,
        source_file=path.name,
    )

    section_stack: list[str] = []

    for idx, row in enumerate(raw_rows[1:], start=1):
        if not any(cell.strip() for cell in row):
            continue

        col0 = row[0].strip() if row else ""
        col1 = row[1].strip() if len(row) > 1 else ""
        col2 = row[2].strip() if len(row) > 2 else ""

        if col0 and not col1 and not col2:
            _update_section_stack(section_stack, col0, statement)
            if not col0.endswith("合計"):
                report.rows.append(
                    AccountRow(
                        raw_name=col0,
                        account_code=None,
                        values={},
                        depth=len(section_stack),
                        is_section=True,
                    )
                )
            continue

        # 補助科目行は親科目に含まれるためスキップ
        if col2:
            continue

        if not col1:
            continue

        if col1.endswith("合計"):
            continue

        values: dict[str, int | float | None] = {}
        for label, col_idx in value_cols.items():
            if col_idx < len(row):
                val = _parse_amount(row[col_idx])
                if val is not None:
                    values[label] = val

        if not values:
            continue

        report.rows.append(
            AccountRow(
                raw_name=col1,
                account_code=None,
                values=values,
                depth=len(section_stack),
                is_section=False,
            )
        )

    return report
