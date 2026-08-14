"""宁波银行交易流水 PDF 解析。

版式：横向页（rotation=90）、无表格线 -> words 坐标法。
数据行顶对齐：日期词的 y0 即记录起始行，下一日期词之前的词都属于本记录。
"""
from __future__ import annotations

import re
from pathlib import Path

import fitz

from .base import ParsedTxn, ParseResult, to_cents
from .pdf_utils import (column_bounds, find_header_row, group_records,
                        record_to_cells, visual_words)

LABELS = ["日期", "摘要", "币种", "交易金额", "余额", "对方户名", "对方账号/卡号",
          "对方开户行", "交易备注", "交易柜员"]
DATE_RE = re.compile(r"\d{4}-\d{2}-\d{2}")

CHANNEL_KEYS = [("财付通", "wechat"), ("微信支付", "wechat"), ("支付宝", "alipay"),
                ("网银在线", "jd"), ("京东", "jd"), ("抖音", "douyin"), ("美团支付", "meituan")]


def _channel(bank: str, remark: str) -> str:
    s = bank + remark
    for k, v in CHANNEL_KEYS:
        if k in s:
            return v
    return ""


def parse(path: Path) -> ParseResult:
    doc = fitz.open(path)
    meta: dict = {}
    warnings: list[str] = []

    p0_text = doc[0].get_text()
    m = re.search(r"卡\s*号:\s*(\d+)", p0_text) or re.search(r"(\d{16,19})", p0_text)
    card_no = m.group(1) if m else ""
    card_tail = card_no[-4:] if card_no else ""
    m = re.search(r"户\s*名:\s*(\S+)", p0_text)
    if m:
        meta["owner_name"] = m.group(1)
    m = re.search(r"(\d{4}-\d{2}-\d{2})\s*—\s*(\d{4}-\d{2}-\d{2})", p0_text)
    if m:
        meta["period_start"], meta["period_end"] = m.group(1), m.group(2)
    # 合并统计：合并收入（+）  合并支出（-）下方  人民币  28984.68  137807.48
    m = re.search(r"人民币\s*\n\s*([\d,.]+)\s*\n\s*([\d,.]+)", p0_text)
    if m:
        meta["income_total"] = to_cents(m.group(1))
        meta["expense_total"] = to_cents(m.group(2))

    txns: list[ParsedTxn] = []
    bounds = None
    date_col = None
    for page in doc:
        words = visual_words(page)
        words = [w for w in words if not re.fullmatch(r"[—\-]+", w["text"])]
        cols = find_header_row(words, LABELS)
        if cols is not None and len(cols) >= 8:
            page_w = max(w["x1"] for w in words) + 10
            bounds = column_bounds(cols, page_w)
            header_y = max(c["cy"] for c in cols)
            date_idx = next(i for i, c in enumerate(cols) if c["label"] == "日期")
            date_col = bounds[date_idx]
        if bounds is None:
            continue
        y_start = header_y + 3 if cols is not None else 0
        y_end = max(w["y1"] for w in words) + 1
        # 页脚提示行之前截断
        for w in words:
            if "本交易流水" in w["text"] or "验证真实" in w["text"]:
                y_end = min(y_end, w["y0"] - 1)
        for rec in group_records(words, DATE_RE, date_col, y_start, y_end):
            cells = record_to_cells(rec, bounds)
            if len(cells) < 10:
                continue
            date_s, summary, ccy, amt_s, bal_s, party, party_acct, bank, remark, teller = cells[:10]
            dm = DATE_RE.match(date_s)
            if not dm:
                continue
            try:
                signed = to_cents(amt_s.replace("−", "-"))
                bal = to_cents(bal_s)
            except ValueError:
                warnings.append(f"金额/余额解析失败: {date_s} {amt_s!r} {bal_s!r}")
                continue
            summary_clean = date_s[len(dm.group(0)):] + summary  # 摘要可能与日期同列粘连
            txns.append(ParsedTxn(
                trans_time=f"{dm.group(0)} 00:00:00",
                time_precision="day",
                amount=abs(signed),
                direction="expense" if signed < 0 else "income",
                counterparty=party,
                counterparty_account=party_acct,
                description=remark,
                trans_type_raw=summary_clean or summary,
                remark=remark,
                balance_after=bal,
                channel_hint=_channel(bank, remark),
                card_tail=card_tail,
                is_refund="退款" in summary_clean or "退款" in remark,
                raw={"cells": cells, "bank": bank, "teller": teller},
            ))
    doc.close()

    # 余额链自检（文件内顺序应按时间升序）
    breaks = 0
    for i in range(1, len(txns)):
        prev, cur = txns[i - 1], txns[i]
        signed = cur.amount if cur.direction == "income" else -cur.amount
        if prev.balance_after is not None and cur.balance_after is not None:
            if prev.balance_after + signed != cur.balance_after:
                breaks += 1
    if breaks:
        warnings.append(f"余额链断裂 {breaks} 处（可能存在漏行或错列）")
    meta["balance_chain_breaks"] = breaks
    meta["parsed_rows"] = len(txns)
    meta["card_no"] = card_no
    return ParseResult(
        source_type="nbcb_pdf", txns=txns, meta=meta, warnings=warnings,
        account={"name": f"宁波银行({card_tail})", "card_tail": card_tail, "type": "bank"},
    )
