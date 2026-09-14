"""freee 形式 CSV のパーサ."""

from __future__ import annotations

import csv
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal

StatementType = Literal["pl", "bs"]
ReportType = Literal["trial", "monthly"]
DataStatus = Literal["confirmed", "provisional"]


@dataclass
class AccountRow:
    raw_name: str
    account_code: str | None
    values: dict[str, int | float | None]
    depth: int
    is_section: bool = False


@dataclass
class ParsedReport:
    company_id: str
    statement: StatementType
    report_type: ReportType
    period_label: str
    period_start: str | None
    period_end: str | None
    rows: list[AccountRow] = field(default_factory=list)
    source_file: str = ""
    data_status: DataStatus = "confirmed"


def _detect_meta(filename: str) -> tuple[StatementType, ReportType]:
    if "損益" in filename:
        statement: StatementType = "pl"
    elif "貸借" in filename:
        statement = "bs"
    else:
        raise ValueError(f"損益/貸借を判定できません: {filename}")

    report_type: ReportType = "monthly" if "月次推移" in filename else "trial"
    return statement, report_type


def _extract_period(filename: str) -> tuple[str, str | None, str | None]:
    m = re.search(r"期間：(\d{4})年(\d{2})月～(\d{4})年(\d{2})月", filename)
    if not m:
        return "", None, None
    y1, m1, y2, m2 = m.groups()
    label = f"{y1}-{m1}～{y2}-{m2}"
    start = f"{y1}-{m1}"
    end = f"{y2}-{m2}"
    return label, start, end


def _parse_amount(text: str) -> int | float | None:
    text = text.strip()
    if not text:
        return None
    text = text.replace(",", "")
    try:
        if "." in text:
            return float(text)
        return int(text)
    except ValueError:
        return None


def _deepest_label(row: list[str], max_cols: int = 6) -> tuple[str | None, int]:
    label: str | None = None
    depth = 0
    for i, cell in enumerate(row[:max_cols]):
        c = cell.strip()
        if not c:
            continue
        if c.replace("-", "").replace("/", "").replace(".", "").isdigit():
            continue
        label = c
        depth = i
    return label, depth


def _is_header_noise(name: str) -> bool:
    return any(
        x in name
        for x in ("勘定科目", "月次推移", "試算表", "表示単位", "構成比")
    )


def _read_csv_rows(path: Path) -> list[list[str]]:
    data = path.read_bytes()
    for enc in ("cp932", "utf-8-sig", "utf-8"):
        try:
            return list(csv.reader(data.decode(enc).splitlines()))
        except UnicodeDecodeError:
            continue
    raise ValueError(f"文字コードを判定できません: {path}")


def _detect_format(filename: str, raw_rows: list[list[str]]) -> str:
    if "残高試算表" in filename:
        return "mfcloud"
    if raw_rows:
        header = raw_rows[0]
        if (
            len(header) >= 3
            and header[1].strip() == "勘定科目"
            and header[2].strip() == "補助科目"
        ):
            return "mfcloud"
    return "freee"


def parse_csv(
    path: Path,
    company_id: str,
    fmt: str | None = None,
    parse_options: dict | None = None,
) -> ParsedReport:
    raw_rows = _read_csv_rows(path)
    detected = fmt or _detect_format(path.name, raw_rows)
    options = parse_options or {}
    if detected == "mfcloud":
        from .parser_mfcloud import parse_mfcloud_csv, parse_mfcloud_monthly_csv

        if "損益" in path.name:
            statement: StatementType = "pl"
        elif "貸借" in path.name:
            statement = "bs"
        else:
            raise ValueError(f"損益/貸借を判定できません: {path.name}")
        if "月次推移" in path.name:
            return parse_mfcloud_monthly_csv(
                path,
                company_id,
                statement,
                fiscal_year_shift=int(options.get("fiscal_year_shift", 0)),
            )
        return parse_mfcloud_csv(path, company_id, statement)

    statement, report_type = _detect_meta(path.name)
    period_label, period_start, period_end = _extract_period(path.name)

    report = ParsedReport(
        company_id=company_id,
        statement=statement,
        report_type=report_type,
        period_label=period_label,
        period_start=period_start,
        period_end=period_end,
        source_file=path.name,
    )

    if report_type == "trial":
        _parse_trial(raw_rows, report)
    else:
        _parse_monthly(raw_rows, report)
    return report


def _find_col(header: list[str], *labels: str) -> int | None:
    for i, cell in enumerate(header):
        c = cell.strip()
        for label in labels:
            if c == label or label in c:
                return i
    return None


_SKIP_TRIAL_COLS = frozenset(
    {"構成比", "前期構成比", "当期構成比", "前年比", "勘定科目コード"}
)


def _is_trial_value_column(label: str) -> bool:
    c = label.strip()
    if not c or c in _SKIP_TRIAL_COLS:
        return False
    if c in ("借方金額", "借方", "貸方金額", "貸方", "前年差額"):
        return True
    if "期末" in c or "期首" in c:
        return True
    if re.match(r"\d{4}年-\d{2}月", c):
        return True
    if re.match(r"\d{4}-\d{2}\s+\d{4}-\d{2}", c):
        return True
    return False


def _parse_trial_header(header: list[str]) -> tuple[int, dict[str, int]]:
    """科目名・数値列の位置をヘッダーから動的に検出."""
    name_col = 1
    if header and header[0].strip() == "勘定科目コード":
        name_col = 1
    else:
        for i, cell in enumerate(header):
            if cell.strip() in ("勘定科目", "科目"):
                name_col = i + 1
                break

    value_cols: dict[str, int] = {}
    for i, cell in enumerate(header):
        c = cell.strip()
        if _is_trial_value_column(c):
            key = c
            if c in ("借方金額", "借方"):
                key = "借方"
            elif c in ("貸方金額", "貸方"):
                key = "貸方"
            value_cols[key] = i

    return name_col, value_cols


