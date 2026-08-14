"""FastAPI 全部路由（单文件，前缀 /api）。"""
from __future__ import annotations

import json
import shutil
import uuid
from pathlib import Path

from fastapi import APIRouter, HTTPException, Query, UploadFile
from fastapi.responses import Response
from pydantic import BaseModel

from .config import LARGE_TXN_DEFAULT_CENTS, UPLOAD_DIR
from .db import get_conn, get_setting, set_setting
from .services import ai, classifier, dedup, export, extras, importer, stats, transfer

router = APIRouter(prefix="/api")

_preview_cache: dict[int, dict] = {}


# ---------------- 导入 ----------------
@router.post("/imports/upload")
async def upload(file: UploadFile):
    dest = UPLOAD_DIR / f"{uuid.uuid4().hex[:8]}_{file.filename}"
    with dest.open("wb") as f:
        shutil.copyfileobj(file.file, f)
    try:
        p = importer.preview(dest)
    except ValueError as e:
        dest.unlink(missing_ok=True)
        raise HTTPException(400, str(e))
    _preview_cache[p["batch_id"]] = {"path": dest, "result": p.pop("_result")}
    return p


@router.post("/imports/{batch_id}/commit")
def commit_import(batch_id: int):
    cached = _preview_cache.pop(batch_id, None)
    if not cached:
        raise HTTPException(404, "预览已过期，请重新上传")
    r = importer.commit(cached["path"], batch_id, cached["result"])
    pipeline = {"transfer": transfer.run(), "dedup": dedup.run(),
                "refund_pairs": transfer.refund_pairs(),
                "member_transfers": transfer.member_transfers(),
                "classify": classifier.run()}
    return {**r, "pipeline": pipeline}


@router.get("/imports")
def list_imports():
    rows = get_conn().execute(
        "SELECT id, filename, source_type, period_start, period_end, row_count, "
        "imported_count, skipped_dup_count, status, created_at FROM import_batches "
        "ORDER BY id DESC").fetchall()
    return [dict(r) for r in rows]


@router.delete("/imports/{batch_id}")
def delete_import(batch_id: int):
    r = importer.rollback_batch(batch_id)
    dedup.run()
    return r


# ---------------- 交易 ----------------
class TxnPatch(BaseModel):
    category_id: int | None = None
    flow_type: str | None = None
    remark: str | None = None
    dup_status: str | None = None
    activity_id: int | None = None    # -1 表示移出活动
    member_id: int | None = None      # -1 表示清除
    is_shared: bool | None = None
    reimburse_status: str | None = None


class TxnCreate(BaseModel):
    trans_time: str
    amount_yuan: float
    direction: str
    counterparty: str = ""
    description: str = ""
    category_id: int | None = None
    account_id: int | None = None
    remark: str = ""
    activity_id: int | None = None
    member_id: int | None = None
    fx_currency: str = ""             # 外币记账：币种 + 原币金额（人民币金额填 amount_yuan）
    fx_amount_orig: float | None = None


class BatchUpdate(BaseModel):
    ids: list[int]
    category_id: int | None = None
    flow_type: str | None = None
    activity_id: int | None = None    # -1 表示移出活动
    member_id: int | None = None
    is_shared: bool | None = None
    reimburse_status: str | None = None


