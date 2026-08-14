"""自动分类引擎：manual > user_rule > builtin_rule > alipay_map > keyword > 未分类。

builtin_rule 与 keyword 同在 classify_rules 表（rule_source 区分），按 priority 排序，
builtin 的结构化映射 priority < 30，关键词规则 priority >= 30，天然形成优先级链。
"""
from __future__ import annotations

import re

from ..db import get_conn


def _uncat_id(conn) -> int:
    return conn.execute(
        "SELECT id FROM categories WHERE name='未分类' AND parent_id IS NULL").fetchone()["id"]


def _transfer_cat_id(conn) -> int:
    return conn.execute(
        "SELECT id FROM categories WHERE name='转账与互转' AND parent_id IS NULL").fetchone()["id"]


def run(only_uncategorized: bool = False) -> dict:
    conn = get_conn()
    rules = [dict(r) for r in conn.execute(
        "SELECT id, priority, field, match_type, direction, pattern, category_id, rule_source "
        "FROM classify_rules WHERE enabled=1 "
        "ORDER BY CASE rule_source WHEN 'user' THEN 0 ELSE 1 END, priority")]
    ali_map = {r["alipay_category"]: r["category_id"] for r in conn.execute(
        "SELECT alipay_category, category_id FROM alipay_category_map")}
    uncat = _uncat_id(conn)
    transfer_cat = _transfer_cat_id(conn)

    where = "is_deleted=0 AND (category_source != 'manual' OR category_source IS NULL OR category_source='')"
    if only_uncategorized:
        where += " AND (category_id IS NULL OR category_id=?)"
        rows = conn.execute(
            f"SELECT id, counterparty, description, trans_type_raw, remark, alipay_category, "
            f"flow_type, direction FROM transactions WHERE {where}", (uncat,)).fetchall()
    else:
        rows = conn.execute(
            f"SELECT id, counterparty, description, trans_type_raw, remark, alipay_category, "
            f"flow_type, direction FROM transactions WHERE {where}").fetchall()

    stats = {"transfer": 0, "user_rule": 0, "builtin": 0, "alipay_map": 0, "uncategorized": 0}
    hit_counts: dict[int, int] = {}
    updates: list[tuple] = []

    for t in rows:
        if t["flow_type"] != "normal":
            updates.append((transfer_cat, "builtin", t["id"]))
            stats["transfer"] += 1
            continue
        fields = {
            "counterparty": t["counterparty"] or "",
            "description": t["description"] or "",
            "trans_type": t["trans_type_raw"] or "",
            "remark": t["remark"] or "",
        }
        fields["any"] = " ".join(fields.values())
        hit = None
        for r in rules:
            if r["direction"] and r["direction"] != t["direction"]:
                continue
            text = fields.get(r["field"], fields["any"])
            ok = (re.search(r["pattern"], text) if r["match_type"] == "regex"
                  else r["pattern"] in text)
            if ok:
                hit = r
                break
        # 用户规则永远优先；builtin 命中但支付宝自带分类更细时，
        # 结构化 builtin(priority<30) 优先于 alipay_map，关键词 builtin(>=30) 让位给 alipay_map
        if hit and (hit["rule_source"] == "user" or hit["priority"] < 30):
            src = "user_rule" if hit["rule_source"] == "user" else "builtin"
            updates.append((hit["category_id"], src, t["id"]))
            stats[src] += 1
            hit_counts[hit["id"]] = hit_counts.get(hit["id"], 0) + 1
        elif t["alipay_category"] and t["alipay_category"] in ali_map:
            updates.append((ali_map[t["alipay_category"]], "alipay_map", t["id"]))
            stats["alipay_map"] += 1
        elif hit:
            updates.append((hit["category_id"], "builtin", t["id"]))
            stats["builtin"] += 1
            hit_counts[hit["id"]] = hit_counts.get(hit["id"], 0) + 1
        else:
            updates.append((uncat, "", t["id"]))
            stats["uncategorized"] += 1

    conn.executemany(
        "UPDATE transactions SET category_id=?, category_source=?, "
        "updated_at=datetime('now','localtime') WHERE id=?", updates)
    for rid, cnt in hit_counts.items():
        conn.execute("UPDATE classify_rules SET hit_count=hit_count+? WHERE id=?", (cnt, rid))
    conn.commit()
    stats["total"] = len(rows)
    return stats
