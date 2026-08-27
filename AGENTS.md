# AGENTS.md — CICC OTA 业绩看板交接

> **最后更新**: 2026-08-18 晚间 UTC+8
> **部署状态**: ✅ 已部署（2026-08-18 晚间手动 surge）——确定性新闻筛选管道上线；线上 content-length 389,212、surge-stamp 哈希 4a926722…==本地 md5，字节级一致
> **筛选管道改造**: 2026-08-18 晚间实施 16 节新闻筛选规格——实体表+硬排除+重点公司判定+OTA 基本面五维评分（纯确定性正则，AI 不可用照常执行）；集成进 daily_update 管道每日对"新抓+保留期旧缓存"全量重筛（被拒旧缓存不得次日回流），拒绝诊断落盘 news_rejected_副本.json，摘要覆盖 49/49=100%（见变更记录与踩坑 23/24）
> **ST按App重构**: 2026-08-18 午后 App 选择改横排 chips + 默认选中 Trip.com 进入即出图（无空态），指标/模式分段控件并入标题行，移动端 chips 横滚+图表高度响应（见变更记录）
> **市场悬浮改造**: 2026-08-18 午后 财报旗标/三角图钉悬浮出**相同**财报卡片（共享 studMeta 解析），悬浮期间三图联动临时断开（未注册 solo_* 组名）+ v2 轴广播接收方不出卡（stockHoverKey 第二道闸，修复旗标周围双卡）、globalout 恢复；`market_smoke_副本.js` 27 项测试（见变更记录与踩坑 22）
> **十项改造**: 2026-08-18 午后实施《OTA 新闻模块逐项修改建议》全部 10 项——前端转义与URL安全、TLS 只验证、Bloomberg Playwright 停用、来源状态+退出码、日期修复、国内分源过滤、三级去重、摘要证据字段、测试扩充、本文档去过时化（见变更记录与踩坑 21）
> **数据快照**: 以 `python3 -c "import json;d=json.load(open('news_data_副本.json'));print({k:{c:len(v) for c,v in d[s].items()} for s,k in [('international','国际'),('domestic','国内')]})"` 实时查看（不在此写死条数）
> **交叉验证**: 2026-08-17 ~14:10 第二 agent 核对：备份系统/翻译白名单移除均与代码一致；2026-08-18 晚间 离线质量测试 70/70（含 G 筛选验收 23 案例）、news_smoke 43/43（17 原有+24 安全段+2 筛选段）、market_smoke 27/27
> **噪音修复**: 2026-08-17 15:00 清理 2 条过滤前遗留噪音（Sembcorp IPO / Stripe 收购案，均 Bloomberg 综合源），并修复合并回流漏洞（见踩坑记录 13）
> **环球旅讯重写**: 2026-08-17 18:15 快讯页+首页双入口专用解析器+质量筛选，国内行业新闻 7→24 条（见踩坑记录 16）
> **移动端修复 v2**: 2026-08-17 18:00 载荷重构——ECharts 改同源独立文件（可缓存）+ ST 数据懒加载（st_data.js 按需加载）+ JSON 紧凑化，首屏 HTML 2.09MB→365KB；同时修复懒加载提示销毁面板结构导致 ST 图表不渲染的 bug（见踩坑记录 14/15）
> **过滤器词边界修复**: 2026-08-18 09:35 'expe' 子串误命中 "Expectations" 放行黄金行情新闻 → 关键词/强排除全部改词边界正则（见踩坑记录 17）；同日修复 Google 系抓取/翻译需走本地代理问题（见踩坑记录 18）
> **翻译 agent 化**: 2026-08-18 上午 cron 指令加代理自动检测（scutil --proxy）+ agent 翻译兜底（agent_translate_副本.py --export/--apply），翻译环节彻底不依赖 Google/代理/API key
> **Skift 补抓+环球旅讯分流**: 2026-08-18 10:20 Skift 加 /news/+page/2 列表页补抓（RSS 只有10条）；白名单源豁免强排除（'war' 曾误杀 2 条沙特行业新闻）；环球旅讯按国内外关键词分流，国际条目并入国际行业新闻（见踩坑记录 19）
> **环球旅讯分流修复 v2**: 2026-08-18 10:50 用户反馈分流未见效——国际标记表漏拉丁公司名（Faye/BCD/BizAway等）→ 补表+环球旅讯国际条目 28 天保留豁免（原 7 天即剪光）+ `--td-only` 防误清空双保险（国内子集也须≥5，曾致 china_industry 被清 0 靠备份恢复）（见踩坑记录 20）


---

## 项目定位

中金互联网组 OTA（BKNG/EXPE/ABNB）财务业绩交互式看板。纯前端 ECharts 单页应用，展示五大维度：
1. **季度财务数据**（营收/利润/增速/分部）
2. **市场行情**（股价/指数/汇率）
3. **股东回报**（回购/分红/持股）
4. **用户数据（ST）**（MAU/DAU/下载量，全球+6大洲+9国家+10 App）
5. **最新信息**（SEC文件/行业新闻/公司新闻/监管/东航）

## 技术栈

- **前端**: 原生 HTML/JS + ECharts 5.4.3（**同源独立文件** `echarts.min.js`，浏览器可缓存，非 CDN）
- **后端**: Python 3（数据提取与构建脚本）
- **数据源**: Excel（.xlsx）+ JSON 缓存
- **部署**: Surge.sh（开启 gzip）

### 载荷结构（移动端性能关键，勿改回内联/CDN）

| 文件 | 角色 | 原始 / gzip | 加载时机 |
|------|------|-------------|----------|
| `index.html`（=dashboard.html） | 首屏 + RAW/ANN/MKT 内联 JSON | ~365KB / ~107KB | 首请求 |
| `echarts.min.js` | ECharts 5.4.3 库 | ~1.02MB / ~325KB | `<head>` preload + 应用脚本前 `<script src>`，跨每日更新可缓存 |
| `st_data.js` | ST 用户数据（`window.ST_DATA=…`） | ~566KB / ~166KB | **懒加载**：仅打开「用户数据(ST)」tab 时注入 |

## 运行方式

### 全量重建与部署
```bash
cd /Users/feifei/Documents/BKNG-EXPE-ABNB业绩

# 1. 提取ST用户数据（如Excel有更新）
python3 extract_st_data_副本.py

# 2. 抓取新闻（强制全量刷新）
python3 fetch_news_副本.py --force

# 3. 生成dashboard（自动复制到deploy/）
python3 generate_副本.py

# 4. 部署
cd deploy && npx --yes surge . bkng-expe-abnb-1q26.surge.sh
```

### 日常更新
```bash
./daily_update_副本.sh           # FULL模式: 股价→新闻(AI全流程)→重建→部署（退出码感知：新闻致命失败=中止不部署，surge失败=报错退出）
./daily_update_副本.sh --fast    # FAST模式: 新闻缓存2h+轻量处理
python3 fetch_news_副本.py --force  # 手动强制刷新新闻（退出码 0=全部成功 / 2=部分失败可部署需披露 / 1=彻底失败且未写缓存）
python3 fetch_news_副本.py --td-only  # 只重抓环球旅讯并整源替换china_industry（解析器调优后用）
python3 agent_translate_副本.py --export  # 提取未翻译英文条目（agent 填 title_zh/summary_zh 后 --apply 写回，再重建部署）
```

### 测试与验收命令（不访问网络）
```bash
python3 -c "import ast; [ast.parse(open(f,encoding='utf-8').read()) for f in ['fetch_news_副本.py','news_ai_helpers_副本.py','news_quality_tests_副本.py','generate_副本.py']]; print('AST OK')"
node --check news_smoke_副本.js && bash -n daily_update_副本.sh
python3 news_quality_tests_副本.py        # 离线质量测试 70 项（A日期/B去重/C来源状态/D TLS/E摘要证据/F国内过滤/G筛选验收23案例），本地 fixture 零联网
node news_smoke_副本.js dashboard.html    # 烟雾测试 43 项（17 原有 + 24 安全段 + 2 筛选管道段：占位符清零/无 rejected 残留）
node market_smoke_副本.js dashboard.html  # 市场行情烟雾测试 27 项（旗标/图钉悬浮卡片一致性、悬浮断开三图联动、旗标周围轴广播接收方不出卡、hideTip/恢复联动）
```

## 关键文件

