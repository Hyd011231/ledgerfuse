"""解析器公共数据模型与工具。"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from decimal import Decimal
from pathlib import Path


@dataclass
class ParsedTxn:
    trans_time: str                   # 'YYYY-MM-DD HH:MM:SS'
    amount: int                       # 分，恒为正
    direction: str                    # income / expense / neutral
    time_precision: str = "second"    # second / day
    counterparty: str = ""
    counterparty_account: str = ""
    description: str = ""
    pay_method_raw: str = ""
    trans_type_raw: str = ""
    status_raw: str = ""
    status_ok: bool = True
    remark: str = ""
    external_id: str = ""
    external_id2: str = ""
    alipay_category: str = ""
    balance_after: int | None = None
    channel_hint: str = ""            # 银行侧：wechat/alipay/jd/...
    card_tail: str = ""               # 渠道侧=扣款卡尾号；银行侧=本卡尾号
    account_name: str = ""            # 资金账户名（钱包类：微信零钱/支付宝余额/...）
    is_combo: bool = False
    is_refund: bool = False
    raw: dict = field(default_factory=dict)


@dataclass
class ParseResult:
    source_type: str                  # alipay_csv/wechat_pdf/nbcb_pdf/ccb_pdf/cmb_pdf
    txns: list[ParsedTxn]
    meta: dict = field(default_factory=dict)      # 账单自带汇总、户名、卡号、账期等
    warnings: list[str] = field(default_factory=list)
    account: dict | None = None       # 银行流水：{'name','card_tail','type'}


_AMOUNT_CLEAN = re.compile(r"[¥￥,，\s]")


def to_cents(s: str | float | int) -> int:
    """金额字符串 -> 整数分（带符号）。"""
    if isinstance(s, (int, float)):
        return int(round(Decimal(str(s)) * 100))
    s = _AMOUNT_CLEAN.sub("", str(s))
    if not s or s in ("-", "/"):
        raise ValueError(f"无法解析金额: {s!r}")
    return int(Decimal(s) * 100)


_CARD_TAIL = re.compile(r"[（(](\d{4})[)）]")


def extract_card_tail(s: str) -> str:
    m = _CARD_TAIL.search(s or "")
    return m.group(1) if m else ""


def norm_date(s: str) -> str:
    """'20250701' / '2025-07-01' -> '2025-07-01'"""
    s = s.strip()
    if re.fullmatch(r"\d{8}", s):
        return f"{s[:4]}-{s[4:6]}-{s[6:]}"
    return s


def detect_file_type(path: str | Path) -> str:
    """返回 source_type，识别失败抛 ValueError。"""
    path = Path(path)
    if path.suffix.lower() == ".csv":
        head = path.read_bytes()[:2000].decode("gb18030", errors="ignore")
        if "支付宝" in head:
            return "alipay_csv"
        raise ValueError("无法识别的 CSV 文件（不是支付宝账单导出）")
    if path.suffix.lower() == ".pdf":
        import fitz
        with fitz.open(path) as doc:
            if doc.needs_pass:
                raise ValueError("PDF 有密码保护，请先解密")
            text = doc[0].get_text()
        if "微信支付交易明细证明" in text:
            return "wechat_pdf"
        if "宁波银行交易流水" in text:
            return "nbcb_pdf"
        if "建设银行" in text and "交易明细" in text:
            return "ccb_pdf"
        if "招商银行交易流水" in text:
            return "cmb_pdf"
        raise ValueError("无法识别的 PDF 账单格式")
    raise ValueError(f"不支持的文件类型: {path.suffix}")


def parse_file(path: str | Path, source_type: str | None = None) -> ParseResult:
    source_type = source_type or detect_file_type(path)
    if source_type == "alipay_csv":
        from .alipay_csv import parse
    elif source_type == "wechat_pdf":
        from .wechat_pdf import parse
    elif source_type == "nbcb_pdf":
        from .nbcb_pdf import parse
    elif source_type == "ccb_pdf":
        from .ccb_pdf import parse
    elif source_type == "cmb_pdf":
        from .cmb_pdf import parse
    else:
        raise ValueError(f"未知 source_type: {source_type}")
    return parse(Path(path))
