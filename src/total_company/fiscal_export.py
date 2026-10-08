"""決算期ビュー HTML 出力."""

from __future__ import annotations

import json
import shutil
from pathlib import Path

from .display import DisplayChart
from .fiscal_year import build_fiscal_year_display
from .mapping import AccountMapper


def build_fiscal_dashboard(
    root: Path,
    companies: list[str] | None = None,
) -> list[Path]:
    from .cli import load_all_reports, load_companies_config
    from .parser import company_has_data

    root = Path(root)
    config = load_companies_config(root)
    mapper = AccountMapper.from_yaml(root / "config" / "account_mapping.yaml")
    chart = DisplayChart.from_yaml(root / "config" / "display_chart.yaml")
    data_dir = root / "data"

    if companies is None:
        companies = sorted(
            cid
            for cid, meta in config.items()
            if company_has_data(data_dir, meta.get("folder", cid))
        )

    out_roots: list[Path] = []
    web_src = root / "web"

    for cid in companies:
        meta = config.get(cid, {})
        name = meta.get("name", cid)
        reports = load_all_reports(data_dir, [cid], root)[cid]
        display = build_fiscal_year_display(cid, name, reports, mapper, chart)
        out_dir = root / "output" / "fiscal" / cid
        out_dir.mkdir(parents=True, exist_ok=True)

        (out_dir / "data.json").write_text(
            json.dumps(display, ensure_ascii=False), encoding="utf-8"
        )
        for fname in ("fiscal.html", "fiscal.js", "styles.css"):
            src = web_src / fname
            if src.is_file():
                shutil.copy2(src, out_dir / fname)
        # 入口
        index = out_dir / "index.html"
        if (web_src / "fiscal.html").is_file():
            shutil.copy2(web_src / "fiscal.html", index)

        out_roots.append(out_dir)

    return out_roots


def project_root() -> Path:
    return Path(__file__).resolve().parents[2]
