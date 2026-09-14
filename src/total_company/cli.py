"""CLI エントリポイント."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import yaml

from .mapping import (
    AccountMapper,
    find_cross_company_variants,
    find_mapping_candidates,
    normalize_report,
)
from .parser import company_has_data, load_company_reports


def project_root() -> Path:
    return Path(__file__).resolve().parents[2]


def load_companies_config(root: Path) -> dict:
    path = root / "config" / "companies.yaml"
    if not path.is_file():
        return {}
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    return data.get("companies", {})


def load_all_reports(data_dir: Path, companies: list[str], root: Path | None = None) -> dict[str, list]:
    from .parser import _parse_options_from_config

    config = load_companies_config(root or project_root())
    return {
        cid: load_company_reports(
            data_dir,
            cid,
            fmt=config.get(cid, {}).get("format"),
            parse_options=_parse_options_from_config(config.get(cid, {})),
            folder=config.get(cid, {}).get("folder", cid),
        )
        for cid in companies
    }


def cmd_scan(args: argparse.Namespace) -> int:
    root = project_root()
    mapper = AccountMapper.from_yaml(root / "config" / "account_mapping.yaml")
    data_dir = root / "data"

    if args.company:
        companies = [args.company]
    else:
        companies = sorted(
            cid
            for cid, meta in load_companies_config(root).items()
            if company_has_data(data_dir, meta.get("folder", cid))
        )

    reports_by_company = load_all_reports(data_dir, companies, root)
    unmapped = find_mapping_candidates(reports_by_company, mapper)
    variants = find_cross_company_variants(reports_by_company, mapper)

    print("=== 未マッピング科目（そのまま表示される名称） ===")
    for company_id, names in unmapped.items():
        print(f"\n[{company_id}] {len(names)} 件")
        for name in names:
            print(f"  - {name}")

    if variants:
        print("\n=== 会社間で名称差分あり（統一済み） ===")
        for item in variants:
            print(f"\n{item['statement'].upper()} / {item['canonical']}")
            for company_id, raw_names in item["by_company"].items():
                print(f"  {company_id}: {', '.join(raw_names)}")

    if args.json:
        out = root / "output" / "scan_result.json"
        out.parent.mkdir(exist_ok=True)
        out.write_text(
            json.dumps({"unmapped": unmapped, "variants": variants}, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        print(f"\nJSON: {out}")

    return 0


def cmd_normalize(args: argparse.Namespace) -> int:
    root = project_root()
    mapper = AccountMapper.from_yaml(root / "config" / "account_mapping.yaml")
    data_dir = root / "data"
    config = load_companies_config(root)
    from .parser import _parse_options_from_config

    meta = config.get(args.company, {})
    reports = load_company_reports(
        data_dir,
        args.company,
        fmt=meta.get("format"),
        parse_options=_parse_options_from_config(meta),
        folder=meta.get("folder", args.company),
    )

    if args.file:
        reports = [r for r in reports if r.source_file == args.file]
        if not reports:
            print(f"ファイルが見つかりません: {args.file}", file=sys.stderr)
            return 1

    output: list[dict] = []
    for report in reports:
        normalized = normalize_report(report, mapper)
        output.append(
            {
                "company": report.company_id,
                "statement": report.statement,
                "report_type": report.report_type,
                "period": report.period_label,
                "source_file": report.source_file,
                "rows": [
                    {
                        "canonical": row.canonical_name,
                        "raw_names": row.raw_names,
                        "rule_ids": row.rule_ids,
                        "values": row.values,
                        "is_section": row.is_section,
                    }
                    for row in normalized
                    if row.values or row.is_section
                ],
            }
        )

    if args.json:
        out_dir = root / "output" / "normalized" / args.company
        out_dir.mkdir(parents=True, exist_ok=True)
        for item in output:
            fname = item["source_file"].replace(".csv", ".json")
            path = out_dir / fname
            path.write_text(json.dumps(item, ensure_ascii=False, indent=2), encoding="utf-8")
            print(path)
    else:
        for item in output:
            print(f"\n=== {item['source_file']} ({item['statement']}) ===")
            for row in item["rows"]:
                if row["is_section"] and not row["values"]:
                    print(f"[{row['canonical']}]")
                    continue
                raw = ""
                if len(row["raw_names"]) > 1 or (
                    row["raw_names"] and row["raw_names"][0] != row["canonical"]
                ):
                    raw = f"  ← {', '.join(row['raw_names'])}"
                vals = row["values"]
                if len(vals) == 1:
                    v = next(iter(vals.values()))
                    print(f"  {row['canonical']}: {v:,}{raw}")
                elif vals:
                    preview = ", ".join(f"{k}={v:,}" for k, v in list(vals.items())[:3])
                    print(f"  {row['canonical']}: {preview}{raw}")

    return 0


def cmd_dashboard(args: argparse.Namespace) -> int:
    from .dashboard import build_dashboard

    root = project_root()
    companies = [args.company] if args.company else None
    out_dir = build_dashboard(root, companies=companies)
    print(f"Dashboard: {out_dir / 'index.html'}")

    if args.serve:
        import functools
        import http.server
        import webbrowser

        port = args.port
        handler = functools.partial(
            http.server.SimpleHTTPRequestHandler, directory=str(out_dir)
        )
        httpd = http.server.ThreadingHTTPServer(("127.0.0.1", port), handler)
        url = f"http://127.0.0.1:{port}/index.html"
        print(f"Serving {out_dir} at {url}")
        if args.open:
            webbrowser.open(url)
        try:
            httpd.serve_forever()
        except KeyboardInterrupt:
            print("\nStopped.")
    return 0


def cmd_list_accounts(args: argparse.Namespace) -> int:
    root = project_root()
    data_dir = root / "data"
    config = load_companies_config(root)
    from .parser import _parse_options_from_config

    meta = config.get(args.company, {})
    reports = load_company_reports(
        data_dir,
        args.company,
        fmt=meta.get("format"),
        parse_options=_parse_options_from_config(meta),
        folder=meta.get("folder", args.company),
    )
    accounts: dict[str, set[str]] = {"pl": set(), "bs": set()}

    for report in reports:
        for row in report.rows:
            if row.raw_name:
                accounts[report.statement].add(row.raw_name)

    for stmt in ("pl", "bs"):
        print(f"\n=== {stmt.upper()} ({len(accounts[stmt])} 件) ===")
        for name in sorted(accounts[stmt]):
            print(f"  {name}")

    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="total_company: 全会社会計統一ビュー")
    sub = parser.add_subparsers(dest="command", required=True)

    p_scan = sub.add_parser("scan", help="未マッピング科目・会社間差分を確認")
    p_scan.add_argument("--company", help="特定会社のみ")
    p_scan.add_argument("--json", action="store_true", help="JSON 出力")
    p_scan.set_defaults(func=cmd_scan)

    p_norm = sub.add_parser("normalize", help="統一科目名に変換して表示")
    p_norm.add_argument("company", help="会社 ID (例: appdate)")
    p_norm.add_argument("--file", help="特定 CSV のみ")
    p_norm.add_argument("--json", action="store_true", help="JSON ファイル出力")
    p_norm.set_defaults(func=cmd_normalize)

    p_list = sub.add_parser("list-accounts", help="raw 科目名一覧")
    p_list.add_argument("company", help="会社 ID")
    p_list.set_defaults(func=cmd_list_accounts)

    p_dash = sub.add_parser("dashboard", help="BS/PL/CF ダッシュボード生成・表示")
    p_dash.add_argument("--company", help="特定会社のみ")
    p_dash.add_argument("--serve", action="store_true", help="ローカルサーバー起動")
    p_dash.add_argument("--port", type=int, default=8765, help="ポート番号")
    p_dash.add_argument("--open", action="store_true", help="ブラウザを開く")
    p_dash.set_defaults(func=cmd_dashboard)

    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