| 文件 | 角色 | 状态 |
|------|------|------|
| `template_副本.html` | 前端模板（所有JS逻辑+数据注入点） | ✅ 活跃 |
| `echarts.min.js` | ECharts 5.4.3 本地库（**独立文件**，generate 时以 `<script src>` 同源引用并复制到 deploy/，勿删勿内联） | ✅ 活跃 |
| `generate_副本.py` | 读取JSON→注入模板→生成`dashboard.html`→输出`st_data.js`→复制到`deploy/` | ✅ 活跃 |
| `extract_st_data_副本.py` | 从Excel提取ST用户数据→`st_data_副本.json` | ✅ 活跃 |
| `fetch_news_副本.py` | 新闻/SEC/披露易抓取主脚本（过滤/**确定性筛选管道**/翻译/缓存/AI管道/来源状态/日期字段/三级去重/摘要证据/selection_report） | ✅ 活跃 |
| `agent_translate_副本.py` | agent 翻译兜底桥接：`--export` 提取未翻译条目→pending_translations.json，agent 填 `title_zh`/`summary_zh` 后 `--apply` 写回（自动备份+原子替换，title_original 留底）；SEC 附件代码(EX-32.1等)豁免 | ✅ 活跃 |
| `news_ai_helpers_副本.py` | AI增强模块（摘要/去重/分类，无key时启发式兜底；摘要证据化——付费墙清空摘要只留标题，无片段不编造） | ⚠️ 可用（无API key时启发式降级） |
| `fetch_stock_prices_副本.py` | 股价抓取（Yahoo Finance，含限流fallback） | ✅ 活跃 |
| `fetch_bloomberg_副本.py` | ~~Bloomberg Playwright爬取~~ **已停用**（2026-08-18 合规改造：不抓付费正文，只保留公开 RSS 源 `feeds.bloomberg.com`，由 fetch_news 直接消费；勿再接回流程） | ❌ 停用 |
| `news_smoke_副本.js` | 新闻tab烟雾测试（43项断言：17 原有 + 24 安全段 + 2 筛选管道段；按 `var RAW =` 定位应用脚本块） | ✅ 可用 |
| `news_quality_tests_副本.py` | 离线质量测试 70 项（A日期/B去重/C来源状态与回退/D TLS/E摘要证据/F国内分源过滤/G筛选验收23案例+拒绝诊断+AI不可用确定性+旧缓存重筛），全部本地 fixture 零联网 | ✅ 可用 |
| `market_smoke_副本.js` | 市场行情tab烟雾测试（27项：echarts stub 捕获 setOption/on/dispatchAction/group+容器事件；旗标/图钉悬浮卡片字节级一致、悬浮断开三图联动+hideTip、旗标周围轴广播接收方不出卡、globalout 恢复联动、setEventEmphasis 未破坏） | ✅ 可用 |
| `daily_update_副本.sh` | 日更入口（股价→新闻(含确定性筛选管道)→重建→部署；`set -euo pipefail`+各步退出码检查；Step 2b 把 selection_report 与各来源状态写入日志；拒绝 NODE_TLS_REJECT_UNAUTHORIZED=0；surge 失败不报 Done） | ✅ 活跃 |
| `dashboard.html` | 最终产物（由generate生成，~365KB，**不含**ECharts库与ST数据） | ✅ 活跃 |
| `st_data.js` | ST用户数据包（`window.ST_DATA=…`，由generate从st_data_副本.json生成，ST tab懒加载） | ✅ 活跃 |
| `deploy/index.html` | 部署入口（Surge默认服务此文件，**必须与dashboard.html同步**） | ✅ 活跃 |
| `news_data_副本.json` | 新闻缓存（国际+国内双分区 + fetch_status 状态块） | ✅ 活跃 |
| `news_cache_backups/` | 新闻缓存版本备份（保留最近3份） | ✅ 活跃 |
| `news_rejected_副本.json` | 最近一次筛选被拒条目+原因诊断（每次 fetch 覆盖写，排查误杀用） | ✅ 活跃 |
| `st_data_副本.json` | ST用户数据缓存（2.6MB，全球+6大洲+9国家+10 App） | ✅ 活跃 |
| `dashboard_data_副本.json` | 财务数据缓存 | ✅ 活跃 |
| `stock_prices_副本.json` | 股价缓存 | ✅ 活跃 |
| `pg_data_副本.json` | 价格/图表数据缓存 | ✅ 活跃 |

### Excel数据源
- `BKNG-EXPE-ABNB业绩20260811.xlsx` — 财务季度数据
- `【中金互联网】海外OTA用户数据2607_副本.xlsx` — ST用户数据

## 目录约定

- 所有工作文件使用 `_副本` 后缀
- `deploy/` 是 Surge 部署源（含 CNAME + index.html + dashboard.html + **echarts.min.js + st_data.js**；后两者由 generate 自动复制，缺一个页面就加载不出图表/ST数据）
- `_deploy/` 是旧版目录，**已废弃可删除**

---

## 新闻管道架构（当前最复杂模块）

### 处理流程（`fetch_news_副本.py`）

```
RSS/官网抓取(safe_request, TLS只验证, mark_source记账)
→ [Relevance Filter] → 公司标签 → Paywall标记 → AI管道(证据化摘要) → 翻译
→ 合并缓存(旧条目补回) → Legacy Cleanup(重跑过滤) → 日期字段回填(apply_date_fields)
→ 【确定性筛选管道 run_selection_pipeline】(对新抓+保留期旧缓存全量执行:
    实体识别 identify_entity → 硬排除 hard_exclude_reason → 重点公司/内容类型判定
    → 五维评分 select_news_item → kept/rejected 分流; rejected→news_rejected_副本.json)
→ 保留期修剪+三级去重(prune_and_dedupe) → 摘要证据回填(backfill_summary_fields)
→ 数据质量检查(data_quality_check) → selection_report/fetch_status/update_status 写入
→ save_cache(原子+备份, 致命失败不落盘)
→ 退出码: 0=全部成功 / 2=部分失败(可部署需披露) / 1=彻底失败(未写缓存)
```

### 关键函数（`fetch_news_副本.py`，按名检索勿记行号，文件约3000行会漂移）

| 函数 | 作用 |
|------|------|
| `_build_ssl_context` / `urlopen_safe` | **TLS 只验证**（certifi→系统默认，无 CERT_NONE 降级路径；`_UNVERIFIED_CTX` 已删） |
| `safe_request` | 统一出站请求入口：source 维度成功/失败记账（`mark_source`），错误分类 error_code ∈ {tls_error, unreachable, http_N, fetch_failed} |
| `mark_source` / `seed_fetch_status_from_cache` / `overall_status` | 来源状态记账三件套；失败保留旧 last_success_at；缓存里未重试的来源标 "cached" 不计入总体状态 |
| `parse_date` / `apply_date_fields` | 日期修复：解析失败返回 **None**（不再兜底今天）；每条补 `published_at`(源日期或None)/`fetched_at`(抓取时刻)/`date_status`(known/unknown)；`date` 字段兼容保留（unknown 时为 ""） |
| `_gov_date_from_url` / `extract_gov_list` | 政府站日期优先级：页面 span → URL `tYYYYMMDD` → None（unknown） |
| `_td_parse_when` / `fetch_traveldaily` / `_td_is_domestic` | 环球旅讯专用双入口抓取 + 国内外分类器（见踩坑 16/20） |
| `fetch_skift_newspage` | Skift /news/+page/2 列表页补抓（RSS 只有 10 条，见踩坑 19） |
| `filter_travel_relevance` | 三层过滤：**白名单最先**（专用源豁免全部三层）→ 强排除（词边界）→ 关键词（词边界，见踩坑 17/19） |
| `filter_domestic_items` | 国内分源过滤（`DOMESTIC_SOURCE_FILTERS` 文旅部/交通运输部/民航网各自 include/exclude），统计 raw/kept/rejected 进 `DOMESTIC_FILTER_STATS` |
| `identify_entity` | 实体识别：ENTITY_TABLE 公司/机构表 → `entity_id`（BKNG/EXPE/ABNB/CEAIR/…）+ `is_core_company`（三大OTA） |
| `hard_exclude_reason` | 硬排除：`HARD_EXCLUDE_PATTERNS`（社群广告/新闻合集/软文/救援八卦等）+ 标题以 ?/？ 结尾判"无新事实短评"（问句检查只看标题，先于拼接文本判定）；返回拒绝原因或 None |
| `select_news_item` | 单条取舍：SEC sec_filings 自动保留(100)；非核心公司五维评分（相关性25+重要性25+基本面25+证据20+来源5），核心公司+25/正式政策+20 加成；保底 60 适用 (核心∧实质动态)∨官方保留∨东航保留∨专业源并购融资；**先扣罚→后加成→保底最后**；≥`CORE_KEEP_THRESHOLD`(60) 保留 |
| `run_selection_pipeline` | 管道编排：对合并后的全量条目（新抓+保留期旧缓存）逐条跑 实体→硬排除→评分；rejected 明细写 `news_rejected_副本.json`；raw/kept/rejected/by_reason 进 `selection_report`（每日重筛，被拒旧缓存不回流） |
| `data_quality_check` | 落盘前质量检查（摘要覆盖率/日期合法性等），结果进 `selection_report.quality` |
| `_norm_url` | URL 归一化：剥 fragment/utm 等跟踪参数、scheme+host 小写、去结尾斜杠 |
| `_source_rank` / `dedupe_same_article` | **二级同文去重**：归一化标题+company+日期±3天 → 合并；主条目按来源权威度（SEC/披露易/政府站 > 直接源 > Google News 转载）；>3 天同名视为不同文章 |
| `group_same_events` | **三级同事件折叠**：标题相似度≥0.72 且日期差≤72h → 非主条目标 `folded_into`，主条目挂 `event_id`+`related_sources`（**折叠不删除**） |
| `sec_deterministic_summary` / `backfill_summary_fields` | SEC 确定性摘要（公司全名+类型+日期+8-K Items，纯元数据零网络）；全量回填 `summary_status`/`summary_generated_at`（`summary_basis` 已于 2026-08-18 删除） |
| `load_cache` / `save_cache` / `_backup_current_cache` / `_restore_from_backup` / `merge_with_cache` | 缓存五件套：完整性校验+备份恢复+原子写+新旧合并 |
| `prune_and_dedupe` | 保留期修剪（按 published_at，无则 fetched_at；环球旅讯 28 天豁免；SEC 定期报告 28 天）+ 三级去重 + unknown 沉底排序 + 数量上限 |
| `refresh_traveldaily_only` | `--td-only` 定向刷新（总数与国内子集双 ≥5 防误清空） |
| `translate_news_items` | 全源翻译（Google gtx，不可达时 fail-fast 跳过，cron agent 兜底） |

### 条目字段规范（2026-08-18 起新增字段，旧字段全部兼容保留）

| 字段 | 取值 | 说明 |
|------|------|------|
| `published_at` | `YYYY-MM-DD HH:MM:SS` 或 `null` | 源头发日期；解析失败为 null（前端显示"发布时间待确认"） |
| `fetched_at` | `YYYY-MM-DD HH:MM:SS` | 本条抓取时刻；保留期无 published_at 时按它算 |
| `date_status` | `known` / `unknown` | unknown 条目排序沉底、前端灰显"待确认" |
| `date` / `title` / `summary` / `url` / `source` | （原有） | **兼容字段勿改**——generate/前端依赖 |
| `summary_status` | `generated` / `insufficient_evidence` | 无证据时 summary 置空，前端显示"来源未提供足够公开信息"占位（付费墙源除外） |
| `summary_generated_at` | 时间戳 | 摘要生成时间 |
| `event_id` / `folded_into` / `related_sources` | `ev_*` / 主条目URL / [来源名] | 同事件折叠三件套；前端跳过 folded_into 条目；主条目显示"同事件: xx, xx" |
| `merged_same_article` | int | 同文合并计数（同标题多 URL 转载） |
| `transport_security` | `http` | 仅纯 HTTP 政府源标记（提示降级传输，其余默认 https 不标） |
| `entity_id` / `is_core_company` | `BKNG`/`EXPE`/`ABNB`/`CEAIR`/… + bool | 实体识别结果；is_core_company=三大OTA（评分+25 加成依据） |
| `source_channel` / `content_type` | 渠道名 / 内容类型 | 筛选管道的来源权威度输入与内容分类（industry_news/employee_policy/…） |
| `substantive_company_change` | bool | 是否实质公司动态变化（核心公司保底判定依据） |
| `selection_score` / `selection_status` / `selection_reasons` | 0-100 / `kept`\|`rejected` / [原因] | 筛选管道评分与取舍诊断；rejected 条目同步落 news_rejected_副本.json |
| `impact_dimensions` | [维度] | FUNDAMENTALS_RULES 命中的基本面维度记录（供给/需求/变现/竞争/新玩家入局等） |
| `paywall` / `title_original` / `summary_original` / `company` / `ai_category_label` | （原有） | 翻译留底与标签 |

