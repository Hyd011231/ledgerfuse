# 参与贡献

感谢你愿意让合账支持更多人的账单。

## 开发环境

Python 3.12 + Node 18+：

```bash
git clone https://github.com/Hyd011231/ledgerfuse.git && cd ledgerfuse
cd backend && python3.12 -m venv .venv && .venv/bin/pip install -r requirements.txt && cd ..
cd frontend && npm install && cd ..

# 开发模式（前后端热更新）
cd backend && .venv/bin/python -m uvicorn app.main:app --reload --port 8000   # 终端 1
cd frontend && npm run dev                                                    # 终端 2，http://localhost:5173
```

API 文档在运行后的 `/docs`（Swagger）。

## 最受欢迎的贡献：新的银行解析器

每个账单格式对应 `backend/app/parsers/` 下的一个文件（约 110 行）。步骤：

1. **拿到样本**：用你自己的账单开发。**永远不要把真实账单提交进仓库**——`.gitignore` 已经挡了 `*.pdf` / `*.csv`，测试数据请脱敏后自建。
2. **写解析器** `parsers/yourbank_pdf.py`，实现 `parse(path: Path) -> ParseResult`：
   - 逐笔产出 `ParsedTxn`（字段见 `parsers/base.py`，金额一律**整数分**，方向 income/expense/neutral）；
   - 银行流水务必填 `balance_after`（余额链校验靠它）、`channel_hint`（对手是财付通/支付宝时标记，去重靠它）、卡尾号；
   - `meta` 里放账单自带的汇总（笔数/合计），解析结果和它对不上时往 `warnings` 里塞警告——宁可报警不可静默错账。
   - PDF 建议用 PyMuPDF 的坐标法（参考 `cmb_pdf.py`）或表格法（参考 `ccb_pdf.py`）。
3. **注册**三处：`parsers/base.py` 的 `detect_file_type()`（用账单首页的特征文字识别）和 `parse_file()`，`services/importer.py` 的 `SOURCE_OF`。
4. **验证**：`cd backend && .venv/bin/python cli.py import-all <你的账单目录>`，看导入笔数、warnings、`report` 的口径对账是否正确。
5. 如果该银行的流水会出现在微信/支付宝的扣款里，跑一次去重看匹配率（`cli.py report` 的「去重与转账」段）。

## 提交规范

- 提交信息用英文祈使句（"Add CMB credit card parser"），一笔提交做一件事。
- 不引入对外部服务的依赖：本项目的底线是**除可选的 AI 分析外，不发起任何网络请求**。
- PR 描述里写清楚：支持什么格式、用什么方式验证过、账单样式有没有多个版本。

## 报告问题

- Bug：用 issue 模板，附复现步骤和报错。**贴日志/截图前先脱敏**（金额、姓名、卡号、商户）。
- 新银行支持请求：说明银行、导出入口、格式（PDF/CSV/Excel），可以贴**打码后的**表头结构。

## 行为准则

友善、就事论事。财务数据是最敏感的个人数据，任何降低隐私保护的改动都会被谨慎对待。