@router.get("/transactions")
def list_transactions(
    page: int = 1, page_size: int = 50,
    date_from: str | None = None, date_to: str | None = None,
    account_id: int | None = None, category_id: int | None = None,
    direction: str | None = None, flow_type: str | None = None,
    dup_status: str | None = None, source: str | None = None,
    keyword: str | None = None, min_amount: float | None = None,
    max_amount: float | None = None, counted_only: bool = False,
    month: str | None = None, activity_id: int | None = None,
    member_id: int | None = None, merchant: str | None = None,
    weekday: int | None = None, hour: int | None = None,
    reimburse_status: str | None = None, no_activity: bool = False,
    status_ok: int | None = None,
    sort_by: str = "time", sort_order: str = "desc",
):
    conn = get_conn()
    cond, args = ["t.is_deleted=0"], []
    if month:
        cond.append("substr(t.trans_time,1,7)=?"); args.append(month)
    if date_from:
        cond.append("t.trans_time>=?"); args.append(date_from)
    if date_to:
        cond.append("t.trans_time<=?"); args.append(date_to + " 23:59:59")
    if account_id:
        cond.append("t.account_id=?"); args.append(account_id)
    if category_id:
        cond.append("(t.category_id=? OR t.category_id IN "
                    "(SELECT id FROM categories WHERE parent_id=?))")
        args += [category_id, category_id]
    if direction:
        cond.append("t.direction=?"); args.append(direction)
    if flow_type:
        cond.append("t.flow_type=?"); args.append(flow_type)
    if dup_status:
        cond.append("t.dup_status=?"); args.append(dup_status)
    if source:
        cond.append("t.source=?"); args.append(source)
    if keyword:
        cond.append("(t.counterparty LIKE ? OR t.description LIKE ? OR t.remark LIKE ?)")
        args += [f"%{keyword}%"] * 3
    if merchant:
        cond.append("t.counterparty=?"); args.append(merchant)
    if min_amount is not None:
        cond.append("t.amount>=?"); args.append(int(min_amount * 100))
    if max_amount is not None:
        cond.append("t.amount<=?"); args.append(int(max_amount * 100))
    if activity_id:
        cond.append("t.activity_id=?"); args.append(activity_id)
    if no_activity:
        cond.append("t.activity_id IS NULL")
    if member_id:
        cond.append("COALESCE(t.member_id, a.member_id)=?"); args.append(member_id)
    if weekday is not None:
        cond.append("CAST(strftime('%w', t.trans_time) AS INT)=?"); args.append(weekday)
    if hour is not None:
        cond.append("CAST(strftime('%H', t.trans_time) AS INT)=?"); args.append(hour)
    if reimburse_status:
        cond.append("t.reimburse_status=?"); args.append(reimburse_status)
    if status_ok is not None:
        cond.append("t.status_ok=?"); args.append(status_ok)
    if counted_only:
        cond.append("t.status_ok=1 AND t.flow_type='normal' AND t.dup_status IN ('none','not_dup')")
    where = " AND ".join(cond)
    total_row = conn.execute(
        f"""SELECT COUNT(*) n,
            COALESCE(SUM(CASE WHEN t.direction='expense' THEN t.amount ELSE 0 END),0) exp,
            COALESCE(SUM(CASE WHEN t.direction='income' THEN t.amount ELSE 0 END),0) inc
            FROM transactions t LEFT JOIN accounts a ON a.id=t.account_id WHERE {where}""",
        args).fetchone()
    order_col = {
        "time": "t.trans_time",
        "amount": "t.amount",
        "category": "COALESCE(p.name, c.name)",
        "counterparty": "t.counterparty",
    }.get(sort_by, "t.trans_time")
    order_dir = "ASC" if sort_order == "asc" else "DESC"
    rows = conn.execute(f"""
        SELECT t.*, c.name AS category_name, p.name AS category_parent,
               a.name AS account_name, m.name AS member_name, act.name AS activity_name
        FROM transactions t
        LEFT JOIN categories c ON c.id=t.category_id
        LEFT JOIN categories p ON p.id=c.parent_id
        LEFT JOIN accounts a ON a.id=t.account_id
        LEFT JOIN members m ON m.id=COALESCE(t.member_id, a.member_id)
        LEFT JOIN activities act ON act.id=t.activity_id
        WHERE {where} ORDER BY {order_col} {order_dir}, t.id DESC
        LIMIT ? OFFSET ?""", args + [page_size, (page - 1) * page_size]).fetchall()
    return {"total": total_row["n"], "sum_expense": total_row["exp"],
            "sum_income": total_row["inc"], "page": page,
            "items": [dict(r) for r in rows]}


@router.post("/transactions")
def create_txn(body: TxnCreate):
    conn = get_conn()
    uncat = conn.execute("SELECT id FROM categories WHERE name='未分类' AND parent_id IS NULL").fetchone()[0]
    cur = conn.execute(
        "INSERT INTO transactions(source, account_id, trans_time, amount, direction, counterparty, "
        "description, remark, category_id, category_source, dedup_key, status_ok, "
        "activity_id, member_id, fx_currency, fx_amount) "
        "VALUES('manual',?,?,?,?,?,?,?,?,'manual',?,1,?,?,?,?)",
        (body.account_id, body.trans_time, int(round(body.amount_yuan * 100)), body.direction,
         body.counterparty, body.description, body.remark, body.category_id or uncat,
         f"manual:{uuid.uuid4().hex}", body.activity_id, body.member_id,
         body.fx_currency,
         int(round(body.fx_amount_orig * 100)) if body.fx_amount_orig else None))
    conn.commit()
    return {"id": cur.lastrowid}


