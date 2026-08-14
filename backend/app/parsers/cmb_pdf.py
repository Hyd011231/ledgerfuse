"""招商银行交易流水 PDF 解析。

版式：纵向、无表格线 -> words 坐标法；单元格多行内容围绕记录中心线上下展开，
用"最近锚点中心"归属词（group_records_centered）。表头中英双行，跳过英文行。
"""
from __future__ import annotations

import re
from pathlib import Path

import fitz

from .base import ParsedTxn, ParseResult, to_cents
from .pdf_utils import (column_bounds, find_header_row, group_records_centered,
                        record_to_cells, visual_words)

LABELS = ["记账日期", "货币", "交易金额", "联机余额", "交易摘要", "对手信息", "客户摘要"]
DATE_RE = re.compile(r"\d{4}-\d{2}-\d{2}")
EN_WORDS = {"Date", "Currency", "Transaction", "Amount", "Balance", "Type",
            "Counter", "Party", "Customer"}

CHANNEL_KEYS = [("财付通", "wechat"), ("微信", "wechat"), ("支付宝", "alipay")]


def parse(path: Path) -> ParseResult:
    doc = fitz.open(path)
    meta: dict = {}
    warnings: list[str] = []

    p0 = doc[0].get_text()
    m = re.search(r"账号：(\d+)", p0)
    card_no = m.group(1) if m else ""
    card_tail = card_no[-4:] if card_no else ""
    m = re.search(r"户\s*名：(\S+)", p0)
    if m:
        meta["owner_name"] = m.group(1)
    m = re.search(r"(\d{4}-\d{2}-\d{2})\s*--\s*(\d{4}-\d{2}-\d{2})", p0)
    if m:
        meta["period_start"], meta["period_end"] = m.group(1), m.group(2)

    full_text = "\n".join(doc[i].get_text() for i in range(doc.page_count))
    m = re.search(r"合并收入\(\+\)[\s\S]*?([\d,]+\.\d{2})[\s\S]*?(-?[\d,]+\.\d{2})", full_text)
    if m:
        meta["income_total"] = to_cents(m.group(1))
        meta["expense_total"] = abs(to_cents(m.group(2)))

    txns: list[ParsedTxn] = []
    bounds = None
    date_col = None
    for page in doc:
        words = [w for w in visual_words(page)
                 if not re.fullmatch(r"[—\-]+", w["text"]) and w["text"] not in EN_WORDS]
        cols = find_header_row(words, LABELS)
        header_y = None
        if cols is not None and len(cols) >= 6:
            page_w = page.rect.width
            bounds = column_bounds(cols, page_w)
            header_y = max(c["cy"] for c in cols)
            date_idx = next(i for i, c in enumerate(cols) if c["label"] == "记账日期")
            date_col = bounds[date_idx]
        if bounds is None:
            continue
        # y 范围：表头下方（跳过英文表头行 ~20pt）到"合并统计"或页脚之前
        y_start = (header_y + 22) if header_y is not None else 0
        y_end = page.rect.height
        for w in words:
            if w["text"] in ("合并统计", "温馨提示：") or "温馨提示" in w["text"]:
                y_end = min(y_end, w["y0"] - 2)
        for rec in group_records_centered(words, DATE_RE, date_col, y_start, y_end):
            cells = record_to_cells(rec, bounds)
            if len(cells) < 7:
                continue
            date_s, ccy, amt_s, bal_s, summary, party, cust = cells[:7]
            dm = DATE_RE.match(date_s)
            if not dm or not amt_s:
                continue
            try:
                signed = to_cents(amt_s)
                bal = to_cents(bal_s) if bal_s else None
            except ValueError:
                warnings.append(f"金额解析失败: {date_s} {amt_s!r}")
                continue
            channel = ""
            for k, v in CHANNEL_KEYS:
                if k in party:
                    channel = v
                    break
            txns.append(ParsedTxn(
                trans_time=f"{dm.group(0)} 00:00:00",
                time_precision="day",
                amount=abs(signed),
                direction="expense" if signed < 0 else "income",
                counterparty=party,
                description=summary,
                trans_type_raw=summary,
                remark=cust,
                balance_after=bal,
                channel_hint=channel,
                card_tail=card_tail,
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
        source_type="cmb_pdf", txns=txns, meta=meta, warnings=warnings,
        account={"name": f"招商银行({card_tail})", "card_tail": card_tail, "type": "bank"},
    )