def _parse_trial(raw_rows: list[list[str]], report: ParsedReport) -> None:
    if len(raw_rows) < 2:
        return
    header = raw_rows[1]
    name_col, value_cols = _parse_trial_header(header)

    for row in raw_rows[2:]:
        if not any(cell.strip() for cell in row):
            continue

        code = ""
        if header and header[0].strip() == "勘定科目コード":
            code = row[0].strip() if row else ""

        name = row[name_col].strip() if len(row) > name_col else ""
        if not name:
            name, _ = _deepest_label(row, max_cols=name_col + 1)
        if not name or _is_header_noise(name):
            continue

        values: dict[str, int | float | None] = {}
        for label, col_idx in value_cols.items():
            if col_idx < len(row):
                val = _parse_amount(row[col_idx])
                if val is not None:
                    values[label] = val

        report.rows.append(
            AccountRow(
                raw_name=name,
                account_code=code or None,
                values=values,
                depth=0,
                is_section=not values and not name.endswith(("の部", " 計")),
            )
        )


_MONTH_COL = re.compile(r"^\d{4}-\d{2}$")
_SKIP_MONTHLY_COLS = frozenset({"期間累計", "構成比"})


def _parse_monthly(raw_rows: list[list[str]], report: ParsedReport) -> None:
    if len(raw_rows) < 2:
        return
    header = raw_rows[1]
    period_cols: list[tuple[int, str]] = []
    for i, cell in enumerate(header):
        c = cell.strip()
        if not c or c in _SKIP_MONTHLY_COLS:
            continue
        if c == "期首" or _MONTH_COL.match(c):
            period_cols.append((i, c))

    for row in raw_rows[2:]:
        if not any(cell.strip() for cell in row):
            continue
        name, depth = _deepest_label(row)
        if not name or _is_header_noise(name):
            continue

        values: dict[str, int | float | None] = {}
        for col_idx, col_name in period_cols:
            if col_idx < len(row):
                values[col_name] = _parse_amount(row[col_idx])

        if not values:
            report.rows.append(
                AccountRow(
                    raw_name=name,
                    account_code=None,
                    values={},
                    depth=depth,
                    is_section=True,
                )
            )
            continue

        report.rows.append(
            AccountRow(
                raw_name=name,
                account_code=None,
                values=values,
                depth=depth,
            )
        )


def _parse_options_from_config(meta: dict | None) -> dict:
    if not meta:
        return {}
    options: dict = {}
    if "fiscal_year_shift" in meta:
        options["fiscal_year_shift"] = meta["fiscal_year_shift"]
    return options


CONFIRMED_DIR = "確定"
PROVISIONAL_DIR = "未確定"
LEGACY_PROVISIONAL_DIR = "_provisional"


def company_has_data(data_dir: Path, folder: str) -> bool:
    """確定 / 未確定 / 旧 data/{会社}/ のいずれかに CSV があるか."""
    candidates = [
        data_dir / CONFIRMED_DIR / folder,
        data_dir / PROVISIONAL_DIR / folder,
        data_dir / folder,
        data_dir / folder / LEGACY_PROVISIONAL_DIR,
    ]
    for path in candidates:
        if path.is_dir() and any(path.glob("*.csv")):
            return True
    return False


def _confirmed_dirs(data_dir: Path, folder: str) -> list[Path]:
    return [data_dir / CONFIRMED_DIR / folder, data_dir / folder]


def _provisional_dirs(data_dir: Path, folder: str) -> list[Path]:
    return [
        data_dir / PROVISIONAL_DIR / folder,
        data_dir / folder / LEGACY_PROVISIONAL_DIR,
    ]


def dedupe_reports_by_period(reports: list[ParsedReport]) -> list[ParsedReport]:
    """同一期間は確定 CSV を未確定より優先."""
    groups: dict[tuple[str, str | None, str | None], list[ParsedReport]] = {}
    for report in reports:
        key = (report.statement, report.period_start, report.period_end)
        groups.setdefault(key, []).append(report)

    selected: list[ParsedReport] = []
    for items in groups.values():
        items.sort(
            key=lambda r: (
                0 if r.data_status == "confirmed" else 1,
                r.source_file,
            )
        )
        selected.append(items[0])
    return sorted(selected, key=lambda r: r.period_start or "")


def report_month_keys(report: ParsedReport) -> set[str]:
    keys: set[str] = set()
    for row in report.rows:
        for key in row.values:
            if re.match(r"^\d{4}-\d{2}$", key):
                keys.add(key)
    return keys


def load_company_reports(
    data_dir: Path,
    company_id: str,
    fmt: str | None = None,
    parse_options: dict | None = None,
    folder: str | None = None,
) -> list[ParsedReport]:
    folder = folder or company_id
    if not company_has_data(data_dir, folder):
        raise FileNotFoundError(
            f"data/確定/{folder} または data/未確定/{folder} に CSV がありません"
        )

    reports: list[ParsedReport] = []

    def load_path(path: Path, status: DataStatus) -> None:
        report = parse_csv(path, company_id, fmt=fmt, parse_options=parse_options)
        report.data_status = status
        reports.append(report)

    for confirmed_dir in _confirmed_dirs(data_dir, folder):
        if not confirmed_dir.is_dir():
            continue
        for path in sorted(confirmed_dir.glob("*.csv")):
            load_path(path, "confirmed")

    for prov_dir in _provisional_dirs(data_dir, folder):
        if not prov_dir.is_dir():
            continue
        for path in sorted(prov_dir.glob("*.csv")):
            load_path(path, "provisional")

    return reports
