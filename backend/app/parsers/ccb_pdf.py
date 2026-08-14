"""建设银行个人活期账户全部交易明细 PDF 解析（find_tables 可靠）。"""
from __future__ import annotations

import re
from pathlib import Path

import fitz

from .base import ParsedTxn, ParseResult, norm_date, to_cents

CHANNEL_KEYS = [("支付宝", "alipay"), ("财付通", "wechat"), ("微信", "wechat"),
                ("美团", "meituan"), ("京东", "jd"), ("抖音", "douyin")]


def _clean(c: str | None) -> str:
    return (c or "").replace("\n", "").strip()


def _channel_and_party(note: str) -> tuple[str, str, str]:
    """附言 '支付宝-天猫-廊坊市积木家居用品有限公司' -> (channel, counterparty, mid)"""
    channel = ""
    for k, v in CHANNEL_KEYS:
        if note.startswith(k) or k in note[:12]:
            channel = v
            break
    parts = [p for p in note.split("-") if p]
    if len(parts) >= 2:
        return channel, parts[-1], "-".join(parts[:-1])
    return channel, note, ""


def parse(path: Path) -> ParseResult:
    doc = fitz.open(path)
    meta: dict = {}
    warnings: list[str] = []

    p0 = doc[0].get_text()
    m = re.search(r"卡号/账号:(\d+)", p0)
    card_no = m.group(1) if m else ""
    card_tail = card_no[-4:] if card_no else ""
    m = re.search(r"客户名称:(\S+)", p0)
    if m:
        meta["owner_name"] = m.group(1)
    m = re.search(r"起止日期:(\d{8})-(\d{8})", p0)
    if m:
        meta["period_start"], meta["period_end"] = norm_date(m.group(1)), norm_date(m.group(2))
    m = re.search(r"总支出：([\d,\.]+)", p0)
    if m:
        meta["expense_total"] = to_cents(m.group(1))
    m = re.search(r"总收入：([\d,\.]+)", p0)
    if m:
        meta["income_total"] = to_cents(m.group(1))

    txns: list[ParsedTxn] = []
    for page in doc:
        for table in page.find_tables():
            for row in table.extract():
                cells = [_clean(c) for c in row]
                if not cells or cells[0] in ("序号", ""):
                    if not (cells and cells[0] == "" and len(cells) > 2 and re.fullmatch(r"\d{8}", cells[2] or "")):
                        continue
                # 列: 序号 摘要 交易日期 交易金额 账户余额 交易地点/附言 对方账号与户名
                if len(cells) < 7:
                    continue
                seq, summary, date_s, amt_s, bal_s, note, party_acct = cells[:7]
                if not re.fullmatch(r"\d{8}", date_s):
                    continue
                try:
                    signed = to_cents(amt_s)
                    bal = to_cents(bal_s) if bal_s else None
                except ValueError:
                    warnings.append(f"金额解析失败: 序号{seq} {amt_s!r}")
                    continue
                channel, party, mid = _channel_and_party(note)
                txns.append(ParsedTxn(
                    trans_time=f"{norm_date(date_s)} 00:00:00",
                    time_precision="day",
                    amount=abs(signed),
                    direction="expense" if signed < 0 else "income",
                    counterparty=party,
                    counterparty_account=party_acct,
                    description=note,
                    trans_type_raw=summary,
                    remark=mid,
                    balance_after=bal,
                    channel_hint=channel,
                    card_tail=card_tail,
                    is_refund="退" in summary,
                    raw={"cells": cells[:7]},
                ))
    doc.close()

    breaks = 0
    for i in range(1, len(txns)):
        prev, cur = txns[i - 1], txns[i]
        signed = cur.amount if cur.direction == "income" else -cur.amount
        if prev.balance_after is not None and cur.balance_after is not None:
            if prev.balance_after + signed != cur.balance_after:
                breaks += 1
    if breaks:
        warnings.append(f"余额链断裂 {breaks} 处")
    meta["balance_chain_breaks"] = breaks
    meta["parsed_rows"] = len(txns)
    meta["card_no"] = card_no
    return ParseResult(
        source_type="ccb_pdf", txns=txns, meta=meta, warnings=warnings,
        account={"name": f"建设银行({card_tail})", "card_tail": card_tail, "type": "bank"},
    )
