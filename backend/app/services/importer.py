"""导入入库：文件 hash 防重、dedup_key 幂等写入、账户自动建档。"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

from ..db import get_conn, set_setting
from ..parsers.base import ParsedTxn, ParseResult, parse_file

SOURCE_OF = {"alipay_csv": "alipay", "wechat_pdf": "wechat",
             "nbcb_pdf": "nbcb", "ccb_pdf": "ccb", "cmb_pdf": "cmb"}

BANK_NAME_OF_TAIL_HINT = {}  # 运行时由已导入银行账户填充


def file_sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _ensure_account(name: str, card_tail: str = "", acct_type: str = "wallet") -> int:
    conn = get_conn()
    # 同尾号视为同一账户（微信/支付宝里的"招商银行储蓄卡(4775)"与银行流水是同一张卡）；
    # 银行流水导入时用其正式名覆盖渠道侧建的临时名
    if card_tail:
        row = conn.execute(
            "SELECT id, name FROM accounts WHERE card_tail=? AND type=?",
            (card_tail, acct_type)).fetchone()
        if row:
            if acct_type == "bank" and "银行(" in name and row["name"] != name:
                conn.execute("UPDATE accounts SET name=? WHERE id=?", (name, row["id"]))
            return row["id"]
    row = conn.execute("SELECT id FROM accounts WHERE name=?", (name,)).fetchone()
    if row:
        return row["id"]
    cur = conn.execute(
        "INSERT INTO accounts(name, type, card_tail) VALUES(?,?,?)",
        (name, acct_type, card_tail or None))
    return cur.lastrowid


def _account_for_txn(t: ParsedTxn, source: str, bank_account_id: int | None) -> int | None:
    """渠道账单按行解析资金账户；银行流水统一用本卡账户。"""
    if bank_account_id is not None:
        return bank_account_id
    if t.card_tail:
        conn = get_conn()
        row = conn.execute(
            "SELECT id FROM accounts WHERE card_tail=? AND type IN ('bank','credit')",
            (t.card_tail,)).fetchone()
        if row:
            return row["id"]
        acct_type = "credit" if "信用卡" in t.pay_method_raw else "bank"
        bank_label = t.pay_method_raw.split("&")[0].strip() or f"银行卡({t.card_tail})"
        return _ensure_account(bank_label, t.card_tail, acct_type)
    if t.account_name:
        return _ensure_account(t.account_name, "", "wallet")
    return None


def _dedup_key(t: ParsedTxn, source: str, occ: int) -> str:
    if source == "alipay" and t.external_id:
        return f"alipay:{t.external_id}"
    if source == "wechat" and t.external_id:
        return f"wechat:{t.external_id}"
    signed = t.amount if t.direction == "income" else -t.amount
    base = f"{source}|{t.card_tail}|{t.trans_time[:10]}|{signed}|{t.balance_after}|{t.counterparty}|{t.trans_type_raw}"
    h = hashlib.sha1(base.encode("utf-8")).hexdigest()
    return f"{source}:{h}#{occ}"


def preview(path: Path) -> dict:
    """解析并登记 previewed 批次（不入库交易），返回预览信息。"""
    conn = get_conn()
    sha = file_sha256(path)
    exist = conn.execute(
        "SELECT id, status, filename FROM import_batches WHERE file_sha256=?", (sha,)).fetchone()
    if exist and exist["status"] == "committed":
        raise ValueError(f"该文件已导入过（批次 #{exist['id']}: {exist['filename']}）")

    result = parse_file(path)
    source = SOURCE_OF[result.source_type]
    if result.meta.get("owner_name"):
        set_setting("owner_name", result.meta["owner_name"])

    if exist:
        batch_id = exist["id"]
        conn.execute("UPDATE import_batches SET filename=?, summary_json=? WHERE id=?",
                     (path.name, json.dumps({"meta": result.meta, "warnings": result.warnings},
                                            ensure_ascii=False), batch_id))
    else:
        cur = conn.execute(
            "INSERT INTO import_batches(filename, file_sha256, source_type, period_start, period_end, "
            "row_count, summary_json, status) VALUES(?,?,?,?,?,?,?,'previewed')",
            (path.name, sha, result.source_type,
             result.meta.get("period_start"), result.meta.get("period_end"),
             len(result.txns),
             json.dumps({"meta": result.meta, "warnings": result.warnings}, ensure_ascii=False)))
        batch_id = cur.lastrowid
    conn.commit()

    dup_in_db = 0
    seen_keys: dict[str, int] = {}
    for t in result.txns:
        occ_base = f"{source}|{t.card_tail}|{t.trans_time[:10]}|{t.amount}|{t.balance_after}|{t.counterparty}|{t.trans_type_raw}|{t.direction}"
        occ = seen_keys.get(occ_base, 0)
        seen_keys[occ_base] = occ + 1
        key = _dedup_key(t, source, occ)
        if conn.execute("SELECT 1 FROM transactions WHERE dedup_key=?", (key,)).fetchone():
            dup_in_db += 1

    return {
        "batch_id": batch_id,
        "source_type": result.source_type,
        "row_count": len(result.txns),
        "dup_in_db": dup_in_db,
        "meta": result.meta,
        "warnings": result.warnings,
        "sample": [t.__dict__ | {"raw": None} for t in result.txns[:20]],
        "_result": result,   # 内部使用（commit 复用），API 层会剔除
    }


def commit(path: Path, batch_id: int | None = None, result: ParseResult | None = None) -> dict:
    """入库（INSERT OR IGNORE by dedup_key）。"""
    conn = get_conn()
    if result is None:
        result = parse_file(path)
    source = SOURCE_OF[result.source_type]
    sha = file_sha256(path)
    if batch_id is None:
        row = conn.execute("SELECT id FROM import_batches WHERE file_sha256=?", (sha,)).fetchone()
        if row is None:
            p = preview(path)
            batch_id = p["batch_id"]
        else:
            batch_id = row["id"]

    bank_account_id = None
    if result.account:
        bank_account_id = _ensure_account(
            result.account["name"], result.account["card_tail"], result.account["type"])
        conn.execute("UPDATE import_batches SET account_id=? WHERE id=?",
                     (bank_account_id, batch_id))

    imported = skipped = 0
    seen_keys: dict[str, int] = {}
    for t in result.txns:
        occ_base = f"{source}|{t.card_tail}|{t.trans_time[:10]}|{t.amount}|{t.balance_after}|{t.counterparty}|{t.trans_type_raw}|{t.direction}"
        occ = seen_keys.get(occ_base, 0)
        seen_keys[occ_base] = occ + 1
        key = _dedup_key(t, source, occ)
        acct_id = _account_for_txn(t, source, bank_account_id)
        cur = conn.execute(
            """INSERT OR IGNORE INTO transactions
               (batch_id, source, account_id, trans_time, time_precision, amount, direction,
                counterparty, counterparty_account, description, pay_method_raw, trans_type_raw,
                status_raw, status_ok, remark, external_id, external_id2, alipay_category,
                balance_after, channel_hint, card_tail, is_combo, is_refund, dedup_key, raw_json)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (batch_id, source, acct_id, t.trans_time, t.time_precision, t.amount, t.direction,
             t.counterparty, t.counterparty_account, t.description, t.pay_method_raw,
             t.trans_type_raw, t.status_raw, int(t.status_ok), t.remark, t.external_id,
             t.external_id2, t.alipay_category, t.balance_after, t.channel_hint, t.card_tail,
             int(t.is_combo), int(t.is_refund), key,
             json.dumps(t.raw, ensure_ascii=False, default=str)))
        if cur.rowcount:
            imported += 1
        else:
            skipped += 1

    conn.execute(
        "UPDATE import_batches SET status='committed', imported_count=?, skipped_dup_count=?, "
        "row_count=? WHERE id=?",
        (imported, skipped, len(result.txns), batch_id))
    conn.commit()
    return {"batch_id": batch_id, "imported": imported, "skipped_dup": skipped,
            "source_type": result.source_type, "warnings": result.warnings}


def rollback_batch(batch_id: int) -> dict:
    conn = get_conn()
    ids = [r["id"] for r in conn.execute(
        "SELECT id FROM transactions WHERE batch_id=?", (batch_id,)).fetchall()]
    if ids:
        ph = ",".join("?" * len(ids))
        conn.execute(f"DELETE FROM dup_matches WHERE channel_txn_id IN ({ph}) OR bank_txn_id IN ({ph})",
                     ids + ids)
        conn.execute(f"UPDATE transactions SET matched_txn_id=NULL, dup_status='none' "
                     f"WHERE matched_txn_id IN ({ph})", ids)
        conn.execute(f"DELETE FROM transactions WHERE id IN ({ph})", ids)
    conn.execute("DELETE FROM import_batches WHERE id=?", (batch_id,))
    conn.commit()
    return {"deleted_txns": len(ids)}
