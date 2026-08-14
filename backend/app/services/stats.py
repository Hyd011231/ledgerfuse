"""统计聚合：看板、趋势、分类占比、Top 商户、习惯分析、大额、定期支出等。"""
from __future__ import annotations

from ..db import get_conn

# 计入统计的记录集合
BASE = ("t.is_deleted=0 AND t.status_ok=1 AND t.flow_type='normal' "
        "AND t.dup_status IN ('none','not_dup')")
# 成员视角需要 join 账户推断归属
MEMBER_JOIN = " LEFT JOIN accounts am ON am.id=t.account_id "


def _member_cond(member_id: int | None) -> tuple[str, list]:
    if member_id is None:
        return "", []
    return " AND COALESCE(t.member_id, am.member_id)=?", [member_id]


def _rows(sql: str, *args) -> list[dict]:
    return [dict(r) for r in get_conn().execute(sql, args).fetchall()]


def overview(month: str | None = None, member_id: int | None = None) -> dict:
    cond, args = BASE, []
    if month:
        cond += " AND substr(t.trans_time,1,7)=?"
        args.append(month)
    mc, ma = _member_cond(member_id)
    cond += mc
    args += ma
    r = _rows(f"""SELECT
        SUM(CASE WHEN direction='income' THEN amount ELSE 0 END) AS income,
        SUM(CASE WHEN direction='expense' THEN amount ELSE 0 END) AS expense,
        COUNT(*) AS n FROM transactions t{MEMBER_JOIN}WHERE {cond}""", *args)[0]
    refund = _rows(f"""SELECT COALESCE(SUM(t.amount),0) AS s FROM transactions t{MEMBER_JOIN}
        JOIN categories c ON c.id=t.category_id
        WHERE {cond} AND t.direction='income' AND c.name IN ('退款')""", *args)[0]["s"]
    suspects = _rows("SELECT COUNT(*) AS n FROM transactions t WHERE t.dup_status='suspect'")[0]["n"]
    uncat = _rows(f"""SELECT COUNT(*) AS n FROM transactions t{MEMBER_JOIN}
        JOIN categories c ON c.id=t.category_id WHERE {cond} AND c.name='未分类'""", *args)[0]["n"]
    return {"income": r["income"] or 0, "expense": r["expense"] or 0,
            "net": (r["income"] or 0) - (r["expense"] or 0),
            "net_expense": (r["expense"] or 0) - refund,
            "count": r["n"], "suspect_count": suspects, "uncategorized_count": uncat}


def monthly_trend(date_from: str | None = None, date_to: str | None = None,
                  member_id: int | None = None) -> list[dict]:
    cond, args = BASE, []
    if date_from:
        cond += " AND t.trans_time>=?"
        args.append(date_from)
    if date_to:
        cond += " AND t.trans_time<=?"
        args.append(date_to + " 23:59:59")
    mc, ma = _member_cond(member_id)
    cond += mc
    args += ma
    return _rows(f"""SELECT substr(t.trans_time,1,7) AS month,
        SUM(CASE WHEN direction='income' THEN amount ELSE 0 END) AS income,
        SUM(CASE WHEN direction='expense' THEN amount ELSE 0 END) AS expense,
        COUNT(*) AS n
        FROM transactions t{MEMBER_JOIN}WHERE {cond} GROUP BY month ORDER BY month""", *args)


def category_breakdown(month: str | None = None, direction: str = "expense",
                       parent_id: int | None = None, member_id: int | None = None) -> list[dict]:
    cond, args = BASE + " AND t.direction=?", [direction]
    if month:
        cond += " AND substr(t.trans_time,1,7)=?"
        args.append(month)
    mc, ma = _member_cond(member_id)
    cond += mc
    args += ma
    if parent_id is not None:
        cond += " AND (c.parent_id=? OR c.id=?)"
        args += [parent_id, parent_id]
        group = "c.id, c.name"
        sel = "c.id AS category_id, c.name AS name"
    else:
        group = "COALESCE(p.id, c.id), COALESCE(p.name, c.name)"
        sel = "COALESCE(p.id, c.id) AS category_id, COALESCE(p.name, c.name) AS name"
    return _rows(f"""SELECT {sel}, COUNT(*) AS n, SUM(t.amount) AS total
        FROM transactions t{MEMBER_JOIN}JOIN categories c ON c.id=t.category_id
        LEFT JOIN categories p ON p.id=c.parent_id
        WHERE {cond} GROUP BY {group} ORDER BY total DESC""", *args)


