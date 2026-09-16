"""ダッシュボード HTML / JSON 生成."""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import yaml

from .display import DisplayChart
from .mapping import AccountMapper
from .monthly import build_consolidated_monthly_display, build_monthly_display


def load_dashboard_config(root: Path) -> dict:
    path = root / "config" / "dashboard.yaml"
    if not path.is_file():
        return {}
    return yaml.safe_load(path.read_text(encoding="utf-8")) or {}


def build_dashboard(
    root: Path,
    companies: list[str] | None = None,
    config: dict | None = None,
    mapper: AccountMapper | None = None,
    chart: DisplayChart | None = None,
) -> Path:
    from .cli import load_all_reports, load_companies_config
    from .parser import company_has_data

    root = Path(root)
    config = config or load_companies_config(root)
    dash_cfg = load_dashboard_config(root)
    mapper = mapper or AccountMapper.from_yaml(root / "config" / "account_mapping.yaml")
    chart = chart or DisplayChart.from_yaml(root / "config" / "display_chart.yaml")
    data_dir = root / "data"

    exclude = set(dash_cfg.get("exclude_companies", []))
    for cid, meta in config.items():
        if meta.get("dashboard") is False:
            exclude.add(cid)

    if companies is None:
        companies = sorted(
            cid
            for cid, meta in config.items()
            if cid not in exclude
            and company_has_data(data_dir, meta.get("folder", cid))
        )
    else:
        companies = [c for c in companies if c not in exclude]

    reports_by_company = load_all_reports(data_dir, companies, root)
    company_displays = []
    by_id: dict[str, dict] = {}

    for cid in companies:
        meta = config.get(cid, {})
        name = meta.get("name", cid)
        reports = reports_by_company[cid]
        monthly_reports = [r for r in reports if r.report_type == "monthly"]
        if not monthly_reports:
            continue
        display = build_monthly_display(cid, name, reports, mapper, chart)
        company_displays.append(display)
        by_id[cid] = display

    consolidated_displays = []
    company_list = []
    default_id = None

    for group in dash_cfg.get("consolidated_groups", []):
        member_displays = [by_id[mid] for mid in group.get("members", []) if mid in by_id]
        if len(member_displays) < 2:
            continue
        consolidated = build_consolidated_monthly_display(
            group["id"],
            group["name"],
            member_displays,
        )
        consolidated_displays.append(consolidated)
        company_list.append(
            {
                "id": consolidated["company_id"],
                "name": consolidated["company_name"],
                "type": "consolidated",
            }
        )
        if group.get("default"):
            default_id = consolidated["company_id"]

    for display in company_displays:
        company_list.append(
            {
                "id": display["company_id"],
                "name": display["company_name"],
                "type": "single",
            }
        )

    if default_id is None and company_list:
        default_id = company_list[0]["id"]

    out_dir = root / "output" / "dashboard"
    out_dir.mkdir(parents=True, exist_ok=True)

    payload = {
        "mode": "monthly",
        "default_company_id": default_id,
        "companies": consolidated_displays + company_displays,
        "company_list": company_list,
    }

    (out_dir / "data.json").write_text(
        json.dumps(payload, ensure_ascii=False), encoding="utf-8"
    )

    web_src = root / "web"
    if web_src.is_dir():
        for name in ("index.html", "chart.html", "app.js", "chart.js", "styles.css"):
            src = web_src / name
            if src.is_file():
                shutil.copy2(src, out_dir / name)

    return out_dir
