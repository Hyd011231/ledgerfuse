"""活动账本 / 成员与双人结算 / 订阅 / 报销 / 净资产。"""
from __future__ import annotations

from datetime import datetime, timedelta

from ..db import get_conn

# 活动账本口径：活动内看每一笔真实消费（含信用卡消费明细），
# 但仍排除去重掉的银行侧影子与转账
ACT_BASE = ("t.is_deleted=0 AND t.status_ok=1 AND t.flow_type!='transfer' "
            "AND t.dup_status IN ('none','not_dup')")


# ---------------- 活动账本 ----------------
def activity_stats(activity_id: int) -> dict:
    conn = get_conn()
    act = conn.execute("SELECT * FROM activities WHERE id=?", (activity_id,)).fetchone()
    if not act:
        raise ValueError("活动不存在")
    total = conn.execute(
        f"SELECT COUNT(*) n, COALESCE(SUM(CASE WHEN direction='expense' THEN amount ELSE 0 END),0) exp, "
        f"COALESCE(SUM(CASE WHEN direction='income' THEN amount ELSE 0 END),0) inc "
        f"FROM transactions t WHERE t.activity_id=? AND {ACT_BASE}", (activity_id,)).fetchone()
    daily = [dict(r) for r in conn.execute(
        f"SELECT substr(t.trans_time,1,10) day, SUM(CASE WHEN direction='expense' THEN amount ELSE 0 END) exp, "
        f"COUNT(*) n FROM transactions t WHERE t.activity_id=? AND {ACT_BASE} "
        f"GROUP BY day ORDER BY day", (activity_id,))]
    cats = [dict(r) for r in conn.execute(
        f"""SELECT COALESCE(p.name, c.name) name, SUM(t.amount) total, COUNT(*) n
            FROM transactions t JOIN categories c ON c.id=t.category_id
            LEFT JOIN categories p ON p.id=c.parent_id
            WHERE t.activity_id=? AND {ACT_BASE} AND t.direction='expense'
            GROUP BY COALESCE(p.id, c.id) ORDER BY total DESC""", (activity_id,))]
    members = [dict(r) for r in conn.execute(
        f"""SELECT COALESCE(m.name,'未指定') name, SUM(t.amount) total, COUNT(*) n
            FROM transactions t
            LEFT JOIN accounts a ON a.id=t.account_id
            LEFT JOIN members m ON m.id=COALESCE(t.member_id, a.member_id)
            WHERE t.activity_id=? AND {ACT_BASE} AND t.direction='expense'
            GROUP BY m.id ORDER BY total DESC""", (activity_id,))]
    return {"activity": dict(act), "count": total["n"], "expense": total["exp"],
            "income": total["inc"], "daily": daily, "categories": cats, "members": members}


def activity_assign_range(activity_id: int, date_from: str, date_to: str,
                          exclude_fixed: bool = True) -> int:
    """按日期范围批量圈入活动。exclude_fixed 排除固定支出类（房租/水电/话费/物业/订阅）。"""
    conn = get_conn()
    if not conn.execute("SELECT 1 FROM activities WHERE id=?", (activity_id,)).fetchone():
        raise ValueError("活动不存在")
    cond = ("is_deleted=0 AND flow_type='normal' AND activity_id IS NULL "
            "AND trans_time>=? AND trans_time<=?")
    args: list = [date_from, date_to + " 23:59:59"]
    if exclude_fixed:
        cond += (" AND category_id NOT IN (SELECT id FROM categories WHERE name IN "
                 "('房租','水电燃气','物业','话费网费','会员订阅','短信服务费','信用卡还款','工资薪酬','投资理财')"
                 " OR parent_id IN (SELECT id FROM categories WHERE name IN ('居住','投资理财')))")
    cur = conn.execute(f"UPDATE transactions SET activity_id=? WHERE {cond}",
                       [activity_id] + args)
    conn.commit()
    return cur.rowcount


# ---------------- 双人结算 ----------------
def settle(month: str | None = None) -> dict:
    """结算：每人实付（自己账户的支出）vs 应担（个人支出 + 共同支出均摊）。"""
    conn = get_conn()
    base = ("t.is_deleted=0 AND t.status_ok=1 AND t.flow_type='normal' "
            "AND t.dup_status IN ('none','not_dup') AND t.direction='expense'")
    args: list = []
    if month:
        base += " AND substr(t.trans_time,1,7)=?"
        args.append(month)
    members = [dict(r) for r in conn.execute("SELECT * FROM members ORDER BY is_self DESC")]
    rows = conn.execute(f"""
        SELECT COALESCE(t.member_id, a.member_id) mid, t.is_shared, SUM(t.amount) s, COUNT(*) n
        FROM transactions t LEFT JOIN accounts a ON a.id=t.account_id
        WHERE {base} GROUP BY mid, t.is_shared""", args).fetchall()
    paid: dict = {m["id"]: 0 for m in members}
    personal: dict = {m["id"]: 0 for m in members}
    shared_total = 0
    unassigned = 0
    for r in rows:
        mid = r["mid"]
        if mid not in paid:
            unassigned += r["s"]
            continue
        paid[mid] += r["s"]
        if r["is_shared"]:
            shared_total += r["s"]
        else:
            personal[mid] += r["s"]
    n = max(len(members), 1)
    share_each = shared_total // n if n else 0
    out = []
    for m in members:
        owed = personal[m["id"]] + share_each
        out.append({"member": m["name"], "member_id": m["id"], "is_self": m["is_self"],
                    "paid": paid[m["id"]], "personal": personal[m["id"]],
                    "shared_part": share_each, "owed": owed,
                    "balance": paid[m["id"]] - owed})   # 正数=多付了，别人欠TA
    return {"month": month, "members": out, "shared_total": shared_total,
            "unassigned": unassigned}


