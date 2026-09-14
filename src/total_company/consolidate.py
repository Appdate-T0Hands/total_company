"""全社合算."""

from __future__ import annotations

from .aggregate import _period_sort_key

ALL_COMPANY_ID = "__all__"
ALL_COMPANY_NAME = "全社合算"


def merge_datasets(datasets: list[dict]) -> dict | None:
    if len(datasets) < 2:
        return None

    all_ends = sorted(
        {end for ds in datasets for end in ds["period_ends"]},
        key=_period_sort_key,
    )
    contributors: dict[str, list[str]] = {end: [] for end in all_ends}

    pl_merged: dict[str, dict[str, float]] = {}
    bs_merged: dict[str, dict[str, float]] = {}
    cf_merged: dict[str, dict[str, float]] = {}

    for ds in datasets:
        cid = ds["company_id"]
        cname = ds["company_name"]
        for i, end in enumerate(ds["period_ends"]):
            contributed = False

            for acct, vals in ds.get("pl", {}).items():
                v = vals[i] if i < len(vals) else None
                if v is not None:
                    pl_merged.setdefault(acct, {})
                    pl_merged[acct][end] = pl_merged[acct].get(end, 0.0) + float(v)
                    contributed = True

            for acct, vals in ds.get("bs", {}).items():
                v = vals[i] if i < len(vals) else None
                if v is not None:
                    bs_merged.setdefault(acct, {})
                    bs_merged[acct][end] = bs_merged[acct].get(end, 0.0) + float(v)
                    contributed = True

            for acct, vals in ds.get("cf", {}).items():
                v = vals[i] if i < len(vals) else None
                if v is not None:
                    cf_merged.setdefault(acct, {})
                    cf_merged[acct][end] = cf_merged[acct].get(end, 0.0) + float(v)

            if contributed:
                entry = {"id": cid, "name": cname}
                if entry not in [{**x} for x in contributors[end]]:
                    if not any(x["id"] == cid for x in contributors[end]):
                        contributors[end].append({"id": cid, "name": cname})

    pl_accounts = sorted(pl_merged.keys())
    bs_accounts = sorted(bs_merged.keys())
    cf_accounts = sorted(cf_merged.keys())

    contributor_names = {
        end: [c["name"] for c in contributors[end]] for end in all_ends
    }

    return {
        "company_id": ALL_COMPANY_ID,
        "company_name": ALL_COMPANY_NAME,
        "is_consolidated": True,
        "periods": [{"end": e, "label": e, "start": None, "source": ""} for e in all_ends],
        "period_ends": all_ends,
        "contributors": contributor_names,
        "pl": {
            a: [pl_merged[a].get(p, None) for p in all_ends] for a in pl_accounts
        },
        "bs": {
            a: [bs_merged[a].get(p, None) for p in all_ends] for a in bs_accounts
        },
        "cf": {
            a: [cf_merged[a].get(p, None) for p in all_ends] for a in cf_accounts
        },
    }