@router.patch("/transactions/{txn_id}")
def patch_txn(txn_id: int, body: TxnPatch):
    conn = get_conn()
    sets, args = [], []
    if body.category_id is not None:
        sets += ["category_id=?", "category_source='manual'"]
        args.append(body.category_id)
    if body.flow_type is not None:
        sets.append("flow_type=?"); args.append(body.flow_type)
    if body.remark is not None:
        sets.append("remark=?"); args.append(body.remark)
    if body.dup_status is not None:
        sets.append("dup_status=?"); args.append(body.dup_status)
    if body.activity_id is not None:
        sets.append("activity_id=?"); args.append(None if body.activity_id == -1 else body.activity_id)
    if body.member_id is not None:
        sets.append("member_id=?"); args.append(None if body.member_id == -1 else body.member_id)
    if body.is_shared is not None:
        sets.append("is_shared=?"); args.append(int(body.is_shared))
    if body.reimburse_status is not None:
        sets.append("reimburse_status=?"); args.append(body.reimburse_status)
    if not sets:
        raise HTTPException(400, "没有要更新的字段")
    sets.append("updated_at=datetime('now','localtime')")
    cur = conn.execute(f"UPDATE transactions SET {', '.join(sets)} WHERE id=?", args + [txn_id])
    conn.commit()
    if not cur.rowcount:
        raise HTTPException(404, "交易不存在")
    return {"ok": True}


@router.post("/transactions/batch-update")
def batch_update(body: BatchUpdate):
    conn = get_conn()
    ph = ",".join("?" * len(body.ids))
    n = 0
    if body.category_id is not None:
        n = conn.execute(f"UPDATE transactions SET category_id=?, category_source='manual', "
                         f"updated_at=datetime('now','localtime') WHERE id IN ({ph})",
                         [body.category_id] + body.ids).rowcount
    if body.flow_type is not None:
        n = conn.execute(f"UPDATE transactions SET flow_type=? WHERE id IN ({ph})",
                         [body.flow_type] + body.ids).rowcount
    if body.activity_id is not None:
        val = None if body.activity_id == -1 else body.activity_id
        n = conn.execute(f"UPDATE transactions SET activity_id=? WHERE id IN ({ph})",
                         [val] + body.ids).rowcount
    if body.member_id is not None:
        val = None if body.member_id == -1 else body.member_id
        n = conn.execute(f"UPDATE transactions SET member_id=? WHERE id IN ({ph})",
                         [val] + body.ids).rowcount
    if body.is_shared is not None:
        n = conn.execute(f"UPDATE transactions SET is_shared=? WHERE id IN ({ph})",
                         [int(body.is_shared)] + body.ids).rowcount
    if body.reimburse_status is not None:
        n = conn.execute(f"UPDATE transactions SET reimburse_status=? WHERE id IN ({ph})",
                         [body.reimburse_status] + body.ids).rowcount
    conn.commit()
    return {"updated": n}


@router.delete("/transactions/{txn_id}")
def delete_txn(txn_id: int):
    conn = get_conn()
    row = conn.execute("SELECT source FROM transactions WHERE id=?", (txn_id,)).fetchone()
    if not row:
        raise HTTPException(404, "交易不存在")
    if row["source"] == "manual":
        conn.execute("DELETE FROM transactions WHERE id=?", (txn_id,))
    else:
        conn.execute("UPDATE transactions SET is_deleted=1 WHERE id=?", (txn_id,))
    conn.commit()
    return {"ok": True}


# ---------------- 去重复核 ----------------
@router.post("/dedup/run")
def rerun_dedup():
    transfer.run()
    r = dedup.run()
    transfer.refund_pairs()
    transfer.member_transfers()
    classifier.run()
    return r


