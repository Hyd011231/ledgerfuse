"""SQLite 连接与 schema。

约定：
- 金额一律整数分（amount >= 0，方向看 direction；余额可为负）。
- 时间存 TEXT：'YYYY-MM-DD HH:MM:SS'。
- dedup_key 全局唯一，防同文件/重叠账期重复导入。
"""
import json
import sqlite3
from .config import DB_PATH, SEED_DIR

_conn: sqlite3.Connection | None = None

SCHEMA = """
CREATE TABLE IF NOT EXISTS settings (
  key TEXT PRIMARY KEY,
  value TEXT
);

CREATE TABLE IF NOT EXISTS accounts (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  name TEXT UNIQUE NOT NULL,
  type TEXT NOT NULL DEFAULT 'bank',      -- bank / wallet / credit / other
  card_tail TEXT,                          -- '3788' 等，钱包类为 NULL
  note TEXT,
  created_at TEXT DEFAULT (datetime('now','localtime'))
);

CREATE TABLE IF NOT EXISTS import_batches (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  filename TEXT NOT NULL,
  file_sha256 TEXT UNIQUE NOT NULL,
  source_type TEXT NOT NULL,               -- alipay_csv/wechat_pdf/nbcb_pdf/ccb_pdf/cmb_pdf
  account_id INTEGER REFERENCES accounts(id),
  period_start TEXT,
  period_end TEXT,
  row_count INTEGER DEFAULT 0,
  imported_count INTEGER DEFAULT 0,
  skipped_dup_count INTEGER DEFAULT 0,
  summary_json TEXT,                       -- 账单自带汇总 + 解析 warnings
  status TEXT DEFAULT 'previewed',         -- previewed / committed
  created_at TEXT DEFAULT (datetime('now','localtime'))
);

CREATE TABLE IF NOT EXISTS categories (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  name TEXT NOT NULL,
  parent_id INTEGER REFERENCES categories(id),
  sort INTEGER DEFAULT 0,
  is_system INTEGER DEFAULT 0,
  UNIQUE(name, parent_id)
);

CREATE TABLE IF NOT EXISTS transactions (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  batch_id INTEGER REFERENCES import_batches(id),
  source TEXT NOT NULL,                    -- alipay/wechat/nbcb/ccb/cmb/manual
  account_id INTEGER REFERENCES accounts(id),
  trans_time TEXT NOT NULL,
  time_precision TEXT DEFAULT 'second',    -- second / day
  amount INTEGER NOT NULL,                 -- 分，恒为正
  direction TEXT NOT NULL,                 -- income / expense / neutral
  counterparty TEXT DEFAULT '',
  counterparty_account TEXT DEFAULT '',
  description TEXT DEFAULT '',
  pay_method_raw TEXT DEFAULT '',
  trans_type_raw TEXT DEFAULT '',
  status_raw TEXT DEFAULT '',
  status_ok INTEGER DEFAULT 1,
  remark TEXT DEFAULT '',
  external_id TEXT DEFAULT '',
  external_id2 TEXT DEFAULT '',
  alipay_category TEXT DEFAULT '',
  balance_after INTEGER,                   -- 银行流水余额列（分）
  channel_hint TEXT DEFAULT '',            -- 银行侧：wechat/alipay/jd/douyin/meituan
  card_tail TEXT DEFAULT '',               -- 渠道侧=扣款卡尾号；银行侧=本卡尾号
  is_combo INTEGER DEFAULT 0,              -- 组合支付（&立减 等）
  is_refund INTEGER DEFAULT 0,
  dedup_key TEXT UNIQUE NOT NULL,
  flow_type TEXT DEFAULT 'normal',         -- normal / transfer / credit_card_spend
  dup_status TEXT DEFAULT 'none',          -- none / suspect / confirmed_dup / not_dup
  matched_txn_id INTEGER,
  category_id INTEGER REFERENCES categories(id),
  category_source TEXT DEFAULT '',         -- manual/user_rule/builtin/alipay_map/keyword/ai
  tags TEXT DEFAULT '[]',
  is_deleted INTEGER DEFAULT 0,
  raw_json TEXT DEFAULT '',
  created_at TEXT DEFAULT (datetime('now','localtime')),
  updated_at TEXT DEFAULT (datetime('now','localtime'))
);
CREATE INDEX IF NOT EXISTS idx_txn_time ON transactions(trans_time);
CREATE INDEX IF NOT EXISTS idx_txn_amount ON transactions(amount, direction);
CREATE INDEX IF NOT EXISTS idx_txn_dup ON transactions(dup_status);
CREATE INDEX IF NOT EXISTS idx_txn_cat ON transactions(category_id);
CREATE INDEX IF NOT EXISTS idx_txn_acct ON transactions(account_id, trans_time);

CREATE TABLE IF NOT EXISTS classify_rules (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  priority INTEGER DEFAULT 100,
  field TEXT DEFAULT 'any',                -- counterparty/description/trans_type/any
  match_type TEXT DEFAULT 'contains',      -- contains / regex
  direction TEXT DEFAULT '',               -- '' 不限 / income / expense
  pattern TEXT NOT NULL,
  category_id INTEGER NOT NULL REFERENCES categories(id),
  rule_source TEXT DEFAULT 'user',         -- builtin / user
  enabled INTEGER DEFAULT 1,
  hit_count INTEGER DEFAULT 0
);

CREATE TABLE IF NOT EXISTS alipay_category_map (
  alipay_category TEXT PRIMARY KEY,
  category_id INTEGER NOT NULL REFERENCES categories(id)
);

CREATE TABLE IF NOT EXISTS dup_matches (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  channel_txn_id INTEGER NOT NULL REFERENCES transactions(id),
  bank_txn_id INTEGER NOT NULL REFERENCES transactions(id),
  score REAL DEFAULT 0,
  date_diff_days INTEGER DEFAULT 0,
  match_reason TEXT DEFAULT '',
  status TEXT DEFAULT 'suspect',           -- auto_confirmed/suspect/confirmed/rejected
  decided_at TEXT,
  UNIQUE(bank_txn_id, channel_txn_id)
);

CREATE TABLE IF NOT EXISTS budgets (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  month TEXT NOT NULL,                     -- 'YYYY-MM' 或 '*'（每月默认）
  category_id INTEGER REFERENCES categories(id),   -- NULL = 总预算
  member_id INTEGER REFERENCES members(id),        -- NULL = 全家
  amount INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS balance_checks (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  account_id INTEGER NOT NULL REFERENCES accounts(id),
  check_date TEXT NOT NULL,
  computed_balance INTEGER,
  actual_balance INTEGER,
  diff INTEGER,
  note TEXT DEFAULT '',
  created_at TEXT DEFAULT (datetime('now','localtime'))
);

CREATE TABLE IF NOT EXISTS ai_reports (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  scope TEXT NOT NULL,                     -- 'month:2026-07' / 'import:12' / 'year:2026' / 'overall'
  model TEXT DEFAULT '',
  digest_json TEXT DEFAULT '',             -- 喂给模型的数据摘要
  report_md TEXT DEFAULT '',
  status TEXT DEFAULT 'pending',           -- pending / done / error
  error TEXT DEFAULT '',
  input_tokens INTEGER DEFAULT 0,
  output_tokens INTEGER DEFAULT 0,
  created_at TEXT DEFAULT (datetime('now','localtime'))
);

CREATE TABLE IF NOT EXISTS members (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  name TEXT UNIQUE NOT NULL,
  is_self INTEGER DEFAULT 0,
  color TEXT DEFAULT '#2f6f4f',
  created_at TEXT DEFAULT (datetime('now','localtime'))
);

CREATE TABLE IF NOT EXISTS activities (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  name TEXT NOT NULL,
  date_from TEXT,
  date_to TEXT,
  budget INTEGER,                          -- 分，可空
  note TEXT DEFAULT '',
  status TEXT DEFAULT 'active',            -- active / archived
  created_at TEXT DEFAULT (datetime('now','localtime'))
);

CREATE TABLE IF NOT EXISTS subscriptions (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  merchant TEXT NOT NULL,
  label TEXT DEFAULT '',
  period_days INTEGER DEFAULT 30,          -- 大致周期
  avg_amount INTEGER DEFAULT 0,            -- 分
  last_time TEXT DEFAULT '',
  active INTEGER DEFAULT 1,
  note TEXT DEFAULT '',
  created_at TEXT DEFAULT (datetime('now','localtime'))
);
"""

