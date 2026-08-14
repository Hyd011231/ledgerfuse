"""flow_type 识别：内部转账 / 信用卡口径 / 卡对卡互转。

在跨源去重之前执行。已人工改过 flow_type 的记录（category_source='manual' 不在此列，
flow_type 无手工标记位，这里约定：只把 flow_type='normal' 的记录改为 transfer，
人工复原的记录用 flow_type='normal' + remark 标记不再自动覆盖 —— 简化：每次重跑
都是从解析属性推导，结果确定性，重复执行幂等。）
"""
from __future__ import annotations

from datetime import datetime

from ..db import get_conn, get_setting


def _owner() -> str:
    return get_setting("owner_name", "")


def run() -> dict:
    conn = get_conn()
    owner = _owner()
    stats = {"neutral": 0, "wallet_topup": 0, "huabei_repay": 0, "self_transfer_pair": 0,
             "cmb_channel_topup": 0, "credit_card_spend": 0, "withdraw_to_self": 0}

    # 0) 复位：本函数管理的自动标记全部重推（人工确认的 dup 状态不动，flow_type 全量重推）
    conn.execute("UPDATE transactions SET flow_type='normal' WHERE flow_type IN ('transfer','credit_card_spend')")

    # 1) 渠道账单 neutral（支付宝不计收支 / 微信其他）→ transfer
    cur = conn.execute(
        "UPDATE transactions SET flow_type='transfer' WHERE direction='neutral'")
    stats["neutral"] = cur.rowcount

    # 2) 微信零钱充值/提现、零钱通存取
    cur = conn.execute(
        "UPDATE transactions SET flow_type='transfer' WHERE source='wechat' AND "
        "(trans_type_raw LIKE '%零钱充值%' OR trans_type_raw LIKE '%零钱提现%' "
        " OR trans_type_raw LIKE '%零钱通%')")
    stats["wallet_topup"] = cur.rowcount

    # 3) 支付宝花呗还款/信用卡还款类（花呗消费已计支出，还款不再计）
    cur = conn.execute(
        "UPDATE transactions SET flow_type='transfer' WHERE source='alipay' AND direction='expense' AND "
        "(description LIKE '%花呗%还款%' OR alipay_category='信用借还')")
    stats["huabei_repay"] = cur.rowcount

    # 4) 招行：微信零钱充值 / 给自己支付宝充值（对手为本人）
    if owner:
        cur = conn.execute(
            "UPDATE transactions SET flow_type='transfer' WHERE source='cmb' AND "
            "trans_type_raw LIKE '%快捷支付%' AND counterparty LIKE ? AND "
            "(remark LIKE '%微信零钱充值%' OR remark LIKE ?)",
            (f"%{owner}%", f"%支付宝-{owner}%"))
        stats["cmb_channel_topup"] = cur.rowcount

    # 5) 微信里信用卡(尾号在 credit 账户)支付的消费：口径=还款记支出，明细不计防双计
    credit_tails = [r["card_tail"] for r in conn.execute(
        "SELECT DISTINCT card_tail FROM accounts WHERE type='credit' AND card_tail IS NOT NULL")]
    for tail in credit_tails:
        cur = conn.execute(
            "UPDATE transactions SET flow_type='credit_card_spend' "
            "WHERE source IN ('wechat','alipay') AND card_tail=? AND flow_type='normal'",
            (tail,))
        stats["credit_card_spend"] += cur.rowcount

    # 6) 渠道"转账到银行卡"且收款人为本人 → transfer（提现）
    if owner:
        cur = conn.execute(
            "UPDATE transactions SET flow_type='transfer' WHERE source='alipay' AND "
            "description LIKE '%转账到银行卡%' AND counterparty LIKE ?",
            (f"%{owner[:1]}%",))
        stats["withdraw_to_self"] = cur.rowcount

    # 7) 本人银行卡对卡互转：金额相等、方向相反、日期差<=2天、对方户名含本人姓名或对方卡号
    #    尾号是自己另一张卡 → 双方 transfer 并互记 matched_txn_id
    rows = conn.execute(
        "SELECT t.id, t.account_id, t.trans_time, t.amount, t.direction, t.counterparty, "
        "t.counterparty_account, t.card_tail FROM transactions t "
        "JOIN accounts a ON a.id=t.account_id "
        "WHERE a.type='bank' AND t.flow_type='normal' AND t.is_deleted=0 "
        "ORDER BY t.trans_time").fetchall()
    my_tails = {r["card_tail"] for r in conn.execute(
        "SELECT DISTINCT card_tail FROM accounts WHERE card_tail IS NOT NULL")}

    def is_self_party(r) -> bool:
        if owner and owner in (r["counterparty"] or ""):
            return True
        acct = (r["counterparty_account"] or "").replace("*", "")
        return bool(acct) and acct[-4:] in my_tails

    used: set[int] = set()
    by_amount: dict[int, list] = {}
    for r in rows:
        by_amount.setdefault(r["amount"], []).append(r)
    pairs = 0
    for amount, group in by_amount.items():
        outs = [r for r in group if r["direction"] == "expense" and is_self_party(r)]
        ins = [r for r in group if r["direction"] == "income" and is_self_party(r)]
        for o in outs:
            if o["id"] in used:
                continue
            od = datetime.fromisoformat(o["trans_time"])
            best = None
            for i_ in ins:
                if i_["id"] in used or i_["account_id"] == o["account_id"]:
                    continue
                dd = abs((datetime.fromisoformat(i_["trans_time"]) - od).days)
                if dd <= 2 and (best is None or dd < best[0]):
                    best = (dd, i_)
            if best:
                i_ = best[1]
                used.update({o["id"], i_["id"]})
                conn.execute("UPDATE transactions SET flow_type='transfer', matched_txn_id=? WHERE id=?",
                             (i_["id"], o["id"]))
                conn.execute("UPDATE transactions SET flow_type='transfer', matched_txn_id=? WHERE id=?",
                             (o["id"], i_["id"]))
                pairs += 1
    stats["self_transfer_pair"] = pairs

    conn.commit()
    return stats


