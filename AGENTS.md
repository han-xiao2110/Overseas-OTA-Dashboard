# AGENTS.md — BKNG/EXPE/ABNB OTA 业绩看板

> **最后更新**: 2026-08-28（Codex 交接版）
> **部署状态**: ✅ 已部署（自动）—— https://bkng-expe-abnb-1q26.surge.sh/
> **GitHub**: https://github.com/han-xiao2110/Overseas-OTA-Dashboard（Private）

---

## 项目定位

中金互联网组 OTA（BKNG/EXPE/ABNB）财务业绩交互式看板。纯前端 ECharts 单页应用，展示五大维度：
1. **季度财务数据**（营收/利润/增速/分部）
2. **市场行情**（股价/指数/汇率）
3. **股东回报**（回购/分红/持股）
4. **用户数据（ST）**（MAU/DAU/下载量，全球+6大洲+9国家+10 App）
5. **最新信息**（SEC文件/行业新闻/公司新闻/监管/东航）

---

## 技术栈

- **前端**: 原生 HTML/JS + ECharts 5.4.3（同源独立文件 `echarts.min.js`）
- **后端**: Python 3.12（数据提取与构建脚本）
- **数据源**: Excel（.xlsx）+ JSON 缓存
- **部署**: Surge.sh（静态托管，自动 gzip）
- **自动化**: GitHub Actions（每日定时抓取+生成+部署）
- **翻译**: MyMemory → Google公开端点 → deep-translator 三路回退（均无 API key）+ 持久译文缓存
- **新闻处理**: 纯程序化（无 AI 调用）——关键词过滤+规则分类+URL哈希/标题相似度去重+SEC官方文件结构化摘要

---

## 自动化流程

### GitHub Actions 每日自动更新

- **股价触发**: 北京时间 06:00，周二至周六（UTC 周一至周五 22:00；周六补抓周五数据）
- **新闻触发**: 北京时间每天 08:00（UTC 00:00；周日、周一也更新）
- **工作流**: `.github/workflows/daily-update.yml`
- **步骤**:
  1. Checkout 代码（含 Excel 财务数据）
  2. Setup Python 3.12 + Node 20
  3. `pip install -r requirements.txt`
  4. `npm install -g surge`
  5. **按触发时段执行**：06:00 仅 Fetch stock prices；08:00 仅 Fetch news；手动触发两者都执行
  7. **Generate dashboard**（读 Excel→注入模板→生成 `deploy/`）
  8. **Deploy to Surge**（环境变量传 SURGE_TOKEN）
  9. **Commit & push**（股价+新闻数据回仓库）
- **失败告警**: 自动邮件到 GitHub 邮箱

### 手动触发

1. 打开 https://github.com/han-xiao2110/Overseas-OTA-Dashboard/actions
2. 点 **Daily Auto-Update & Deploy** → **Run workflow**

### 本地手动部署

```bash
cd "/Users/feifei/Documents/BKNG-EXPE-ABNB业绩"
bash deploy_local.sh
```

流程：git pull → generate → surge deploy。用于紧急手动上线。

---

## 新闻处理规则（当前生效）

### 排序
- **纯按日期降序**（最新在上，越往下越旧）
- 不再按 selection_score 优先排序

### 保留期
- **统一 14 天**（用户要求只保留最近 2 周新闻）
- SEC、官方 IR 及国内披露模块也统一保留 14 天，不再对长报告做 28 天例外

### 处理管线（`fetch_news_副本.py`）
```
RSS/官网抓取(safe_request, TLS 只验证)
→ 相关性过滤（三层：白名单→强排除→关键词）
→ 实体识别（BKNG/EXPE/ABNB/CEAIR）
→ 确定性筛选管道（五维评分≥60 保留）
→ 最终保留新闻翻译（三路回退+持久缓存；标题未译不展示，摘要未译留空待重试）
→ 合并缓存
→ 保留期修剪（14 天）
→ 三级去重（URL→同文→同事件折叠）
→ 按日期降序排序
→ 路由到 modules（intl_core_company / intl_industry / intl_disclosures / dom_industry / dom_disclosures）
→ 模块内再次按日期降序排序
→ 保存缓存
```

### 数据源（纯程序化，无 AI）
- RSS 源: Skift, PhocusWire, Travel Weekly, 环球旅讯, 36氪, Google News
- 官网: SEC EDGAR, 披露易(港交所), 民航网, 交通运输部, 文旅部
- 公司 IR: Booking Holdings IR, Expedia Group IR, Airbnb IR（直读三家官网 Q4 PressRelease feed，不经 Google News）
- IR 路由: 业绩/财报/股东信/业绩材料进“披露与文件”；投资者大会、路演、产品、并购、合作、战略和管理层动作进“核心公司动态”
- 同事件主来源优先级: 一手监管/公司官方源 > 通讯社/主流财经媒体 > 国际垂直行业媒体 > 国内转载/聚合源；具体评分见 `SOURCE_RANK_MAP`

---

## 关键文件