@router.get("/dedup/suspects")
def list_suspects():
    conn = get_conn()
    rows = conn.execute("""
        SELECT m.id AS match_id, m.score, m.date_diff_days, m.match_reason, m.status,
               c.id AS c_id, c.trans_time AS c_time, c.amount AS c_amount, c.source AS c_source,
               c.counterparty AS c_party, c.description AS c_desc, c.pay_method_raw AS c_pay,
               b.id AS b_id, b.trans_time AS b_time, b.amount AS b_amount, b.source AS b_source,
               b.counterparty AS b_party, b.description AS b_desc, b.trans_type_raw AS b_type
        FROM dup_matches m
        JOIN transactions c ON c.id=m.channel_txn_id
        JOIN transactions b ON b.id=m.bank_txn_id
        WHERE m.status='suspect' ORDER BY m.score""").fetchall()
    return [dict(r) for r in rows]


@router.post("/dedup/matches/{match_id}/confirm")
def confirm_match(match_id: int):
    return dedup.decide(match_id, True)


@router.post("/dedup/matches/{match_id}/reject")
def reject_match(match_id: int):
    return dedup.decide(match_id, False)


@router.get("/dedup/report")
def dedup_report():
    conn = get_conn()
    by_status = {r["dup_status"]: r["n"] for r in conn.execute(
        "SELECT dup_status, COUNT(*) n FROM transactions GROUP BY dup_status")}
    by_flow = {r["flow_type"]: r["n"] for r in conn.execute(
        "SELECT flow_type, COUNT(*) n FROM transactions GROUP BY flow_type")}
    return {"by_dup_status": by_status, "by_flow_type": by_flow}


# ---------------- 统计 ----------------
@router.get("/stats/overview")
def api_overview(month: str | None = None, member_id: int | None = None):
    return stats.overview(month, member_id)


@router.get("/stats/monthly-trend")
def api_trend(date_from: str | None = None, date_to: str | None = None,
              member_id: int | None = None):
    return stats.monthly_trend(date_from, date_to, member_id)


@router.get("/stats/category-breakdown")
def api_breakdown(month: str | None = None, direction: str = "expense",
                  parent_id: int | None = None, member_id: int | None = None):
    return stats.category_breakdown(month, direction, parent_id, member_id)


@router.get("/stats/top-merchants")
def api_merchants(month: str | None = None, limit: int = 10, direction: str = "expense",
                  member_id: int | None = None):
    return stats.top_merchants(month, limit, direction, member_id)


@router.get("/stats/heatmap")
def api_heatmap(month: str | None = None, member_id: int | None = None):
    return stats.weekday_hour_heatmap(month, member_id)


@router.get("/stats/audit")
def api_audit(month: str | None = None):
    return stats.audit(month)


@router.get("/stats/balance-trend")
def api_balance_trend():
    return extras.balance_trend()


@router.get("/stats/large")
def api_large(month: str | None = None, threshold: float | None = None):
    cents = int(threshold * 100) if threshold else LARGE_TXN_DEFAULT_CENTS
    return stats.large_transactions(cents, month)


@router.get("/stats/recurring")
def api_recurring():
    return stats.recurring_expenses()


@router.get("/stats/yearly")
def api_yearly(year: str):
    return stats.yearly_summary(year)


# ---------------- 分类与规则 ----------------
class RuleCreate(BaseModel):
    pattern: str
    category_id: int
    field: str = "any"
    match_type: str = "contains"
    direction: str = ""
    priority: int = 50


@router.get("/categories")
def list_categories():
    rows = get_conn().execute(
        "SELECT c.id, c.name, c.parent_id, COUNT(t.id) AS txn_count FROM categories c "
        "LEFT JOIN transactions t ON t.category_id=c.id AND t.is_deleted=0 "
        "GROUP BY c.id ORDER BY c.parent_id IS NOT NULL, c.sort").fetchall()
    return [dict(r) for r in rows]


class CategoryCreate(BaseModel):
    name: str
    parent_id: int | None = None


@router.post("/categories")
def create_category(body: CategoryCreate):
    conn = get_conn()
    cur = conn.execute("INSERT INTO categories(name, parent_id) VALUES(?,?)",
                       (body.name, body.parent_id))
    conn.commit()
    return {"id": cur.lastrowid}


@router.get("/rules")
def list_rules():
    rows = get_conn().execute(
        "SELECT r.*, c.name AS category_name FROM classify_rules r "
        "JOIN categories c ON c.id=r.category_id ORDER BY r.rule_source='builtin', r.priority").fetchall()
    return [dict(r) for r in rows]


