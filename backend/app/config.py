"""全局常量与路径配置。

个人身份信息（户名、卡号）不写死在代码里：
- 户名从银行/微信账单解析时自动提取，存 settings 表；
- 账户（卡尾号/钱包）在导入时自动建档，存 accounts 表。

数据目录：开发模式放 backend/data；打包成可执行文件后放各系统的用户数据目录，
可用环境变量 LEDGERFUSE_DATA_DIR 覆盖。
"""
import os
import sys
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent      # backend/
SEED_DIR = Path(__file__).resolve().parent / "seed"


def _data_dir() -> Path:
    env = os.environ.get("LEDGERFUSE_DATA_DIR")
    if env:
        return Path(env).expanduser()
    if getattr(sys, "frozen", False):      # PyInstaller 打包运行
        if sys.platform == "darwin":
            return Path.home() / "Library" / "Application Support" / "LedgerFuse"
        if sys.platform == "win32":
            return Path(os.environ.get("APPDATA", str(Path.home()))) / "LedgerFuse"
        xdg = os.environ.get("XDG_DATA_HOME", str(Path.home() / ".local" / "share"))
        return Path(xdg) / "ledgerfuse"
    return BASE_DIR / "data"


DATA_DIR = _data_dir()
DB_PATH = DATA_DIR / "bills.db"
UPLOAD_DIR = DATA_DIR / "uploads"
BACKUP_DIR = DATA_DIR / "backups"

# 去重匹配的日期窗口（银行记账相对渠道账单的滞后/提前容忍）
DEDUP_LAG_BEFORE_DAYS = 1   # 银行偶尔早于渠道记账
DEDUP_LAG_AFTER_DAYS = 3    # 清算滞后 + 周末

# 组合支付（如 "储蓄卡&碰一下立减"）宽松匹配：银行实扣 < 账单金额
COMBO_MAX_DISCOUNT_CENTS = 5000     # 立减最多 50 元
COMBO_MAX_DISCOUNT_RATIO = 0.5      # 立减不超过账单金额一半

# 大额交易阈值（分析页默认值，前端可调）
LARGE_TXN_DEFAULT_CENTS = 50000     # 500 元

# 银行流水里渠道方的识别关键词 -> 渠道标识
BANK_CHANNEL_KEYWORDS = {
    "财付通": "wechat",
    "微信支付": "wechat",
    "支付宝": "alipay",
    "网银在线": "jd",
    "京东支付": "jd",
    "抖音支付": "douyin",
    "美团支付": "meituan",
}

for _d in (DATA_DIR, UPLOAD_DIR, BACKUP_DIR):
    _d.mkdir(parents=True, exist_ok=True)