# ---------------- 订阅 ----------------
def detect_subscriptions() -> list[dict]:
    """从定期支出检测里找候选（排除已登记的）。"""
    from . import stats as st
    conn = get_conn()
    known = {r["merchant"] for r in conn.execute("SELECT merchant FROM subscriptions")}
    out = []
    for r in st.recurring_expenses(min_months=3):
        if r["merchant"] in known:
            continue
        try:
            d1 = datetime.fromisoformat(r["first_time"])
            d2 = datetime.fromisoformat(r["last_time"])
            period = max(1, (d2 - d1).days // max(r["n"] - 1, 1))
        except ValueError:
            period = 30
        out.append({**r, "period_days": period})
    return out


def subscription_list() -> list[dict]:
    conn = get_conn()
    out = []
    for r in conn.execute("SELECT * FROM subscriptions WHERE active=1 ORDER BY avg_amount DESC"):
        d = dict(r)
        last = conn.execute(
            "SELECT MAX(trans_time) t, COUNT(*) n, COALESCE(SUM(amount),0) total "
            "FROM transactions WHERE counterparty=? AND direction='expense' AND is_deleted=0 "
            "AND flow_type='normal' AND dup_status IN ('none','not_dup')",
            (r["merchant"],)).fetchone()
        d["last_time"] = last["t"] or d["last_time"]
        d["total_spent"] = last["total"]
        d["times"] = last["n"]
        if d["last_time"]:
            try:
                nxt = datetime.fromisoformat(d["last_time"]) + timedelta(days=d["period_days"])
                d["next_estimate"] = nxt.strftime("%Y-%m-%d")
            except ValueError:
                d["next_estimate"] = None
        yearly = int(d["avg_amount"] * 365 / max(d["period_days"], 1))
        d["yearly_estimate"] = yearly
        out.append(d)
    return out


# ---------------- 报销 ----------------
def reimburse_summary() -> dict:
    conn = get_conn()
    pending = conn.execute(
        "SELECT COUNT(*) n, COALESCE(SUM(amount),0) s FROM transactions "
        "WHERE reimburse_status='pending' AND is_deleted=0").fetchone()
    done = conn.execute(
        "SELECT COUNT(*) n, COALESCE(SUM(amount),0) s FROM transactions "
        "WHERE reimburse_status='done' AND is_deleted=0").fetchone()
    items = [dict(r) for r in conn.execute(
        """SELECT t.id, t.trans_time, t.amount, t.counterparty, t.description, c.name category
           FROM transactions t LEFT JOIN categories c ON c.id=t.category_id
           WHERE t.reimburse_status='pending' AND t.is_deleted=0
           ORDER BY t.trans_time DESC""")]
    return {"pending_count": pending["n"], "pending_total": pending["s"],
            "done_count": done["n"], "done_total": done["s"], "pending_items": items}


# ---------------- 净资产曲线 ----------------
def balance_trend() -> dict:
    """各银行账户按日末笔余额（前向填充），及合计。"""
    conn = get_conn()
    accounts = [dict(r) for r in conn.execute(
        "SELECT id, name FROM accounts WHERE type='bank' ORDER BY id")]
    series: dict[int, dict[str, int]] = {}
    all_days: set[str] = set()
    for a in accounts:
        rows = conn.execute(
            "SELECT substr(trans_time,1,10) day, balance_after FROM transactions "
            "WHERE account_id=? AND balance_after IS NOT NULL AND is_deleted=0 "
            "ORDER BY trans_time, id", (a["id"],)).fetchall()
        daily: dict[str, int] = {}
        for r in rows:
            daily[r["day"]] = r["balance_after"]     # 同日取末笔
        series[a["id"]] = daily
        all_days.update(daily)
    days = sorted(all_days)
    out_series = []
    totals = []
    fills: dict[int, int | None] = {a["id"]: None for a in accounts}
    per_acct: dict[int, list] = {a["id"]: [] for a in accounts}
    for d in days:
        tot = 0
        for a in accounts:
            v = series[a["id"]].get(d)
            if v is not None:
                fills[a["id"]] = v
            per_acct[a["id"]].append(fills[a["id"]])
            tot += fills[a["id"]] or 0
        totals.append(tot)
    for a in accounts:
        out_series.append({"name": a["name"], "data": per_acct[a["id"]]})
    return {"days": days, "series": out_series, "total": totals}