### 来源状态与退出码协议

```
缓存顶层: fetch_status = {attempted_at, last_success_at, status: success|partial|failed,
                          sources: {来源名: {status: success|failed|cached, item_count,
                                            last_success_at, attempted_at, error_code, filter:{raw,kept,rejected}}}}
         update_status = overall_status（只统计本次实际尝试的来源）
前端: statusLine() → failed="全部来源更新失败…（以下为缓存数据）" / partial="部分来源更新失败（N个）…" / success="更新于 …"
退出码: 0 全部成功；2 部分或全部失败但有缓存数据（可部署，页面披露）；1 彻底失败且零数据（不写缓存不重建不部署）
日更脚本: 新闻 rc=1 → 中止；generate/surge 失败 → 报错退出，不再打印 "Done deployed"
         Step 2b: 新闻抓取后把 selection_report（raw/kept/rejected/by_reason/quality）
         与各来源 status/last_success_at 写入日志（python3 -c 只读，|| true 保护不阻塞）
```

### 三层过滤机制

| 过滤层 | 规则 | 目标 |
|--------|------|------|
| **白名单** | Skift/PhocusWire/Travel Weekly/环球旅讯 等旅游专用源 → **全部保留（最先判定，豁免后两层）** | 信任专业源（见踩坑19） |
| **强排除** | 综合源命中 crypto/war/crime/disaster 等关键词（词边界）→ 直接丢弃 | 绝对排除 |
| **关键词** | Bloomberg/CNBC 等综合源 → 必须命中 40+ OTA/旅游关键词之一 | 严格筛选 |

### 筛选管道评分模型（2026-08-18 晚间上线，纯确定性零 AI）

- **执行时机**: 每次 fetch 对**新抓条目+保留期内旧缓存**全量执行（daily_update 正式管道内置）；被规则拒绝的旧缓存条目次日不得回流；AI 不可用时照常执行（全正则+字段运算）
- **自动保留**: SEC sec_filings 全保留（selection_score=100）；官方保留规则（`OFFICIAL_KEEP_RULES`，披露易运营/運營类公告等）与东航保留规则（`CEAIR_KEEP_RE` 票价/退改/航班/行李/上线等）命中直接 kept
- **五维评分**（非核心公司，满分100）: 相关性 25 + 重要性 25 + OTA 基本面 25（`FUNDAMENTALS_RULES`：供给/需求/变现/竞争/新玩家入局直订等）+ 证据 20（摘要质量，来源权威≥4 或核心公司各再+4）+ 来源 5
- **加成与保底**: 核心公司+25、正式政策+20；保底 60 适用：(核心公司∧实质动态) ∨ 官方保留 ∨ 东航保留 ∨ 专业源(src_q≥4)并购/融资类；顺序**先扣罚→后加成→保底最后**
- **阈值**: `CORE_KEEP_THRESHOLD=60`；硬排除命中直接 rejected（不进评分）
- **诊断落盘**: 每条记 `selection_score`/`selection_status`/`selection_reasons`；全量拒绝明细写 `news_rejected_副本.json`；汇总（raw/kept/rejected/by_reason/quality）进缓存 `selection_report`，daily_update Step 2b 转写日志
- **调参入口**: `HARD_EXCLUDE_PATTERNS` / `FUNDAMENTALS_RULES` / `OFFICIAL_KEEP_RULES` / `CEAIR_KEEP_RE` / `CONTENT_TYPE_RULES` / `ACTION_MARKER_RE`——改任何一项后必须跑 `news_quality_tests_副本.py` G 段 23 案例回归

### 前端渲染（`template_副本.html`）

| 特性 | 状态 | 说明 |
|------|------|------|
| **HTML 转义** | ✅ 2026-08-18 | 所有动态字段（标题/摘要/日期/来源/company）经 `escapeHtml`；SEC 卡片与新闻卡片共用 |
| **URL 安全** | ✅ 2026-08-18 | `safeExternalUrl` 只放行 http(s)://，拒绝 javascript:/data:/相对路径；非法 URL 降级为无链接标题；外链带 `rel="noopener noreferrer"` |
| 状态披露 | ✅ 2026-08-18 | update_status partial/failed 时显示来源失败提示（见状态协议） |
| 摘要状态 | ✅ 2026-08-18 | summary_status=insufficient_evidence → 显示"来源未提供足够公开信息"占位（summary_basis 已于 2026-08-18 删除） |
| 未知日期 | ✅ 2026-08-18 | date_status=unknown → "发布时间待确认"/SEC"待确认" |
| AI 分类标签 | ✅ 保留 | 显示：行业趋势/公司新闻/科技创新/宏观经济/竞争动态/投资动态 |
| 同事件标签 | ✅ 保留 | 显示"同事件: xxx, xxx"提示（related_sources+same_event_sources 去重） |
| 源标签 / 公司徽章 | ✅ 保留 | BKNG(暗红)/EXPE(红)/ABNB(粉)/东航(蓝) |
| ★ 重点 / 🔒 付费内容标签 | ❌ 已移除 | — |

### 新闻数据统计（勿在此写死，实时查看）

```bash
python3 -c "import json;d=json.load(open('news_data_副本.json'));print({k:{c:len(v) for c,v in d[s].items()} for s,k in [('international','国际'),('domestic','国内')]})"
# 翻译残留检查（英文标题条数）:
python3 -c "import json,re;d=json.load(open('news_data_副本.json'));items=[i for v in d['international'].values() for i in v];print(sum(1 for i in items if re.search(r'[A-Za-z]{2,}',i.get('title','')) and not re.search(r'[\u4e00-\u9fff]',i.get('title',''))))"
```

> 注：环球旅讯条目(国际+国内)保留期一律 28 天（prune 来源豁免）；其余国际行业新闻 7 天。**新管道首次运行后缓存条数会略降**——同文转载被合并（merged_same_article）、同事件被折叠（folded_into，前端不渲染），属预期不是丢数据。

---

## ST用户数据Tab架构

### 两个子视图
1. **按市场划分** (`data-sttab="country"`)：全球+6大洲图表，可展开9个重点国家
2. **按App划分** (`data-sttab="app"`)：横排 App chips 选择器（`.st-app-rail`）+ 图表面板；**默认选中第一个 App（Trip.com）进入即出图**，无空态等待点击；桌面 chips 换行铺排，≤768px 横向滚动（scroll-snap+隐藏滚动条）；指标（MAU/DAU/下载量）跨 App 保留，数据模式按 App 记忆；图表高度随屏宽响应（430/400/360/300）

### 关键函数（`template_副本.html`）

| 函数 | 作用 |
|------|------|
| `stRenderChart` | 单线图渲染（全球图表） |
| `stRenderMultiLineChart` | 多线图渲染（大洲/App对比） |
| `stRenderGlobalChart` | 渲染全球MAU/DAU/下载量图表 |
| `stRenderCountryCharts` | 渲染大洲+国家图表网格 |
| `stRenderAppCharts` | 渲染按App划分面板（横排chips+分段控件+图表，2026-08-18 重构） |
| `stGetAppRegionSeries` | 构建App跨地区数据序列 |
| `initSTTab` | ST tab初始化入口 |

### 图表特性
- 数据精度：2位小数（Excel原始值÷100万）
- 曲线：`smooth: true`，`symbol: "none"`（无数据点标记）
- 图例：`type: "scroll"` 横向滚动（支持10个App图例）
- 数据模式：绝对值/YoY/Share 三种切换
- 响应式：CSS Grid 单列布局，媒体查询适配PC/平板/手机

---

## 缓存管理系统

### 版本备份
- 目录: `news_cache_backups/`
- 命名: `news_data_YYYYMMDD_HHMMSS.json`
- 保留: 最近 3 个版本，自动轮转

### 原子写入
```python
def save_cache(data):
    _backup_current_cache()    # 先备份旧版本
    tmp_path = OUTPUT + '.tmp'  # 写临时文件
    json.dump(data, tmp_path)
    os.replace(tmp_path, OUTPUT)  # 原子替换
```

### 损坏恢复
```python
def load_cache():
    try:
        data = json.load(open(OUTPUT))
        # 完整性校验
        if 'international' not in data and 'domestic' not in data:
            raise ValueError("Cache missing sections")
        # ...
    except (json.JSONDecodeError, ValueError):
        data = _restore_from_backup()  # 从最新备份恢复
```

---

## 数据注入点（`template_副本.html`）

```
/*__DATA_PLACEHOLDER__*/{}  → dashboard_data_副本.json（RAW，紧凑JSON内联）
/*__ANN_PLACEHOLDER__*/{}   → 财务年报数据（紧凑JSON内联）
/*__MKT_PLACEHOLDER__*/{}   → 市场行情+新闻+股价（紧凑JSON内联）
<!--__ECHARTS__-->          → <script src="echarts.min.js">（独立文件，缺失时回退CDN标签）
<!--__ECHARTS_PRELOAD__-->  → <link rel="preload" href="echarts.min.js" as="script">（head）
```

**ST 数据不再内联**：`generate_副本.py` 将 st_data_副本.json 序列化为独立 `st_data.js`（`window.ST_DATA=…`），前端 `initSTTab()` 打开 ST tab 时动态注入 `<script src="st_data.js">` 懒加载。注意 JSON 用 `separators=(',',':')` 紧凑输出以减小体积。

---

## 新闻管道踩坑记录（实战经验）

