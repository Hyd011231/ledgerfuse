"""CLI 验证入口：解析 -> 入库 -> 转账识别 -> 去重 -> 分类 -> 对账报告。

用法：
  python cli.py import-all <账单目录>
  python cli.py report
  python cli.py reset        # 清空数据库重来
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from app.config import DB_PATH  # noqa: E402
from app.db import get_conn, init_db  # noqa: E402


def cmd_reset():
    for suffix in ("", "-wal", "-shm"):
        p = Path(str(DB_PATH) + suffix)
        if p.exists():
            p.unlink()
    init_db()
    print("数据库已重置")


def cmd_import_all(folder: str):
    init_db()
    from app.parsers.base import detect_file_type
    from app.services import classifier, dedup, importer, transfer

    files = sorted(Path(folder).iterdir())
    for f in files:
        if f.suffix.lower() not in (".csv", ".pdf"):
            continue
        try:
            st = detect_file_type(f)
        except ValueError as e:
            print(f"跳过 {f.name}: {e}")
            continue
        try:
            r = importer.commit(f)
            print(f"[{st}] {f.name}: 新增 {r['imported']} 跳过 {r['skipped_dup']}"
                  + (f" warnings={r['warnings']}" if r["warnings"] else ""))
        except ValueError as e:
            print(f"[{st}] {f.name}: {e}")

    print("\n-- 转账识别 --")
    print(transfer.run())
    print("-- 跨源去重 --")
    print(dedup.run())
    print("-- 转账退款对冲 --")
    print(transfer.refund_pairs())
    print("-- 成员互转 --")
    print(transfer.member_transfers())
    print("-- 自动分类 --")
    print(classifier.run())


def cmd_report():
    conn = get_conn()

    def q(sql, *args):
        return conn.execute(sql, args).fetchall()

    print("=== 账户 ===")
    for r in q("SELECT a.id, a.name, a.type, COUNT(t.id) AS n FROM accounts a "
               "LEFT JOIN transactions t ON t.account_id=a.id GROUP BY a.id ORDER BY n DESC"):
        print(f"  #{r['id']} {r['name']} ({r['type']}) {r['n']}笔")

    print("\n=== 各源入库 ===")
    for r in q("SELECT source, COUNT(*) n, SUM(CASE WHEN direction='expense' THEN amount ELSE 0 END)/100.0 exp "
               "FROM transactions GROUP BY source"):
        print(f"  {r['source']}: {r['n']}笔 原始支出合计 {r['exp']:.2f}")

    print("\n=== 去重与转账 ===")
    for r in q("SELECT flow_type, dup_status, COUNT(*) n FROM transactions "
               "GROUP BY flow_type, dup_status ORDER BY n DESC"):
        print(f"  flow={r['flow_type']:<18} dup={r['dup_status']:<14} {r['n']}笔")

    print("\n=== 统计口径（计入统计）===")
    base = ("is_deleted=0 AND status_ok=1 AND flow_type='normal' "
            "AND dup_status IN ('none','not_dup')")
    for d, label in (("income", "收入"), ("expense", "支出")):
        r = q(f"SELECT COUNT(*) n, COALESCE(SUM(amount),0)/100.0 s FROM transactions "
              f"WHERE {base} AND direction=?", d)[0]
        print(f"  {label}: {r['n']}笔 {r['s']:.2f}")

    print("\n=== 未分类占比 ===")
    r = q("SELECT COUNT(*) n FROM transactions t JOIN categories c ON c.id=t.category_id "
          "WHERE c.name='未分类'")[0]
    total = q("SELECT COUNT(*) n FROM transactions")[0]["n"]
    print(f"  未分类 {r['n']}/{total} ({r['n']*100.0/max(total,1):.1f}%)")

    print("\n=== 支出分类 Top15（计入统计）===")
    for r in q(f"""SELECT COALESCE(p.name, c.name) top, COUNT(*) n, SUM(t.amount)/100.0 s
                  FROM transactions t JOIN categories c ON c.id=t.category_id
                  LEFT JOIN categories p ON p.id=c.parent_id
                  WHERE {base} AND t.direction='expense'
                  GROUP BY top ORDER BY s DESC LIMIT 15"""):
        print(f"  {r['top']:<10} {r['n']:>5}笔 {r['s']:>12.2f}")


def main():
    if len(sys.argv) < 2:
        print(__doc__)
        return
    cmd = sys.argv[1]
    if cmd == "reset":
        cmd_reset()
    elif cmd == "import-all":
        cmd_import_all(sys.argv[2] if len(sys.argv) > 2 else str(Path.home() / "账单"))
    elif cmd == "report":
        cmd_report()
    else:
        print(__doc__)


if __name__ == "__main__":
    main()
