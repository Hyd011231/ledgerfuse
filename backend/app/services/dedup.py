"""跨源去重引擎：渠道账单（微信/支付宝）为主记录，银行流水中对应扣款标记重复。

分桶(channel, card_tail, direction, amount) -> 日期窗口内贪心一对一匹配。
人工裁决（confirmed / rejected / not_dup）永不被重跑覆盖。
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta

from ..config import (COMBO_MAX_DISCOUNT_CENTS, COMBO_MAX_DISCOUNT_RATIO,
                      DEDUP_LAG_AFTER_DAYS, DEDUP_LAG_BEFORE_DAYS)
from ..db import get_conn

BANK_SOURCES = ("nbcb", "ccb", "cmb")


def _channel_period_start(conn) -> dict[str, str]:
    """各渠道已导入账单的最早日期，用于账期裁剪。"""
    out = {}
    for src in ("alipay", "wechat"):
        row = conn.execute(
            "SELECT MIN(period_start) AS s FROM import_batches "
            "WHERE status='committed' AND source_type LIKE ?", (f"{src}%",)).fetchone()
        if row and row["s"]:
            out[src] = row["s"]
    return out


def run() -> dict:
    conn = get_conn()
    stats = {"auto_confirmed": 0, "suspect": 0, "combo_suspect": 0, "unmatched_channel": 0,
             "unmatched_bank": 0, "protected": 0}

    # 人工裁决保护集
    protected_bank = {r["bank_txn_id"] for r in conn.execute(
        "SELECT bank_txn_id FROM dup_matches WHERE status IN ('confirmed','rejected')")}
    manual_not_dup = {r["id"] for r in conn.execute(
        "SELECT id FROM transactions WHERE dup_status='not_dup'")}
    rejected_pairs = {(r["channel_txn_id"], r["bank_txn_id"]) for r in conn.execute(
        "SELECT channel_txn_id, bank_txn_id FROM dup_matches WHERE status='rejected'")}
    stats["protected"] = len(protected_bank) + len(manual_not_dup)

    # 复位自动结果（保留人工裁决）
    conn.execute("DELETE FROM dup_matches WHERE status IN ('auto_confirmed','suspect')")
    conn.execute(
        "UPDATE transactions SET dup_status='none', matched_txn_id=NULL "
        "WHERE dup_status IN ('suspect','confirmed_dup') AND id NOT IN "
        "(SELECT bank_txn_id FROM dup_matches WHERE status='confirmed')")

    period = _channel_period_start(conn)

    # 渠道侧候选：卡支付、normal、成功状态
    channel_rows = conn.execute(
        "SELECT id, source, trans_time, amount, direction, card_tail, is_combo, counterparty "
        "FROM transactions WHERE source IN ('alipay','wechat') AND flow_type='normal' "
        "AND status_ok=1 AND is_deleted=0 AND card_tail != '' "
        "AND direction IN ('income','expense')").fetchall()

    # 银行侧候选：渠道扣款且未被保护
    bank_rows = conn.execute(
        "SELECT t.id, t.source, t.trans_time, t.amount, t.direction, t.channel_hint, "
        "a.card_tail AS card_tail FROM transactions t JOIN accounts a ON a.id=t.account_id "
        "WHERE t.source IN ('nbcb','ccb','cmb') AND t.flow_type='normal' AND t.is_deleted=0 "
        "AND t.channel_hint IN ('alipay','wechat')").fetchall()

    lag_before = timedelta(days=DEDUP_LAG_BEFORE_DAYS)
    lag_after = timedelta(days=DEDUP_LAG_AFTER_DAYS)

    def bank_in_period(b) -> bool:
        start = period.get(b["channel_hint"])
        if not start:
            return False  # 该渠道无账单，全部保持 normal 由分类兜底
        return b["trans_time"][:10] >= (datetime.fromisoformat(start) - lag_before).strftime("%Y-%m-%d")

    bank_pool = [b for b in bank_rows
                 if b["id"] not in protected_bank and b["id"] not in manual_not_dup
                 and bank_in_period(b)]

    # ---- 第一轮：金额精确相等 ----
    buckets: dict[tuple, dict[str, list]] = {}
    for c in channel_rows:
        key = (c["source"], c["card_tail"], c["direction"], c["amount"])
        buckets.setdefault(key, {"c": [], "b": []})["c"].append(dict(c))
    for b in bank_pool:
        key = (b["channel_hint"], b["card_tail"], b["direction"], b["amount"])
        if key in buckets:
            buckets[key]["b"].append(dict(b))

    used_c: set[int] = set()
    used_b: set[int] = set()

    def try_match(c_list, b_list, strict: bool):
        matched = []
        pairs = []
        for c in c_list:
            ct = datetime.fromisoformat(c["trans_time"])
            for b in b_list:
                if (c["id"], b["id"]) in rejected_pairs:
                    continue
                bt = datetime.fromisoformat(b["trans_time"])
                delta = bt.date() - ct.date()
                if -lag_before.days <= delta.days <= lag_after.days:
                    cost = abs(delta.days) * 86400 + abs((bt - ct).total_seconds()) % 86400
                    pairs.append((cost, c, b))
        pairs.sort(key=lambda p: p[0])
        for cost, c, b in pairs:
            if c["id"] in used_c or b["id"] in used_b:
                continue
            used_c.add(c["id"])
            used_b.add(b["id"])
            matched.append((c, b, cost))
        return matched

    for key, bucket in buckets.items():
        c_list, b_list = bucket["c"], bucket["b"]
        if not b_list:
            continue
        matched = try_match(c_list, b_list, strict=True)
        unambiguous = len(c_list) == len(b_list) == len(matched)
        for c, b, cost in matched:
            date_diff = (datetime.fromisoformat(b["trans_time"]).date()
                         - datetime.fromisoformat(c["trans_time"]).date()).days
            if unambiguous or (len(matched) == len(b_list)):
                status, dup = "auto_confirmed", "confirmed_dup"
                stats["auto_confirmed"] += 1
            else:
                status, dup = "suspect", "suspect"
                stats["suspect"] += 1
            conn.execute(
                "INSERT OR IGNORE INTO dup_matches(channel_txn_id, bank_txn_id, score, "
                "date_diff_days, match_reason, status) VALUES(?,?,?,?,?,?)",
                (c["id"], b["id"], cost, date_diff,
                 json.dumps({"amount_equal": True, "bucket": list(map(str, key))}, ensure_ascii=False),
                 status))
            conn.execute("UPDATE transactions SET dup_status=?, matched_txn_id=? WHERE id=?",
                         (dup, c["id"], b["id"]))

    # ---- 第二轮：组合支付立减（银行实扣 < 渠道账单金额）----
    combo_channel = [c for c in channel_rows
                     if c["is_combo"] and c["id"] not in used_c and c["direction"] == "expense"]
    remaining_bank = [b for b in bank_pool if b["id"] not in used_b and b["direction"] == "expense"]
    for c in combo_channel:
        ct = datetime.fromisoformat(c["trans_time"])
        best = None
        for b in remaining_bank:
            if b["id"] in used_b or b["channel_hint"] != c["source"] or b["card_tail"] != c["card_tail"]:
                continue
            if (c["id"], b["id"]) in rejected_pairs:
                continue
            diff = c["amount"] - b["amount"]
            if not (0 < diff <= min(int(c["amount"] * COMBO_MAX_DISCOUNT_RATIO), COMBO_MAX_DISCOUNT_CENTS)):
                continue
            bt = datetime.fromisoformat(b["trans_time"])
            dd = (bt.date() - ct.date()).days
            if -lag_before.days <= dd <= lag_after.days:
                cost = abs(dd) * 86400 + diff
                if best is None or cost < best[0]:
                    best = (cost, b, dd)
        if best:
            cost, b, dd = best
            used_c.add(c["id"])
            used_b.add(b["id"])
            conn.execute(
                "INSERT OR IGNORE INTO dup_matches(channel_txn_id, bank_txn_id, score, "
                "date_diff_days, match_reason, status) VALUES(?,?,?,?,?,'suspect')",
                (c["id"], b["id"], cost, dd,
                 json.dumps({"amount_equal": False, "combo_discount": c["amount"] - b["amount"]},
                            ensure_ascii=False)))
            conn.execute("UPDATE transactions SET dup_status='suspect', matched_txn_id=? WHERE id=?",
                         (c["id"], b["id"]))
            stats["combo_suspect"] += 1

    # ---- 第三轮：合单匹配（银行一笔 = 渠道同卡同日 2~3 笔之和，如外卖拆单）----
    from itertools import combinations
    rem_c = [c for c in channel_rows if c["id"] not in used_c and c["direction"] == "expense"]
    rem_b = [b for b in bank_pool if b["id"] not in used_b and b["direction"] == "expense"]
    c_by_day: dict[tuple, list] = {}
    for c in rem_c:
        c_by_day.setdefault((c["source"], c["card_tail"], c["trans_time"][:10]), []).append(dict(c))
    for b in rem_b:
        if b["id"] in used_b:
            continue
        bt = datetime.fromisoformat(b["trans_time"])
        found = None
        for dd in range(-DEDUP_LAG_BEFORE_DAYS, DEDUP_LAG_AFTER_DAYS + 1):
            day = (bt - timedelta(days=dd)).strftime("%Y-%m-%d")
            group = [c for c in c_by_day.get((b["channel_hint"], b["card_tail"], day), [])
                     if c["id"] not in used_c]
            if len(group) < 2:
                continue
            for k in (2, 3):
                for combo in combinations(group, k):
                    if sum(c["amount"] for c in combo) == b["amount"]:
                        found = (combo, dd)
                        break
                if found:
                    break
            if found:
                break
        if found:
            combo, dd = found
            used_b.add(b["id"])
            for c in combo:
                used_c.add(c["id"])
                conn.execute(
                    "INSERT OR IGNORE INTO dup_matches(channel_txn_id, bank_txn_id, score, "
                    "date_diff_days, match_reason, status) VALUES(?,?,?,?,?,'suspect')",
                    (c["id"], b["id"], abs(dd) * 86400, dd,
                     json.dumps({"amount_equal": False, "split_order": len(combo)}, ensure_ascii=False)))
            conn.execute("UPDATE transactions SET dup_status='suspect', matched_txn_id=? WHERE id=?",
                         (combo[0]["id"], b["id"]))
            stats["combo_suspect"] += 1

    stats["unmatched_channel"] = len([c for c in channel_rows if c["id"] not in used_c])
    stats["unmatched_bank"] = len([b for b in bank_pool if b["id"] not in used_b])

    # 一致性清理：suspect 状态必须有对应的 suspect 匹配行，否则复位
    # （人工确认/拒绝与管线重跑交错时可能残留孤儿状态）
    conn.execute(
        "UPDATE transactions SET dup_status='confirmed_dup' WHERE dup_status='suspect' "
        "AND id IN (SELECT bank_txn_id FROM dup_matches WHERE status IN ('confirmed','auto_confirmed'))")
    conn.execute(
        "UPDATE transactions SET dup_status='none', matched_txn_id=NULL WHERE dup_status='suspect' "
        "AND id NOT IN (SELECT bank_txn_id FROM dup_matches WHERE status='suspect')")
    conn.commit()
    return stats


def decide(match_id: int, accept: bool) -> dict:
    """复核：accept=True 确认重复；False 拒绝（银行记录恢复计入）。

    同一笔银行扣款可能对应多行匹配（合单：多笔渠道交易 = 一笔银行扣款），
    人工裁决按银行交易整组生效，避免"确认了一行还剩几行"的残留。
    """
    conn = get_conn()
    m = conn.execute("SELECT * FROM dup_matches WHERE id=?", (match_id,)).fetchone()
    if not m:
        raise ValueError(f"匹配 #{match_id} 不存在")
    group = conn.execute(
        "SELECT id, channel_txn_id FROM dup_matches WHERE bank_txn_id=? AND "
        "status IN ('suspect','auto_confirmed')", (m["bank_txn_id"],)).fetchall()
    ids = [g["id"] for g in group] or [match_id]
    ph = ",".join("?" * len(ids))
    if accept:
        conn.execute(f"UPDATE dup_matches SET status='confirmed', "
                     f"decided_at=datetime('now','localtime') WHERE id IN ({ph})", ids)
        conn.execute("UPDATE transactions SET dup_status='confirmed_dup', matched_txn_id=? WHERE id=?",
                     (m["channel_txn_id"], m["bank_txn_id"]))
    else:
        conn.execute(f"UPDATE dup_matches SET status='rejected', "
                     f"decided_at=datetime('now','localtime') WHERE id IN ({ph})", ids)
        conn.execute("UPDATE transactions SET dup_status='not_dup', matched_txn_id=NULL WHERE id=?",
                     (m["bank_txn_id"],))
    conn.commit()
    return {"match_id": match_id, "accepted": accept, "group_size": len(ids)}