1. **Google 系网络时通时不通**: `UNREACHABLE_HOSTS` fail-fast 机制 → 单次运行跳过，下次重试
2. **东航官网已死**: wcm.ceair.com NXDOMAIN → 改用港交所披露易+民航网+GNews
3. **HKEX 披露易**: POST 接口 + 内部 stockId（东航 00670→1558），需 prefix.do 查询映射
4. **政府站正则**: `t\d{8}_\d+` 不是 t20 开头；交通运输部=`.news-link`块，文旅部=`a[title]`结构
5. **环球旅讯**: 正确域名 `www.traveldaily.cn`（旧 `traveldaily.com.cn` 已废）；通用 DOM 解析器对它效果差（日期错乱+混入合作站链接），已改用专用双入口解析器 `fetch_traveldaily`（见记录16）
6. **macOS Python 3.13 证书**: 所有出站走 `urlopen_safe()`（certifi 优先→系统默认回退）。**2026-08-18 起仅验证模式**：`_UNVERIFIED_CTX`/无证书重试已删除，SSL 错误分类 `tls_error` 记入 fetch_status 并用旧缓存兜底，**绝不静默降级**；`daily_update_副本.sh` 检测到 `NODE_TLS_REJECT_UNAUTHORIZED=0` 直接拒绝运行
7. **SEC 保留期**: 定期报告 28 天，其他 7 天（`SEC_LONG_RETENTION_TYPES`）
8. **缓存污染历史**: 旧缓存含错误公司标签 → `SOURCE_BLOCKLIST` + `CEAIR_ALIASES` 兜底
9. **缓存丢合并防护**: 已实现完整性校验+自动恢复（见缓存管理系统章节）
10. **Cron**: 唯一有效 job b922a522（周二至周六 5:30 北京时间运行 `daily_update_副本.sh`）
11. **Surge 验证**: curl 超时设 `-m 60`；轻量核验三件套=`curl -sI` 看 content-length/surge-stamp、surge-stamp 里的哈希段==本地 `md5 -q`、小范围 `curl -r 0-N` grep 关键标记。**勿全量下载**（用户拒绝慢速整页下载）
12. **Bloomberg 合规边界**（2026-08-18 更新）: `fetch_bloomberg_副本.py`（Playwright 爬取）**永久停用**——只用公开 RSS（feeds.bloomberg.com，量少但合规）；`PAYWALL_SOURCES` 已移除 Bloomberg（WSJ/FT/Reuters 仍在，无公开输入渠道的付费源摘要清空只留标题）；日更脚本已删 Bloomberg 步骤，勿再接回
13. **遗留噪音经缓存合并回流**: 相关性过滤只作用于新抓数据，`merge_with_cache` 会把旧缓存条目补回 → 过滤上线前的噪音（如 Sembcorp IPO、Stripe 收购案）曾存活至保留期到期。已修复：main() 在合并后对国际行业新闻重跑 `filter_travel_relevance`（Legacy Cleanup）；过滤器同时检查 `title_original`/`summary_original`，已翻译条目不会被误杀。新过滤规则上线时注意同类问题
14. **移动端加载慢/图表不显示的两层根因与载荷重构**: ① 最初在 `<head>` 用渲染阻塞 `<script src>` 引 cdnjs.cloudflare.com 的 ECharts，国内移动网络该 CDN 慢/不可达 → 白屏、`echarts` 缺失图表不渲染；② 改成内联后产物膨胀到 2.09MB 单体文件，慢网络下整个 blob 必须下完才能执行图表代码，**仍然很慢、仍无图表**。最终方案（当前架构）：`echarts.min.js`（5.4.3，1.02MB）作为**同源独立文件**引用（head preload + 应用脚本前 `<script src>`，浏览器可跨每日更新缓存）；ST 数据拆为独立 `st_data.js`（566KB）仅打开 ST tab 时懒加载；内联 JSON 用紧凑 separators。首屏 HTML 2,089,876 B → 364,903 B（gzip ~107KB）。今后**不要**再往模板里加外部 CDN 的 `<script src>`/字体/图片；升级 ECharts 时替换本地 echarts.min.js 即可；**不要把 echarts 或 ST 数据改回内联**
15. **懒加载提示别用 innerHTML 覆盖面板**: ST 懒加载第一版在等待 `st_data.js` 时用 `panel.innerHTML="<div>正在加载…</div>"` 显示提示，**销毁了面板里的静态图表容器**（chart-section/chart-title/stGlobalChart 等）；数据 onload 后 `stRenderGlobalChart` 的 `document.querySelector('#tab-st .chart-section .chart-title')` 返回 null → TypeError，图表永不渲染且 loading 文案永久残留（headless 下 canvas 数停在 13、DOM 残留 loading 文案即可确诊）。修复：先 `panelHTML=panel.innerHTML` 备份，onload 成功且数据有效时**先恢复 innerHTML 再** `stBindEvents()+stRenderAll()`。验证法：headless --dump-dom 数 `<canvas>`（修复前 13 → 修复后 20）+ grep loading 文案应为 0。给任何"加载中"提示做 innerHTML 替换前，确认目标容器没有后续渲染依赖的静态子节点
16. **环球旅讯专用解析器的坑**（2026-08-17 重写，`fetch_traveldaily`）: ① 首页 `newsCard` 必须**整卡原子解析**——先定位 `<a class="newsCard" href="/article/{id}/">`，取该锚点到其**自身第一个 `</a>`** 的片段再在片段内找标题/摘要/时间；若用 href 后的定长前向窗口找第一个 h3，轮播区会把**下一张卡**的 h3 误配给当前卡（曾出现同一标题挂在两个不同文章 ID 上）。② 头条/轮播卡没有 h3，标题在 `<h2>`（titleOverlay）或 img alt 里 → 标题兜底链 h3→h2→img alt，否则头条会被丢弃。③ 首页时间是相对格式（"6 小时前"/"4 天前"/"昨天"/"08-10 15:02" 无年份）→ `_td_parse_when` 统一换算，跨年保护：解析出的日期若晚于今天+1天则年份-1。④ 快讯页（expressPage）条目自带精确 `YYYY-MM-DD`（`articleItemTime` span），链接形如 `/expressPage/{id}/`，质量最高应优先。⑤ 新旧缓存 URL 结尾斜杠不一致（`/article/190541` vs `/article/190541/`）会绕过 merge/prune 去重 → 统一走 `_norm_url`（rstrip '/'）。⑥ `china_industry` 栏目唯一来源就是环球旅讯，所以解析器大改后可用 `--td-only` **整源替换**（内置 <5 条放弃保护，防抓空误清空），旧低质条目不必等 28 天保留期自然过期
17. **关键词子串误命中（词边界修复）**（2026-08-18）: `filter_travel_relevance` 原用 `kw in text` 子串匹配，`TRAVEL_STRICT_KEYWORDS` 里的 `'expe'`（EXPE ticker）误命中 "Reduced Rate-Hike **Expe**ctations" → Bloomberg 黄金行情新闻被当旅游新闻放行（"黄金保持两日涨幅"混入看板）。同类隐患：`'ota'`→rotation/notable、`'adr'`→madrid；`TRAVEL_BLOCK_STRONG` 反向同样中招：`'war'`→award/software（会误杀 Skift 获奖报道）、`'vote'`→devoted。修复：新增模块级预编译 `TRAVEL_KEYWORD_PATTERNS`/`TRAVEL_BLOCK_PATTERNS`（`\b` + `re.escape(kw)` + `\b`），函数内两处循环改用 `p.search(text)`。副作用可接受：`'adr'` 不再匹配复数 "ADRs" 等极端写法。今后往关键词表加短词（≤5 字母）时务必想一遍常见英文单词的子串碰撞
18. **Google 系抓取/翻译必须走本地代理**: 用户浏览器可达 Google 系服务是因为系统代理（`scutil --proxy` 可查，当前 `127.0.0.1:7892`），但 shell 里的 curl 默认不读系统代理、python urllib 对系统代理的继承也不可靠 → 裸跑脚本时 `news.google.com`/`feeds.bloomberg.com`/`translate.googleapis.com` 全部超时（被 `UNREACHABLE_HOSTS` fail-fast 跳过），翻译环节日志出现 `Google Translate unreachable — disabling translation for this run`，新抓条目整批保持英文。解决：运行抓取前显式 `export https_proxy=http://127.0.0.1:7892 http_proxy=http://127.0.0.1:7892`（端口以 `scutil --proxy` 实测为准）。2026-08-18 带代理重跑后 79 条全部翻译成功。日常 cron 裸跑若代理未开仍会跳过 Google 源——若要彻底摆脱依赖，配 `DASHSCOPE_API_KEY`（翻译/摘要走阿里云，国内直达）或把 Google News RSS 换成各公司 newsroom RSS。**已缓解（2026-08-18 上午）**: cron b922a522 指令改为先 `scutil --proxy` 检测系统代理并自动 export 再跑主流程（代理开着的早晨 Google 源抓取自动恢复）；翻译环节由 agent 兜底（`agent_translate_副本.py --export/--apply`），彻底不依赖 Google 翻译/DASHSCOPE key。仍存在的残余依赖：代理没开的早晨，Google News/Bloomberg 的**抓取**（非翻译）依旧跳过，彻底根治需换 newsroom RSS 源
19. **强排除误杀白名单源 + Skift RSS 条数上限**（2026-08-18 上午，用户发现看板缺新闻）: ① `filter_travel_relevance` 原顺序是"先强排除、后白名单"，导致 Skift 这类专用源也被强排除词拦截——"Saudi OTA Almosafer IPO **Despite Iran War** Disruption" 和 "中东酒店建设（摘要含 war）" 两条正经行业新闻被 'war' 误杀。修复：白名单判定提前到最前，专用源豁免全部三层过滤（专业旅游媒体的 'war' 等词多是行业报道上下文，编辑已做过选题把关）。② Skift RSS（skift.com/feed）只给最近 10 条，用户对比 skift.com/news/ 发现漏新闻 → 新增 `fetch_skift_newspage()` 补抓 /news/ + /news/page/2/ 列表页（每页 7-8 张 c-tease 卡片，链接 aria-label 是标题、URL 路径含发布日期），与 RSS 按 `_norm_url` 去重后并入，Skift 覆盖 12→15 条。教训：给专业源做内容过滤时，任何"绝对排除"规则都可能误伤行业语境；RSS feed 的条数上限≠站点实际更新量，重要源要列表页兜底
20. **环球旅讯分流三层坑**（2026-08-18 10:50，用户反馈"没有国内外分流"）: ① **标记表覆盖不足**: 首版 `TD_INTL_MARKERS` 只有 Booking/万豪/达美等大牌，环球旅讯大量国际新闻是拉丁字母中小公司名（Faye/Entravel/BCD Travel/30 Sundays/BizAway/Options Travel/欧铁）和漏掉的国家名（意大利/荷兰/西班牙/加拿大/瑞士/迪拜）→ 全部落默认国内，分流形同虚设（国际区只剩新秀丽 1 条）。修复：补全上述标记 + `全球最大差旅` 这类特定短语；国内表同时补 豆包/万达/复星/港澳台（防标题同时含国际地名时误判）。教训：环球旅讯摘要普遍为空，分类全靠标题，标记表必须跟着实际条目滚动补。② **国际区 7 天保留期剪光分流条目**: 分流过去的国际条目按 industry_news 7 天保留，07-22~08-06 的条目立即被剪 → `prune_and_dedupe` 加来源豁免：`source==环球旅讯` 时 `item_retention=max(retention,28)`（该源条目少而精，与国内 28 天一致才让分流可见）。③ **`--td-only` 防误清空保护只查总条数**: 首页入口超时、只抓到快讯页 11 条国际旧闻时，总数 11≥5 绕过保护 → china_industry 22 条被整源替换成 0 条（自动备份恢复）。修复：总数与**国内子集**都必须≥5 才放行——国内子集是 china_industry 的替换内容，入口部分失败时它最先不完整
21. **十项改造的实施与测试坑**（2026-08-18 午后）: ① **致命路径写缓存顺序**: 首版 main() 在算退出码前就 `save_cache`，全部失败且无缓存时会把空数据落盘毒化缓存——修复为 save 移到退出码判定之后，`rc=1` 路径直接 return 不落盘（质量测试 C2 专门锁此行为）。② **测试 fixture 的 CIK 过滤陷阱**: SEC EDGAR fixture 把 `ciks` 写死为 BKNG 一个，`fetch_sec_filings` 按 `entity=CIK%3A{cik}` 过滤后 EXPE/ABNB 命中 0 条 → 三源全"failed"破坏全成功场景——fixture 必须从请求 URL 解析 CIK 动态生成命中。③ **escapeHtml 断言写法**: 断言转义后输出时引号已是 `&quot;`，用原始 `alert("sec")` 匹配必假失败；同理 URL 归一化断言要先想清楚结尾斜杠被 rstrip。④ **占位符计数**: "来源未提供足够公开信息"对**所有**无摘要非付费墙条目触发（含未知日期 fixture），断言计数要数全。⑤ **同文去重首版算法 bug**: 按顺序处理 [转载A,转载B,官方P] 时 P 被重复追加——重写为 clusters 字典 + 顺序表 + emitted 集合；相隔>3 天的同名条目要作为独立文章重新输出。⑥ **basis 回填阈值**: 环球旅讯/披露易的短摘要（"月報表"3字）被 ≥10 字阈值漏掉 → 改为非空即有证据，按源归类（环球旅讯=public_snippet 站点自身摘要属性、披露易=filing_metadata 公告类型），非 SEC 摘要 basis 覆盖率 100%。⑦ **离线测试禁网三件套**: patch `fn.safe_request`+`load_cache`/`save_cache`、`UNREACHABLE_HOSTS` 预置 translate.googleapis.com 禁翻译、patch `time.sleep`——缺一个都会让"离线"测试偷偷联网或变慢
22. **echarts.connect 联动的临时断开与恢复 + 旗标/图钉共用 studMeta + 轴广播残留**（2026-08-18 午后，市场tab悬浮改造）: 需求"悬浮财报旗标时三家公司图表不要联动弹卡"，但价格线悬浮仍要联动 → 不能取消 connect。读 minified 源码确认：联动事件分发要求 `connectedGroups[groupName]` 已注册，`echarts.connect(charts)` 把所有实例 `.group` 设为同一个新生成组名并**注册**后**返回该名**；把实例 `.group` 临时改成未注册的唯一名（如 `solo_bkng`）即可**静默断链**，改回保存的共享组名即恢复。实现：`stockLinkGroup=echarts.connect(chartInstances)` 存返回值；旗标/图钉 scatter 的 mouseover 里 `unlinkStockCharts(key)`（三图改 solo_*，非当前图 dispatchAction hideTip 抹掉已弹联动卡），globalout/mouseout 里 `relinkStockCharts()`。**首版残留 bug（用户截图反馈"旗标周围仍两卡同屏"）**: 断链只挂在 series mouseover（指针压中符号）上，但 tooltip 是 `trigger:'axis'`——指针在旗标**周围**未压中符号时没有 mouseover、断链不触发，connect 仍把轴指针位置实时广播，其余图的 axis tooltip 会把自己**最近的**旗标点带进 params 各自出卡（截图里 EXPE 05-15 与 ABNB 05-06 相隔 9 天，指针落在两旗标之间即双卡）。修复=第二道闸 `stockHoverKey`：容器 mouseenter/mouseleave 跟踪指针所在图（mouseenter 先于图内任何 tooltip 处理，时序确定），formatter 里 `isStockHoverLocal()` 判定——**只有指针所在图出财报卡，广播接收方一律只显示价格行**；scatter mouseover 里兜底设置同值。教训：connect 断链是事件级的（压中符号才触发），而 axis tooltip 广播是连续的——凡"悬浮 X 时不联动"的需求，必须同时考虑"悬浮在 X 附近"的连续区间，仅靠离散事件断链必有缝隙；per-chart 本地化闸门（渲染时判定）比事件断链更可靠，两者叠加。另一坑：旗标(series[2])与图钉(series[1])是两条 scatter 但共享同一 studMeta 数组——tooltip formatter 统一按 `studMeta[scatterParam.dataIndex]` 解析，两种悬浮天然产出**字节级相同**的卡片（卡片头日期=实际财报日 meta.date，而非悬浮点的 x 日期）；价格行须精确匹配悬浮日期（图钉钉在财报日后首个交易日 priceDate，财报日落在周末时 priceDate≠财报日），不匹配时用 `meta.price`/`meta.priceDate` 输出回退行 "公司 (priceDate 收盘): $xx"。旧实现 `e.date === date` 查 earnings_dates 在图钉悬浮下永远失配（日期不同）→ 卡片消失，就是此坑的表象
23. **筛选评分校准坑**（2026-08-18 晚间，筛选管道上线）: ① **Python `\b` 把 CJK 当词字符**——中英混排文本里 `\b` 边界判定不可靠，筛选管道统一对 lowercased 文本用 ASCII 环视 `(?<![a-z0-9])kw(?![a-z0-9])`（G3 测试锁 booking/trip 词边界行为）。② **加成/保底顺序**: 先扣罚→后加成→保底最后落定，顺序写反会让"软文+核心公司"组合被加成抬过阈值。③ **校准基准=G_ACCEPT 23 案例**: 携程陪产假留/获奖删、飞猪帮帮留/赞助删、Expedia收购Layla留、豆包直订酒店留（竞品入局规则+12 恰好到 60）、Saudi Almosafer IPO 留（证据分里来源权威+4 救回）、酒店RevPAR留/300家软文删、东航数据+退改留/篮球救援删、采购广告/超哥短评/大湾区实测/国航新玩法/差旅大坑删——改任何权重后必须 23 案例全过再上线。④ **问句标题硬排除**: 标题以 ?/？ 结尾一律判"无新事实短评"，且必须在拼接文本判定**之前**只查标题（否则摘要文本会稀释问句特征）
24. **环球旅讯渠道抓取与筛选集成坑**（2026-08-18 晚间）: ① **单条 None date 灭掉整个源**: `fetch_traveldaily` 收尾 `all_items.sort(key=lambda x: x.get("date"))` 遇一条 date=None 即 `'<' not supported between NoneType and str`，异常冒泡把整个环球旅讯源标 failed（63 条全丢）、首次真实抓取退出码 2——排序 key 改 `(x.get("date") or "")`。教训：**单条脏数据不应灭整个源**，聚合/排序处一律给默认值。② **旧缓存重筛防回流**: 筛选管道必须挂在 `merge_with_cache` **之后**对全量（新+旧）执行，被拒条目从列表移除并落 news_rejected_副本.json——只在抓取侧筛、合并后不重筛，被拒噪音次日必然回流（与踩坑 13 同源教训，G6 测试锁此行为）。③ **fetch_status.status 曾为 None**: main() 只写 news_data["update_status"] 未回写 `FETCH_STATUS["status"]` 就深拷贝 → 缓存顶层 status 恒 None；补 `FETCH_STATUS["status"]=status`。④ **硬排除补漏清单**（真实数据回流发现）: 投融资动态/这N笔交易（新闻合集）、股票股价/股吧（社群广告）、网红（软文）、走红/旅客突发疾病（救援八卦）、月報表（`OFFICIAL_EXCLUDE_RE` 繁体变体）——新规则上线后第一次真实抓取，务必 kept/rejected 双侧逐条过一遍