# 增量迁移：旧库补新列（列名 -> ALTER 语句），新库由 SCHEMA 直接建好
MIGRATIONS: dict[str, list[tuple[str, str]]] = {
    "transactions": [
        ("activity_id", "ALTER TABLE transactions ADD COLUMN activity_id INTEGER"),
        ("member_id", "ALTER TABLE transactions ADD COLUMN member_id INTEGER"),
        ("is_shared", "ALTER TABLE transactions ADD COLUMN is_shared INTEGER DEFAULT 0"),
        ("reimburse_status", "ALTER TABLE transactions ADD COLUMN reimburse_status TEXT DEFAULT ''"),
        ("fx_currency", "ALTER TABLE transactions ADD COLUMN fx_currency TEXT DEFAULT ''"),
        ("fx_amount", "ALTER TABLE transactions ADD COLUMN fx_amount INTEGER"),
    ],
    "accounts": [
        ("member_id", "ALTER TABLE accounts ADD COLUMN member_id INTEGER"),
    ],
    "budgets": [
        ("member_id", "ALTER TABLE budgets ADD COLUMN member_id INTEGER"),
    ],
}


def _migrate(conn: sqlite3.Connection):
    for table, cols in MIGRATIONS.items():
        existing = {r["name"] for r in conn.execute(f"PRAGMA table_info({table})")}
        for col, ddl in cols:
            if col not in existing:
                conn.execute(ddl)
    # budgets 的 UNIQUE(month, category_id) 需要扩成含 member_id —— 用唯一索引替代旧约束
    # （旧表约束无法删除，重建一次）
    sql = conn.execute("SELECT sql FROM sqlite_master WHERE type='table' AND name='budgets'").fetchone()
    if sql and "UNIQUE(month, category_id)" in (sql["sql"] or ""):
        conn.executescript("""
            CREATE TABLE budgets_new (
              id INTEGER PRIMARY KEY AUTOINCREMENT,
              month TEXT NOT NULL,
              category_id INTEGER REFERENCES categories(id),
              member_id INTEGER REFERENCES members(id),
              amount INTEGER NOT NULL
            );
            INSERT INTO budgets_new(id, month, category_id, member_id, amount)
              SELECT id, month, category_id, member_id, amount FROM budgets;
            DROP TABLE budgets;
            ALTER TABLE budgets_new RENAME TO budgets;
        """)
    conn.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_budget_uniq ON budgets("
                 "month, COALESCE(category_id,0), COALESCE(member_id,0))")
    conn.commit()