def top_merchants(month: str | None = None, limit: int = 10, direction: str = "expense",
                  member_id: int | None = None) -> list[dict]:
    cond, args = BASE + " AND t.direction=? AND t.counterparty!=''", [direction]
    if month:
        cond += " AND substr(t.trans_time,1,7)=?"
        args.append(month)
    mc, ma = _member_cond(member_id)
    cond += mc
    args += ma
    return _rows(f"""SELECT t.counterparty AS merchant, COUNT(*) AS n, SUM(t.amount) AS total
        FROM transactions t{MEMBER_JOIN}WHERE {cond}
        GROUP BY t.counterparty ORDER BY total DESC LIMIT ?""", *args, limit)


def weekday_hour_heatmap(month: str | None = None, member_id: int | None = None) -> list[dict]:
    """消费习惯：星期 x 小时 热力图（仅有精确时间的渠道记录）。"""
    cond, args = BASE + " AND t.direction='expense' AND t.time_precision='second'", []
    if month:
        cond += " AND substr(t.trans_time,1,7)=?"
        args.append(month)
    mc, ma = _member_cond(member_id)
    cond += mc
    args += ma
    return _rows(f"""SELECT CAST(strftime('%w', t.trans_time) AS INT) AS weekday,
        CAST(strftime('%H', t.trans_time) AS INT) AS hour,
        COUNT(*) AS n, SUM(t.amount) AS total
        FROM transactions t{MEMBER_JOIN}WHERE {cond} GROUP BY weekday, hour""", *args)


def large_transactions(threshold_cents: int = 50000, month: str | None = None,
                       limit: int = 50) -> list[dict]:
    cond, args = BASE + " AND t.direction='expense' AND t.amount>=?", [threshold_cents]
    if month:
        cond += " AND substr(t.trans_time,1,7)=?"
        args.append(month)
    return _rows(f"""SELECT t.id, t.trans_time, t.amount, t.counterparty, t.description,
        c.name AS category FROM transactions t
        LEFT JOIN categories c ON c.id=t.category_id
        WHERE {cond} ORDER BY t.amount DESC LIMIT ?""", *args, limit)


def recurring_expenses(min_months: int = 3) -> list[dict]:
    """定期支出：同商户 + 相近金额，出现在 >= min_months 个不同月份。"""
    return _rows(f"""SELECT t.counterparty AS merchant, ROUND(AVG(t.amount)) AS avg_amount,
        COUNT(*) AS n, COUNT(DISTINCT substr(t.trans_time,1,7)) AS months,
        MIN(t.trans_time) AS first_time, MAX(t.trans_time) AS last_time,
        SUM(t.amount) AS total
        FROM transactions t
        WHERE {BASE} AND t.direction='expense' AND t.counterparty!=''
        GROUP BY t.counterparty
        HAVING months>=? AND n>=months AND (MAX(t.amount)-MIN(t.amount))*1.0/MAX(t.amount,1)<0.35
        ORDER BY total DESC""", min_months)