---

## 最近变更记录

### 2026-08-18 晚间：新闻确定性筛选管道上线（16 节规格全量实施，fixture→一次抓取→一次部署）
- **范围**: 实体表+硬排除+重点公司判定+OTA 基本面五维评分，纯确定性（正则+字段运算，AI 不可用照常执行）；集成进 daily_update 正式管道，每日对"新抓+保留期旧缓存"全量重筛，被拒旧缓存不得次日回流
- **改动**:
  1. `fetch_news_副本.py`: 新增筛选管道（identify_entity/hard_exclude_reason/select_news_item/run_selection_pipeline/data_quality_check）+ §11 字段（entity_id/is_core_company/source_channel/content_type/substantive_company_change/selection_score/selection_status/selection_reasons/impact_dimensions）；SEC 自动保留、核心+25/政策+20 加成、四类保底 60、CORE_KEEP_THRESHOLD=60；拒绝明细落 news_rejected_副本.json，汇总进 selection_report；修复 fetch_traveldaily None-date sort 崩溃与 fetch_status.status=None；补硬排除（新闻合集/社群广告/救援八卦/软文网红/问句短评）与 OFFICIAL_EXCLUDE_RE 月報表
  2. `news_quality_tests_副本.py`: +G 段（23 案例验收+字段完整性+词边界+拒绝诊断 JSON+AI 不可用确定性+旧缓存重筛），60→70 项
  3. `news_smoke_副本.js`: +筛选管道段（占位符清零/无 rejected 残留），41→43 项
  4. `daily_update_副本.sh`: Step 2b 把 selection_report 与各来源状态写日志
