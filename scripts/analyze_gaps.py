"""データ欠損分析."""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from total_company.aggregate import build_timeline, _period_sort_key
from total_company.cli import load_all_reports, load_companies_config, project_root
from total_company.dashboard import build_dashboard
from total_company.mapping import AccountMapper


def main() -> None:
    root = project_root()
    build_dashboard(root)
    config = load_companies_config(root)
    mapper = AccountMapper.from_yaml(root / "config" / "account_mapping.yaml")
    company_ids = sorted(config.keys())
    reports = load_all_reports(root / "data", company_ids, root)

    companies = []
    for cid in company_ids:
        meta = config[cid]
        reps = reports[cid]
        tl = build_timeline(cid, meta["name"], reps, mapper)

        pl_periods = sorted({end for acct in tl.pl.values() for end in acct}, key=_period_sort_key)
        bs_periods = sorted({end for acct in tl.bs.values() for end in acct}, key=_period_sort_key)
        all_periods = sorted({p.end for p in tl.periods}, key=_period_sort_key)

        files = []
        for r in sorted(reps, key=lambda x: x.period_start or ""):
            files.append(
                {
                    "file": r.source_file,
                    "statement": r.statement,
                    "type": r.report_type,
                    "period": r.period_label,
                    "end": r.period_end,
                    "rows": sum(1 for row in r.rows if row.values),
                }
            )

        companies.append(
            {
                "id": cid,
                "name": meta["name"],
                "format": meta.get("format", "freee"),
                "csv_count": len(reps),
                "pl_csv": sum(1 for r in reps if r.statement == "pl"),
                "bs_csv": sum(1 for r in reps if r.statement == "bs"),
                "monthly_csv": sum(1 for r in reps if r.report_type == "monthly"),
                "periods": all_periods,
                "pl_periods": pl_periods,
                "bs_periods": bs_periods,
                "no_pl": not pl_periods,
                "no_bs": not bs_periods,
                "files": files,
            }
        )

    all_ends = sorted({p for c in companies for p in c["periods"]}, key=_period_sort_key)
    by_period = []
    for end in all_ends:
        present = []
        missing = []
        for c in companies:
            has_pl = end in c["pl_periods"]
            has_bs = end in c["bs_periods"]
            if has_pl or has_bs:
                tag = "PL+BS" if has_pl and has_bs else ("PLのみ" if has_pl else "BSのみ")
                present.append({"id": c["id"], "name": c["name"], "tag": tag})
            else:
                missing.append({"id": c["id"], "name": c["name"]})
        by_period.append(
            {
                "end": end,
                "present_count": len(present),
                "present": present,
                "missing": missing,
            }
        )

    payload = json.loads((root / "output/dashboard/data.json").read_text(encoding="utf-8"))
    all_ds = next(c for c in payload["companies"] if c["company_id"] == "__all__")

    sparse_accounts = []
    for stmt in ("pl", "bs", "cf"):
        for acct, vals in all_ds.get(stmt, {}).items():
            null_ends = [
                all_ds["period_ends"][i]
                for i, v in enumerate(vals)
                if v is None
            ]
            if null_ends and len(null_ends) < len(all_ds["period_ends"]):
                sparse_accounts.append(
                    {"statement": stmt, "account": acct, "missing_periods": null_ends}
                )

    out = root / "output" / "data_gaps.json"
    out.write_text(
        json.dumps(
            {"companies": companies, "by_period": by_period, "sparse_account_count": len(sparse_accounts)},
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )

    print("=== 会社別 ===")
    for c in companies:
        print(f"\n【{c['name']}】 ({c['id']}, {c['format']})")
        print(f"  CSV {c['csv_count']}件: PL {c['pl_csv']} / BS {c['bs_csv']} / 月次 {c['monthly_csv']}")
        if c["no_pl"]:
            print("  ※ PL データなし")
        if c["no_bs"]:
            print("  ※ BS データなし")
        if c["periods"]:
            print(f"  ある年度(期末): {', '.join(c['periods'])}")
        else:
            print("  ある年度: なし")
        if c["pl_periods"] and c["bs_periods"]:
            pl_only = set(c["pl_periods"]) - set(c["bs_periods"])
            bs_only = set(c["bs_periods"]) - set(c["pl_periods"])
            if pl_only:
                print(f"  BSが無い年度: {', '.join(sorted(pl_only, key=_period_sort_key))}")
            if bs_only:
                print(f"  PLが無い年度: {', '.join(sorted(bs_only, key=_period_sort_key))}")

    print("\n=== 期末ごと（全社合算で空欄になる列） ===")
    for row in by_period:
        end = row["end"]
        n = row["present_count"]
        total = len(companies)
        if n < total:
            names = ", ".join(p["name"] for p in row["present"]) or "なし"
            miss = ", ".join(m["name"] for m in row["missing"])
            print(f"  {end} ({n}/{total}社): あり={names} / なし={miss}")

    print(f"\n詳細: {out}")


if __name__ == "__main__":
    main()
