"""微信支付交易明细证明 PDF 解析（find_tables 可靠，跨行断裂单元格自动合并）。"""
from __future__ import annotations

import re
from pathlib import Path

import fitz

from .base import ParsedTxn, ParseResult, extract_card_tail, to_cents

COLS = ["交易单号", "交易时间", "交易类型", "收/支/其他", "交易方式", "金额", "交易对方", "商户单号"]
DT_RE = re.compile(r"(\d{4}-\d{2}-\d{2})\s*(\d{2}:\d{2}:\d{2})?")


def _clean(cell: str | None, keep_space: bool = False) -> str:
    if cell is None:
        return ""
    return cell.replace("\n", " " if keep_space else "").strip()


def _col_index(header_row: list[str]) -> dict[int, str] | None:
    mapping = {}
    for i, cell in enumerate(header_row):
        c = _clean(cell)
        for name in COLS:
            if c and (name in c or c in name):
                mapping[i] = name
                break
    return mapping if len(mapping) >= 6 else None


def parse(path: Path) -> ParseResult:
    doc = fitz.open(path)
    meta: dict = {}
    warnings: list[str] = []

    p0_text = doc[0].get_text()
    m = re.search(r"兹证明：(\S+?)（", p0_text)
    if m:
        meta["owner_name"] = m.group(1)
    m = re.search(r"微信号：(\S+?)中", p0_text)
    if m:
        meta["wechat_id"] = m.group(1)
    m = re.search(r"(\d{4}-\d{2}-\d{2}) \d{2}:\d{2}:\d{2}\s*至\s*(\d{4}-\d{2}-\d{2})", p0_text)
    if m:
        meta["period_start"], meta["period_end"] = m.group(1), m.group(2)

    txns: list[ParsedTxn] = []
    col_map: dict[int, str] | None = None
    for page in doc:
        for table in page.find_tables():
            rows = table.extract()
            for row in rows:
                cells = [(_clean(c)) for c in row]
                if not any(cells):
                    continue
                maybe = _col_index(row)
                if maybe and any("交易单号" in (c or "") for c in cells):
                    col_map = maybe
                    continue
                if col_map is None:
                    continue
                rec = {name: "" for name in COLS}
                for i, cell in enumerate(row):
                    name = col_map.get(i)
                    if name:
                        rec[name] = _clean(cell, keep_space=(name == "交易时间"))
                dm = DT_RE.search(rec["交易时间"])
                if not dm:
                    continue
                trans_time = f"{dm.group(1)} {dm.group(2) or '00:00:00'}"
                inout = rec["收/支/其他"]
                direction = {"支出": "expense", "收入": "income"}.get(inout, "neutral")
                pay = rec["交易方式"]
                tail = extract_card_tail(pay)
                wallet = ""
                if not tail:
                    if "零钱通" in pay:
                        wallet = "微信零钱通"
                    elif "零钱" in pay:
                        wallet = "微信零钱"
                    elif pay and pay != "/":
                        wallet = pay
                try:
                    amount = abs(to_cents(rec["金额"]))
                except ValueError:
                    warnings.append(f"金额解析失败: {rec['金额']!r} @ {trans_time}")
                    continue
                ttype = rec["交易类型"]
                txns.append(ParsedTxn(
                    trans_time=trans_time,
                    amount=amount,
                    direction=direction,
                    counterparty=rec["交易对方"] if rec["交易对方"] != "/" else "",
                    description=ttype,
                    pay_method_raw=pay,
                    trans_type_raw=ttype,
                    status_ok=True,
                    external_id=rec["交易单号"],
                    external_id2=rec["商户单号"] if rec["商户单号"] != "/" else "",
                    card_tail=tail,
                    account_name=wallet,
                    is_refund="退款" in ttype,
                    raw={"row": [(_clean(c)) for c in row]},
                ))
    doc.close()
    meta["parsed_rows"] = len(txns)
    n_exp = sum(1 for t in txns if t.direction == "expense")
    n_inc = sum(1 for t in txns if t.direction == "income")
    meta["expense_count"], meta["income_count"] = n_exp, n_inc
    meta["neutral_count"] = len(txns) - n_exp - n_inc
    meta["expense_total"] = sum(t.amount for t in txns if t.direction == "expense")
    meta["income_total"] = sum(t.amount for t in txns if t.direction == "income")
    return ParseResult(source_type="wechat_pdf", txns=txns, meta=meta, warnings=warnings)