- **执行记录（严格按阶段）**: 阶段1 fixture 全绿（quality 70/70、news_smoke 43/43、market_smoke 27/27）→ 阶段2 一次真实抓取：首抓因 traveldaily sort bug 退出码 2，修复后抓取 exit 0 全源成功（环球旅讯恢复 40 国内/23 国际），筛选 97 raw→53 kept→离线精炼 49 kept → 阶段3 一次构建+部署：部署前备份至工作区 pre_deploy_backup_20260818/，dashboard.html=deploy/index.html=389,212 B，surge exit 0，线上 content-length 389,212、md5 4a926722c08c00db4191281c51413894==surge-stamp 哈希；摘要覆盖 49/49=100%（filing_metadata 13/rss_snippet 17/full_text 16/public_snippet 3）；update_status=success

### 2026-08-18 午后：ST「按App划分」视图重构（横排 App 选择 + 默认选中即出图 + 移动端适配）
- **需求**: 用户反馈旧版"左侧竖排 App 列表 + 右侧空面板(需先点击)"逻辑不直接；要求横排展示、逻辑更直接、移动端适配
- **改动**（`template_副本.html`）:
  1. `stRenderAppCharts` 重写：左竖列表改为**横排 chips 选择器**（`.st-app-rail`，6 个 App 胶囊按钮，圆点指示 + active 填充 #1677ff）；**默认选中第一个 App（Trip.com）进入即渲染图表**，删除"👉 请在左侧选择"空态
  2. 面板头部重构：App 名 + "全球 + 6 大洲 · N 条曲线"副标题 + 两组分段控件（`.st-seg`：指标 MAU/DAU/下载量、模式 绝对值/YoY/Share）同行右侧；**顺带修复旧版模式按钮 idx===0 恒亮的 bug**（现按 `stState.appMode[appActive]` 真实高亮）
  3. 交互保留：指标跨 App 保留、模式按 App 记忆、重复点击同一 App 不重绘；新增 chips `aria-pressed`/`focus-visible` 可访问性
  4. 移动端（≤768px）：chips 行 `nowrap + overflow-x 横滚 + scroll-snap + 隐藏滚动条`；头部纵排、分段控件铺满一行；图表高度响应 430/400/360/300（≥1400/≥1024/>768/其余）
  5. 新增 CSS 类 `.st-app-wrap/.st-app-rail/.st-app-chip/.st-app-panel/.st-app-head/.st-seg` 等（内联样式全部移入 class，含 hover/active/focus 过渡）
- **验证**: news_smoke 41/41、market_smoke 27/27 回归通过；Chrome headless 桌面(1600px)+移动(390px) 截图确认：桌面 chips 一行铺排+Trip.com 默认出图 7 条曲线，移动端 chips 横滚可滑、控件换行铺满、图表正常渲染
- **部署**: 手动 surge 上线，线上 content-length/surge-stamp 哈希==本地 md5（curl 核验）

### 2026-08-18 午后：市场行情tab 财报日悬浮卡片改造（旗标/图钉卡片统一 + 悬浮期间断开三图联动 + 旗标周围广播抑制 v2）
- **需求**: ① 悬浮季度旗标出现财报卡片；② 悬浮对应三角图钉出现**相同**卡片；③ 旗标/图钉悬浮期间三家公司图表**不要**联动同时弹同时期卡片（价格线悬浮的联动保持不变）
- **改动**（`template_副本.html` 市场行情段）:
  1. tooltip formatter 重写：旗标(series[2])/图钉(series[1]) 共享 studMeta 数组，悬浮一律按 `studMeta[dataIndex]` 解析 → 两种悬浮输出**完全一致**的财报卡片（卡片头日期=实际财报日）；价格行仅在与悬浮日期同日时显示，否则回退行 "公司 (priceDate 收盘): $xx"（财报日落在周末/节假日时取其后首个交易日价格）
  2. 新增 `stockLinkGroup`/`unlinkStockCharts`/`relinkStockCharts`：悬浮旗标/图钉时把三图 `.group` 临时改为未注册的 `solo_*` 名（联动要求组名已注册，未注册=静默断链），非当前图 dispatchAction hideTip；globalout/mouseout 恢复共享组名 → 联动恢复。`echarts.connect` 返回值存入 `stockLinkGroup`（机制细节见踩坑 22）
  3. 悬浮联动 IIFE 签名改为携带 `cfg.chartKey`；`endLink()` 统一负责 clearLink+restore+relink
  4. **v2 修复（用户截图反馈旗标周围仍两卡同屏）**: 断链只挂在 series mouseover（压中符号）上，axis tooltip 广播是连续的——指针在旗标周围未压中符号时其余图仍会各自出卡。加第二道闸 `stockHoverKey`：容器 mouseenter/mouseleave 跟踪指针所在图，formatter 的 `isStockHoverLocal()` 判定只有指针所在图出财报卡，广播接收方只显示价格行；scatter mouseover 兜底设置同值（详见踩坑 22 残留 bug 段）
- **新增测试**: `market_smoke_副本.js` 27 项全过（echarts stub 捕获 setOption/on/dispatchAction/.group+容器事件；旗标卡==图钉卡字符串相等、悬浮时三图 solo_* 且非悬浮图收到 hideTip、globalout 恢复共享组名、价格回退行正则、非财报日普通悬浮无卡片、**旗标周围接收方不出卡/本图照常出卡/mouseleave 恢复**、setEventEmphasis 未破坏）
- **回归**: `news_smoke_副本.js` 41/41；`generate_副本.py` 重建 dashboard.html 390,364 字节（generate 打印 376,336 为字符数），`deploy/index.html` 字节一致
- **部署**: 用户确认后手动 surge 上线（与十项改造同包）——v1 部署后用户截图反馈旗标周围仍双卡，v2 修复后再次部署；线上 content-length 390,364、surge-stamp 哈希 8d9a0bdb…==本地 md5，curl 核验通过

### 2026-08-18 午后：《OTA 新闻模块逐项修改建议》十项改造全部实施（随市场悬浮改造同包部署）
- **范围**: 前端转义与URL安全① / TLS 只验证⑤ / Bloomberg 合规停用② / 来源状态+真实更新时间+退出码③ / 日期修复④ / 国内分源过滤⑥ / 三级去重⑦ / 摘要证据字段⑧ / 测试扩充⑨ / 本文档去过时化⑩。改动文件：`fetch_news_副本.py`、`template_副本.html`、`news_ai_helpers_副本.py`、`daily_update_副本.sh`、`news_smoke_副本.js`（+24 安全断言）、`news_quality_tests_副本.py`（新增 60 项离线测试）、`AGENTS.md`
- **① 安全**: `escapeHtml`/`safeExternalUrl`（只放行 http(s)，javascript:/data:/相对路径降级为无链接标题）+ `rel="noopener noreferrer"`，SEC 卡片与新闻卡片共用
- **② Bloomberg**: `daily_update_副本.sh` 删除 Playwright 步骤；`PAYWALL_SOURCES` 移除 Bloomberg（公开 RSS 片段保留，basis=public_snippet）；WSJ/FT/Reuters 无公开输入渠道 → 摘要清空只留标题（headline_only）
- **③ 状态与退出码**: `fetch_status`（全局+每来源 attempted_at/last_success_at/status/item_count/error_code/filter 统计）+ `update_status` + 前端 statusLine 披露；退出码 0/2/1（1=致命不写缓存不部署）；日更脚本 `set -euo pipefail` + 每步 rc 检查 + surge 失败不打印 Done + 拒绝 NODE_TLS_REJECT_UNAUTHORIZED=0
- **④ 日期**: `parse_date` 失败→None；`published_at`/`fetched_at`/`date_status` 三字段；政府站日期优先级 span→URL tYYYYMMDD→unknown；unknown 沉底+"待确认"显示；保留期按 published_at 否则 fetched_at
- **⑤ TLS**: `_UNVERIFIED_CTX` 删除，证书错误→该源 failed（error_code=tls_error）+旧缓存兜底，不降级
- **⑥ 国内分源过滤**: `DOMESTIC_SOURCE_FILTERS`（文旅部/交通运输部/民航网各 include/exclude）+ raw/kept/rejected 统计入 fetch_status
- **⑦ 三级去重**: `_norm_url` 强化（剥跟踪参数/fragment）→ `dedupe_same_article`（归一标题+company+±3天，官方源优先）→ `group_same_events`（相似度≥0.72+≤72h，folded_into 折叠不删，related_sources 聚合）
- **⑧ 摘要状态**: `summary_status`/`summary_generated_at`；SEC 确定性摘要（元数据零网络）；无证据不编造 → 前端"来源未提供足够公开信息"占位；`summary_basis` 字段已于 2026-08-18 彻底删除（保留 `summary`/`summary_status`/`summary_generated_at`）
- **⑨ 测试**: 质量测试 60/60（A日期10/B去重9/C来源状态与回退19/D TLS6/E摘要12/F国内过滤4，全离线 fixture）；烟雾测试 41/41（17 原有+24 安全段：恶意HTML注入/javascript:URL/大小写混淆/待确认日期/partial·failed状态行/折叠跳过/空摘要占位/付费墙例外）
- **⑩ 文档**: 删固定条数/行号（改可复现命令），Bloomberg 流程移除，新增条目字段规范+状态协议+验收命令章节，踩坑 6/12 更新、21 新增
- **验收实测**: 4 个 py AST 通过 + bash -n + node --check；本地 generate 产出 dashboard.html 386,446 字节（generate 打印的 373,434 是字符数非字节数，中文 UTF-8 占 3 字节/字）；deploy/index.html 与 dashboard.html 字节一致；前后对比 127→127 条 / 空摘要 56→56 / 非法日期 0→0（数据兼容无损，SEC 同类型同名与东航旧缓存重复标题按设计保留待下次抓取时合并）；缓存**副本**干跑新管道：127→125（2 条东航同文折叠）、event_id 6 条、SEC 确定性摘要 12 条
- **遗留/注意**: ① 本次**未部署**（按任务要求不跑 surge），线上仍是 10:50 版本，下次日更自动生效；② 现有缓存的同文折叠字段在**下次抓取运行时**回填（generate 只透传缓存）；③ `news_ai_helpers_副本.py` 的启发式分类/摘要仍可用，规则见踩坑 21-⑥

