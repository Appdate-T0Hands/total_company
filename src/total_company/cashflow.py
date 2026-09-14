"""簡易キャッシュフロー（役員借入金を除く財務CF）."""

from __future__ import annotations

from .aggregate import CompanyTimeline, _period_sort_key

# 財務CFから除外（ユーザー指定）
FINANCING_EXCLUDE = frozenset(
    {
        "役員借入金",
        "役員貸付金",
        "株主借入金",
    }
)

CASH_ACCOUNTS = frozenset(
    {
        "現金及び預金",
        "現金",
        "銀行預金",
        "銀行預金（API連携）",
        "普通預金",
    }
)

WORKING_CAPITAL_ASSETS = frozenset(
    {
        "売掛金",
        "医業未収金",
        "未収入金",
        "未収収益",
        "前払費用",
        "前払金",
        "仮払金",
        "仮払税金",
        "仮払消費税",
        "仮払法人税",
        "立替金",
        "短期貸付金",
        "商品売上原価",
    }
)

WORKING_CAPITAL_LIABILITIES = frozenset(
    {
        "買掛金",
        "未払金",
        "未払費用",
        "未払消費税等",
        "未払消費税",
        "未払法人税等",
        "預り金",
        "仮受金",
        "クレジットカード未払",
    }
)

FIXED_ASSET_ACCOUNTS = frozenset(
    {
        "有形固定資産",
        "無形固定資産",
        "固定資産",
        "建物",
        "建物附属設備",
        "工具器具備品",
        "車両運搬具",
        "土地",
        "ソフトウェア",
        "一括償却資産",
        "有価証券",
        "投資その他の資産",
        "差入保証金",
        "保証金",
        "長期前払費用",
        "建設仮勘定",
    }
)

FINANCING_ACCOUNTS = frozenset(
    {
        "長期借入金",
        "短期借入金",
        "リース債務",
        "資本金",
        "資本剰余金",
    }
)

PL_NET_INCOME_KEYS = (
    "当期純損益金額",
    "当期純利益",
    "（うち当期純利益）",
)

PL_DEPRECIATION_KEYS = ("減価償却費",)


def _bs_get(bs: dict[str, dict[str, float]], account: str, period: str) -> float:
    return bs.get(account, {}).get(period, 0.0)


def _pl_get(pl: dict[str, dict[str, float]], keys: tuple[str, ...], period: str) -> float:
    for key in keys:
        if key in pl and period in pl[key]:
            return pl[key][period]
    return 0.0


def _sum_accounts(
    bs: dict[str, dict[str, float]], accounts: frozenset[str], period: str
) -> float:
    total = 0.0
    for acct in bs:
        if acct in accounts or any(a in acct for a in accounts):
            total += bs[acct].get(period, 0.0)
    return total


def _cash_total(bs: dict[str, dict[str, float]], period: str) -> float:
    total = 0.0
    for acct, series in bs.items():
        if acct in CASH_ACCOUNTS or "預金" in acct or acct == "現金":
            total += series.get(period, 0.0)
    return total


def _wc_change(
    bs: dict[str, dict[str, float]], prev: str, curr: str
) -> float:
    """運転資本増加は CF マイナス."""
    asset_delta = _sum_accounts(bs, WORKING_CAPITAL_ASSETS, curr) - _sum_accounts(
        bs, WORKING_CAPITAL_ASSETS, prev
    )
    liab_delta = _sum_accounts(bs, WORKING_CAPITAL_LIABILITIES, curr) - _sum_accounts(
        bs, WORKING_CAPITAL_LIABILITIES, prev
    )
    return -(asset_delta - liab_delta)


def compute_cashflow(timeline: CompanyTimeline) -> dict[str, dict[str, float]]:
    """各年度（期末）について、その年度の CF を計算."""
    cf: dict[str, dict[str, float]] = {}
    ends = [p.end for p in timeline.periods]
    if len(ends) < 2:
        return cf

    for i in range(1, len(ends)):
        prev, curr = ends[i - 1], ends[i]
        pl, bs = timeline.pl, timeline.bs

        net_income = _pl_get(pl, PL_NET_INCOME_KEYS, curr)
        depreciation = _pl_get(pl, PL_DEPRECIATION_KEYS, curr)
        wc = _wc_change(bs, prev, curr)

        fixed_prev = _sum_accounts(bs, FIXED_ASSET_ACCOUNTS, prev)
        fixed_curr = _sum_accounts(bs, FIXED_ASSET_ACCOUNTS, curr)
        investing = -(fixed_curr - fixed_prev)

        financing = 0.0
        for acct, series in bs.items():
            if acct in FINANCING_EXCLUDE or "役員借" in acct or "役員貸" in acct:
                continue
            if acct in FINANCING_ACCOUNTS or ("借入" in acct and "役員" not in acct):
                financing += series.get(curr, 0.0) - series.get(prev, 0.0)

        operating = net_income + depreciation + wc
        cash_delta = _cash_total(bs, curr) - _cash_total(bs, prev)
        adjustment = cash_delta - (operating + investing + financing)

        cf.setdefault("当期純損益", {})[curr] = net_income
        cf.setdefault("減価償却費", {})[curr] = depreciation
        cf.setdefault("運転資本増減", {})[curr] = wc
        cf.setdefault("営業CF", {})[curr] = operating
        cf.setdefault("投資CF", {})[curr] = investing
        cf.setdefault("財務CF（役員借入除く）", {})[curr] = financing
        cf.setdefault("現金増減（BS）", {})[curr] = cash_delta
        cf.setdefault("調整差額", {})[curr] = adjustment

    return cf


def timeline_to_dict(timeline: CompanyTimeline) -> dict:
    cf = compute_cashflow(timeline)
    periods = [p.end for p in timeline.periods]
    pl_accounts = sorted(timeline.pl.keys())
    bs_accounts = sorted(timeline.bs.keys())
    cf_accounts = sorted(cf.keys())

    return {
        "company_id": timeline.company_id,
        "company_name": timeline.company_name,
        "periods": [
            {"end": p.end, "label": p.label, "start": p.start, "source": p.source_file}
            for p in timeline.periods
        ],
        "pl": {a: [timeline.pl[a].get(p, None) for p in periods] for a in pl_accounts},
        "bs": {a: [timeline.bs[a].get(p, None) for p in periods] for a in bs_accounts},
        "cf": {a: [cf[a].get(p, None) for p in periods] for a in cf_accounts},
        "period_ends": periods,
    }
