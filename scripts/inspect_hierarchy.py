import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from total_company.parser import load_company_reports

for cid, fmt in [("ej", "mfcloud"), ("appdate", None), ("jincli", None)]:
    reps = load_company_reports(Path("data"), cid, fmt=fmt)
    bs = [r for r in reps if r.statement == "bs"][-1]
    print("===", cid, bs.source_file[:40], "===")
    for row in bs.rows[:25]:
        if row.values:
            print(row.raw_name, list(row.values.keys())[:2])
    aws = [r for r in bs.rows if "AWS" in r.raw_name or "Google" in r.raw_name]
    print("AWS/Google rows:", [(r.raw_name, r.values) for r in aws[:5]])
    print()