def member_transfers() -> dict:
    """家庭成员间往来标为内部转账（在 dedup + refund_pairs 之后执行）。

    渠道侧转账的银行影子已被 dedup 标 confirmed_dup；这里处理：
    - 渠道侧给成员的转账（含转账到银行卡）
    - 银行流水中对手户名直接是成员的往来（账期外没有渠道明细的）
    """
    conn = get_conn()
    names = [r["name"] for r in conn.execute("SELECT name FROM members WHERE is_self=0")]
    n = 0
    for name in names:
        cur = conn.execute(
            "UPDATE transactions SET flow_type='transfer' WHERE flow_type='normal' AND "
            "source IN ('alipay','wechat') AND counterparty LIKE ? AND "
            "(trans_type_raw LIKE '%转账%' OR description LIKE '%转账%' "
            " OR description LIKE '%Transfer%')",
            (f"%{name}%",))
        n += cur.rowcount
        cur = conn.execute(
            "UPDATE transactions SET flow_type='transfer' WHERE flow_type='normal' AND "
            "source IN ('nbcb','ccb','cmb') AND dup_status IN ('none','not_dup') "
            "AND counterparty LIKE ?",
            (f"%{name}%",))
        n += cur.rowcount
    conn.commit()
    return {"member_transfer": n}


def refund_pairs() -> dict:
    """渠道内"转账支出 + 转账退款收入"对冲（转出又被退回，净额为零）。

    在 dedup 之后执行：渠道对标 transfer 后，其银行侧影子已是 confirmed_dup 不计。
    """
    conn = get_conn()
    rows = conn.execute(
        "SELECT id, source, trans_time, amount, direction, trans_type_raw, counterparty "
        "FROM transactions WHERE source IN ('alipay','wechat') AND flow_type='normal' "
        "AND is_deleted=0 AND ("
        " (direction='expense' AND trans_type_raw LIKE '%转账%') OR "
        " (direction='income'  AND trans_type_raw LIKE '%退款%' AND trans_type_raw LIKE '%转账%'))"
        "ORDER BY trans_time").fetchall()
    outs = [dict(r) for r in rows if r["direction"] == "expense"]
    ins = [dict(r) for r in rows if r["direction"] == "income"]
    used: set[int] = set()
    pairs = 0
    for i_ in ins:
        it = datetime.fromisoformat(i_["trans_time"])
        best = None
        for o in outs:
            if o["id"] in used or o["source"] != i_["source"] or o["amount"] != i_["amount"]:
                continue
            ot = datetime.fromisoformat(o["trans_time"])
            dd = (it - ot).total_seconds()
            if 0 <= dd <= 7 * 86400 and (best is None or dd < best[0]):
                best = (dd, o)
        if best:
            o = best[1]
            used.update({o["id"], i_["id"]})
            conn.execute("UPDATE transactions SET flow_type='transfer', matched_txn_id=? WHERE id=?",
                         (i_["id"], o["id"]))
            conn.execute("UPDATE transactions SET flow_type='transfer', matched_txn_id=? WHERE id=?",
                         (o["id"], i_["id"]))
            pairs += 1
    conn.commit()
    return {"refund_pairs": pairs}