def account_balances() -> list[dict]:
    """各账户：银行卡取流水末笔余额；钱包类给出净流水累计（参考值）。"""
    conn = get_conn()
    out = []
    for a in conn.execute("SELECT * FROM accounts ORDER BY id").fetchall():
        last = conn.execute(
            "SELECT balance_after, trans_time FROM transactions "
            "WHERE account_id=? AND balance_after IS NOT NULL AND is_deleted=0 "
            "ORDER BY trans_time DESC, id DESC LIMIT 1", (a["id"],)).fetchone()
        net = conn.execute(
            "SELECT COALESCE(SUM(CASE WHEN direction='income' THEN amount "
            "WHEN direction='expense' THEN -amount ELSE 0 END),0) AS s, COUNT(*) AS n "
            "FROM transactions WHERE account_id=? AND is_deleted=0", (a["id"],)).fetchone()
        check = conn.execute(
            "SELECT * FROM balance_checks WHERE account_id=? ORDER BY created_at DESC LIMIT 1",
            (a["id"],)).fetchone()
        out.append({
            "id": a["id"], "name": a["name"], "type": a["type"], "card_tail": a["card_tail"],
            "txn_count": net["n"], "net_flow": net["s"],
            "statement_balance": last["balance_after"] if last else None,
            "statement_balance_time": last["trans_time"] if last else None,
            "last_check": dict(check) if check else None,
        })
    return out


def yearly_summary(year: str) -> dict:
    cond = BASE + " AND substr(t.trans_time,1,4)=?"
    months = _rows(f"""SELECT substr(t.trans_time,1,7) AS month,
        SUM(CASE WHEN direction='income' THEN amount ELSE 0 END) AS income,
        SUM(CASE WHEN direction='expense' THEN amount ELSE 0 END) AS expense
        FROM transactions t WHERE {cond} GROUP BY month ORDER BY month""", year)
    cats = _rows(f"""SELECT COALESCE(p.name, c.name) AS name, SUM(t.amount) AS total, COUNT(*) AS n
        FROM transactions t JOIN categories c ON c.id=t.category_id
        LEFT JOIN categories p ON p.id=c.parent_id
        WHERE {cond} AND t.direction='expense' GROUP BY name ORDER BY total DESC""", year)
    merchants = _rows(f"""SELECT t.counterparty AS merchant, SUM(t.amount) AS total, COUNT(*) AS n
        FROM transactions t WHERE {cond} AND t.direction='expense' AND t.counterparty!=''
        GROUP BY merchant ORDER BY total DESC LIMIT 20""", year)
    total_inc = sum(m["income"] or 0 for m in months)
    total_exp = sum(m["expense"] or 0 for m in months)
    return {"year": year, "months": months, "categories": cats, "top_merchants": merchants,
            "income": total_inc, "expense": total_exp, "net": total_inc - total_exp}


def audit(month: str | None = None) -> dict:
    """口径对账：原始金额 -> 计入统计金额 的完整拆解，每项可下钻。

    数字任何时候变化，对比两次拆解即可定位是哪一项变了。
    """
    conn = get_conn()
    cond, args = "is_deleted=0", []
    if month:
        cond += " AND substr(trans_time,1,7)=?"
        args.append(month)
    out = {}
    for direction in ("expense", "income"):
        rows = conn.execute(f"""
            SELECT CASE
                WHEN status_ok=0 THEN 'closed'
                WHEN flow_type='transfer' THEN 'transfer'
                WHEN flow_type='credit_card_spend' THEN 'credit_card'
                WHEN dup_status='confirmed_dup' THEN 'dedup'
                WHEN dup_status='suspect' THEN 'suspect'
                ELSE 'counted'
              END AS bucket, COUNT(*) n, COALESCE(SUM(amount),0) s
            FROM transactions WHERE {cond} AND direction=?
            GROUP BY bucket""", args + [direction]).fetchall()
        buckets = {r["bucket"]: {"n": r["n"], "total": r["s"]} for r in rows}
        for k in ("counted", "dedup", "suspect", "transfer", "credit_card", "closed"):
            buckets.setdefault(k, {"n": 0, "total": 0})
        buckets["raw"] = {"n": sum(b["n"] for b in buckets.values()),
                          "total": sum(b["total"] for b in buckets.values())}
        out[direction] = buckets
    out["member_count"] = conn.execute("SELECT COUNT(*) FROM members").fetchone()[0]
    return out
