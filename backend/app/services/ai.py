"""AI 分析：调用 Claude 生成财务分析报告 + 批量分类建议。

- 报告：非流式 messages 调用，输入为聚合摘要（不上传原始明细全量，控制 token）。
- 分类建议：结构化输出（output_config.format json_schema），批量给未分类交易建议分类。
- API Key：环境变量 ANTHROPIC_API_KEY 或 settings 表 anthropic_api_key。
"""
from __future__ import annotations

import json
import os
import threading

from ..db import get_conn, get_setting
from . import stats

MODEL = "claude-opus-4-8"


def _client():
    import anthropic
    key = os.environ.get("ANTHROPIC_API_KEY") or get_setting("anthropic_api_key")
    if not key:
        # 允许 ant auth login 等零参凭据链
        try:
            return anthropic.Anthropic()
        except Exception as e:
            raise RuntimeError("未配置 Claude API Key：请设置环境变量 ANTHROPIC_API_KEY，"
                               "或在设置页保存 Key") from e
    return anthropic.Anthropic(api_key=key)


def build_digest(scope: str) -> dict:
    """构建喂给模型的数据摘要。scope: 'overall' | 'month:YYYY-MM' | 'year:YYYY'"""
    month = scope.split(":", 1)[1] if scope.startswith("month:") else None
    year = scope.split(":", 1)[1] if scope.startswith("year:") else None

    digest: dict = {"scope": scope, "unit": "元（已从分换算）"}

    def yuan(rows, keys):
        out = []
        for r in rows:
            d = dict(r)
            for k in keys:
                if d.get(k) is not None:
                    d[k] = round(d[k] / 100, 2)
            out.append(d)
        return out

    digest["overview"] = {k: (round(v / 100, 2) if k in ("income", "expense", "net", "net_expense") else v)
                          for k, v in stats.overview(month).items()}
    digest["monthly_trend"] = yuan(stats.monthly_trend(), ["income", "expense"])
    digest["category_breakdown"] = yuan(stats.category_breakdown(month), ["total"])[:20]
    digest["top_merchants"] = yuan(stats.top_merchants(month, limit=15), ["total"])
    digest["large_transactions"] = yuan(stats.large_transactions(month=month, limit=20), ["amount"])
    digest["recurring"] = yuan(stats.recurring_expenses(), ["avg_amount", "total"])[:15]
    if year:
        digest["yearly"] = {k: (round(v / 100, 2) if k in ("income", "expense", "net") else v)
                            for k, v in stats.yearly_summary(year).items()
                            if k in ("income", "expense", "net")}
    # 预算执行
    conn = get_conn()
    if month:
        budgets = conn.execute(
            "SELECT b.amount, c.name FROM budgets b LEFT JOIN categories c ON c.id=b.category_id "
            "WHERE b.month IN (?, '*')", (month,)).fetchall()
        digest["budgets"] = [{"category": r["name"] or "总预算", "budget": round(r["amount"] / 100, 2)}
                             for r in budgets]
    return digest


SYSTEM_PROMPT = """你是一位懂中国互联网支付生态的个人财务分析师。用户导入了银行卡流水、\
支付宝和微信账单，系统已完成跨账单去重（渠道账单为主记录，银行侧重复扣款已剔除）。\
你收到的是去重后的聚合数据摘要（单位：元）。

写一份 Markdown 财务分析报告，中文，要求：
- 先给 TL;DR：3-5 条最重要的结论（每条一句话，有数字支撑）。
- 然后分节：收支全貌、消费结构与异常、大额与定期支出、省钱与优化建议。
- 结论要具体到数字和商户/分类名，不要空话；发现反常的月份或激增的分类要点出来。
- 涉及"人情往来/转账"类大额资金时，提示这可能是互相转账，统计上已尽量对冲但仍建议人工确认。
- 建议部分给可执行动作（如可设预算的分类和参考值、可取消的订阅、可优化的支付习惯）。
- 篇幅 600-1200 字。不要输出免责声明。"""


def generate_report(scope: str = "overall") -> int:
    """创建报告任务（后台线程执行），返回 ai_reports.id。"""
    conn = get_conn()
    digest = build_digest(scope)
    cur = conn.execute(
        "INSERT INTO ai_reports(scope, model, digest_json, status) VALUES(?,?,?,'pending')",
        (scope, MODEL, json.dumps(digest, ensure_ascii=False)))
    conn.commit()
    report_id = cur.lastrowid
    threading.Thread(target=_run_report, args=(report_id,), daemon=True).start()
    return report_id