### 2026-08-18 上午（~10:50）：环球旅讯分流修复 v2（标记表扩充+保留期豁免+防误清空加固）
- **问题**: 用户反馈"现在环球旅讯没有国内外分流"。排查缓存：国际区环球旅讯仅 1 条（新秀丽 08-14），国内区 22 条里混着 8+ 条明显国际新闻（Faye/Entravel/BCD/BizAway/30 Sundays/Engine/欧铁/全球最大差旅收购）——三个根因见踩坑记录 20：标记表漏拉丁公司名和国家名、国际区 7 天保留期把分流条目立即剪光、`--td-only` 保护只查总条数
- **修复**（`fetch_news_副本.py`）: ① `TD_INTL_MARKERS` 补 Faye/Entravel/BCD Travel/Amgine/30 Sundays/BizAway/Uniglobe/Options Travel/欧铁/Eurail/全球最大差旅/意大利/荷兰/西班牙/加拿大/瑞士/迪拜；`TD_DOMESTIC_MARKERS` 补 豆包/万达/复星/香港/澳门/台湾；② `prune_and_dedupe` 加来源豁免：`source==环球旅讯` 时保留期取 `max(retention, 28)`；③ `refresh_traveldaily_only` 防误清空双保险：总数与国内子集都必须≥5（途中实测触发过一次事故：首页超时只抓到快讯页 11 条国际旧闻，总数≥5 绕过旧保护把 china_industry 22 条清成 0，已从 news_cache_backups/ 自动备份恢复后再修）
- **结果**: `--td-only` 重抓后 china_industry 12 条全为真国内（华住/万达/国航/飞猪/豆包/复星等），国际区环球旅讯 12 条全为真国际（新秀丽/Entravel/欧铁/Faye/BCD/30 Sundays/BizAway/Fora 等，含 07-22 旧条目靠 28 天豁免存活）；总计 127 条（sec 12/industry 49/china 12/reg 27/company 27）。注：整源替换语义下，已滚出列表页的旧条目（璞隐 08-04/广深机场 08-03）自然退出
- **验证**: 烟雾测试 17/17；已部署，线上 content-length 383,713、surge-stamp 哈希==本地 md5（eddbd4da...）；Faye/BizAway/30 Sundays/欧铁/Fora 五条分流条目 grep 线上各 1 处

### 2026-08-18 上午（~10:20）：Skift 列表页补抓 + 白名单豁免 + 环球旅讯国内外分流
- **问题**: ① 用户对比 skift.com/news/ 发现看板缺好几条 Skift 新闻——两个根因：RSS（skift.com/feed）只给最近 10 条，且 `filter_travel_relevance` 先强排除后白名单，'war' 词把 "Saudi OTA Almosafer IPO Despite Iran War Disruption" 等 2 条行业新闻误杀（见踩坑记录 19）；② 环球旅讯的国际新闻（如新秀丽收购 Béis）此前全塞在国内 china_industry，用户要求国内外分流
- **方案**（`fetch_news_副本.py`）:
  1. 新增 `fetch_skift_newspage()`：补抓 /news/ + /news/page/2/ 列表页（c-tease 卡片，aria-label 标题+URL 路径日期），与 RSS 经 `_norm_url` 去重后并入，Skift 覆盖 12→15 条
  2. 白名单判定提前到过滤器最前，专用源（Skift/PhocusWire 等）豁免全部三层过滤
  3. 新增 `_td_is_domestic()` 分类器：`TD_DOMESTIC_MARKERS`（携程/飞猪/华住/国航/民航局/出境游等）先查、`TD_INTL_MARKERS`（Booking/万豪/达美/日本/东南亚等）后查、默认国内——国内标记优先保证"携程收购 Skyscanner"判国内；main() 路由分流，国际条目走 `tag_company_news` 后 extend 进 international.industry_news；`--td-only` 同步改为分栏替换（china_industry 整源替换 + 国际区只替换环球旅讯来源条目）
- **结果**: 总计 126 条（sec 12/industry 38/china_industry 22/regulatory 27/company_news 27）；Skift 15 条含找回的 3 条（沙特 Almosafer IPO/中东酒店建设/Google-Spirit 航司投资）；环球旅讯 27 条存量经分类器迁移=22 国内+5 国际（国际区受 7 天保留期，8-03 之前的 4 条被修剪属栏目既定策略）；全部条目 0 英文残留
- **验证**: 烟雾测试 17/17；已部署，线上 content-length 383,495、md5 a8500036...==本地；找回的 3 条标题 grep 线上产物各 1 处

### 2026-08-18 上午（~10:00）：翻译环节 agent 化 + cron 代理自动检测
- **背景**: 上午发现 shell 不继承系统代理（踩坑记录 18）→ cron 裸跑时 Google 翻译不可用，新抓条目整批英文残留。用户选择"agent 自动翻译"方案（零 API key、零注册），放弃强制配 DASHSCOPE
- **方案**:
  1. 新增 `agent_translate_副本.py`：`--export` 提取缓存中未翻译条目（标题含 2+ 连续英文字母且无 CJK / 摘要 4+ 字母且无 CJK；SEC 附件代码 EX-32.1 等豁免——管道历来不翻译）→ `pending_translations.json`；agent 填 `title_zh`（必填，须含中文）/`summary_zh`（≤200字）后 `--apply` 写回（校验→写回 title/summary 并留底 title_original/summary_original→时间戳备份到 news_cache_backups/→原子替换）
  2. cron b922a522 指令更新（用户经 AskUserQuestion 确认）：① 先 `scutil --proxy` 检测系统代理并 export（代理开着的早晨 Google 源抓取也恢复）；② 主流程跑完后 `--export`，pending>0 则 agent 自己翻译→`--apply`→重建→重新部署；③ 最终 `curl -sI -m 60` 核验
- **验证**: 临时缓存闭环测试 10/10（含 URL 斜杠归一化匹配、原题留底、备份隔离在缓存同目录、中文条目不动、纯代码标题豁免）；真实缓存 `--export` 结果 0 条待翻译
- **影响**: 翻译环节不再依赖 Google/代理/DASHSCOPE key；`DASHSCOPE_API_KEY` 仅剩"真 AI 摘要/去重"用途（可选）。残余依赖：代理没开的早晨 Google News/Bloomberg 抓取仍跳过，根治需换 newsroom RSS 源

### 2026-08-18 上午（~09:35）：带代理重跑+过滤器词边界修复
- **问题**: ① 今早 daily_update 裸跑时 Google 系（news.google.com/feeds.bloomberg.com/translate.googleapis.com）全部超时 → 13 个 Google News 源 + 2 个 Bloomberg 源跳过、7 条新 Skift 新闻保持英文（用户截图发现）；② 重跑后发现 1 条 Bloomberg 黄金行情新闻混入国际行业新闻——`'expe'` 关键词子串误命中 "Expectations"
- **修复**: ① 确认系统代理 `127.0.0.1:7892`（`scutil --proxy`），带 `https_proxy`/`http_proxy` 环境变量重跑 `fetch_news_副本.py --force`，79 条全部翻译成功；② `filter_travel_relevance` 的严格关键词与强排除两处匹配均改词边界预编译正则（`TRAVEL_KEYWORD_PATTERNS`/`TRAVEL_BLOCK_PATTERNS`），并用新过滤器清理缓存（34→33，备份 news_cache_backups/news_data_20260818_093526.json）
- **结果**: 国际行业新闻 33 条 0 条未翻译（此前 7/28 英文）；总计 117 条（sec 12/industry 33/china_industry 27/regulatory 19/company_news 26）；黄金噪音已从线上移除
- **验证**: 烟雾测试 17/17；线上 surge-stamp 哈希==本地 md5（bc5a10ce...）；grep 线上产物黄金标题 0 处、中文标题（达美诉讼/Airbnb营销引擎）各 1 处
- **遗留**: cron 裸跑仍依赖代理开启；根治需配 `DASHSCOPE_API_KEY` 或更换新闻源（见下一步建议）

### 2026-08-17 晚（~18:15）：环球旅讯抓取重写（国内行业新闻质量修复）
- **问题**: 用户反馈环球旅讯爬取质量太低。根因：通用 DOM 解析器对 traveldaily.cn（Next.js 站）水土不服——首页相对时间（"6 小时前"/"昨天"）解析错误、混入合作站外链（chinatravelnews 等）、采购/报名/开业类软文通稿也照单全收
- **方案**（用户指定：快讯+首页双入口，仍需筛选）:
  1. 新增专用抓取 `fetch_traveldaily`：**快讯页**（`/expressPage/`，条目带精确 `YYYY-MM-DD` 时间戳）+ **首页**（`newsCard` 新闻卡片，整卡原子解析，标题兜底链 h3→h2→img alt，摘要取 summary title 属性）
  2. 质量筛选 `TD_JUNK_PATTERNS`：拦截采购需求/观众登记/招聘投稿/门店开业/软文措辞（满分口碑、领跑等）/仪式通稿；相对时间由 `_td_parse_when` 统一换算（含跨年保护）
  3. 新增 `--td-only` 定向刷新模式：只重抓环球旅讯并**整源替换** china_industry（该栏目唯一来源即环球旅讯，内置 <5 条放弃保护）；URL 去重统一经 `_norm_url` 归一化（新旧缓存结尾斜杠不一致会绕过去重）
- **结果**: china_industry 7 条低质 → **24 条高质量**（2026-07-22..08-17），如 Expedia 收购 Layla、新秀丽收购 Béis、Faye C 轮融资、飞猪帮帮上线、国航会员权益等；旧缓存自动备份至 news_cache_backups/
- **验证**: 重建+部署，烟雾测试 17/17；线上 content-length 与 surge-stamp 哈希==本地 md5（fa95c692...）；新标题 grep 确认已嵌入、chinatravelnews 外链 0 条