| 文件 | 角色 | 备注 |
|------|------|------|
| `fetch_news_副本.py` | 新闻抓取+筛选+翻译+排序+去重 | 核心脚本 |
| `fetch_stock_prices_副本.py` | 股价抓取（yfinance） | 含代理自动检测 |
| `generate_副本.py` | 读 Excel+JSON→注入模板→生成 `deploy/` | 自动查找目录下的 Excel |
| `template_副本.html` | 前端模板（所有 JS 逻辑） | 数据注入点: `/*__DATA_PLACEHOLDER__*/{}` 等 |
| `extract_st_data_副本.py` | 从 Excel 提取 ST 用户数据 | |
| `daily_update_副本.sh` | 旧本地日更脚本 | ⚠️ 已被 GitHub Actions 替代，仅作参考 |
| `deploy_local.sh` | 本地一键部署 | 紧急手动上线用 |
| `news_ai_helpers_副本.py` | AI 辅助模块 | ⚠️ 已禁用（AI_MODULE_AVAILABLE=False） |
| `agent_translate_副本.py` | AI 翻译桥接 | ⚠️ 已禁用（改用 deep-translator） |
| `news_quality_tests_副本.py` | 离线质量测试（138 项） | 不含 AI 依赖 |
| `news_smoke_副本.js` | 前端烟雾测试（42 项） | |
| `market_smoke_副本.js` | 市场行情测试（32 项） | |
| `translation_cache_副本.json` | 成功译文持久缓存 | GitHub Actions 每次更新后回仓库 |
| `requirements.txt` | Python 依赖 | yfinance, feedparser, deep-translator, openpyxl, requests, beautifulsoup4, certifi |
| `.github/workflows/daily-update.yml` | GitHub Actions 工作流 | |

### 数据文件（纳入版本控制）

| 文件 | 角色 |
|------|------|
| `news_data_副本.json` | 新闻缓存（国际+国内+modules） |
| `stock_prices_副本.json` | 股价缓存 |
| `dashboard_data_副本.json` | 财务数据缓存（从 Excel 生成） |
| `news_rejected_副本.json` | 筛选被拒条目诊断 |
| `st_data_副本.json` | ST 用户数据缓存 |
| `pg_data_副本.json` | 价格/图表数据缓存 |
| `BKNG-EXPE-ABNB业绩20260811.xlsx` | 财务季度数据 |

### Excel 数据源
- `BKNG-EXPE-ABNB业绩20260811.xlsx` — 财务季度数据（generate_副本.py 自动查找目录下 `BKNG-EXPE-ABNB业绩*.xlsx`）
- `【中金互联网】海外OTA用户数据2607_副本.xlsx` — ST 用户数据

---

## 目录约定

- 所有工作文件使用 `_副本` 后缀
- `deploy/` 是 Surge 部署源（含 CNAME + index.html + dashboard.html + echarts.min.js + st_data.js）
- `.gitignore` 排除: `__pycache__/`, `*.pyc`, `.trae/`, `deploy/`, `*.log`, `.DS_Store`, `news_cache_backups/`, `*.json.bak`

---

## GitHub Secrets

仓库 Settings → Secrets and variables → Actions 中配置:
- `SURGE_TOKEN`: Surge.sh API token（当前值: `50cdbd8c01842d4ff413345fa4bfcbb6`）

---

## 踩坑速查

1. **macOS 代理**: 本机 Clash 代理 `127.0.0.1:7892`，shell 脚本需 `export http_proxy=https://127.0.0.1:7892 https_proxy=https://127.0.0.1:7892` 才能访问 Google 系服务（翻译/Google News RSS）
2. **Python global 声明**: `fetch_stock_prices_副本.py` 的 `global _PROXY` 必须在函数开头声明，不能在 `if` 块内（Python 3.12 严格模式）
3. **公共翻译端点限流**: 三路端点均可能临时失败；成功译文写入持久缓存。标题未译不进入展示模块，摘要未译则留空并保留 `summary_original` 供后续重试，禁止生成标题占位摘要
4. **Excel 路径**: `generate_副本.py` 已改为自动查找，兼容本地 macOS 和 GitHub Actions Ubuntu
5. **Surge 部署**: 用环境变量 `SURGE_TOKEN` 传 token，不用 `--token` 命令行参数
6. **排序**: 必须在去重/折叠之后排序，否则去重操作会打乱日期顺序
7. **缓存备份**: `news_cache_backups/` 保留最近 3 个版本，自动轮转
8. **SEC/IR 保留期**: 全部披露与新闻统一 14 天；SEC 同一 accession 的目录链接与正文链接只保留证据更完整的一条
9. **IR 跨公司去重**: 不同公司参加同一投资者大会时必须分别展示，不得因标题相似折叠

---

## 测试命令

```bash
# 语法检查
python3 -c "import ast; [ast.parse(open(f).read()) for f in ['fetch_news_副本.py','fetch_stock_prices_副本.py','generate_副本.py']]; print('AST OK')"

# 离线质量测试（149 项）
python3 news_quality_tests_副本.py

# 前端烟雾测试（44 项）
node news_smoke_副本.js dashboard.html

# 市场行情测试（32 项）
node market_smoke_副本.js dashboard.html

# 查看新闻数据统计
python3 -c "import json;d=json.load(open('news_data_副本.json'));print({k:{c:len(v) for c,v in d[s].items()} for s,k in [('international','国际'),('domestic','国内')]})"
```