def _run_report(report_id: int):
    import sqlite3
    from ..config import DB_PATH
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    try:
        row = conn.execute("SELECT digest_json FROM ai_reports WHERE id=?", (report_id,)).fetchone()
        client = _client()
        resp = client.messages.create(
            model=MODEL,
            max_tokens=16000,
            system=SYSTEM_PROMPT,
            messages=[{"role": "user", "content": f"数据摘要：\n```json\n{row['digest_json']}\n```"}],
        )
        text = next((b.text for b in resp.content if b.type == "text"), "")
        conn.execute(
            "UPDATE ai_reports SET report_md=?, status='done', input_tokens=?, output_tokens=? WHERE id=?",
            (text, resp.usage.input_tokens, resp.usage.output_tokens, report_id))
        conn.commit()
    except Exception as e:
        conn.execute("UPDATE ai_reports SET status='error', error=? WHERE id=?",
                     (str(e), report_id))
        conn.commit()
    finally:
        conn.close()


CLASSIFY_SCHEMA = {
    "type": "object",
    "properties": {
        "suggestions": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "txn_id": {"type": "integer"},
                    "category": {"type": "string",
                                 "description": "必须从提供的分类列表中选择，格式 '一级' 或 '一级/二级'"},
                    "confidence": {"type": "string", "enum": ["high", "medium", "low"]},
                },
                "required": ["txn_id", "category", "confidence"],
                "additionalProperties": False,
            },
        }
    },
    "required": ["suggestions"],
    "additionalProperties": False,
}


def suggest_categories(limit: int = 80) -> dict:
    """对未分类交易批量生成分类建议（结构化输出），中高置信度自动应用。

    返回带交易明细的逐笔结果与剩余未分类数（前端循环调用直到 remaining=0）。
    """
    conn = get_conn()
    uncat = conn.execute(
        "SELECT id FROM categories WHERE name='未分类' AND parent_id IS NULL").fetchone()["id"]
    rows = conn.execute(
        "SELECT t.id, t.trans_time, t.amount, t.direction, t.counterparty, t.description, "
        "t.trans_type_raw, t.remark FROM transactions t "
        "WHERE t.category_id=? AND t.is_deleted=0 AND t.flow_type='normal' "
        "ORDER BY t.amount DESC LIMIT ?", (uncat, limit)).fetchall()
    if not rows:
        return {"suggested": 0, "applied": 0, "remaining": 0, "results": [],
                "message": "没有待分类交易"}
    txn_by_id = {r["id"]: dict(r) for r in rows}

    cats = conn.execute(
        "SELECT c.id, c.name, p.name AS parent FROM categories c "
        "LEFT JOIN categories p ON p.id=c.parent_id WHERE c.name!='未分类'").fetchall()
    cat_paths = {}
    for c in cats:
        path = f"{c['parent']}/{c['name']}" if c["parent"] else c["name"]
        cat_paths[path] = c["id"]

    txn_lines = [
        {"txn_id": r["id"], "time": r["trans_time"][:16], "amount": round(r["amount"] / 100, 2),
         "direction": r["direction"], "counterparty": r["counterparty"],
         "desc": r["description"][:50], "type": r["trans_type_raw"], "remark": r["remark"][:30]}
        for r in rows]

    client = _client()
    resp = client.messages.create(
        model=MODEL,
        max_tokens=16000,
        system=("你是记账分类助手。根据交易的商户、描述、类型给每笔交易选择最合适的消费分类。"
                "分类必须严格从给定列表中选择（原样返回路径字符串）。必须给每一笔输入的交易都返回建议；"
                "看不出来的给 low 置信度并选最接近的分类。"),
        messages=[{"role": "user", "content":
                   f"可选分类列表：\n{json.dumps(sorted(cat_paths), ensure_ascii=False)}\n\n"
                   f"待分类交易：\n{json.dumps(txn_lines, ensure_ascii=False)}"}],
        output_config={"format": {"type": "json_schema", "schema": CLASSIFY_SCHEMA}},
    )
    text = next((b.text for b in resp.content if b.type == "text"), "{}")
    data = json.loads(text)

    applied = 0
    results = []
    for s in data.get("suggestions", []):
        cid = cat_paths.get(s["category"])
        txn = txn_by_id.get(s["txn_id"])
        if txn is None:
            continue
        item = {
            "txn_id": s["txn_id"],
            "trans_time": txn["trans_time"],
            "amount": txn["amount"],
            "direction": txn["direction"],
            "counterparty": txn["counterparty"],
            "description": txn["description"],
            "category": s["category"],
            "category_id": cid,
            "confidence": s["confidence"],
            "applied": False,
        }
        if cid is not None and s["confidence"] in ("high", "medium"):
            conn.execute(
                "UPDATE transactions SET category_id=?, category_source='ai', "
                "updated_at=datetime('now','localtime') WHERE id=? AND category_source!='manual'",
                (cid, s["txn_id"]))
            item["applied"] = True
            applied += 1
        results.append(item)
    conn.commit()
    remaining = conn.execute(
        "SELECT COUNT(*) FROM transactions WHERE category_id=? AND is_deleted=0 "
        "AND flow_type='normal'", (uncat,)).fetchone()[0]
    return {"suggested": len(results), "applied": applied, "remaining": remaining,
            "results": results,
            "usage": {"input_tokens": resp.usage.input_tokens,
                      "output_tokens": resp.usage.output_tokens}}