@router.post("/rules")
def create_rule(body: RuleCreate):
    conn = get_conn()
    cur = conn.execute(
        "INSERT INTO classify_rules(priority, field, match_type, direction, pattern, category_id, "
        "rule_source) VALUES(?,?,?,?,?,?,'user')",
        (body.priority, body.field, body.match_type, body.direction, body.pattern, body.category_id))
    conn.commit()
    return {"id": cur.lastrowid}


@router.delete("/rules/{rule_id}")
def delete_rule(rule_id: int):
    conn = get_conn()
    conn.execute("DELETE FROM classify_rules WHERE id=? AND rule_source='user'", (rule_id,))
    conn.commit()
    return {"ok": True}


@router.post("/rules/reapply")
def reapply_rules():
    return classifier.run()


# ---------------- 预算 ----------------
class BudgetPut(BaseModel):
    month: str
    category_id: int | None = None
    member_id: int | None = None
    amount_yuan: float


@router.get("/budgets")
def get_budgets(month: str, member_id: int | None = None):
    conn = get_conn()
    rows = conn.execute(
        "SELECT b.*, c.name AS category_name, m.name AS member_name FROM budgets b "
        "LEFT JOIN categories c ON c.id=b.category_id "
        "LEFT JOIN members m ON m.id=b.member_id WHERE b.month IN (?, '*')",
        (month,)).fetchall()
    # 具体月覆盖每月默认
    merged: dict = {}
    for r in sorted(rows, key=lambda r: r["month"] == "*"):
        key = (r["category_id"], r["member_id"])
        if key not in merged or r["month"] != "*":
            merged[key] = dict(r)
    out = []
    for b in merged.values():
        if member_id and b["member_id"] != member_id:
            continue
        spent_rows = stats.category_breakdown(month, member_id=b["member_id"])
        spent = {r["category_id"]: r["total"] for r in spent_rows}
        s = (stats.overview(month, member_id=b["member_id"])["expense"]
             if b["category_id"] is None else spent.get(b["category_id"], 0))
        out.append({**b, "spent": s})
    return out


@router.put("/budgets")
def put_budget(body: BudgetPut):
    conn = get_conn()
    row = conn.execute(
        "SELECT id FROM budgets WHERE month=? AND COALESCE(category_id,0)=COALESCE(?,0) "
        "AND COALESCE(member_id,0)=COALESCE(?,0)",
        (body.month, body.category_id, body.member_id)).fetchone()
    amount = int(round(body.amount_yuan * 100))
    if row:
        conn.execute("UPDATE budgets SET amount=? WHERE id=?", (amount, row["id"]))
    else:
        conn.execute("INSERT INTO budgets(month, category_id, member_id, amount) VALUES(?,?,?,?)",
                     (body.month, body.category_id, body.member_id, amount))
    conn.commit()
    return {"ok": True}


@router.delete("/budgets/{budget_id}")
def delete_budget(budget_id: int):
    conn = get_conn()
    conn.execute("DELETE FROM budgets WHERE id=?", (budget_id,))
    conn.commit()
    return {"ok": True}


# ---------------- 账户与核对 ----------------
class ReconcileBody(BaseModel):
    actual_balance_yuan: float
    check_date: str
    note: str = ""


@router.get("/accounts")
def list_accounts():
    return stats.account_balances()


@router.post("/accounts/{account_id}/reconcile")
def reconcile(account_id: int, body: ReconcileBody):
    conn = get_conn()
    last = conn.execute(
        "SELECT balance_after FROM transactions WHERE account_id=? AND balance_after IS NOT NULL "
        "AND trans_time<=? ORDER BY trans_time DESC, id DESC LIMIT 1",
        (account_id, body.check_date + " 23:59:59")).fetchone()
    computed = last["balance_after"] if last else None
    actual = int(round(body.actual_balance_yuan * 100))
    diff = (actual - computed) if computed is not None else None
    conn.execute(
        "INSERT INTO balance_checks(account_id, check_date, computed_balance, actual_balance, "
        "diff, note) VALUES(?,?,?,?,?,?)",
        (account_id, body.check_date, computed, actual, diff, body.note))
    conn.commit()
    return {"computed_balance": computed, "actual_balance": actual, "diff": diff}