### 2026-08-17 傍晚（18:00）：移动端载荷重构 v2（图表不显示/加载慢的彻底修复）
- **问题**: 上一版把 ECharts 内联后产物 2.09MB 单体文件，慢网络下整页要下完才执行图表代码 → 用户反馈"还是没有图表、加载很慢"
- **方案**（载荷拆分 + 缓存友好）:
  1. **ECharts 改同源独立文件**: head 加 `<link rel="preload" href="echarts.min.js" as="script">`，应用脚本前 `<script src="echarts.min.js">`。内容不随每日数据更新变化 → 浏览器可长期缓存，首屏 HTML 减 1MB
  2. **ST 数据懒加载**: 模板 `ST_DATA=null`，`initSTTab()` 打开 ST tab 时动态注入 `<script src="st_data.js">`（onload 渲染/onerror 提示并允许重开 tab 重试）；resize 守卫仅在 `ST_DATA.by_country` 就绪时执行
  3. **JSON 紧凑化**: RAW/ANN/MKT/ST 一律 `json.dumps(..., separators=(',',':'))`
- **generate_副本.py 改动**: `<!--__ECHARTS__-->`→`<script src="echarts.min.js">`（缺失才回退CDN）、`<!--__ECHARTS_PRELOAD__-->`→preload 链接、ST 数据不再内联而是写出 `st_data.js`（`window.ST_DATA=…`）、deploy 复制环节新增 echarts.min.js + st_data.js 两个资产
- **踩坑（已修复，见记录15）**: 懒加载 loading 提示用 innerHTML 覆盖 stCountryPanel，销毁静态图表容器导致 onload 后渲染 TypeError、图表不出。修复为先备份后恢复
- **效果**: 首屏 HTML 364,903 B（gzip ~107KB）；echarts.min.js 1,024,740 B（gzip ~325KB，缓存）；st_data.js 565,702 B（gzip ~166KB，按需）
- **验证**: 烟雾测试 17/17；headless 桌面/移动端/ST tab 三组截图正常（ST 懒加载 canvas 13→20、loading 文案 0）；已部署，三个文件线上 content-length 与 surge-stamp 哈希全部与本地一致

### 2026-08-17 傍晚：ECharts 内联（移动端加载慢/图表不显示修复，已被 v2 取代）
- **问题**: 用户反馈移动端加载很慢、ECharts 图表加载不出来。根因：`template_副本.html` 在 `<head>` 中以渲染阻塞方式引用 `cdnjs.cloudflare.com/ajax/libs/echarts/5.4.3/echarts.min.js`，国内网络访问 Cloudflare CDN 慢且时断时续 → HTML 解析被卡住、`echarts` 全局变量缺失，所有图表无法初始化
- **修复**: ① 下载 echarts 5.4.3 min 版到项目根 `echarts.min.js`（1,024,740 B，已校验版本号且不含 `</script>` 序列）；② 模板 head 移除 CDN 标签，应用脚本前新增 `<!--__ECHARTS__-->` 占位符；③ `generate_副本.py` 构建时将本地库内联为 `<script>` 块（本地文件缺失时回退 CDN 标签并打印 WARNING）；④ `news_smoke_副本.js` 改为按 `var RAW =` 特征定位应用脚本块（内联后页面有两个 inline script，取第一个的正则会误中 echarts）
- **遗留问题**: 内联使产物膨胀到 2,089,876 B 单体文件，慢网络下仍需整页下完才能执行图表 → 用户仍反馈慢/无图表，故被上面的 v2 载荷重构取代（内联方案仅保留其"移除外部 CDN 依赖"的正确部分）

### 2026-08-17 下午晚些：响应式布局（超宽屏适配 + 移动端修复）
- **需求**: 用户在 2526px 超宽屏上看到 1600px 容器两侧大片空白；要求加宽页面并保证移动端自适应
- **改动**（`template_副本.html` 纯 CSS + 2 处小 JS）:
  1. 新增 `@media(min-width:1600px)`: `.dashboard`/`.tab-bar` max-width 1600→2200px
  2. 新增 `@media(min-width:1920px)`: 主网格 2 列→3 列（`repeat(3,1fr)`），`.chart-box` 高度 380→400px，`.chart-pair .chart-box` 340px
  3. `.news-panel` 布局: ≥1024px 时 `grid-column:1/-1` + 内部 2 列网格（修复了此前新闻面板只占左列、右半空白的问题）；≥1920px 内部 3 列（SEC/公司新闻/行业新闻正好三卡并排）
  4. **JS 配套**: `bindNewsTabs` 中面板切换 `display:"block"`→`""`（否则内联样式会压掉 CSS 网格）；`stGetChartHeight` 增加 ≥1920 档（480/380px）
  5. **移动端 ≤768px**: `.header` 改 static（标题在窄屏折行导致高度超 52px，tab-bar sticky 被遮挡）；`.tab-bar` top:0 + 横向滚动（6 个 tab 窄屏溢出）；市场 tab 事件图例 sticky top 用 `!important` 调到 42px；body padding 12px
- **注意**: has-btn/section-header/chart-pair/info-card 的 `grid-column:1/-1` 在 3 列网格下自动横跨，无需改；`.st-dashboard`(1fr !important) 与 `#marketDashboard>*`(1/-1) 不受 3 列影响
- **验证**: 烟雾测试 17/17；headless 截图 2560px（新闻三卡并排/Quarterly 3 列网格）+ 390px（tab 横滚/卡片堆叠）均正常；已部署，产物 1,065,255 B


### 2026-08-17 傍晚：遗留噪音清理与合并回流修复
- **问题**: 用户发现国际行业新闻混入 2 条无关条目（胜科印度子公司 IPO、Stripe 收购 OpenRouter，均 Bloomberg 综合源）。验证确认：两条均无法通过现行 `filter_travel_relevance`，属过滤功能上线（13:30）前的 12:55 批次遗留，经 `merge_with_cache` 回流存活
- **代码修复**（`fetch_news_副本.py`）: ① main() 在 merge_with_cache 之后对国际行业新闻重跑相关性过滤（Legacy Cleanup）；② `filter_travel_relevance` 同时检查 `title_original`/`summary_original`，避免已翻译条目被误杀
- **数据清理**: 27→25 条（剔除 2 条噪音，6 条已翻译合法综合源新闻全部保留），重建+部署，烟雾测试 17/17

### 2026-08-17 下午：新闻管道三大改进
- **严格行业相关性过滤**: 新增 `filter_travel_relevance()`，三层过滤（强排除+白名单+关键词）。移除 Bloomberg 等综合源的 48 条无关新闻（铜价/债券/油价等），27 条全为 OTA/旅游行业相关
- **全源翻译**: 移除 `translate_news_items` 中的源白名单限制，所有含英文的条目自动翻译。从 ~5-6 条英文残留 → 27/27 条 100% 中文
- **缓存版本备份系统**: 新增 `news_cache_backups/` 目录，保存前自动备份（3版本轮转），主缓存损坏时自动从备份恢复，原子写入防并发损坏
- **前端精简**: 移除"★重点"和"🔒付费内容"标签渲染（CSS class 保留供潜在样式使用）

### 2026-08-17 上午：图表优化
- 数据精度 1→2 位小数
- `symbol: "none"` 移除数据点标记
- `smooth: true` 保持曲线平滑

### 2026-08-17 凌晨：新闻管道重建
- 多源抓取（SEC EDGAR + Skift + GNews + 文旅部/交通部/港交所）
- AI 增强模块（摘要/去重/翻译/分类，无key时启发式兜底）
- `--fast` 快速模式（2h缓存）
- `news_smoke_副本.js` 烟雾测试

### 2026-08-14：布局与功能改进
- 全宽单列布局（CSS Grid `1fr`）
- 图例横向滚动（`type: 'scroll'`）
- 按App划分：仅保留地区对比视图
- 图表单位动态切换

---

## 部署地址
**https://bkng-expe-abnb-1q26.surge.sh/**

## 下一步建议

### 高优先级
- ~~部署十项改造版~~ ✅ 已完成（2026-08-18 午后与市场悬浮改造同包手动部署，curl 核验哈希一致）
- **配置 AI API Key**（优先级已降，可选）: 翻译已由 cron agent 兜底（2026-08-18），`DASHSCOPE_API_KEY` 仅用于把 `news_ai_helpers_副本.py` 的启发式摘要/去重升级为真 AI
- **更换 Google 新闻源**（彻底摆脱代理依赖）: 把 Google News RSS 换成各公司 newsroom RSS（BKNG/EXPE/ABNB 官网 IR 页）+ Skift/PhocusWire 原生 RSS，代理没开的早晨也不再漏源

### 中优先级
- **删除废弃文件**（需用户确认）:
  - `_deploy/` 目录（旧部署目录）
  - `index_副本.html` (304KB 旧模板)
  - `earnings_demo_副本.html` / `earnings_ui_playground_副本.html`
  - `legend_demo_副本.html` / `legend_playground_副本.html`
  - `CNAME_副本`
  - `BKNG-EXPE-ABNB业绩20260804_副本.xlsx` (4.6MB 旧数据)
  - `daily_update_副本.log` (590B 旧日志)
  - `fetch_bloomberg_副本.py`（Playwright 爬虫已停用，2026-08-18 合规改造后无消费方；删除前再确认）

### 低优先级
- 新增 ST 地区或指标 → 修改 `extract_st_data_副本.py` 中的 `REGION_DATE_COL_MAU`/`REGION_DATE_COL_DAU`
- 考虑将 `daily_update_副本.sh` 改为 cron 定时任务（已完成 QoderWork 接入）

---

## 发布状态矩阵

| 事实面 | 状态 | 说明 |
|--------|------|------|
| 代码 | ✅ verified-current | 确定性筛选管道已在代码中确认（AST+quality 70/70+news_smoke 43/43+market_smoke 27/27） |
| 运行态 | ✅ live-verified | https://bkng-expe-abnb-1q26.surge.sh/ 2026-08-18 晚间部署筛选管道版；content-length 389,212、surge-stamp 哈希==本地 md5（4a926722…），curl 核验通过 |
| 文档 | ✅ changed-and-verified | AGENTS.md 与当前代码一致（2026-08-18 晚间筛选管道章节/字段规范/评分模型/踩坑 23-24 更新） |
| 规则 | ✅ verified-current | 无矛盾规则文件 |
| 记忆 | ✅ managed | QoderWork agent 记忆已登记关键事实（HKEX接口/域名更替/cron/部署命令），可通过 memory 工具维护 |
| 工作区 | ⚠️ pending-cleanup | 7+ 个废弃文件待用户确认删除（含已停用的 fetch_bloomberg_副本.py） |