def get_conn() -> sqlite3.Connection:
    global _conn
    if _conn is None:
        _conn = sqlite3.connect(DB_PATH, check_same_thread=False)
        _conn.row_factory = sqlite3.Row
        _conn.execute("PRAGMA journal_mode=WAL")
        _conn.execute("PRAGMA foreign_keys=ON")
    return _conn


def init_db():
    conn = get_conn()
    conn.executescript(SCHEMA)
    _migrate(conn)
    _seed(conn)
    # 默认成员：本人（户名来自账单解析）
    if conn.execute("SELECT COUNT(*) FROM members").fetchone()[0] == 0:
        owner = get_setting("owner_name") or "我"
        conn.execute("INSERT INTO members(name, is_self) VALUES(?,1)", (owner,))
    # 未归属的账户默认归本人（可在设置里改，如亲情卡归 TA）
    self_row = conn.execute("SELECT id FROM members WHERE is_self=1").fetchone()
    if self_row:
        conn.execute("UPDATE accounts SET member_id=? WHERE member_id IS NULL", (self_row["id"],))
    conn.commit()
    return conn


def _seed(conn: sqlite3.Connection):
    if conn.execute("SELECT COUNT(*) FROM categories").fetchone()[0] > 0:
        return
    data = json.loads((SEED_DIR / "categories.json").read_text(encoding="utf-8"))
    name_to_id: dict[str, int] = {}
    for i, top in enumerate(data["categories"]):
        cur = conn.execute(
            "INSERT INTO categories(name, parent_id, sort, is_system) VALUES(?,NULL,?,1)",
            (top["name"], i),
        )
        pid = cur.lastrowid
        name_to_id[top["name"]] = pid
        for j, sub in enumerate(top.get("children", [])):
            cur2 = conn.execute(
                "INSERT INTO categories(name, parent_id, sort, is_system) VALUES(?,?,?,1)",
                (sub, pid, j),
            )
            name_to_id[f"{top['name']}/{sub}"] = cur2.lastrowid

    def cat_id(path: str) -> int:
        if path not in name_to_id:
            raise KeyError(f"seed 引用了不存在的分类: {path}")
        return name_to_id[path]

    for ali, path in data["alipay_map"].items():
        conn.execute(
            "INSERT OR IGNORE INTO alipay_category_map(alipay_category, category_id) VALUES(?,?)",
            (ali, cat_id(path)),
        )

    rules = json.loads((SEED_DIR / "builtin_rules.json").read_text(encoding="utf-8"))
    for r in rules["rules"]:
        conn.execute(
            "INSERT INTO classify_rules(priority, field, match_type, direction, pattern, category_id, rule_source) "
            "VALUES(?,?,?,?,?,?,'builtin')",
            (r.get("priority", 100), r.get("field", "any"), r.get("match_type", "contains"),
             r.get("direction", ""), r["pattern"], cat_id(r["category"])),
        )
    conn.commit()


def get_setting(key: str, default: str = "") -> str:
    row = get_conn().execute("SELECT value FROM settings WHERE key=?", (key,)).fetchone()
    return row["value"] if row else default


def set_setting(key: str, value: str):
    conn = get_conn()
    conn.execute(
        "INSERT INTO settings(key,value) VALUES(?,?) "
        "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
        (key, value),
    )
    conn.commit()