# ---------------- 导出 ----------------
@router.get("/export/transactions.csv")
def export_csv(month: str | None = None, date_from: str | None = None,
               date_to: str | None = None, counted_only: bool = False,
               activity_id: int | None = None):
    data = export.to_csv({"month": month, "date_from": date_from, "date_to": date_to,
                          "counted_only": counted_only, "activity_id": activity_id})
    return Response(data, media_type="text/csv",
                    headers={"Content-Disposition": "attachment; filename=transactions.csv"})


@router.get("/export/transactions.xlsx")
def export_xlsx(month: str | None = None, date_from: str | None = None,
                date_to: str | None = None, counted_only: bool = False,
                activity_id: int | None = None):
    data = export.to_xlsx({"month": month, "date_from": date_from, "date_to": date_to,
                           "counted_only": counted_only, "activity_id": activity_id})
    return Response(
        data,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": "attachment; filename=report.xlsx"})


# ---------------- AI 分析 ----------------
class AIKeyBody(BaseModel):
    api_key: str


@router.post("/ai/report")
def create_ai_report(scope: str = "overall"):
    try:
        report_id = ai.generate_report(scope)
    except RuntimeError as e:
        raise HTTPException(400, str(e))
    return {"report_id": report_id}


@router.get("/ai/reports")
def list_ai_reports():
    rows = get_conn().execute(
        "SELECT id, scope, model, status, error, input_tokens, output_tokens, created_at "
        "FROM ai_reports ORDER BY id DESC LIMIT 50").fetchall()
    return [dict(r) for r in rows]


@router.get("/ai/reports/{report_id}")
def get_ai_report(report_id: int):
    row = get_conn().execute("SELECT * FROM ai_reports WHERE id=?", (report_id,)).fetchone()
    if not row:
        raise HTTPException(404, "报告不存在")
    return dict(row)


@router.post("/ai/classify")
def ai_classify(limit: int = 80):
    try:
        return ai.suggest_categories(limit)
    except RuntimeError as e:
        raise HTTPException(400, str(e))
    except Exception as e:
        raise HTTPException(500, f"AI 分类失败: {e}")


# ---------------- 成员（双人记账）----------------
class MemberBody(BaseModel):
    name: str
    is_self: bool = False


class AccountPatch(BaseModel):
    member_id: int | None = None      # -1 清除


@router.get("/members")
def list_members():
    return [dict(r) for r in get_conn().execute(
        "SELECT m.*, (SELECT COUNT(*) FROM accounts a WHERE a.member_id=m.id) AS account_count "
        "FROM members m ORDER BY m.is_self DESC, m.id")]


@router.post("/members")
def create_member(body: MemberBody):
    conn = get_conn()
    try:
        cur = conn.execute("INSERT INTO members(name, is_self) VALUES(?,?)",
                           (body.name.strip(), int(body.is_self)))
    except Exception:
        raise HTTPException(400, "成员已存在")
    conn.commit()
    # 新成员加入后重跑转账识别（TA 的互转变为家庭内部转账）+ 重新分类
    transfer.run()
    dedup.run()
    transfer.refund_pairs()
    transfer.member_transfers()
    classifier.run()
    return {"id": cur.lastrowid}


@router.delete("/members/{member_id}")
def delete_member(member_id: int):
    conn = get_conn()
    conn.execute("UPDATE accounts SET member_id=NULL WHERE member_id=?", (member_id,))
    conn.execute("UPDATE transactions SET member_id=NULL WHERE member_id=?", (member_id,))
    conn.execute("DELETE FROM members WHERE id=? AND is_self=0", (member_id,))
    conn.commit()
    # 删除成员后立即重跑管线：与 TA 的转账恢复计入收支，统计实时一致
    transfer.run()
    dedup.run()
    transfer.refund_pairs()
    transfer.member_transfers()
    classifier.run()
    return {"ok": True}


@router.patch("/accounts/{account_id}")
def patch_account(account_id: int, body: AccountPatch):
    conn = get_conn()
    val = None if body.member_id == -1 else body.member_id
    conn.execute("UPDATE accounts SET member_id=? WHERE id=?", (val, account_id))
    conn.commit()
    return {"ok": True}


@router.get("/settle")
def api_settle(month: str | None = None):
    return extras.settle(month)


# ---------------- 活动账本 ----------------
class ActivityBody(BaseModel):
    name: str
    date_from: str | None = None
    date_to: str | None = None
    budget_yuan: float | None = None
    note: str = ""


class AssignRangeBody(BaseModel):
    date_from: str
    date_to: str
    exclude_fixed: bool = True


@router.get("/activities")
def list_activities():
    conn = get_conn()
    return [dict(r) for r in conn.execute("""
        SELECT a.*, COUNT(t.id) AS txn_count,
               COALESCE(SUM(CASE WHEN t.direction='expense' AND t.flow_type!='transfer'
                    AND t.dup_status IN ('none','not_dup') AND t.is_deleted=0
                    THEN t.amount ELSE 0 END),0) AS expense
        FROM activities a LEFT JOIN transactions t ON t.activity_id=a.id
        GROUP BY a.id ORDER BY a.status='archived', a.date_from DESC""")]


@router.post("/activities")
def create_activity(body: ActivityBody):
    conn = get_conn()
    cur = conn.execute(
        "INSERT INTO activities(name, date_from, date_to, budget, note) VALUES(?,?,?,?,?)",
        (body.name, body.date_from, body.date_to,
         int(round(body.budget_yuan * 100)) if body.budget_yuan else None, body.note))
    conn.commit()
    return {"id": cur.lastrowid}


@router.patch("/activities/{activity_id}")
def update_activity(activity_id: int, body: ActivityBody):
    conn = get_conn()
    conn.execute(
        "UPDATE activities SET name=?, date_from=?, date_to=?, budget=?, note=? WHERE id=?",
        (body.name, body.date_from, body.date_to,
         int(round(body.budget_yuan * 100)) if body.budget_yuan else None, body.note, activity_id))
    conn.commit()
    return {"ok": True}


@router.delete("/activities/{activity_id}")
def delete_activity(activity_id: int):
    conn = get_conn()
    conn.execute("UPDATE transactions SET activity_id=NULL WHERE activity_id=?", (activity_id,))
    conn.execute("DELETE FROM activities WHERE id=?", (activity_id,))
    conn.commit()
    return {"ok": True}


@router.get("/activities/{activity_id}/stats")
def api_activity_stats(activity_id: int):
    try:
        return extras.activity_stats(activity_id)
    except ValueError as e:
        raise HTTPException(404, str(e))


@router.post("/activities/{activity_id}/assign-range")
def api_assign_range(activity_id: int, body: AssignRangeBody):
    try:
        n = extras.activity_assign_range(activity_id, body.date_from, body.date_to, body.exclude_fixed)
    except ValueError as e:
        raise HTTPException(404, str(e))
    return {"assigned": n}


# ---------------- 订阅 ----------------
class SubscriptionBody(BaseModel):
    merchant: str
    label: str = ""
    period_days: int = 30
    avg_amount_yuan: float = 0
    note: str = ""


@router.get("/subscriptions")
def api_subscriptions():
    return {"subscriptions": extras.subscription_list(),
            "candidates": extras.detect_subscriptions()}


@router.post("/subscriptions")
def add_subscription(body: SubscriptionBody):
    conn = get_conn()
    cur = conn.execute(
        "INSERT INTO subscriptions(merchant, label, period_days, avg_amount, note) VALUES(?,?,?,?,?)",
        (body.merchant, body.label or body.merchant, body.period_days,
         int(round(body.avg_amount_yuan * 100)), body.note))
    conn.commit()
    return {"id": cur.lastrowid}


@router.delete("/subscriptions/{sub_id}")
def remove_subscription(sub_id: int):
    conn = get_conn()
    conn.execute("DELETE FROM subscriptions WHERE id=?", (sub_id,))
    conn.commit()
    return {"ok": True}


# ---------------- 报销 ----------------
@router.get("/reimburse")
def api_reimburse():
    return extras.reimburse_summary()


# ---------------- 设置 ----------------
@router.get("/settings")
def get_settings():
    return {"owner_name": get_setting("owner_name"),
            "has_api_key": bool(get_setting("anthropic_api_key")
                                or __import__("os").environ.get("ANTHROPIC_API_KEY"))}


@router.post("/settings/api-key")
def set_api_key(body: AIKeyBody):
    set_setting("anthropic_api_key", body.api_key.strip())
    return {"ok": True}
