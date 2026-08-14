# 合账 LedgerFuse

**把银行卡流水、支付宝、微信账单合成一本账。** 纯本地个人记账：自动跨账单去重、自动分类、多维度收支统计，可选接入 Claude 做 AI 财务分析。所有数据只存在你自己电脑的 SQLite 里，不上传任何服务器。

> Fuse your bank statements, Alipay and WeChat Pay bills into one local ledger — automatic cross-source deduplication, auto-categorization, rich statistics, and optional AI reports. All data stays on your machine.

## 下载安装

去 [Releases](../../releases) 下载对应平台的包，解压即用：

| 平台 | 包 | 说明 |
|---|---|---|
| macOS (Apple Silicon) | `LedgerFuse-macos-arm64.zip` | 解压后把 App 拖进「应用程序」；首次打开若被拦截，右键 → 打开 |
| macOS (Intel) | `LedgerFuse-macos-x64.zip` | 同上 |
| Windows | `LedgerFuse-windows-x64.zip` | 解压后运行 `LedgerFuse.exe` |
| Linux | `LedgerFuse-linux-x64.tar.gz` | 需要 WebKitGTK：`sudo apt install gir1.2-webkit2-4.1`；没有桌面环境时 `./LedgerFuse --server` 用浏览器打开 |

数据存放位置：macOS `~/Library/Application Support/LedgerFuse`；Windows `%APPDATA%\LedgerFuse`；Linux `~/.local/share/ledgerfuse`。可用环境变量 `LEDGERFUSE_DATA_DIR` 改。

## 支持的账单格式

| 来源 | 获取方式 | 格式 |
|---|---|---|
| 支付宝 | APP：我的-账单-右上角…-开具交易流水证明 | CSV (GB18030) |
| 微信支付 | APP：我-服务-钱包-账单-常见问题-下载账单-用于个人对账 | 交易明细证明 PDF |
| 宁波银行 | 手机银行导出交易流水 | PDF |
| 建设银行 | 手机银行导出活期明细 | PDF |
| 招商银行 | 手机银行导出交易流水 | PDF |

导入时自动识别格式；解析结果与账单自带汇总核对（笔数/收支合计/余额链），预览确认后入库。**欢迎 PR 增加更多银行的解析器**（见 `backend/app/parsers/`，每个解析器 ~110 行，有统一的数据模型和校验框架）。

## 跨账单去重（核心）

同一笔消费会同时出现在渠道账单（微信/支付宝）和扣款银行卡流水里。系统：

1. **渠道账单为主记录**（有商户/商品信息，用于分类统计）；银行流水中对应扣款标记为重复，不计统计但可查。
2. 匹配依据：渠道标识（财付通=微信、支付宝）+ 卡尾号 + 金额 + 日期窗口（银行记账可滞后 1-3 天）。
3. 特殊场景：组合支付立减（银行实扣<账单额）、外卖合单（渠道 2-3 笔=银行 1 笔）、转账后被退回（自动对冲）、微信零钱充值/提现、卡对卡互转 —— 均自动识别。
4. 无法确定的进「去重复核」页人工确认；人工裁决永不被重跑覆盖。
5. 信用卡口径：还款记支出；渠道账单里的信用卡消费明细不计（防双计）。

## 隐私

- 账单数据、数据库、上传文件全部只存本地，`.gitignore` 从源头挡住 `*.pdf` / `*.csv` / `*.db` 进仓库。
- AI 分析是**可选**功能：只在你主动点击时才调用 Claude API，且只上传聚合摘要（分类合计、月度趋势等），不上传任何一笔原始明细。API Key 存本地数据库，不进代码不进配置文件。
- 界面自带「演示模式」，一键隐藏金额和交易对象，方便截图分享。

## 从源码运行 / 开发

依赖：Python 3.12、Node 18+。

```bash
# 后端
cd backend
python3.12 -m venv .venv && .venv/bin/pip install -r requirements.txt
# 前端
cd ../frontend && npm install && npm run build && cd ..
# 桌面模式（原生窗口）
cd backend && .venv/bin/python desktop.py
# 或纯服务器模式（浏览器访问 http://127.0.0.1:8642）
cd backend && .venv/bin/python desktop.py --server
```

开发热更新：终端 1 `cd backend && .venv/bin/python -m uvicorn app.main:app --reload --port 8000`，终端 2 `cd frontend && npm run dev`。

macOS 想要「双击图标」的本地开发版：`mac/make_app.sh` 会在 ~/Applications 生成 App。

命令行批量导入：`cd backend && .venv/bin/python cli.py import-all <账单目录>`。

## 目录结构

```
backend/
  app/parsers/     账单解析器（PDF 用 PyMuPDF 坐标法/表格法），每种格式一个文件
  app/services/    importer 导入 / transfer 转账识别 / dedup 去重 / classifier 分类
                   stats 统计 / ai Claude 集成 / export 导出
  app/routes.py    全部 API（运行后 /docs 可看）
  desktop.py       桌面/服务器双模式入口
  cli.py           命令行工具：reset / import-all / report
frontend/          React + AntD + ECharts
mac/               macOS 本地打包脚本与图标
.github/workflows/ 多平台可执行文件自动构建
```

## License

[MIT](LICENSE)
