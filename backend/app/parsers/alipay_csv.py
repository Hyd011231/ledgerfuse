"""支付宝交易明细 CSV 解析（GB18030 编码，官方导出格式）。"""
from __future__ import annotations

import csv
import re
from pathlib import Path

from .base import ParsedTxn, ParseResult, extract_card_tail, to_cents

STATUS_OK = {"交易成功", "支付成功", "还款成功", "退款成功", "转出成功"}

HEADER_PREFIX = "交易时间,交易分类"


def _wallet_account(pay_method_main: str) -> tuple[str, str]:
    """收/付款方式主方式 -> (钱包账户名, 卡尾号)。银行卡返回 ('', tail)。"""
    s = pay_method_main
    if not s or s == "/":
        return "", ""
    tail = extract_card_tail(s)
    if "信用卡" in s and tail:
        return "", tail
    if tail:
        return "", tail
    if "余额宝" in s:
        return "余额宝", ""
    if "余利宝" in s:
        return "余利宝", ""
    if s == "账户余额" or "余额" in s:
        return "支付宝余额", ""
    if s.startswith("花呗"):
        return "花呗", ""
    if s.startswith("亲情卡"):
        return "亲情卡", ""
    return s, ""


def parse(path: Path) -> ParseResult:
    text = path.read_text(encoding="gb18030")
    lines = text.splitlines()
    meta: dict = {}
    warnings: list[str] = []

    header_idx = None
    for i, line in enumerate(lines):
        if line.startswith(HEADER_PREFIX):
            header_idx = i
            break
        m = re.search(r"共(\d+)笔记录", line)
        if m:
            meta["total_rows"] = int(m.group(1))
        m = re.search(r"收入：(\d+)笔\s*([\d.]+)元", line)
        if m:
            meta["income_count"], meta["income_total"] = int(m.group(1)), to_cents(m.group(2))
        m = re.search(r"支出：(\d+)笔\s*([\d.]+)元", line)
        if m:
            meta["expense_count"], meta["expense_total"] = int(m.group(1)), to_cents(m.group(2))
        m = re.search(r"不计收支：(\d+)笔\s*([\d.]+)元", line)
        if m:
            meta["neutral_count"], meta["neutral_total"] = int(m.group(1)), to_cents(m.group(2))
        m = re.search(r"支付宝账户：(\S+)", line)
        if m:
            meta["account_id"] = m.group(1)
        m = re.search(r"起始时间：\[([\d\- :]+)\].*终止时间：\[([\d\- :]+)\]", line)
        if m:
            meta["period_start"], meta["period_end"] = m.group(1)[:10], m.group(2)[:10]
    if header_idx is None:
        raise ValueError("未找到支付宝 CSV 表头行（交易时间,交易分类,...）")

    txns: list[ParsedTxn] = []
    reader = csv.reader(lines[header_idx + 1:])
    for row in reader:
        if len(row) < 12:
            continue
        cells = [c.strip(" \t") for c in row]
        (t_time, t_cat, party, party_acct, desc, inout, amount_s,
         pay_method, status, order_id, merchant_id, remark) = cells[:12]
        if not re.match(r"\d{4}-\d{2}-\d{2}", t_time):
            continue
        direction = {"收入": "income", "支出": "expense", "不计收支": "neutral"}.get(inout)
        if direction is None:
            warnings.append(f"未知收/支值 {inout!r}：{t_time} {desc[:20]}")
            continue
        parts = pay_method.split("&")
        main = parts[0].strip()
        wallet, tail = _wallet_account(main)
        txns.append(ParsedTxn(
            trans_time=t_time if len(t_time) > 10 else t_time + " 00:00:00",
            amount=abs(to_cents(amount_s)),
            direction=direction,
            counterparty=party,
            counterparty_account=party_acct if party_acct != "/" else "",
            description=desc,
            pay_method_raw=pay_method,
            trans_type_raw=t_cat,
            status_raw=status,
            status_ok=status in STATUS_OK,
            remark=remark,
            external_id=order_id,
            external_id2=merchant_id,
            alipay_category=t_cat,
            card_tail=tail,
            account_name=wallet,
            is_combo=len(parts) > 1,
            is_refund=("退款" in status) or ("退款" in t_cat) or ("退款" in desc),
            raw={"row": cells[:12]},
        ))
    meta["parsed_rows"] = len(txns)
    return ParseResult(source_type="alipay_csv", txns=txns, meta=meta, warnings=warnings)
