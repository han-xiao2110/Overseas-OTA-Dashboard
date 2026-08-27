#!/usr/bin/env python3
"""
fetch_news_副本.py - 自动抓取新闻和 SEC 文件
分为两类: 国外 (daily) 和 国内 (weekly)

输出: news_data_副本.json
"""

import json, os, sys, time, datetime, re, shutil
import html as html_lib
import html
import unicodedata
import difflib
import ssl
import xml.etree.ElementTree as ET
import urllib.request
import urllib.error
import urllib.parse
from urllib.parse import urlparse, urljoin
import hashlib

# AI 模块已禁用 — 全流程纯程序化（RSS + deep-translator + 启发式摘要/分类/去重）
AI_MODULE_AVAILABLE = False

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
OUTPUT = os.path.join(SCRIPT_DIR, "news_data_副本.json")
CACHE_MAX_AGE_HOURS = 12
CACHE_MAX_AGE_FAST_HOURS = 2


def _build_ssl_context():
    """Build a VERIFIED SSL context using certifi's CA bundle (macOS Python
    doesn't auto-load the system trust store). There is NO unverified fallback:
    certificate failures mark the source as failed and cached data is kept."""
    try:
        import certifi
        return ssl.create_default_context(cafile=certifi.where())
    except Exception:
        return ssl.create_default_context()


SSL_CONTEXT = _build_ssl_context()

# TLS 安全策略（2026-08-18）: 不再提供任何无证书校验的降级路径。
# 证书校验失败的来源按"来源失败"处理（error_code=tls_error，保留旧缓存数据），
# 绝不静默降级为 CERT_NONE。
_UNVERIFIED_CTX = None  # 兼容占位: 任何代码不得再使用无验证上下文


def urlopen_safe(req, timeout=15):
    """urlopen with certificate verification (certifi CA). SSL/certificate
    errors propagate to the caller — they are recorded as a source failure
    (tls_error) and the previous cache is kept, never bypassed silently."""
    return urllib.request.urlopen(req, timeout=timeout, context=SSL_CONTEXT)

# ── 配置 ──

COMPANIES = {
    "BKNG": {"cik": "0001075531", "name": "Booking Holdings Inc.", "ticker": "BKNG"},
    "EXPE": {"cik": "0001324424", "name": "Expedia Group, Inc.", "ticker": "EXPE"},
    "ABNB": {"cik": "0001559720", "name": "Airbnb, Inc.", "ticker": "ABNB"},
}

SEC_FILING_TYPES = {
    "10-Q": "季度报告 (10-Q)",
    "10-K": "年度报告 (10-K)",
    "8-K": "重大事件 (8-K)",
    "4": "董事/高管交易 (Form 4)",
    "144": "证券出售登记 (Rule 144)",
    "SC 13D": "大股东变动 (13D)",
    "SC 13G": "机构持仓 (13G)",
    "DEFA14A": "代理声明 (Proxy)",
    "S-1": "注册声明 (S-1)",
    "4/A": "Form 4 修订",
}

# International RSS feeds
INTL_RSS_FEEDS = [
    # Direct RSS (work without auth)
    {"name": "Skift", "url": "https://skift.com/feed/", "category": "industry_news", "translate": True},
    {"name": "Bloomberg Markets", "url": "https://feeds.bloomberg.com/markets/news.rss", "category": "industry_news", "translate": True},
    {"name": "Bloomberg Technology", "url": "https://feeds.bloomberg.com/technology/news.rss", "category": "industry_news", "translate": True},
    # Google News RSS - OTA/Travel companies
    {"name": "PhocusWire", "url": "https://news.google.com/rss/search?q=site:phocuswire.com&hl=en-US&gl=US&ceid=US:en", "category": "industry_news", "translate": True, "max_items": 40},
    {"name": "Travel Weekly", "url": "https://news.google.com/rss/search?q=site:travelweekly.com&hl=en-US&gl=US&ceid=US:en", "category": "industry_news", "translate": True},
    {"name": "Skyscanner", "url": "https://news.google.com/rss/search?q=skyscanner+travel&hl=en-US&gl=US&ceid=US:en", "category": "industry_news", "translate": True},
    {"name": "Klook", "url": "https://news.google.com/rss/search?q=klook+travel+ota&hl=en-US&gl=US&ceid=US:en", "category": "industry_news", "translate": True},
    {"name": "MakeMyTrip", "url": "https://news.google.com/rss/search?q=makemytrip+travel&hl=en-US&gl=US&ceid=US:en", "category": "industry_news", "translate": True},
    {"name": "Traveloka", "url": "https://news.google.com/rss/search?q=traveloka+travel&hl=en-US&gl=US&ceid=US:en", "category": "industry_news", "translate": True},
    {"name": "Agoda", "url": "https://news.google.com/rss/search?q=agoda+travel+hotel&hl=en-US&gl=US&ceid=US:en", "category": "industry_news", "translate": True},
    {"name": "Trip.com", "url": "https://news.google.com/rss/search?q=trip.com+travel&hl=en-US&gl=US&ceid=US:en", "category": "industry_news", "translate": True},
    {"name": "Booking.com", "url": "https://news.google.com/rss/search?q=booking.com+travel+hotel&hl=en-US&gl=US&ceid=US:en", "category": "industry_news", "translate": True},
    {"name": "Expedia", "url": "https://news.google.com/rss/search?q=expedia+travel&hl=en-US&gl=US&ceid=US:en", "category": "industry_news", "translate": True},
    {"name": "Airbnb", "url": "https://news.google.com/rss/search?q=airbnb+travel+vacation+rental&hl=en-US&gl=US&ceid=US:en", "category": "industry_news", "translate": True},
    {"name": "Tripadvisor", "url": "https://news.google.com/rss/search?q=tripadvisor+travel&hl=en-US&gl=US&ceid=US:en", "category": "industry_news", "translate": True},
    # Google News RSS - Bloomberg (travel/mobility sections)
    {"name": "Bloomberg Travel (GN)", "url": "https://news.google.com/rss/search?q=bloomberg+travel+hotel+airline&hl=en-US&gl=US&ceid=US:en", "category": "industry_news", "translate": True},
    {"name": "Bloomberg Mobility (GN)", "url": "https://news.google.com/rss/search?q=bloomberg+mobility+autonomous+robotaxi&hl=en-US&gl=US&ceid=US:en", "category": "industry_news", "translate": True},
]

# ── 官方 IR 新闻稿源（2026-08-20 改造: 用 Google News RSS 替代 JS 渲染页面）──
# Q4 Inc. IR 页面通过 JavaScript 动态渲染, 简单 HTTP 请求拿不到新闻列表。
# 改用 Google News RSS 抓取公司官方新闻稿。
IR_SOURCES = [
    {"entity_id": "BKNG", "name": "Booking Holdings IR",
     "url": "https://news.google.com/rss/search?q=site:bookingholdings.com+press+release+OR+news&hl=en-US&gl=US&ceid=US:en",
     "news_selector": "google_news"},
    {"entity_id": "EXPE", "name": "Expedia Group IR",
     "url": "https://news.google.com/rss/search?q=site:expediagroup.com+press+release+OR+news&hl=en-US&gl=US&ceid=US:en",
     "news_selector": "google_news"},
    {"entity_id": "ABNB", "name": "Airbnb IR",
     "url": "https://news.google.com/rss/search?q=site:investors.airbnb.com+press+release&hl=en-US&gl=US&ceid=US:en",
     "news_selector": "google_news"},
]

# Google News RSS items should have source overridden to original source
GOOGLE_NEWS_SOURCES = {"PhocusWire", "Travel Weekly", "Skyscanner", "Klook", "MakeMyTrip",
                        "Traveloka", "Agoda", "Trip.com", "Booking.com", "Expedia", "Airbnb", "Tripadvisor",
                        "Bloomberg Travel (GN)", "Bloomberg Mobility (GN)"}

# ── 翻译配置 ──
TRANSLATE_SOURCES = {"Skift", "PhocusWire", "Bloomberg Markets", "Bloomberg Technology", "Bloomberg",
                     "Travel Weekly", "Skyscanner", "Klook", "MakeMyTrip",
                     "Traveloka", "Agoda", "Trip.com", "Booking.com", "Expedia", "Airbnb", "Tripadvisor",
                     "WebInTravel", "Travel Pulse", "Hospitality Net", "Breaking Travel News",
                     "TTG Asia", "Simply Wall St", "Seeking Alpha", "Yahoo Finance", "CNBC"}
TRANSLATE_CACHE = {}  # 内存缓存，避免重复翻译

_TRANSLATE_FAILS = 0  # 连续失败计数，超过阈值临时熔断避免限流


def _translate_chunk(text):
    """Translate a single chunk (one sentence) using deep-translator.
    Returns None on failure. Applies a circuit-breaker after too many
    consecutive failures (Google 429 throttle) to avoid waiting forever."""
    global _TRANSLATE_FAILS
    if not text or not text.strip():
        return None
    # Circuit breaker: 连续失败超过 8 次后跳过剩余翻译（限流期间）
    if _TRANSLATE_FAILS >= 8:
        return None
    try:
        from deep_translator import GoogleTranslator
    except ImportError:
        return None
    # GoogleTranslator free endpoint fails on long multi-clause text.
    # Strategy: try 'en' source first; on TranslationNotFound, retry 'auto'.
    # 每种 source 最多重试 1 次，合计最多 4 次 HTTP 请求，防卡住。
    sources = ('en', 'auto')
    for src in sources:
        for attempt in range(2):
            try:
                r = GoogleTranslator(source=src, target='zh-CN').translate(text)
                if r and r != text and 'Server Error' not in r and "That's an error" not in r:
                    _TRANSLATE_FAILS = 0
                    return r
                # Server error：尝试下一个 source
                break
            except Exception:
                time.sleep(0.3)
                continue
    _TRANSLATE_FAILS += 1
    return None


def translate_text(text, max_chars=500):
    """Translate English text to Chinese using deep-translator (Google Translate free API).
    Splits text by sentence and translates each chunk separately to avoid the
    'No translation was found' failure on long multi-clause inputs.
    Falls back to original text on total failure."""
    if not text or not text.strip():
        return text
    if not re.search(r'[a-zA-Z]{2}', text):
        return text
    cache_key = hashlib.md5(text.encode()).hexdigest()
    if cache_key in TRANSLATE_CACHE:
        return TRANSLATE_CACHE[cache_key]

    snippet = text[:max_chars]
    # Split by sentence, preserve trailing punctuation; translate each chunk.
    parts = re.split(r'(?<=[.!?])\s+', snippet)
    parts = [p.strip() for p in parts if p.strip()]
    if not parts:
        parts = [snippet]

    out_chunks = []
    any_success = False
    for chunk in parts:
        r = _translate_chunk(chunk)
        if r is not None:
            out_chunks.append(r)
            any_success = True
            time.sleep(0.25)  # gentle pacing to avoid 500 errors
        else:
            out_chunks.append(chunk)  # keep original on per-chunk failure
            time.sleep(0.15)

    translated = ' '.join(out_chunks) if any_success else text
    TRANSLATE_CACHE[cache_key] = translated
    return translated

# ── 筛选配置 ──

# 旅游/OTA 严格白名单关键词 (必须命中至少一个才保留)
TRAVEL_CORE_KEYWORDS = [
    # OTA 核心
    'ota', 'online travel', 'travel tech', 'travel technology',
    'skift', 'phocuswright', 'phocuswire',
    # 指定公司名单
    'airbnb', 'agoda', 'booking.com', 'expedia', 'skyscanner', 'trip.com',
    'klook', 'makemytrip', 'traveloka', 'tripadvisor',
    # 上市公司/ticker
    'booking holdings', 'bkng', 'expedia group', 'expe', 'abnb',
    # 酒店/住宿
    'hotel', 'hotels', 'lodging', 'hospitality',
    'vacation rental', 'short-term rental', 'vacation home',
    'marriott', 'hilton', 'hyatt', 'ihg', 'wyndham', 'accor',
    'bnb', 'resort', 'inn', 'motel',
    # 航空/交通
    'airline', 'airlines', 'airport', 'aviation', 'flight',
    'delta', 'united', 'american airlines', 'jetblue', 'southwest',
    'ryanair', 'easyjet', 'lufthansa', 'air france',
    # 旅游宏观
    'tourism', 'tourist', 'travel', 'traveling', 'trip', 'vacation',
    'overseas travel', 'international travel', 'cross-border travel',
    'travel demand', 'travel spending', 'travel recovery',
    # 旅游行业指标
    'gross bookings', 'room nights', 'adr', 'revpar', 'take rate',
    'occupancy', 'occupancy rate', 'hotel revenue',
    # 旅游交通/出行
    'uber', 'lyft', 'didi', 'grab',
    # 中国旅游
    'china tourism', 'china travel', '出境游', '入境游', '国内旅游',
]

# 必须排除的低价值内容
BLOCK_KEYWORDS = [
    'giveaway', 'sweepstakes', 'win a', 'contest', 'prize',
    'best places', 'top 10', 'bucket list', 'instagrammable',
    'fashion', 'beauty', 'foodie', 'recipe', 'diy', 'home decor',
    'sports', 'fitness', 'health tips', 'celebrity', 'gossip',
    'crude oil', 'fuel price', 'oil market', 'oil price',
    'bond market', 'bond sale', 'sovereign debt',
    'drone', 'drones', 'energy trader',
]

NEWS_KEEP_MIN_SCORE = 0.3  # 基础筛选分
NEWS_MAX_PER_SOURCE = 10  # 每个来源最多保留条数

# Domestic China - web sources (no reliable RSS, use HTML scraping)
DOMESTIC_WEB_SOURCES = [
    {
        "name": "环球旅讯",
        "url": "https://www.traveldaily.cn/",
        "category": "china_industry",
        # 专用解析：快讯页(expressPage)+首页新闻卡片，带质量筛选（见 fetch_traveldaily）
        "news_selector": "traveldaily",
        "express_url": "https://www.traveldaily.cn/expressPage/",
    },
    {
        "name": "文旅部",
        "url": "https://www.mct.gov.cn/whzx/whyw/",
        "category": "regulatory",
        "news_selector": "gov_list",
    },
    {
        "name": "交通运输部",
        "url": "https://www.mot.gov.cn/xinwen/jiaotongyaowen/",
        "category": "regulatory",
        "news_selector": "gov_list",
    },
    {
        "name": "中国民航网",
        "url": "http://www.caacnews.com.cn/",
        "category": "company_news",
        "news_selector": "caac",
    },
    {
        "name": "披露易 (港交所)",
        "url": "https://www1.hkexnews.hk/search/titlesearch.xhtml",
        "category": "regulatory",
        "news_selector": "hkex",
        # 中国东航 H股 (00670) 内部stockId，经 prefix.do 查询确认
        "stock_id": "1558",
        "stock_name": "中国东航",
    },
]

# 国内来源分源过滤规则（改造项⑥, 2026-08-18）
# 各源独立 include/exclude; 命中 exclude 或（定义了 include 时）未命中 include → 拒绝并计数。
# None = 该源已有专用质量筛选（环球旅讯 TD_JUNK_PATTERNS）或内容本身即目标（披露易公告）。
DOMESTIC_SOURCE_FILTERS = {
    "文旅部": {
        "include": [
            r"旅游|旅行社|导游|入境游|出境游|国内游|酒店|住宿|景区|度假|游客|旅游市场|文旅消费|旅游消费|假日|旅游数据|旅游统计|市场数据|游客量|旅游收入|在线旅游|签证|消费政策",
        ],
        "exclude": [
            r"人事任免", r"任前公示", r"遴选", r"资格审查", r"招聘", r"笔试", r"面试",
            r"招标", r"采购公告", r"询价", r"成交公告", r"单一来源",
            r"舞台艺术|演出|展演|美术|博物馆|非遗|文化馆|图书馆|戏曲|音乐会|文艺|艺术作品|内部会议",
        ],
    },
    "交通运输部": {
        # 仅保留与旅客出行直接相关的数据/政策/监管文件
        # 排除宣传稿（暑运繁忙/热力十足/流动的XX/圆满完成/顺利进行）
        "include": [
            r"民航|航空|机场|航班|航线|旅客|客运|客流|春运|暑运|黄金周|节假日|自驾|城际|高铁|铁路|出行|网约车|出租车|道路客运|票价|退改签|退改|吞吐量",
        ],
        "exclude": [
            r"招标公告", r"采购", r"询价", r"成交公告", r"人事", r"任免", r"任前公示",
            r"意见征集", r"征求意见", r"听证", r"招聘", r"遴选",
            r"货运|快递|邮政|大宗散货|集装箱|渔船|危险源|危化|中欧班列|卸船机|海事执法|物流园",
            r"道路施工|公路建设|旅游公路|项目建设|港口|码头",
            # 宣传稿/活动稿（2026-08-18 收紧: 用户要求"普通政府新闻、工程宣传不得进入"）
            r"热力十足|流动的.{0,6}|圆满完成|顺利进行|成效显著|展现.{0,6}风采|谱写.{0,6}篇章|助力.{0,6}发展|服务.{0,6}升级|保障.{0,6}有力",
        ],
    },
    "中国民航网": {
        # 民航网门户混有大量非航空内容, 只保留航空出行相关
        "include": [
            r"东航|东方航空|国航|南航|航空公司|机票|客票|航班|航线|机场|旅客|客运|OTA|在线旅游|航司|客座率|运力|退改签|值机|行李|会员",
        ],
        "exclude": [
            r"招标", r"采购", r"招聘", r"培训通知", r"征文", r"摄影大赛", r"答题",
            r"篮球|集体婚礼|人物故事|劳模|高温坚守|防汛|救援队",
        ],
    },
    "环球旅讯": {
        "exclude": [
            r"自驾.*实测|实测完整流程|保级升卡指南|飞行结束后还能留下什么|怎么玩|打卡攻略|旅行攻略",
        ],
    },
    "36氪": {
        # 36氪是综合科技媒体, 只保留旅游/出行/OTA/酒店/航空相关
        # include-only: 不含旅游词的标题自动被"include未命中"拒绝, 无需 exclude
        "include": [
            r"旅游|旅行|OTA|在线旅游|酒店|住宿|民宿|机票|航班|航空|出行|差旅|度假|景区|签证|文旅|客座率|运力|退改签",
            r"携程|同程|飞猪|美团|去哪儿|途家|华住|锦江|首旅|东航|国航|南航",
            r"Booking|Expedia|Airbnb|Trip\.com|Tripadvisor|Agoda|Klook|MakeMyTrip|Skyscanner|Traveloka|Vrbo",
            r"Marriott|Hilton|Hyatt|Accor|IHG|万豪|希尔顿|凯悦|雅高|洲际",
            r"Delta|United|American Airlines|Lufthansa|Emirates|达美|美联航|美国航空|汉莎|阿联酋航空",
        ],
    },
    "披露易 (港交所)": None,  # 公告检索结果本身即目标内容
}

# 分源过滤统计: name -> {raw, kept, rejected, reasons{pattern: count}}
DOMESTIC_FILTER_STATS = {}


def _domestic_filter_decision(name, item):
    """返回 (是否保留, 拒绝原因)，供新抓取和旧缓存使用同一套规则。"""
    rule = DOMESTIC_SOURCE_FILTERS.get(name)
    if not rule:
        return True, None
    text = f"{item.get('title', '')} {item.get('summary', '')}"
    for pattern in (rule.get("exclude") or []):
        if re.search(pattern, text):
            return False, pattern
    includes = rule.get("include") or []
    if includes and not any(re.search(pattern, text) for pattern in includes):
        return False, "include未命中"
    return True, None


def filter_domestic_items(name, items, record_stats=True):
    """按分源规则过滤国内条目, 记录 raw/kept/rejected 与拒绝原因统计。

    统计最终并入 FETCH_STATUS["sources"][name]["filter"]，供诊断与测试断言。
    """
    stats = DOMESTIC_FILTER_STATS.setdefault(
        name, {"raw": 0, "kept": 0, "rejected": 0, "reasons": {}}) if record_stats else None
    kept = []
    for it in items:
        accepted, reason = _domestic_filter_decision(name, it)
        if stats is not None:
            stats["raw"] += 1
        if not accepted:
            if stats is not None:
                stats["rejected"] += 1
                stats["reasons"][reason] = stats["reasons"].get(reason, 0) + 1
            continue
        if stats is not None:
            stats["kept"] += 1
        kept.append(it)
    if stats is not None and stats["rejected"]:
        print(f"    [{name}] filter: {stats['raw']} raw → {stats['kept']} kept, "
              f"{stats['rejected']} rejected {stats['reasons']}")
    return kept


def refilter_cached_domestic(news_data):
    """缓存合并后再次过滤，避免旧缓存绕过新规则。"""
    removed = 0
    for cat, items in (news_data.get("domestic") or {}).items():
        if not isinstance(items, list):
            continue
        clean = []
        for item in items:
            src = str(item.get("source", "") or "")
            rule_name = next((name for name in DOMESTIC_SOURCE_FILTERS if src.startswith(name)), None)
            if rule_name and not _domestic_filter_decision(rule_name, item)[0]:
                removed += 1
                continue
            clean.append(item)
        news_data["domestic"][cat] = clean
    intl = (news_data.get("international") or {}).get("industry_news") or []
    clean_intl = []
    for item in intl:
        if str(item.get("source", "") or "").startswith("环球旅讯") \
                and not _domestic_filter_decision("环球旅讯", item)[0]:
            removed += 1
            continue
        clean_intl.append(item)
    news_data["international"]["industry_news"] = clean_intl
    if removed:
        print(f"  [Domestic legacy cleanup] Removed {removed} cached low-relevance items")
    return news_data

# 国内公司新闻 RSS（Google News 中文源）
CN_COMPANY_FEEDS = [
    {
        "name": "中国东航",
        "url": "https://news.google.com/rss/search?q=%E4%B8%9C%E8%88%AA+OR+%E4%B8%9C%E6%96%B9%E8%88%AA%E7%A9%BA+when:14d&hl=zh-CN&gl=CN&ceid=CN:zh-Hans",
        "category": "company_news",
        "company": "中国东航",
    },
    # 36氪快讯（2026-08-18 新增: 国内行业新闻源, 通过 Google News RSS 抓取 36kr.com 内容）
    # 36氪是 SPA 无公开 RSS, 借 Google News 索引获取最新快讯
    {
        "name": "36氪",
        "url": "https://news.google.com/rss/search?q=site:36kr.com+when:7d&hl=zh-CN&gl=CN&ceid=CN:zh-Hans",
        "category": "china_industry",
    },
]


# ── HTTP 请求工具 ──

# 记录连接超时/拒绝的主机，本次运行内直接跳过（避免每个 feed 干等超时）
UNREACHABLE_HOSTS = set()


def _host_of(url):
    try:
        return urlparse(url).netloc
    except Exception:
        return ""


def _is_connect_failure(e):
    """连接超时/拒绝/DNS失败 → 视为主机不可达。"""
    reason = getattr(e, 'reason', None)
    txt = f"{type(e).__name__} {e} {reason}".lower()
    return any(k in txt for k in ('timed out', 'timeout', 'refused', 'unreachable',
                                  'name or service not known', 'nodename nor servname',
                                  'getaddrinfo', 'network is unreachable'))


# ── 来源状态追踪（2026-08-18, 改造项④）──
# FETCH_STATUS 随每次抓取运行构建, 最终写入缓存顶层 fetch_status 字段:
#   attempted_at / last_success_at / status(success|partial|failed)
#   sources{名称: {status, item_count, last_success_at, attempted_at, error_code}}
# error_code 取值: tls_error / unreachable / http_N / fetch_failed
FETCH_STATUS = {
    "attempted_at": None,
    "last_success_at": None,
    "status": None,
    "sources": {},
}


def _now_iso():
    return datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def _classify_request_error(e):
    """把请求异常映射为稳定 error_code。"""
    if isinstance(e, urllib.error.HTTPError):
        return f"http_{e.code}"
    if isinstance(e, ssl.SSLError) or isinstance(getattr(e, 'reason', None), ssl.SSLError):
        return "tls_error"
    txt = f"{type(e).__name__} {e} {getattr(e, 'reason', '')}".upper()
    if 'CERTIFICATE' in txt or 'SSL' in txt:
        return "tls_error"
    if _is_connect_failure(e):
        return "unreachable"
    return "fetch_failed"


def mark_source(name, status, item_count=None, error_code=None):
    """记录单个来源的本次抓取状态; success 时刷新 last_success_at 并清除 error_code。

    失败记录保留旧 last_success_at（不覆盖）→ 前端可显示"上次成功于何时"。
    """
    if not name:
        return None
    now = _now_iso()
    rec = FETCH_STATUS["sources"].setdefault(name, {})
    rec["status"] = status
    rec["attempted_at"] = now
    if status == "success":
        rec["last_success_at"] = now
        rec.pop("error_code", None)
    elif error_code:
        rec["error_code"] = error_code
    if item_count is not None:
        rec["item_count"] = item_count
    return rec


def seed_fetch_status_from_cache(cached_data):
    """运行开始时从旧缓存继承 last_success_at: 本轮未尝试的来源标记 status=cached。

    避免一次失败就把"上次成功时间"清空; overall_status 只统计本轮尝试过的来源。
    """
    old = (cached_data or {}).get("fetch_status") or {}
    if old.get("last_success_at"):
        FETCH_STATUS["last_success_at"] = old["last_success_at"]
    for name, rec in (old.get("sources") or {}).items():
        if name not in FETCH_STATUS["sources"]:
            FETCH_STATUS["sources"][name] = {
                "status": "cached",
                "last_success_at": rec.get("last_success_at"),
                "item_count": rec.get("item_count"),
            }


def overall_status():
    """汇总本轮抓取状态: 无尝试→None; 全部失败→failed; 有失败→partial; 否则 success。"""
    attempted = [r for r in FETCH_STATUS["sources"].values() if r.get("attempted_at")]
    if not attempted:
        return None
    statuses = [r.get("status") for r in attempted]
    if statuses and all(s == "failed" for s in statuses):
        return "failed"
    if any(s != "success" for s in statuses):
        return "partial"
    return "success"


def safe_request(url, timeout=15, retries=2, source=None):
    host = _host_of(url)
    if host and host in UNREACHABLE_HOSTS:
        print(f"  Skip unreachable host: {host}")
        if source:
            mark_source(source, "failed", error_code="unreachable")
        return None

    headers = {
        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.9,zh-CN;q=0.8",
    }

    last_err_code = None
    for attempt in range(retries):
        try:
            req = urllib.request.Request(url, headers=headers)
            with urlopen_safe(req, timeout=timeout) as resp:
                content_type = resp.headers.get('Content-Type', '')
                data = resp.read().decode('utf-8', errors='replace')

                if 'json' in content_type or '/submissions/' in url or '/search-index' in url:
                    try:
                        return json.loads(data)
                    except json.JSONDecodeError:
                        pass
                return data
        except urllib.error.HTTPError as e:
            last_err_code = _classify_request_error(e)
            if e.code == 429:
                wait = (attempt + 1) * 5
                print(f"  Rate limited (429), waiting {wait}s...")
                time.sleep(wait)
                continue
            elif e.code == 404:
                print(f"  Not found (404): {url}")
                if source:
                    mark_source(source, "failed", error_code=last_err_code)
                return None
            else:
                print(f"  HTTP error {e.code}: {url}")
                if source:
                    mark_source(source, "failed", error_code=last_err_code)
                return None
        except Exception as e:
            last_err_code = _classify_request_error(e)
            if _is_connect_failure(e):
                if host:
                    UNREACHABLE_HOSTS.add(host)
                print(f"  Host unreachable ({host}): {e}")
                if source:
                    mark_source(source, "failed", error_code="unreachable")
                return None
            if attempt < retries - 1:
                time.sleep(2)
            else:
                print(f"  Error fetching {url}: {e}")
                if source:
                    mark_source(source, "failed", error_code=last_err_code)
                return None
    if source:
        mark_source(source, "failed", error_code=last_err_code or "fetch_failed")
    return None


# ── SEC EDGAR 抓取 ──

def fetch_sec_filings_edgar_fulltext(ticker, cik, company_name):
    """Fetch recent SEC filings using EDGAR full-text search API."""
    print(f"  Fetching SEC filings for {ticker}...")
    
    filings = []
    
    # Use EDGAR full-text search API with company name and CIK
    today = datetime.date.today()
    one_year_ago = today - datetime.timedelta(days=365)
    
    # Search URL - use company name with CIK entity filter
    encoded_name = company_name.replace(' ', '+').replace(',', '%2C')
    forms_filter = "10-Q,10-K,8-K,4,144,SC%2013D,SC%2013G,DEFA14A,S-1"
    
    search_url = (
        f"https://efts.sec.gov/LATEST/search-index?"
        f"q=%22{encoded_name}%22&dateRange=custom&"
        f"startdt={one_year_ago.isoformat()}&enddt={today.isoformat()}&"
        f"forms={forms_filter}&"
        f"entity=CIK%3A{cik}&"
        f"category=custom&start=0&rows=30"
    )
    
    data = safe_request(search_url, source=f"SEC EDGAR {ticker}")
    
    if data and isinstance(data, dict):
        hits = data.get('hits', {}).get('hits', [])
        
        for hit in hits:
            if isinstance(hit, dict):
                src = hit.get('_source', {})
                form_type = src.get('form', '')
                filing_date = src.get('file_date', '')
                adsh = src.get('adsh', '')
                display_name = src.get('display_names', [''])[0] if src.get('display_names') else ''
                file_type = src.get('file_type', '')
                file_desc = src.get('file_description', '')
                
                if not filing_date:
                    continue
                
                # Verify this belongs to our company (check CIK)
                hit_ciks = src.get('ciks', [])
                if hit_ciks and cik not in hit_ciks:
                    # Check if ticker is in display name
                    if ticker not in display_name:
                        continue
                
                # Build filing URL
                if adsh:
                    acc_clean = adsh.replace('-', '')
                    doc_url = f"https://www.sec.gov/Archives/edgar/data/{int(cik)}/{acc_clean}/"
                else:
                    doc_url = f"https://www.sec.gov/cgi-bin/browse-edgar?action=getcompany&CIK={cik}&type={form_type}"
                
                # Build title
                if file_desc and file_desc != form_type:
                    title = file_desc
                elif file_type and file_type != form_type:
                    title = SEC_FILING_TYPES.get(form_type, f"{form_type} ({file_type})")
                else:
                    title = SEC_FILING_TYPES.get(form_type, form_type)
                
                # Add item numbers for 8-K
                items = src.get('items', [])
                if items and form_type == '8-K':
                    title += f' (Item {", ".join(items[:3])})'
                
                filings.append({
                    "date": filing_date,
                    "company": ticker,
                    "type": form_type,
                    "title": title,
                    "url": doc_url,
                    "source": "SEC EDGAR",
                })
    
    # If search returned nothing, try without entity filter
    if not filings:
        search_url2 = (
            f"https://efts.sec.gov/LATEST/search-index?"
            f"q=%22{encoded_name}%22&dateRange=custom&"
            f"startdt={one_year_ago.isoformat()}&enddt={today.isoformat()}&"
            f"forms={forms_filter}&"
            f"category=custom&start=0&rows=30"
        )
        data2 = safe_request(search_url2, source=f"SEC EDGAR {ticker}")
        
        if data2 and isinstance(data2, dict):
            hits2 = data2.get('hits', {}).get('hits', [])
            
            for hit in hits2:
                if isinstance(hit, dict):
                    src = hit.get('_source', {})
                    form_type = src.get('form', '')
                    filing_date = src.get('file_date', '')
                    adsh = src.get('adsh', '')
                    display_name = src.get('display_names', [''])[0] if src.get('display_names') else ''
                    file_type = src.get('file_type', '')
                    
                    if not filing_date:
                        continue
                    
                    # Filter: must contain our ticker or company name
                    if ticker not in display_name and company_name.split(',')[0].strip() not in display_name:
                        continue
                    
                    if adsh:
                        acc_clean = adsh.replace('-', '')
                        doc_url = f"https://www.sec.gov/Archives/edgar/data/{int(cik)}/{acc_clean}/"
                    else:
                        doc_url = f"https://www.sec.gov/cgi-bin/browse-edgar?action=getcompany&CIK={cik}&type={form_type}"
                    
                    title = SEC_FILING_TYPES.get(form_type, form_type)
                    
                    filings.append({
                        "date": filing_date,
                        "company": ticker,
                        "type": form_type,
                        "title": title,
                        "url": doc_url,
                        "source": "SEC EDGAR",
                    })
    
    # Fallback: use the submissions API (works for some companies)
    if not filings:
        sub_url = f"https://data.sec.gov/submissions/CIK{cik}.json"
        sub_data = safe_request(sub_url, source=f"SEC EDGAR {ticker}")
        
        if sub_data and isinstance(sub_data, dict) and 'filings' in sub_data:
            recent = sub_data.get('filings', {}).get('recent', {})
            forms = recent.get('form', [])
            dates = recent.get('filingDate', [])
            accession = recent.get('accessionNumber', [])
            primary = recent.get('primaryDocument', [])
            
            important_forms = set(SEC_FILING_TYPES.keys())
            
            count = min(len(forms), 20)
            for i in range(count):
                form_type = forms[i] if i < len(forms) else ""
                filing_date = dates[i] if i < len(dates) else ""
                acc = accession[i] if i < len(accession) else ""
                doc = primary[i] if i < len(primary) else ""
                
                if not form_type or not filing_date:
                    continue
                
                if form_type not in important_forms:
                    continue
                
                if acc and doc:
                    acc_clean = acc.replace('-', '')
                    base_url = f"https://www.sec.gov/Archives/edgar/data/{int(cik)}/{acc_clean}/{doc}"
                else:
                    base_url = f"https://www.sec.gov/cgi-bin/browse-edgar?action=getcompany&CIK={cik}&type={form_type}"
                
                filings.append({
                    "date": filing_date,
                    "company": ticker,
                    "type": form_type,
                    "title": SEC_FILING_TYPES.get(form_type, form_type),
                    "url": base_url,
                    "source": "SEC EDGAR",
                })
    
    mark_source(f"SEC EDGAR {ticker}",
                "success" if filings else "failed",
                item_count=len(filings),
                error_code=None if filings else "fetch_failed")
    # If still nothing, add a placeholder
    if not filings:
        filings = [{
            "date": None,
            "date_status": "unknown",
            "company": ticker,
            "type": "INFO",
            "title": f"SEC filings for {company_name}",
            "url": f"https://www.sec.gov/cgi-bin/browse-edgar?action=getcompany&CIK={cik}",
            "source": "SEC EDGAR",
        }]

    filings.sort(key=lambda x: x.get('date') or '', reverse=True)
    # Remove duplicates
    seen_urls = set()
    unique = []
    for f in filings:
        if f['url'] not in seen_urls:
            seen_urls.add(f['url'])
            unique.append(f)
    filings = unique[:15]
    
    print(f"    Found {len(filings)} filings for {ticker}")
    return filings


def parse_edgar_atom_feed(xml_text, ticker, cik):
    """Parse EDGAR Atom feed."""
    filings = []
    cik_clean = str(int(cik))
    
    try:
        root = ET.fromstring(xml_text)
        ns = {'atom': 'http://www.w3.org/2005/Atom'}
        
        # Try with namespace first, then without
        entries = root.findall('.//atom:entry', ns)
        if not entries:
            entries = root.findall('.//entry')
        
        important_forms = set(SEC_FILING_TYPES.keys())
        
        for entry in entries:
            try:
                title_elem = entry.find('atom:title', ns) or entry.find('title')
                title = title_elem.text.strip() if title_elem is not None and title_elem.text else ""
                
                link_elem = entry.find('atom:link', ns) or entry.find('link')
                if link_elem is not None:
                    url = link_elem.get('href', '')
                else:
                    url = ""
                
                updated_elem = entry.find('atom:updated', ns) or entry.find('updated')
                updated = updated_elem.text.strip() if updated_elem is not None and updated_elem.text else ""
                
                # Extract form type from title
                form_type = ""
                for ft in important_forms:
                    if ft in title:
                        form_type = ft
                        break
                
                # Clean up
                if title:
                    title = re.sub(r'<[^>]+>', '', title).strip()
                    # Remove date prefix from title if present
                    title = re.sub(r'^\d{4}-\d{2}-\d{2}\s*', '', title).strip()
                
                if not form_type:
                    form_type = "OTHER"
                    display_title = title or "Other SEC filing"
                else:
                    display_title = SEC_FILING_TYPES.get(form_type, title)
                
                # Parse date (失败→None, 由 apply_date_fields 统一处理)
                filing_date = parse_date(updated) if updated else None
                
                if url and not url.startswith('http'):
                    url = f"https://www.sec.gov{url}"
                
                filings.append({
                    "date": filing_date,
                    "company": ticker,
                    "type": form_type,
                    "title": display_title,
                    "url": url or f"https://www.sec.gov/cgi-bin/browse-edgar?action=getcompany&CIK={cik}",
                    "source": "SEC EDGAR",
                })
            except Exception:
                continue
    except ET.ParseError:
        pass
    
    return filings


def parse_edgar_browse_page(html, ticker, cik):
    """Parse EDGAR browse page HTML for filing links."""
    filings = []
    
    # Find filing rows in the EDGAR results table
    pattern = r'<tr[^>]*>\s*<td[^>]*>\s*<a[^>]*href="([^"]*)"[^>]*>([^<]*)</a>[^>]*</td>\s*<td[^>]*>\s*<a[^>]*href="([^"]*)"[^>]*>([^<]*)</a>[^>]*</td>\s*<td[^>]*>([^<]*)</td>'
    
    matches = re.findall(pattern, html, re.DOTALL)
    
    for match in matches:
        link = match[0].strip()
        type_text = match[1].strip()
        title_link = match[2].strip()
        title_text = match[3].strip()
        date_text = match[4].strip()
        
        if not type_text or not date_text:
            continue
        
        # Build URL
        if link and not link.startswith('http'):
            link = f"https://www.sec.gov{link}"
        
        if title_link and not title_link.startswith('http'):
            title_link = f"https://www.sec.gov{title_link}"
        
        filings.append({
            "date": date_text,
            "company": ticker,
            "type": type_text,
            "title": SEC_FILING_TYPES.get(type_text, title_text or type_text),
            "url": title_link or link,
            "source": "SEC EDGAR",
        })
    
    return filings


def fetch_all_sec_filings():
    all_filings = []
    for ticker, info in COMPANIES.items():
        filings = fetch_sec_filings_edgar_fulltext(ticker, info['cik'], info['name'])
        all_filings.extend(filings)
        time.sleep(1)
    
    all_filings.sort(key=lambda x: x.get('date') or '', reverse=True)
    return all_filings


# ── RSS 抓取 ──

def parse_rss(xml_text, source_name, category, max_items=15):
    items = []
    try:
        root = ET.fromstring(xml_text)
        
        # Standard RSS 2.0
        for item in root.iter('item'):
            title = item.findtext('title', '').strip()
            link = item.findtext('link', '').strip()
            pub_date = item.findtext('pubDate', '').strip()
            description = item.findtext('description', '').strip()
            
            if description:
                description = re.sub(r'<[^>]+>', '', description)
                description = description[:200] + '...' if len(description) > 200 else description
            
            if title and link:
                parsed_date = parse_date(pub_date)
                items.append({
                    "date": parsed_date,
                    "source": source_name,
                    "category": category,
                    "title": title,
                    "url": link,
                    "summary": description or "",
                })
            
            if len(items) >= max_items:
                break
                
        # Atom format fallback
        if not items:
            ns = {'atom': 'http://www.w3.org/2005/Atom'}
            for entry in root.findall('.//atom:entry', ns) or root.findall('.//entry'):
                title = entry.findtext('title', '').strip()
                link_elem = entry.find('link')
                link = link_elem.get('href', '') if link_elem is not None else ''
                updated = entry.findtext('updated', '') or entry.findtext('published', '')
                summary = entry.findtext('summary', '') or entry.findtext('content', '')
                
                if summary:
                    summary = re.sub(r'<[^>]+>', '', summary)
                    summary = summary[:200] + '...' if len(summary) > 200 else summary
                
                if title and link:
                    items.append({
                        "date": parse_date(updated),
                        "source": source_name,
                        "category": category,
                        "title": title,
                        "url": link,
                        "summary": summary or "",
                    })
                
                if len(items) >= max_items:
                    break
                    
    except ET.ParseError as e:
        print(f"  RSS parse error for {source_name}: {e}")
    except Exception as e:
        print(f"  RSS error for {source_name}: {e}")
    
    return items


def parse_date(date_str):
    """解析日期字符串 → 'YYYY-MM-DD'; 无法解析返回 None（不再兜底为今天）。

    历史问题: 解析失败返回今天 → 无日期条目被标成"今日新闻"，
    交通运输部等政府站列表页一旦结构变化全部条目集体穿越到当天。
    现在: None 交给 apply_date_fields 标记 date_status=unknown，
    前端显示"发布时间待确认"，排序沉底，保留期按抓取时间算。
    """
    if not date_str:
        return None

    date_formats = [
        "%a, %d %b %Y %H:%M:%S %z",
        "%a, %d %b %Y %H:%M:%S %Z",
        "%Y-%m-%dT%H:%M:%S%z",
        "%Y-%m-%dT%H:%M:%SZ",
        "%Y-%m-%d %H:%M:%S",
        "%Y-%m-%d",
        "%d %b %Y",
        "%B %d, %Y",
        "%Y年%m月%d日",
        "%Y-%m-%dT%H:%M:%S.%f%z",
    ]

    for fmt in date_formats:
        try:
            dt = datetime.datetime.strptime(date_str.strip(), fmt)
            return dt.strftime("%Y-%m-%d")
        except ValueError:
            continue

    match = re.search(r'(\d{4}[-/]\d{1,2}[-/]\d{1,2})', date_str)
    if match:
        return match.group(1).replace('/', '-')

    return None


def _valid_date_str(s):
    """校验 'YYYY-MM-DD' 形态且为真实日历日。"""
    if not isinstance(s, str):
        return None
    m = re.match(r'^(\d{4})-(\d{2})-(\d{2})$', s.strip())
    if not m:
        return None
    try:
        datetime.date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
    except ValueError:
        return None
    return s.strip()


def apply_date_fields(items, fetched_at=None):
    """统一日期字段语义（改造项⑤, 2026-08-18）:

    - published_at: 来源发布日期 'YYYY-MM-DD' 或 None（真实发布时间未知就是 None）
    - fetched_at:   本条目被抓取的系统时间 'YYYY-MM-DD HH:MM:SS'
    - date:         兼容字段 = published_at 或 ''（未知为空串, 排序安全）
    - date_status:  'known' / 'unknown'
    保留期修剪时 unknown 条目按 fetched_at 的日期部分计算。
    """
    now = fetched_at or _now_iso()
    for it in items:
        if not isinstance(it, dict):
            continue
        pub = _valid_date_str(it.get("published_at")) or _valid_date_str(it.get("date"))
        if not it.get("fetched_at"):
            it["fetched_at"] = now
        it["published_at"] = pub
        it["date"] = pub or ""
        it["date_status"] = "known" if pub else "unknown"
    return items


# ── 摘要字段（改造项⑧, 2026-08-18；2026-08-18 晚删除 summary_basis）──
# 付费墙发行方（WSJ/FT/Reuters）—— 无公开输入渠道, 摘要留空, summary_status=insufficient_evidence。
# 摘要证据改由 summary_status 单字段表达（generated / insufficient_evidence），不再写 summary_basis。
SUMMARY_DETAIL_HOSTS = {
    "www.traveldaily.cn", "traveldaily.cn", "www.mct.gov.cn", "mct.gov.cn",
    "www.mot.gov.cn", "mot.gov.cn", "www.caacnews.com.cn", "caacnews.com.cn",
    "skift.com", "www.skift.com", "www.phocuswire.com", "phocuswire.com",
    "www.travelweekly.com", "travelweekly.com",
}

SUMMARY_BOILERPLATE = (
    "环球旅讯是中国领先的旅游商业", "中国民航网", "版权所有", "责任编辑",
    "来源：", "当前位置", "网站地图", "登录", "注册", "点击查看详情",
)


def _clean_summary_candidate(raw, title=""):
    text = re.sub(r"<[^>]+>", " ", raw or "")
    text = html_lib.unescape(text)
    text = text.replace("\\n", " ").replace("\\t", " ").replace("\u3000", " ")
    text = re.sub(r"\s+", " ", text).strip(" -—|｜:：")
    if title and text.startswith(title):
        text = text[len(title):].strip(" -—|｜:：")
    if len(text) < 28 or text == title or any(x in text for x in SUMMARY_BOILERPLATE):
        return ""
    if len(text) > 220:
        cut = max(text.rfind(mark, 0, 221) for mark in "。！？.!?")
        text = text[:cut + 1] if cut >= 60 else text[:217].rstrip() + "…"
    return text


def extract_public_page_summary(page, title=""):
    """从公开详情页提取首个有信息量的段落，不猜测、不访问付费正文。"""
    if not isinstance(page, str) or not page:
        return ""
    # Next.js 页面常把正文以 \u003cp\u003e 写在公开 HTML 中。
    expanded = (page.replace("\\u003c", "<").replace("\\u003e", ">")
                .replace("\\u0026", "&").replace("\\\"", '"'))
    candidates = []
    for pattern in (
        r'<meta[^>]+(?:name|property)=["\'](?:description|og:description)["\'][^>]+content=["\']([^"\']+)',
        r'<meta[^>]+content=["\']([^"\']+)["\'][^>]+(?:name|property)=["\'](?:description|og:description)["\']',
        r'<p[^>]*>([\s\S]*?)</p>',
    ):
        candidates.extend(re.findall(pattern, expanded, re.IGNORECASE))
    for raw in candidates:
        cleaned = _clean_summary_candidate(raw, title)
        if cleaned:
            return cleaned
    return ""


def enrich_public_summaries(news_data, max_fetches=36):
    """为缺摘要的公开网页补首段摘要；Bloomberg/付费墙/新闻索引不抓正文。"""
    now = _now_iso()
    fetched = 0
    host_counts = {}
    groups = [(news_data.get("international") or {}).get("industry_news") or []]
    groups.extend(v for v in (news_data.get("domestic") or {}).values() if isinstance(v, list))
    for items in groups:
        for item in items:
            if fetched >= max_fetches or item.get("summary") or item.get("paywall"):
                continue
            src = str(item.get("source", "") or "")
            url = str(item.get("url", "") or "")
            host = urlparse(url).netloc.lower()
            if (not url.startswith(("https://", "http://")) or host not in SUMMARY_DETAIL_HOSTS
                    or "Bloomberg" in src or "news.google." in host):
                continue
            if host_counts.get(host, 0) >= 15:
                continue
            page = safe_request(url, timeout=8, retries=1)
            fetched += 1
            host_counts[host] = host_counts.get(host, 0) + 1
            summary = extract_public_page_summary(page, str(item.get("title", "") or ""))
            if not summary:
                continue
            if re.search(r"[A-Za-z]{4}", summary) and not re.search(r"[\u4e00-\u9fff]", summary):
                summary = translate_text(summary, max_chars=350)
            item["summary"] = summary
            item["summary_status"] = "generated"
            item["summary_generated_at"] = now
    if fetched:
        enriched = sum(1 for items in groups for item in items if item.get("summary"))
        print(f"  Public detail summaries: attempted {fetched}, summaries present {enriched}")
    return news_data


def sec_deterministic_summary(f):
    """SEC 文件确定性摘要: 只用文件元数据（公司/类型/日期/8-K Items），零生成成分。

    不调用任何 AI —— SEC 列表 100% 确定性, 输入相同输出相同（可回归测试）。
    """
    ticker = str(f.get("company", "") or "")
    comp = COMPANIES.get(ticker, {}).get("name") or ticker or "该公司"
    ttype = str(f.get("type", "") or "")
    tname = str(f.get("title", "") or "")
    date = f.get("date") or ""
    label = tname or SEC_FILING_TYPES.get(ttype, ttype or "文件")
    parts = [f"{comp}于{date}向SEC提交" if date else f"{comp}向SEC提交"]
    parts.append(f"{label}。")
    summary = "".join(parts)
    # 8-K 标题常含 "Items 2.02, 9.01" —— 元数据的一部分, 原样保留
    m = re.search(r'Items?\s*[\d\.]+(?:\s*,\s*[\d\.]+)*', tname, re.IGNORECASE)
    if m:
        summary += f"（涉及条款 {m.group(0)}）"
    return summary


def backfill_summary_fields(news_data, fetched_at=None):
    """为缓存全部条目补齐摘要状态字段:
    summary_status ∈ {generated, insufficient_evidence}
    summary_generated_at = 'YYYY-MM-DD HH:MM:SS'

    - SEC: 确定性摘要（来自文件元数据）
    - 有摘要(≥10字) → generated
    - paywall 标记且无摘要 → insufficient_evidence（不虚构内容）
    - 其余无摘要 → insufficient_evidence
    """
    now = fetched_at or _now_iso()

    def _fill(item, is_sec=False):
        if not isinstance(item, dict):
            return
        if is_sec:
            if not item.get("summary"):
                item["summary"] = sec_deterministic_summary(item)
            item["summary_status"] = "generated"
            item.setdefault("summary_generated_at", now)
            return
        s = str(item.get("summary", "") or "").strip()
        if s:
            # §12 守卫: 摘要≈标题(相似度≥0.85)视为无摘要, 降级为仅标题
            t = str(item.get("title", "") or "").strip()
            if t and difflib.SequenceMatcher(None, s, t).ratio() >= 0.85:
                item["summary"] = ""
                s = ""
        if s:
            item["summary_status"] = "generated"
        elif item.get("paywall"):
            item["summary_status"] = "insufficient_evidence"
        else:
            item["summary_status"] = "insufficient_evidence"
        item.setdefault("summary_generated_at", now)

    intl = news_data.get("international", {}) or {}
    for f in intl.get("sec_filings", []) or []:
        _fill(f, is_sec=True)
    for n in intl.get("industry_news", []) or []:
        _fill(n)
    for cat, lst in (news_data.get("domestic", {}) or {}).items():
        if isinstance(lst, list):
            for n in lst:
                _fill(n)
    return news_data


# ── 模块路由（2026-08-18 新增: 把原 international.{sec_filings, industry_news} / domestic.{china_industry, regulatory, company_news} 分流到 5 个展示模块）──
# 模块优先级（同事件跨模块时取最高优先级）: intl_disclosures > intl_core_company > intl_industry ; dom_disclosures > dom_industry
MODULE_KEYS = (
    "intl_core_company",   # 国际·核心公司动态（BKNG/EXPE/ABNB 实质动态，非披露类）
    "intl_industry",       # 国际·行业新闻（统一列表，含事件标签）
    "intl_disclosures",    # 国际·披露与文件（SEC + IR 财报 + 股东信 + 业绩演示）
    "dom_industry",        # 国内·行业新闻（统一列表，含公司动态标签）
    "dom_disclosures",     # 国内·披露与文件（披露易/民航局/文旅部/交通运输部）
)
# 模块优先级（同 event_id 冲突时，越大越优先保留主条目）
MODULE_PRIORITY = {
    "intl_disclosures": 5,
    "intl_core_company": 4,
    "intl_industry": 3,
    "dom_disclosures": 2,
    "dom_industry": 1,
}
MODULE_MAX_ITEMS = {
    "intl_core_company": 30,
    "intl_industry": 80,
    "intl_disclosures": 50,
    "dom_industry": 60,
    "dom_disclosures": 40,
}
MODULE_RETENTION_DAYS = {
    # 2026-08-20: intl_core_company 从 14 放宽到 28 天
    # Expedia收购Layla等重大公司动态需要保留更久（Google News RSS 返回的 IR 文章可能有数周历史）
    "intl_core_company": 28,
    "intl_industry": 7,
    "intl_disclosures": 120,   # SEC/IR 财报类保留更久 (120天, 覆盖约半年)
    "dom_industry": 28,
    "dom_disclosures": 28,
}

# 披露类 content_type（财报/股东信/业绩演示/监管文件统一进入披露模块）
DISCLOSURE_CONTENT_TYPES = {"earnings", "operating_data", "governance_legal", "regulation"}

# 披露类来源（即使 content_type 未归类，来源命中即视为披露）
DISCLOSURE_SOURCE_KEYWORDS = (
    "SEC EDGAR", "披露易", "民航局", "文旅部", "交通运输部",
    "Booking Holdings IR", "Expedia Group IR", "Airbnb IR",
)


def _route_single_item(item, section, category):
    """根据 item 的 section/category/entity_id/content_type/source 决定其归属的展示模块 key。

    返回 MODULE_KEYS 之一；若条目不属于任何模块（如测试噪音）返回 None。
    """
    text = _sel_text(item)
    src = str(item.get("source", "") or "")
    ctype = str(item.get("content_type", "") or "")
    entity_id = str(item.get("entity_id", "") or "")
    is_core = entity_id in ("BKNG", "EXPE", "ABNB")

    # 国内分区
    if section == "domestic":
        # 披露与文件: 仅接受官方源（披露易/民航局/文旅部/交通运输部/东航公告等）
        # 行业媒体（环球旅讯/36氪/中国民航网）的公司财报/并购新闻不进披露模块, 留在 dom_industry 带公司标签
        if any(k in src for k in DISCLOSURE_SOURCE_KEYWORDS):
            # 2026-08-20: 国内 IR 源(如不存在)若有 BKNG/EXPE/ABNB 收购/投资动态 → intl_core_company
            if is_core and ctype in ("ma_investment", "management_org", "product", "partnership"):
                if not re.search(r"财报|季报|年报|业绩|营收|earnings|revenue", text, re.I):
                    return "intl_core_company"
            return "dom_disclosures"
        # 2026-08-20: 国内分区中 BKNG/EXPE/ABNB 的重大动态（并购/投资/高管/产品/合作）
        # → 路由到 intl_core_company。例："Expedia收购AI旅行规划平台Layla（环球旅讯转载）"
        # 应该进入国际核心公司动态, 而不是被当成"国内行业"
        if is_core:
            # 财报/业绩类 → 国际披露 (非官方媒体写的 BKNG/EXPE/ABNB 财报也算披露类)
            if ctype in DISCLOSURE_CONTENT_TYPES or re.search(
                    r"财报|季报|年报|业绩|营收|盈利|股东信|earnings|revenue|results", text, re.I):
                return "intl_disclosures"
            # 实质公司动态 → intl_core_company
            if ctype in ("ma_investment", "management_org", "product", "partnership",
                         "employee_policy", "strategy_marketing") or \
                    item.get("substantive_company_change"):
                return "intl_core_company"
            # 其他 BKNG/EXPE/ABNB 核心公司标题相关 → 核心公司动态(默认)
            return "intl_core_company"
        # 非官方源但标题明确是政府数据/公告转发（如"民航局X月旅客量统计"被中国民航网转载）→ 进披露
        if re.search(r"^民航局|^文旅部|^交通运输部|运营数据公告|月度统计|旅客量统计|客座率统计|航班量统计", text):
            return "dom_disclosures"
        # 其余国内条目（含行业媒体的公司财报新闻/服务升级/产品发布）→ 国内行业, 带公司标签
        return "dom_industry"

    # 国际分区
    # SEC 备案 → 国际披露
    if category == "sec_filings":
        return "intl_disclosures"
    # 来源命中 IR / SEC → 披露类
    if any(k in src for k in DISCLOSURE_SOURCE_KEYWORDS):
        # IR 来源: 若 content_type 命中 earnings/governance → 披露;
        # 但收购/投资 (ma_investment) / 高管人事 (management_org) / 产品 (product) 等
        # 实质公司动态 → 核心公司动态 (2026-08-20: Expedia收购Layla应该进核心公司, 而不是披露)
        if ctype in DISCLOSURE_CONTENT_TYPES or re.search(
                r"财报|季报|年报|业绩|营收|盈利|股东信|8-K|10-K|10-Q|earnings|revenue|results|"
                r"shareholder letter|investor|guidance", text, re.I):
            return "intl_disclosures"
        # 非披露类 IR 新闻稿（收购/投资/产品/高管/合作等）→ 核心公司动态
        if is_core:
            return "intl_core_company"
        return "intl_industry"
    # content_type 命中披露类
    if ctype in DISCLOSURE_CONTENT_TYPES:
        # BKNG/EXPE/ABNB 的财报类新闻 → 披露模块（即便来源是媒体）
        if is_core or re.search(r"财报|季报|年报|业绩|营收|盈利|股东信|earnings|revenue", text, re.I):
            return "intl_disclosures"
        return "intl_industry"
    # BKNG/EXPE/ABNB 实质动态 → 核心公司动态
    if is_core and item.get("substantive_company_change"):
        return "intl_core_company"
    # 其余国际条目 → 国际行业
    return "intl_industry"


def route_to_modules(news_data):
    """根据 module_router 规则把原分区的条目复制到 news_data["modules"][module_key] 列表。

    - 同 event_id 跨模块时只保留优先级最高模块的主条目，其余来源并入主条目的 related_sources；
    - 旧缓存中的 modules 数据先清空再重新路由（保证规则升级后旧条目走新规则）；
    - 各模块按 selection_score 倒序 + date 倒序排序，截断至 MODULE_MAX_ITEMS；
    - 保留期修剪：有发布日期按发布日期，无日期按 fetched_at；超期条目移除。
    """
    today = datetime.date.today()
    modules = {k: [] for k in MODULE_KEYS}
    # 暂存同 event_id 跨模块冲突，用于 related_sources 合并
    event_owner = {}   # event_id -> (module_key, item_ref)

    # 收集所有原始分区条目（不修改原分区）
    sources = []
    intl = news_data.get("international", {}) or {}
    for cat in ("sec_filings", "industry_news"):
        for it in (intl.get(cat) or []):
            sources.append((it, "international", cat))
    dom = news_data.get("domestic", {}) or {}
    for cat, lst in dom.items():
        if isinstance(lst, list):
            for it in lst:
                sources.append((it, "domestic", cat))

    for item, section, cat in sources:
        mk = _route_single_item(item, section, cat)
        if not mk:
            continue
        # 跨模块同事件去重
        eid = item.get("event_id")
        if eid:
            owner = event_owner.get(eid)
            if owner:
                owner_mk, owner_item = owner
                if MODULE_PRIORITY.get(mk, 0) > MODULE_PRIORITY.get(owner_mk, 0):
                    # 当前条目优先级更高 → 成为新主，原主条目降级为 related_source
                    related = list(owner_item.get("related_sources") or [])
                    if owner_item.get("source") and owner_item["source"] not in related:
                        related.append(owner_item["source"])
                    item.setdefault("related_sources", [])
                    item["related_sources"] = list(item.get("related_sources") or []) + related
                    event_owner[eid] = (mk, item)
                    modules[mk].append(item)
                    # 标记原主条目为已合并（不加入新模块，但仍计入原分区缓存）
                    owner_item["folded_into"] = owner_item.get("url") or "moved_to_higher_module"
                    continue
                else:
                    # 当前条目优先级更低 → 折叠，并入主条目 related_sources
                    item["folded_into"] = owner_item.get("url") or "moved_to_higher_module"
                    related = list(owner_item.get("related_sources") or [])
                    if item.get("source") and item["source"] not in related:
                        related.append(item["source"])
                    owner_item["related_sources"] = related
                    continue
            else:
                event_owner[eid] = (mk, item)
        modules[mk].append(item)

    # 保留期修剪 + 排序 + 限量
    for mk in MODULE_KEYS:
        items = modules[mk]
        retention = MODULE_RETENTION_DAYS.get(mk, 28)
        cap = MODULE_MAX_ITEMS.get(mk, 50)
        kept = []
        for it in items:
            if it.get("folded_into"):
                continue  # 渲染层过滤：被折叠条目不进入模块列表
            # 2026-08-20: 模块保留期豁免——
            # ① IR 官方新闻稿：120 天（覆盖财报季度周期）
            # ② 核心公司(BKNG/EXPE/ABNB)的并购/投资(ma_investment)重大事件: 60 天
            # ③ 环球旅讯源: 28 天(该源条目少而精)
            ir_src = bool(it.get("is_ir_source")) or any(k in str(it.get("source") or "") for k in
                ("Booking Holdings IR", "Expedia Group IR", "Airbnb IR", "SEC EDGAR"))
            eid = str(it.get("entity_id") or "")
            ct = str(it.get("content_type") or "")
            core_ma = (eid in ("BKNG", "EXPE", "ABNB")) and ct == "ma_investment"
            if ir_src:
                retention = max(retention, 120)
            elif core_ma:
                retention = max(retention, 60)
            elif str(it.get("source") or "") == "环球旅讯":
                retention = max(retention, 28)
            d = it.get("date") or ""
            if not d and it.get("fetched_at"):
                d = str(it.get("fetched_at"))[:10]
            try:
                pd = datetime.date.fromisoformat(d) if d else today
                if (today - pd).days > retention:
                    continue
            except Exception:
                pass
            kept.append(it)
        # 排序：重要性分数倒序 → 发布时间倒序（最新在上）
        # reverse=True: 分数值大的在前（100>60），日期值大的在前（08-06>08-04）
        kept.sort(key=lambda x: (
            int(x.get("selection_score") or 0),
            x.get("date") or "9999",
        ), reverse=True)
        # 2026-08-20: 模块内再跑一次同事件折叠（prune_and_dedupe 跑在 selection 之前,
        # 选择后不同分区路由过来的条目可能再次重复, 如"东航14天免费退改"被5家媒体报道）
        if mk in ("dom_industry", "dom_disclosures", "intl_industry", "intl_core_company"):
            kept = dedupe_same_article(kept)
            kept = group_same_events(kept)
            # folded_into 的条目不展示
            kept = [it for it in kept if not it.get("folded_into")]
        modules[mk] = kept[:cap]

    news_data["modules"] = modules
    return news_data


def fetch_rss_feeds(feeds, max_items_per_feed=10):
    all_items = []
    for feed in feeds:
        name = feed["name"]
        url = feed["url"]
        category = feed["category"]

        print(f"  Fetching RSS: {name}...")
        content = safe_request(url, timeout=10, source=name)

        if content:
            # 优先使用 feed 配置中的 max_items（如 PhocusWire 40 条）
            feed_max = feed.get("max_items") or max_items_per_feed
            items = parse_rss(content, name, category, feed_max)

            # For Google News RSS, extract actual source from title suffix
            # Google News format: "Title - Source Name" or "Title - site.com"
            if name in GOOGLE_NEWS_SOURCES:
                for item in items:
                    orig_title = item['title']
                    # Extract real source from title
                    extracted = extract_google_news_source(orig_title, name)
                    if extracted:
                        item['title'] = extracted['title']
                        item['source'] = extracted['source']

            # News Briefs 拆解：将 "tech news briefs: CompanyA, CompanyB..."
            # 拆解为每个公司的独立子条目（2026-08-18 新增）
            items = _expand_news_briefs(items)

            all_items.extend(items)
            mark_source(name, "success", item_count=len(items))
            print(f"    Found {len(items)} items from {name}")
        else:
            # safe_request 已按 error_code 标记 failed; 此处兜底确保状态存在
            if FETCH_STATUS["sources"].get(name, {}).get("status") != "failed":
                mark_source(name, "failed", error_code="fetch_failed")
            print(f"    Failed to fetch {name}")

        time.sleep(0.5)

    return all_items


# ── News Briefs 拆解（2026-08-18 新增）──
# PhocusWire 等媒体的 "travel tech news briefs: CompanyA, CompanyB, ... and more"
# 标题类文章实际包含多条独立子事件。由于详情页被 Cloudflare 403，无法抓取正文，
# 因此从标题中提取公司名列表，为每个公司创建一个独立子条目。
NEWS_BRIEFS_TITLE_RE = re.compile(
    r"^(.+?tech\s+news\s+briefs?\s*:\s*)(.+?)(?:\s+and\s+more.{0,3}|\s*\.+)$",
    re.IGNORECASE,
)
# 公司名识别（大写首字母单词，或已知品牌）
KNOWN_BRANDS_RE = re.compile(
    r"\b(SAP Concur|American Airlines|United Airlines|Booking\.com|Airbnb|Expedia|Trip\.com|Tripadvisor|"
    r"Agoda|Klook|MakeMyTrip|Skyscanner|Traveloka|Vrbo|Marriott|Hilton|Hyatt|Accor|IHG|Wyndham|"
    r"Mews|Spotnana|Omio|Ixigo|Navan|Mindtrip|Despegar|Almosafer|Lighthouse|ForwardKeys|"
    r"Amadeus|Sabre|Travelport|Yotel|Checkyeti|Manawa|Fliggy|Grab|Ryanair|Lufthansa|"
    r"Google|OpenAI|Capital One|Spirit Airlines|TripWorks|Clarasight|BizTrip|Q Concierge|"
    r"Fikäfi|Katanox|Rappi|TPConnects|HBX Group|Derek Jeter)\b"
)


def _expand_news_briefs(items):
    """拆解 News Briefs 类文章为多个公司子条目。

    输入: items 列表
    输出: 扩展后的 items 列表（News Briefs 原文被替换为多个子条目）

    子条目格式:
      title: "[公司名] 入选 PhocusWire 旅游科技快讯"
      source: "PhocusWire Briefs"
      url: 原文 URL（所有子条目共享）
      date: 原文日期
      content_type: "tech_brief"
    """
    expanded = []
    for it in items:
        title = it.get("title", "")
        m = NEWS_BRIEFS_TITLE_RE.match(title)
        if not m:
            expanded.append(it)
            continue

        prefix = m.group(1).strip()
        companies_str = m.group(2).strip()

        # 提取公司名列表
        companies = KNOWN_BRANDS_RE.findall(companies_str)
        if not companies:
            # 无法提取公司名, 保留原文
            expanded.append(it)
            continue

        # 去重（保持顺序）
        seen = set()
        unique_companies = []
        for c in companies:
            if c not in seen:
                seen.add(c)
                unique_companies.append(c)

        # 保留原文作为汇总条目
        expanded.append(it)

        # 为每个公司创建子条目
        for company in unique_companies:
            sub_item = {
                "title": f"{company} 入选 PhocusWire 旅游科技快讯",
                "source": "PhocusWire Briefs",
                "url": it.get("url", ""),
                "date": it.get("date", ""),
                "content_type": "tech_brief",
                "summary": f"{company} 入选 PhocusWire 旅游科技快讯。详情见原文。",
                # 不标记为实质动态: Briefs 子条目只是快讯提述, 不是实质公司变更
                "substantive_company_change": False,
            }
            # 复制原文的其他字段
            for k in ("entity_id", "company", "region", "translate"):
                if k in it:
                    sub_item[k] = it[k]
            expanded.append(sub_item)

    return expanded


def extract_google_news_source(title, fallback_source):
    """Extract actual source from Google News RSS title.
    Google News titles often have format: 'Actual Title - Source Name'
    Returns dict with 'title' and 'source' keys, or None if no extraction needed.
    
    2026-08-20: 如果 fallback_source 本身是旅游专用源 (TRAVEL_DEDICATED_SOURCES),
    保持原来源名 (如 "Bloomberg Travel (GN)"), 避免被降格为 "Bloomberg" 后
    在相关性过滤中被误杀。
    """
    if not title:
        return None
    
    # 如果 fallback_source 是旅游专用源, 保持原来源名
    if fallback_source in TRAVEL_DEDICATED_SOURCES:
        # 仍然清理标题 (去掉 " - Source" 后缀), 但保持来源名
        separators = [' - ', ' — ', ' – ']
        for sep in separators:
            if sep in title:
                parts = title.rsplit(sep, 1)
                if len(parts) == 2 and len(parts[0].strip()) > 10:
                    return {
                        'title': parts[0].strip(),
                        'source': fallback_source,  # 保持原来源
                    }
        return None  # 不清理标题, 保持原样
    
    # Domain to friendly name mapping
    DOMAIN_NAME_MAP = {
        'phocuswire.com': 'PhocusWire',
        'travelweekly.com': 'Travel Weekly',
        'skift.com': 'Skift',
        'bloomberg.com': 'Bloomberg',
        'bloomberg': 'Bloomberg',
        'bnbloomberg.ca': 'BNN Bloomberg',
        'webintravel.com': 'WebInTravel',
        'travelpulse.com': 'Travel Pulse',
        'hospitalitynet.org': 'Hospitality Net',
        'hotel-online.com': 'Hotel Online',
        'hotelnewsresource.com': 'Hotel News Resource',
        'breakingtravelnews.com': 'Breaking Travel News',
        'ttgasia.com': 'TTG Asia',
        'simplywall.st': 'Simply Wall St',
        'seekingalpha.com': 'Seeking Alpha',
        'yfinance.com': 'Yahoo Finance',
        'finance.yahoo.com': 'Yahoo Finance',
        'investing.com': 'Investing.com',
        'prnewswire.com': 'PR Newswire',
        'businessjournals.com': 'The Business Journals',
        'thepointsguy.com': 'The Points Guy',
        'thriftytraveler.com': 'Thrifty Traveler',
        'condenasttraveler.com': 'Condé Nast Traveler',
        'travelandleisure.com': 'Travel + Leisure',
        'forbes.com': 'Forbes',
        'techcrunch.com': 'TechCrunch',
        'businessinsider.com': 'Business Insider',
        'ft.com': 'Financial Times',
        'economist.com': 'The Economist',
        'reuters.com': 'Reuters',
        'apnews.com': 'AP News',
        'foxnews.com': 'Fox News',
        'cnbc.com': 'CNBC',
        'marketwatch.com': 'MarketWatch',
        'barrons.com': 'Barron\'s',
        'wsj.com': 'Wall Street Journal',
        'nytimes.com': 'New York Times',
        'washingtonpost.com': 'Washington Post',
        'theguardian.com': 'The Guardian',
        'cnn.com': 'CNN',
        'nbcnews.com': 'NBC News',
        'abcnews.go.com': 'ABC News',
        'cbsnews.com': 'CBS News',
        'usatoday.com': 'USA Today',
        'latimes.com': 'Los Angeles Times',
        'sfgate.com': 'SFGATE',
        'boston.com': 'Boston.com',
        'theindependent.co.uk': 'The Independent',
        'china.org.cn': 'China Daily',
        'chinadaily.com.cn': 'China Daily',
        'jingdaily.com': 'Jing Daily',
        'tmtpost.com': 'TMTPost',
        'sohu.com': 'Sohu',
        'sina.com.cn': 'Sina',
        '163.com': 'NetEase',
        'qq.com': 'QQ News',
        'tencent.com': 'Tencent',
        'baidu.com': 'Baidu',
        'cls.cn': '财联社',
        'cls.cn': '财联社',
        'caixin.com': '财新网',
        'yicai.com': '第一财经',
        'jiemian.com': '界面新闻',
        'thepaper.cn': '澎湃新闻',
        'infzm.com': '南方周末',
    }
    
    # Pattern: "Some Title - actualsource.com" or "Some Title - Source Name"
    # Google News appends " - source.com" at the end
    separators = [' - ', ' — ', ' – ']
    
    for sep in separators:
        if sep in title:
            parts = title.rsplit(sep, 1)
            if len(parts) == 2:
                clean_title = parts[0].strip()
                extracted_source = parts[1].strip()
                
                # Only extract if the source looks like a domain or known source
                # and the title is substantial
                if clean_title and len(clean_title) > 10 and extracted_source:
                    # Clean up extracted source
                    source_clean = extracted_source.rstrip('.')
                    
                    # Try to map domain to friendly name
                    source_lower = source_clean.lower()
                    for domain, friendly in DOMAIN_NAME_MAP.items():
                        if domain in source_lower:
                            source_clean = friendly
                            break
                    
                    return {
                        'title': clean_title,
                        'source': source_clean,
                    }
    
    return None


# ── 新闻评分与筛选 ──

def score_news_item(item):
    """Score a news item. Returns score 0-5. Returns -999 if not travel-related."""
    text = f"{item.get('title', '')} {item.get('summary', '')}".lower()
    score = 0.0
    
    # Block check - hard filter on spam/low-value content
    for kw in BLOCK_KEYWORDS:
        if kw in text:
            return -999
    
    # STRICT: Must match at least one travel/OTA core keyword
    # (Skip this for travel-dedicated sources like Skift, 环球旅讯)
    source = item.get('source', '')
    travel_dedicated = source in ('Skift', 'PhocusWire', '环球旅讯', '中国民航网') or source in GOOGLE_NEWS_SOURCES
    
    if not travel_dedicated:
        has_travel_keyword = False
        for kw in TRAVEL_CORE_KEYWORDS:
            if kw.lower() in text:
                has_travel_keyword = True
                break
        if not has_travel_keyword:
            return -999
    
    # Count travel keyword hits for ranking
    travel_hits = 0
    for kw in TRAVEL_CORE_KEYWORDS:
        if kw.lower() in text:
            travel_hits += 1
    score += min(travel_hits * 0.5, 3.0)
    
    # Source quality bonus
    if travel_dedicated:
        score += 0.5
    if 'Bloomberg' in source:
        score += 0.3
    
    # Recency bonus (newer = better)
    try:
        date_str = item.get('date', '')
        if date_str:
            dt = datetime.datetime.strptime(date_str, '%Y-%m-%d')
            days_old = (datetime.date.today() - dt.date()).days
            if days_old <= 1:
                score += 1.0
            elif days_old <= 3:
                score += 0.5
            elif days_old <= 7:
                score += 0.2
    except Exception:
        pass
    
    return score


# ── 严格行业相关性过滤 ──

# 旅游/OTA 行业严格关键词 (Bloomberg 等综合源必须命中才能保留)
# 仅匹配这些词中的任何一个才视为行业相关
TRAVEL_STRICT_KEYWORDS = [
    # OTA 公司名
    'airbnb', 'booking.com', 'booking holdings', 'bkng',
    'expedia', 'expedia group', 'expe',
    'tripadvisor', 'trip.com', 'agoda', 'skyscanner',
    'klook', 'makemytrip', 'traveloka', 'trip.com',
    # 酒店/住宿
    'hotel', 'hotels', 'lodging', 'hospitality', 'vacation rental',
    'short-term rental', 'homestay', 'bnb',
    'marriott', 'hilton', 'hyatt', 'ihg', 'wyndham', 'accor',
    'resort', 'inn', 'motel',
    # 航空
    'airline', 'airlines', 'airport', 'aviation',
    'delta air lines', 'united airlines', 'american airlines',
    'jetblue', 'southwest airlines', 'ryanair', 'easyjet',
    # 旅游行业指标 (强信号)
    'gross bookings', 'room nights', 'adr', 'revpar', 'take rate',
    'occupancy rate', 'hotel revenue', 'hotel bookings',
    # 旅游上下文
    'tourism', 'tourist', 'travel demand', 'travel spending',
    'travel recovery', 'vacation', 'getaway', 'escape',
    # 竞品/市场
    'ota', 'online travel', 'travel tech', 'travel technology',
    'travel platform', 'booking platform',
]

# 绝对排除的关键词 (命中任一直接丢弃, 即使源是旅游源也过滤)
TRAVEL_BLOCK_STRONG = [
    'crypto', 'bitcoin', 'blockchain', 'nft',
    'poker', 'casino', 'gambling', 'betting',
    'murder', 'shooting', 'arrest', 'prison', 'crime',
    'war', 'invasion', 'missile', 'bombing',
    'election', 'vote', 'ballot', 'political race',
    'earthquake', 'hurricane', 'tsunami', 'flood', 'wildfire',
    'stock market crash', 'recession', 'bank failure',
]

# 旅游专用源 (全部保留, 不做关键词过滤)
TRAVEL_DEDICATED_SOURCES = {
    'Skift', 'PhocusWire', 'PhocusWire Briefs', 'Travel Weekly', 'Skyscanner',
    'Klook', 'MakeMyTrip', 'Traveloka', 'Agoda',
    'Booking.com', 'Expedia', 'Airbnb', 'Tripadvisor',
    'Trip.com', 'Bloomberg Travel (GN)', 'Bloomberg Mobility (GN)',
    '环球旅讯', '中国民航网', 'WebInTravel',
    'Hospitality Net', 'Breaking Travel News',
    # IR 官方源 (2026-08-20 新增): 公司官方新闻稿, 必定相关
    'Booking Holdings IR', 'Expedia Group IR', 'Airbnb IR',
}

# 词边界正则（防子串陷阱）: 'expe'曾误命中"Rate-Hike Expectations"放过黄金行情新闻;
# 同类隐患 'ota'→rotation/notable, 'adr'→madrid/ADReSS, 'war'→award/software, 'vote'→devoted 等
TRAVEL_KEYWORD_PATTERNS = [re.compile(r'\b' + re.escape(kw) + r'\b') for kw in TRAVEL_STRICT_KEYWORDS]
TRAVEL_BLOCK_PATTERNS = [re.compile(r'\b' + re.escape(kw) + r'\b') for kw in TRAVEL_BLOCK_STRONG]


def filter_travel_relevance(items):
    """严格过滤: 只保留 OTA/旅游/酒店/航空行业相关新闻。
    
    规则:
    1. 旅游专用源 → 全部保留
    2. Bloomberg/CNBC 等综合源 → 必须命中 TRAVEL_STRICT_KEYWORDS 至少一个
    3. 命中 TRAVEL_BLOCK_STRONG 任一关键词 → 直接排除
    """
    kept = []
    removed = 0
    
    for item in items:
        # 同时检查译文与英文原文：缓存合并后重过滤时 title 可能已是中文
        title_lower = ((item.get('title', '') or '') + ' ' + (item.get('title_original', '') or '')).lower()
        summary_lower = ((item.get('summary', '') or '') + ' ' + (item.get('summary_original', '') or '')).lower()
        text = f"{title_lower} {summary_lower}"
        source = item.get('source', '') or ''
        
        # Rule 1: 旅游专用源 → 全部保留（含强排除豁免: 专业旅游媒体标题里的 'war' 等词
        # 多是行业报道上下文, 如 "Almosafer IPO Despite Iran War Disruption";
        # 2026-08-18 曾因强排除误杀 2 条 Skift 沙特酒店/OTA 行业新闻, 用户发现看板缺新闻）
        # 2026-08-20: 同时豁免 is_ir_source 标记的条目 (IR 官方新闻稿)
        if source in TRAVEL_DEDICATED_SOURCES or item.get('is_ir_source'):
            kept.append(item)
            continue

        # Rule 3: 强排除关键词 (仅对综合源; 词边界匹配, 防 'war' 误杀 award/software 等)
        blocked = False
        for p in TRAVEL_BLOCK_PATTERNS:
            if p.search(text):
                blocked = True
                break
        if blocked:
            removed += 1
            continue
        
        # Rule 2: 综合源 → 必须命中严格关键词 (词边界匹配, 防 'expe' 误命中 expectations)
        has_keyword = False
        for p in TRAVEL_KEYWORD_PATTERNS:
            if p.search(text):
                has_keyword = True
                break
        
        if has_keyword:
            kept.append(item)
        else:
            removed += 1
    
    if removed > 0:
        print(f"  [Relevance Filter] Removed {removed} non-travel items, kept {len(kept)}")
    
    return kept


def filter_and_rank_news(items, min_score=None, max_per_source=None):
    """Filter news by score, then rank by score desc, and limit per source.
    Only keeps travel/OTA related news. Returns -999 for non-travel items."""
    min_score = min_score if min_score is not None else NEWS_KEEP_MIN_SCORE
    max_per = max_per_source if max_per_source is not None else NEWS_MAX_PER_SOURCE
    
    # Score each item
    for item in items:
        item['_score'] = score_news_item(item)
    
    # Filter: SEC filings always kept; news must be travel-related and pass min score
    sec_items = [i for i in items if i.get('category') == 'sec_filings']
    news_items = [i for i in items if i.get('category') != 'sec_filings']
    
    # Remove non-travel items (score == -999) and items below min score
    filtered = [i for i in news_items if i['_score'] > -999 and i['_score'] >= min_score]
    
    # Sort by score desc
    filtered.sort(key=lambda x: x['_score'], reverse=True)
    
    # Limit per source
    source_counts = {}
    limited = []
    for item in filtered:
        src = item.get('source', 'unknown')
        src_count = source_counts.get(src, 0)
        if src_count < max_per:
            limited.append(item)
            source_counts[src] = src_count + 1
    
    # Add SEC items back (unfiltered, sorted by date)
    sec_items.sort(key=lambda x: x.get('date', ''), reverse=True)
    result = sec_items + limited
    
    # Remove internal scoring field
    for item in result:
        item.pop('_score', None)
    
    return result


def translate_news_items(items):
    """Translate titles and summaries for ALL news items with English content.
    Implements a global circuit breaker: once Google translation throttles
    (>=10 consecutive failures), remaining items keep their original English."""
    global _TRANSLATE_FAILS
    translated = 0
    skipped = 0
    total = len(items)
    breaker_triggered = False
    for idx, item in enumerate(items, 1):
        if _TRANSLATE_FAILS >= 10 and not breaker_triggered:
            breaker_triggered = True
            print(f"    [translate] Circuit breaker tripped at item {idx}/{total}. "
                  f"Keeping original English for remaining {total - idx + 1} items.")
            # Keep looping but skip actual API calls (cache + breaker will block)
        title = item.get('title', '')
        if title and re.search(r'[a-zA-Z]{2}', title):
            original = title
            item['title_original'] = title
            item['title'] = translate_text(title)
            if item['title'] != original:
                translated += 1
            else:
                skipped += 1
        summary = item.get('summary', '')
        if summary and re.search(r'[a-zA-Z]{4}', summary):
            item['summary_original'] = summary[:200]
            item['summary'] = translate_text(summary[:200])
    if breaker_triggered:
        print(f"    Translated {translated} items, kept English for {skipped} "
              f"(breaker tripped — Google 429 throttle)")
    else:
        print(f"    Translated {translated} items from English to Chinese ({skipped} unchanged)")
    return items


# ── 公司新闻标签（国际） ──
# 严格品牌模式，避免 "bookings" 这类通用词误判。
# 边界同样用 ASCII 环视（\b 遇中文失效, 见 CORE_COMPANY_TABLE 注释）。
COMPANY_BRAND_PATTERNS = {
    "BKNG": r"booking\.com|booking holdings|(?<![a-z0-9])bkng(?![a-z0-9])|priceline|(?<![a-z0-9])kayak(?![a-z0-9])|opentable|(?<![a-z0-9])agoda(?![a-z0-9])",
    "EXPE": r"expedia|(?<![a-z0-9])vrbo(?![a-z0-9])|hotels\.com|orbitz|travelocity|hotwire|(?<![a-z0-9])expe(?![a-z0-9])",
    "ABNB": r"(?<![a-z0-9])airbnb(?![a-z0-9])|(?<![a-z0-9])abnb(?![a-z0-9])",
}


def tag_company_news(items):
    """给命中三家 OTA 品牌关键词的新闻打 company 标签。"""
    for item in items:
        text = " ".join([
            str(item.get("title", "")), str(item.get("title_original", "")),
            str(item.get("summary", "")), str(item.get("summary_original", "")),
        ]).lower()
        for co, pat in COMPANY_BRAND_PATTERNS.items():
            if re.search(pat, text, re.IGNORECASE):
                item["company"] = co
                break
    return items


# ══════════════════════════════════════════════════════════════════════════
# 统一新闻筛选管道（2026-08-18 规范 §3-§11）
# 执行顺序: 实体识别 → 硬排除 → 重点公司判定 → 实质动态判定 → OTA基本面评分 → 去重(上游已做) → 记理由
# 新抓取数据 + 保留期内旧缓存在 merge_with_cache 之后统一走本管道（同一套规则）;
# 被拒条目移出列表并写入 news_rejected_副本.json 诊断文件。
# 全程确定性（正则+字段计算）: AI 只可输出结构化分类, 最终分数由程序按字段计算。
# ══════════════════════════════════════════════════════════════════════════

# ── 重点公司实体表（§3）: 稳定 entity_id + 严格品牌匹配 ──
# 裸词 booking/trip 绝不匹配——必须带品牌后缀/公司全名/股票代码。
# 边界坑: Python re 的 \b 把中文视为单词字符, \bairbnb\b 匹配不了 "Airbnb重建营销引擎",
# 因此一律用 ASCII 字母数字环视 (?<![a-z0-9])X(?![a-z0-9]) 做品牌词边界。
CORE_COMPANY_TABLE = [
    # (entity_id, 别名正则, 说明)
    ("BKNG", r"booking\s*holdings|booking\.com|(?<![a-z0-9])bkng(?![a-z0-9])|priceline|(?<![a-z0-9])kayak(?![a-z0-9])|(?<![a-z0-9])agoda(?![a-z0-9])|opentable", "Booking Holdings"),
    ("EXPE", r"expedia|(?<![a-z0-9])vrbo(?![a-z0-9])|hotels\.com|orbitz|travelocity|hotwire|(?<![a-z0-9])expe(?![a-z0-9])", "Expedia Group"),
    ("ABNB", r"(?<![a-z0-9])airbnb(?![a-z0-9])|(?<![a-z0-9])abnb(?![a-z0-9])", "Airbnb"),
    ("TCOM", r"trip\.com|trip\s*group|携程|去哪儿|(?<![a-z0-9])ctrip(?![a-z0-9])", "Trip.com Group"),
    ("TONGCHENG", r"同程旅行|同程旅游|同程艺龙", "同程旅行"),
    ("FLIGGY", r"飞猪", "飞猪"),
    ("MEITUAN", r"美团酒旅|美团旅行|美团酒店|美团民宿", "美团酒旅"),
]
CORE_COMPANY_IDS = {e[0] for e in CORE_COMPANY_TABLE}
CORE_KEEP_THRESHOLD = 60   # 准入线（重点公司实质动态保底同样取此值）


def identify_entity(item):
    """实体识别: 返回 entity_id 或 None（同时检查译文与英文原文）。"""
    text = " ".join([
        str(item.get("title", "") or ""), str(item.get("title_original", "") or ""),
        str(item.get("summary", "") or ""), str(item.get("summary_original", "") or ""),
    ]).lower()
    for eid, pat, _label in CORE_COMPANY_TABLE:
        if re.search(pat, text):
            return eid
    return None


# ── 硬排除（§6）: 无论重点/非重点命中即拒绝 ──
HARD_EXCLUDE_PATTERNS = [
    (r"活动报名|参会报名|观众登记|专业观众|报名通道|参会指南|会议预告|峰会预告|论坛预告|展会预告", "活动报名/会议预告"),
    (r"采购需求|旅业采购|寻找供应商|供应商对接|采购对接|寻.*地接社|地接社.*合作", "采购对接"),
    (r"入群|扫码加入|加入社群|广告招商|招商合作|投稿信箱|广告报价", "社群广告"),
    (r"实测|亲测|打卡|攻略|怎么玩|保级升卡|会员升级指南|自驾.*(实测|流程|多方便)|路线推荐|避坑指南|省钱秘籍", "消费者攻略/实测"),
    (r"篮球|足球赛|集体婚礼|庆典|颁奖|荣获|斩获|摘得.{0,4}奖|获评|获奖|公益|慈善|捐赠|志愿服务|爱心助考", "体育赞助/庆典/获奖/公益"),
    (r"救援故事|紧急救援|机上救援|成功救援|备降救人|坚守岗位|高温坚守|防汛抗|人物故事|员工故事|劳模|最美.{0,6}人|暖心故事|走红|紧急救助|旅客.{0,6}突发疾病", "救援/员工个人故事/坚守"),
    (r"短评|随笔|行业鸡汤|流向何方|趋势漫谈|超哥|闲话|漫谈", "无新事实短评"),
    (r"如何避开|差旅大坑|踩坑指南|如何避坑|有哪些坑", "泛观点/攻略型长文"),
    (r"新玩法|满分口碑|深度好眠|种草|安利|宝藏|天花板|绝绝子|焕新出发|重磅升级|荣耀启程|网红", "品牌软文"),
    (r"一周要闻|新闻合集|本周速览|行业动态合集|周报盘点|每日速览|投融资动态|这\d+笔交易|\d+笔交易值得关注", "新闻合集"),
    (r"股票股价|股价行情|_股价_|行情_讨论|股吧", "社群广告"),
    # 名人/运动员投资非核心项目(2026-08-20 新增: 用户指定 Derek Jeter 投资大学城酒店品牌不重要)
    (r"德里克·杰特|Derek Jeter|运动员|体育明星|球星|明星.{0,4}(?:投资|入股|收购)|(?:投资|入股|收购).{0,4}(?:运动员|体育明星|球星)", "名人/运动员投资非核心项目"),
    # 箱包皮具类收购(2026-08-20 新增: 新秀丽收购Béis属于箱包行业, 非OTA/旅游业核心)
    # 仅排除箱包行业内部并购, 不影响航司行李政策等合法旅游新闻
    (r"(?:箱包皮具|行李箱|duffel|backpack|新秀丽|Samsonite).{0,8}(?:收购|并购|投资|入股|融资|acquir|merger|invest|raises)", "箱包皮具类并购(非旅行核心业务)"),
]
HARD_EXCLUDE_COMPILED = [(re.compile(p), label) for p, label in HARD_EXCLUDE_PATTERNS]


def hard_exclude_reason(item):
    """硬排除判定: 返回拒绝原因标签或 None。"""
    title_only = str(item.get("title", "") or "")
    if re.search(r"[?？]\s*$", title_only):
        return "无新事实短评"
    text = "{} {}".format(title_only, item.get("summary", "") or "")
    for pat, label in HARD_EXCLUDE_COMPILED:
        if pat.search(text):
            return label
    return None


# ── 内容类型分类器（确定性; 优先级即列表顺序） ──
CONTENT_TYPE_RULES = [
    ("earnings", r"财报|季报|年报|业绩|营收|盈利|亏损|净利润|利润|业绩指引|指引|guidance|earnings|revenue|profit|beat estimates|beat expectations"),
    ("operating_data", r"运营数据|经营数据|旅客量|客座率|运力|间夜|room ?nights?|revpar|\badr\b|出租率|入住率|净增|净开店|新开店|门店数|吞吐量|航班量|游客量|旅游收入|接待游客"),
    ("ma_investment", r"收购|并购|投资|融资|入股|合资|合并|出售|剥离|分拆|上市|ipo|acquisition|acquire|to acquire|invest|raises|funding"),
    ("employee_policy", r"陪产假|产假|育儿假|员工福利|员工.{0,6}制度|福利政策|薪酬|股权激励|人才战略|员工关怀|人才争夺|争夺.{0,6}人才|AI\s*人才|人才战"),
    ("product", r"上线|推出|发布|开放|新功能|新产品|直订|服务升级|帮帮|launch|unveil|introduce|roll ?out|debuts?"),
    ("policy_commission", r"佣金|退改签|退票|改签|价格政策|商家政策|履约|手续费|commission|refund|cancel"),
    ("management_org", r"任命|履新|离任|辞任|辞职|ceo|cfo|总裁|高管|管理层|组织架构|重组|裁员|appointment|steps down"),
    ("ai_application", r"\bai\b|人工智能|大模型|智能体|生成式|agent|artificial intelligence"),
    ("expansion", r"扩张|进军|进入.{0,6}市场|开业|拓展|出海|国际化|新增.{0,6}航线|开通|expansion|enters?"),
    ("regulation", r"监管|处罚|约谈|整改|立法|法规|政策|办法|规定|统计|通报"),
    ("governance_legal", r"诉讼|调查|和解|庭审|起诉|指控|回购|分红|治理|lawsuit|settlement|probe|sued"),
    ("partnership", r"合作|战略协议|签约|联盟|携手|partner|partnership"),
    ("strategy_marketing", r"营销|品牌战略|广告|推广|marketing|brand"),
    ("opinion", r"观点|观察|评论|解读|专访|对话|思考|前瞻|展望|如何|为何|为什么|浅析|探讨|浅谈"),
]

FORMAL_POLICY_TYPES = {"employee_policy", "management_org", "policy_commission", "governance_legal"}

DIMENSION_BY_CTYPE = {
    "earnings": ["financials"],
    "operating_data": ["operating_data"],
    "ma_investment": ["capital", "competition"],
    "employee_policy": ["talent", "organization"],
    "product": ["product"],
    "policy_commission": ["policy", "distribution"],
    "management_org": ["organization"],
    "ai_application": ["technology"],
    "expansion": ["supply", "market"],
    "regulation": ["policy"],
    "governance_legal": ["governance"],
    "partnership": ["cooperation"],
    "strategy_marketing": ["marketing"],
    "opinion": [],
    "general": [],
}


def classify_content_type(text):
    low = text.lower()
    for ctype, pat in CONTENT_TYPE_RULES:
        if re.search(pat, low):
            return ctype
    return "general"


# 重点公司实质动态判定: 必须有具体公司行为/制度/产品/数据/事件, "提及"不算
ACTION_MARKER_RE = re.compile(
    r"收购|并购|投资|融资|入股|出售|剥离|分拆|上市|ipo|合作|签约|结盟|"
    r"上线|推出|发布|开放|直订|重建|重构|升级|改版|内测|新增|开通|开放预订|"
    r"任命|履新|离任|辞任|辞职|裁员|重组|"
    r"财报|业绩|营收|盈利|亏损|指引|guidance|beat|miss|"
    r"运营数据|旅客量|客座率|revpar|adr|间夜|入住率|净增|开店|吞吐量|"
    r"佣金|退改签|退票|改签|政策|制度|福利|陪产假|产假|薪酬|"
    r"回购|分红|诉讼|和解|调查|处罚|起诉|判决|"
    r"进军|扩张|进入|开业|拓展|出海|国际化|人才争夺|争夺.{0,6}人才|"
    r"acquir|launch|unveil|introduc|report|announce|expand|partner|invest|rais",
    re.IGNORECASE)

# ── 官方/披露来源保留清单（§8）: 命中即保底准入 ──
OFFICIAL_KEEP_RULES = [
    ("文旅部", re.compile(
        r"在线旅游|旅游监管|入境游|出境游|国内旅游|旅游统计|游客量|旅游收入|假日|酒店|住宿|"
        r"旅行社|平台监管|签证|消费政策|市场数据|旅游市场|文旅消费|旅游消费|游客")),
    ("交通运输部", re.compile(
        r"民航|航班|机场|吞吐量|旅客|客运|客流|票价|退改|春运|暑运|黄金周|航空")),
    ("披露易", re.compile(
        r"月報表|月报表|月度|运营|運營|業績|业绩|盈利預警|盈利预警|虧損|亏损|報告|报告|"
        r"运力|客座率|旅客|航線|航线|票價|票价|退改|渠道|重大交易|融資|融资|管理層|管理层")),
]
# 披露易形式性公告: 不走保底, 按普通条目评分（多数会被拒）
OFFICIAL_EXCLUDE_RE = re.compile(
    r"董事名單|代表委任|股東週年大會通告|股东周年大会|董事會會議通告|董事会会议通告|召開.{0,8}會議通知|月報表|月报表")

# 东航（company_news 栏目主体）实质运营动态保留规则（§7/§8, 2026-08-18 收窄）
# 东航不是重点跟踪公司，抓取东航官网和中国民航网仅用于发现可能影响 OTA 机票业务的航空行业变化。
# 必须命中以下"业务影响词"之一才保留：票价/退改签/运力/客座率/渠道/收费/航班取消/重大航线调整
# 单独出现"上线/推出/行李/合作/旅客/航班"等过宽词不保留
CEAIR_LABELS = ("中国东航", "中国东方航空", "东航")
# 业务影响词（必命中之一）
# 2026-08-18 修复: 燃油附加费（民航标准说法，非"燃油费"）；航线调整支持"调整...航线"双向词序
CEAIR_IMPACT_RE = re.compile(
    r"票价|燃油附加费|燃油费|行李费|退改|退票|改签|手续费|免费退改|提前\d+天|"
    r"运力|客座率|旅客量|航班量|吞吐量|运营数据|经营数据|"
    r"渠道|代理|佣金|直销|OTA|客票|票务|"
    r"航班取消|大范围取消|特殊退改|复航|新增航线|航线.{0,4}调整|调整.{0,4}航线|机队|宽体机|"
    r"盈利预警|业绩|财报")
# 排除词：无量化商业影响的宣传稿（即使命中 IMPACT_RE 也排除）
CEAIR_EXCLUDE_RE = re.compile(
    r"智能机器人|机器人矩阵|远程医疗|急救平台|急救系统|"
    r"宠物进客舱|宠物进舱|篮球|婚礼|颁奖|荣获|斩获|获评|获奖|"
    r"救援故事|机上救援|备降救人|人物故事|员工故事|劳模|最美.{0,6}人|暖心故事|"
    r"提升出行品质|智慧服务|焕新|焕新出发|荣耀启程|网红|"
    r"机场部署|分公司|地方分公司|"
    r"行李状态推送|服务升级|体验升级|应用首[次发]|首次应用")
# 14天免费退改 = 固定回归样本（必须高分保留）
CEAIR_REFUND_RE = re.compile(r"提前\s*14\s*天|14\s*天.{0,4}免费退改|免费退改.{0,4}14\s*天")


def _sel_text(item):
    return "{} {} {} {}".format(
        item.get("title", "") or "", item.get("summary", "") or "",
        item.get("title_original", "") or "", item.get("summary_original", "") or "")


# ── 五维评分（非重点公司满分100: 相关性25+重要性25+基本面25+证据20+来源5） ──
RELEVANCE_RULES = [
    (re.compile(r"ota|在线旅游|online travel|预订平台|booking platform|travel platform|travel tech|分销", re.I), 10),
    (re.compile(r"revpar|adr|间夜|入住率|客座率|旅客量|净开店|净增.{0,4}(客房|门店)|经营数据|运营数据", re.I), 8),
    (re.compile(r"酒店|hotel|住宿|民宿|度假村|间夜|room ?night", re.I), 6),
    (re.compile(r"航空|航司|airline|airport|机场|航班|机票", re.I), 6),
    (re.compile(r"预订|booking|gmv|gbv|交易额|订单", re.I), 5),
    (re.compile(r"携程|飞猪|美团|同程|去哪儿|华住|锦江|亚朵|首旅|万豪|希尔顿|洲际|雅高|凯悦|温德姆|"
                r"booking|expedia|airbnb|agoda|kayak|tripadvisor|达美|美联航|国航|东航|南航|海航|"
                r"春秋航空|吉祥航空|marriott|hilton|hyatt|accor", re.I), 5),
    (re.compile(r"旅游|出游|出行|游客|度假|tourism|tourist|travel", re.I), 3),
]
IMPORTANCE_RULES = [
    (re.compile(r"收购|并购|合并|融资|ipo|上市|入股|acquisition|acquire|raises|funding", re.I), 22),
    (re.compile(r"财报|业绩|营收|盈利|亏损|指引|earnings|revenue", re.I), 22),
    (re.compile(r"直订|入局|进军|新玩家|进入.{0,6}市场|流量入口|跨界.{0,4}(旅游|酒店|出行)", re.I), 25),
    (re.compile(r"监管|政策|法规|办法|规定|处罚|约谈|立法", re.I), 16),
    (re.compile(r"上线|推出|发布|开放|launch|unveil|introduce", re.I), 14),
    (re.compile(r"任命|辞任|裁员|重组|ceo|管理层变动", re.I), 14),
    (re.compile(r"运营数据|统计|旅客量|revpar|吞吐量|数据发布", re.I), 18),
    (re.compile(r"退改签|退票|改签|佣金", re.I), 12),
    (re.compile(r"新增.{0,6}航线|开通.{0,6}航线|复航", re.I), 12),
    (re.compile(r"合作|签约|战略协议|partner", re.I), 10),
]
FUNDAMENTALS_RULES = [
    (re.compile(r"revpar|adr|间夜|room ?night|take rate|佣金率|获客成本|取消率|入住率|客座率|旅客量|净增|净开店", re.I), 22),
    (re.compile(r"分销|渠道|直连|代理|佣金结构|平台化|流量入口|直订|自营平台", re.I), 18),
    (re.compile(r"新玩家|新竞争者|入局|直订|跨界.{0,4}(旅游|酒店|出行)|流量入口|挑战.{0,4}(携程|Booking|Expedia|Airbnb)", re.I), 12),
    (re.compile(r"游客量|旅游收入|出行数据|客流|春运|暑运|节假日.{0,4}数据|市场数据", re.I), 16),
    (re.compile(r"开店|门店|客房|运力|航线|新增航班|供给|机队", re.I), 14),
    (re.compile(r"竞争|市场份额|market share|竞品|对手|gbv|gmv", re.I), 12),
    (re.compile(r"签证|免签|入境|出境政策|消费政策", re.I), 14),
    (re.compile(r"ipo|上市|并购|融资|市场进入|新竞争者", re.I), 15),
]
NUMBERS_RE = re.compile(r"\d+(?:\.\d+)?\s*%|\d+\s*(?:亿|万|元|美元|天|家)|[$￥]\s*\d|\d+(?:\.\d+)?\s*(?:billion|million|bn|mn|k)\b", re.I)
PUFFERY_RE = re.compile(r"突破\s*\d+\s*家|门店突破|盛大开业|焕新升级|重磅升级|盛大启幕|荣耀启幕|盛大揭幕")
DATA_PROOF_RE = re.compile(r"净增|净开店|revpar|adr|营收|收入|利润|同比|环比|增长\s*\d|下降\s*\d|\d+%", re.I)


def _dim_score(rules, text, cap):
    s = 0
    for pat, pts in rules:
        if pat.search(text):
            s += pts
    return min(s, cap)


def _sel_evidence(item, text):
    """数据与证据质量（0-20）: 数字+摘要+可靠来源语境。"""
    s = 0
    if NUMBERS_RE.search(text):
        s += 10
    if str(item.get("summary", "") or "").strip():
        s += 6
    if _sel_source(item) >= 4:
        s += 4
    if item.get("is_core_company"):
        s += 4
    return min(s, 20)


def _sel_source(item):
    """来源质量（0-5）。"""
    src = str(item.get("source", "") or "")
    if "SEC" in src or "EDGAR" in src:
        return 5
    if any(k in src for k in ("文旅部", "交通运输部", "披露易", "民航网")):
        return 5
    # IR 官方源 (2026-08-20 新增): 公司官方新闻稿, 最高质量
    if any(k in src for k in ("Booking Holdings IR", "Expedia Group IR", "Airbnb IR")):
        return 5
    if any(k in src for k in ("Skift", "PhocusWire", "环球旅讯", "Travel Weekly", "WebInTravel",
                              "Hospitality Net", "Breaking Travel News")):
        return 4
    # Bloomberg Travel/Mobility (2026-08-20 调整): 旅游垂直 Bloomberg, 给 4 分
    if any(k in src for k in ("Bloomberg Travel", "Bloomberg Mobility")):
        return 4
    if any(k in src for k in ("Bloomberg", "Reuters", "CNBC", "WSJ", "Financial Times")):
        return 3
    return 2


def select_news_item(item, section, category):
    """单条筛选决策: 写入 §11 字段, 返回 (是否保留, 拒绝原因或None)。

    全流程确定性: 正则识别实体/类型 → 规则计分 → 阈值判定。不依赖 AI。
    """
    title = str(item.get("title", "") or "")
    summary = str(item.get("summary", "") or "")
    source = str(item.get("source", "") or "")
    text = _sel_text(item)
    reasons = []

    entity_id = identify_entity(item) or item.get("entity_id")
    is_core = entity_id in CORE_COMPANY_IDS
    ctype = classify_content_type(text)
    item["entity_id"] = entity_id
    item["is_core_company"] = is_core
    item.setdefault("source_channel", item.get("source_channel") or "")
    item["content_type"] = ctype

    def _finalize(kept, score, rejection_reason):
        item["selection_score"] = int(max(0, min(100, score)))
        item["selection_status"] = "kept" if kept else "rejected"
        item["selection_reasons"] = reasons
        item["rejection_reason"] = rejection_reason
        dims = list(DIMENSION_BY_CTYPE.get(ctype, []))
        if is_core:
            dims.append("core_company")
        for pat, dim in ((re.compile(r"分销|渠道|直连|直订|佣金", re.I), "distribution"),
                         (re.compile(r"游客|出行需求|需求", re.I), "demand"),
                         (re.compile(r"供给|开店|客房|运力|航线|机队", re.I), "supply"),
                         (re.compile(r"竞争|新玩家|入局|份额", re.I), "competition")):
            if pat.search(text) and dim not in dims:
                dims.append(dim)
        item["impact_dimensions"] = dims
        return kept, rejection_reason

    # SEC 备案文件: 重点公司强制披露, 直接保留（确定性）
    if category == "sec_filings":
        item["substantive_company_change"] = True
        item["entity_id"] = entity_id or item.get("company")
        item["is_core_company"] = (item["entity_id"] in CORE_COMPANY_IDS) or bool(item.get("company"))
        reasons.append("SEC备案(重点公司强制披露)")
        return _finalize(True, 100, None)

    # 1. 硬排除（§6）: 活动/采购/攻略/赞助/人物稿/软文/合集/短评
    hr = hard_exclude_reason(item)
    if hr:
        item["substantive_company_change"] = False
        reasons.append(f"硬排除: {hr}")
        return _finalize(False, 0, hr)

    # 2. 官方/披露来源保留清单（§8）
    official_floor = False
    if not OFFICIAL_EXCLUDE_RE.search(text):
        for key, pat in OFFICIAL_KEEP_RULES:
            if key in source and pat.search(text):
                official_floor = True
                reasons.append(f"官方来源保留清单({key})")
                break

    # 3. 东航航空业影响判定（2026-08-18 收窄: 仅保留影响 OTA 机票业务的航空新闻）
    # 东航不再享受保底加分；必须命中 CEAIR_IMPACT_RE 业务影响词且不命中 CEAIR_EXCLUDE_RE 宣传词
    ceair_floor = False
    score_boost = 0
    co_field = str(item.get("company", "") or "")
    is_ceair_item = any(a in co_field or a in title for a in CEAIR_LABELS)
    if is_ceair_item:
        if CEAIR_EXCLUDE_RE.search(text):
            item["substantive_company_change"] = False
            reasons.append("东航宣传稿排除(机器人/救援/庆典/服务升级等)")
            return _finalize(False, 0, "东航宣传稿(CiftonEXCLUDE_RE)")
        if CEAIR_REFUND_RE.search(text):
            # 14天免费退改 = 固定回归样本，高分保留
            ceair_floor = True
            reasons.append("东航14天免费退改(固定保留样本)")
            score_boost = 30
        elif CEAIR_IMPACT_RE.search(text):
            ceair_floor = True
            reasons.append("东航航空业影响(票价/退改签/运力/客座率/渠道/收费)")
            score_boost = 0
        else:
            # 命中东航标签但未命中业务影响词 → 拒绝
            item["substantive_company_change"] = False
            reasons.append("东航非业务影响(无票价/退改签/运力/客座率/渠道/收费)")
            return _finalize(False, 0, "东航非业务影响词")

    # 4. 重点公司实质动态判定
    substantive = bool(ACTION_MARKER_RE.search(text)) and ctype not in ("opinion", "general")
    if is_core and ctype == "general":
        # 有行动动词但类型未归类: 仍视为实质（如"重建营销引擎"归入 strategy_marketing 前的兜底）
        substantive = bool(ACTION_MARKER_RE.search(text))
    item["substantive_company_change"] = substantive

    # 5. 五维评分
    relevance = _dim_score(RELEVANCE_RULES, text, 25)
    importance = _dim_score(IMPORTANCE_RULES, text, 25) or 4
    fundamentals = _dim_score(FUNDAMENTALS_RULES, text, 25)
    evidence = _sel_evidence(item, text)
    src_q = _sel_source(item)
    score = relevance + importance + fundamentals + evidence + src_q
    reasons.append(f"评分(相关{relevance}/重要{importance}/基本面{fundamentals}/证据{evidence}/来源{src_q})")

    # 重点公司加分
    if is_core:
        score += 25
        reasons.append(f"重点公司({entity_id})")
        if ctype in FORMAL_POLICY_TYPES and substantive:
            score += 20
            reasons.append("正式制度/组织变化")

    # 扣分项
    if PUFFERY_RE.search(text) and not DATA_PROOF_RE.search(text):
        score -= 30
        reasons.append("品牌软文(-30)")
    # 2026-08-20: Skift/PhocusWire 等旅游垂直媒体的 opinion/analysis 是行业深度内容,
    # 不应因"没数字"就被当成泛观点扣 30 分（"Delta的德州野心"这类战略分析本身就是核心信息）
    _travel_opinion_exempt = any(k in source for k in ("Skift", "PhocusWire", "环球旅讯", "Travel Weekly"))
    if ctype == "opinion" and not NUMBERS_RE.search(text) and not _travel_opinion_exempt:
        score -= 30
        reasons.append("泛观点无新事实(-30)")
    if summary and title and difflib.SequenceMatcher(None, summary, title).ratio() >= 0.85:
        score -= 20
        reasons.append("摘要重复标题(-20)")
    if not summary.strip() and src_q <= 2:
        score -= 15
        reasons.append("只有标题无公开证据(-15)")

    # §7 准入: 重要并购/融资/IPO（专业来源语境）保底, 不受摘要缺失影响
    if category in ("industry_news", "china_industry") and src_q >= 4 and \
            re.search(r"收购|并购|合并|ipo|上市|融资|投资|acquir|merger|raises|funding", text, re.I):
        if score < CORE_KEEP_THRESHOLD:
            reasons.append("重要并购/融资保底60")
        score = max(score, CORE_KEEP_THRESHOLD)

    # 2026-08-20: 旅游垂直媒体(Skift/PhocusWire)保底 55 分准入
    # Skift 的深度分析/观点类文章 (ctype=opinion): 内容可能没有具体数字,
    # 但涉及 BKNG/EXPE/ABNB/OTA 生态的战略分析很有价值, 之前被 opinion -30 扣分后全部被拒
    # 同时豁免: Skift/PhocusWire 的 opinion 不做 "opinion无新事实 -30" 扣分
    TRAVEL_DEDICATED_SRC = any(k in source for k in ("Skift", "PhocusWire", "环球旅讯", "Travel Weekly"))
    if TRAVEL_DEDICATED_SRC:
        # +8 基础加分 (旅游垂直媒体自带行业相关性)
        score += 8
        reasons.append("旅游垂直媒体加分(+8)")
        if score < 55:
            score = 55
            reasons.append("旅游垂直媒体保底55")

    # 保底: 重点公司实质动态 / 官方保留清单 / 东航实质动态 → 最低准入分 60
    # 注：东航 14 天免费退改样本额外加 score_boost（仅 ceair_refund 路径设置过 score_boost）
    if score_boost:
        score += score_boost
        reasons.append(f"东航14天退改样本加分(+{score_boost})")
    
    # 保底: IR 官方新闻稿 / Bloomberg Travel/Mobility 垂直频道
    # 这些来源本身就是高度相关的旅游/OTA新闻, 不应因评分低被误杀
    ir_floor = bool(item.get("is_ir_source")) or ("IR" in source and entity_id in CORE_COMPANY_IDS)
    bloomberg_travel_floor = ("Bloomberg Travel" in source) or ("Bloomberg Mobility" in source)
    if ir_floor or bloomberg_travel_floor:
        if score < CORE_KEEP_THRESHOLD:
            reasons.append("IR/ Bloomberg垂直源保底60")
        score = max(score, CORE_KEEP_THRESHOLD)
    
    if (is_core and substantive) or official_floor or ceair_floor:
        if score < CORE_KEEP_THRESHOLD:
            reasons.append("实质动态/官方清单保底60")
        score = max(score, CORE_KEEP_THRESHOLD)

    kept = score >= CORE_KEEP_THRESHOLD
    if not kept:
        reasons.append("低于准入分60")
    return _finalize(kept, score, None if kept else "评分低于60且无保底资格")


REJECTED_OUTPUT = os.path.join(SCRIPT_DIR, "news_rejected_副本.json")


def run_selection_pipeline(news_data):
    """统一筛选管道入口（§9）: 对合并后的新+旧全量条目执行 select_news_item。

    被拒条目移出列表并写入 news_rejected_副本.json（标题/来源/分数/原因）;
    缓存顶层写入 selection_report（raw/kept/rejected/by_reason）。
    """
    raw_count = kept_count = rejected_count = 0
    by_reason = {}
    rejected_records = []

    for section in ("international", "domestic"):
        sec_data = news_data.get(section, {}) or {}
        for cat in list(sec_data.keys()):
            items = sec_data.get(cat, [])
            if not isinstance(items, list):
                continue
            kept = []
            for item in items:
                raw_count += 1
                ok, reason = select_news_item(item, section, cat)
                if ok:
                    kept_count += 1
                    kept.append(item)
                else:
                    rejected_count += 1
                    key = reason or "未知"
                    by_reason[key] = by_reason.get(key, 0) + 1
                    rejected_records.append({
                        "title": item.get("title", ""),
                        "source": item.get("source", ""),
                        "date": item.get("date", ""),
                        "url": item.get("url", ""),
                        "section": section,
                        "category": cat,
                        "entity_id": item.get("entity_id"),
                        "content_type": item.get("content_type"),
                        "selection_score": item.get("selection_score", 0),
                        "rejection_reason": reason,
                    })
            sec_data[cat] = kept

    # 诊断文件（被拒新闻不展示, 仅留档供调规则）
    try:
        payload = {
            "run_at": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "total_rejected": rejected_count,
            "by_reason": by_reason,
            "items": rejected_records,
        }
        tmp = REJECTED_OUTPUT + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False, indent=1)
        os.replace(tmp, REJECTED_OUTPUT)
    except Exception as e:
        print(f"  [Selection] rejected-log write failed (non-fatal): {e}")

    news_data["selection_report"] = {
        "run_at": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "raw_count": raw_count,
        "kept_count": kept_count,
        "rejected_count": rejected_count,
        "by_reason": by_reason,
    }
    print(f"  [Selection] {raw_count} raw → {kept_count} kept, {rejected_count} rejected; "
          f"top reasons: {sorted(by_reason.items(), key=lambda kv: -kv[1])[:5]}")
    return news_data


def data_quality_check(news_data):
    """数据质量检查: 空分区/无日期比例/摘要覆盖率, 报告写入 selection_report.quality。"""
    report = {"empty_categories": [], "total_items": 0,
              "unknown_date_count": 0, "no_summary_count": 0}
    total = unknown = nosum = 0
    for section in ("international", "domestic"):
        for cat, items in (news_data.get(section) or {}).items():
            if not isinstance(items, list):
                continue
            if not items:
                report["empty_categories"].append(f"{section}/{cat}")
            for it in items:
                total += 1
                if it.get("date_status") == "unknown":
                    unknown += 1
                if cat != "sec_filings" and not str(it.get("summary", "") or "").strip():
                    nosum += 1
    report["total_items"] = total
    report["unknown_date_count"] = unknown
    report["no_summary_count"] = nosum
    if total == 0:
        report["empty_categories"].append("ALL_EMPTY")
    if unknown and total and unknown / total > 0.5:
        report["empty_categories"].append("WARN_UNKNOWN_DATE_MAJORITY")
    return report


# ── 网页抓取 (国内网站) ──

# ====== 环球旅讯 (traveldaily.cn) 专用解析 ======
# 旧 generic 解析质量问题(2026-08-17 用户反馈): 日期全回退成当天、混入合作站
# 垃圾链接(ChinaTravelNews 首页)、无摘要、PR 软文多。
# 新方案: 只从两个高质量入口抓——快讯页(/expressPage/, 带精确时间戳的行业快讯)
# 与首页新闻卡片(newsCard, 含标题/摘要/时间/栏目)，再做质量筛选与去重。

TD_EXPRESS_URL = "https://www.traveldaily.cn/expressPage/"
TD_HOME_URL = "https://www.traveldaily.cn/"

# 频道抓取（规范§5）: 高优先级候选频道 ota/distribute/traveltech/ai + 条件频道 hotel/airline。
# 每条记录 source_channel。OTA 频道只是候选池, 不是无条件保留（统一走筛选管道）。
TD_CHANNELS = [
    ("ota", "https://www.traveldaily.cn/ota/"),
    ("distribute", "https://www.traveldaily.cn/distribute/"),
    ("traveltech", "https://www.traveldaily.cn/traveltech/"),
    ("ai", "https://www.traveldaily.cn/ai/"),
    ("hotel", "https://www.traveldaily.cn/hotel/"),
    ("airline", "https://www.traveldaily.cn/airline/"),
]

# 低价值内容直接排除（采购对接/活动报名/招聘广告/单店软文等）
TD_JUNK_PATTERNS = [
    r'采购需求|旅业采购|寻.*地接社|地接社.*合作',
    r'观众登记|参会登记|专业观众|报名火热|登记火热',
    r'招聘|投稿信箱|广告报价|联系我们|关于我们',
    r'门店(正式|盛大)?开业|正式开业|盛大开业',
    r'满分口碑|深度好眠|领跑',      # 单店营销软文措辞
    r'仪式落幕',                    # 颁奖/发布仪式通稿
]


def _td_parse_when(s):
    """解析环球旅讯时间: '2026-08-14 09:36' / '08-10 15:02' / '4 天前' / '6 小时前' / '昨天 12:00' → YYYY-MM-DD"""
    s = (s or '').strip()
    today = datetime.date.today()
    m = re.match(r'(\d{4})-(\d{1,2})-(\d{1,2})', s)
    if m:
        return f"{int(m.group(1)):04d}-{int(m.group(2)):02d}-{int(m.group(3)):02d}"
    m = re.match(r'(\d{1,2})-(\d{1,2})', s)
    if m:
        mo, d = int(m.group(1)), int(m.group(2))
        try:
            dt = datetime.date(today.year, mo, d)
        except ValueError:
            return None  # 非法日期(如02-30) → unknown
        # 跨年防护: 1月看到12月的 MM-DD → 上一年
        if dt > today + datetime.timedelta(days=1):
            try:
                dt = datetime.date(today.year - 1, mo, d)
            except ValueError:
                return None
        return dt.isoformat()
    m = re.match(r'(\d+)\s*天前', s)
    if m:
        return (today - datetime.timedelta(days=int(m.group(1)))).isoformat()
    if re.match(r'(\d+)\s*(小时|分钟)前', s) or s.startswith('今天'):
        return today.isoformat()
    if s.startswith('昨天'):
        return (today - datetime.timedelta(days=1)).isoformat()
    return None  # 完全无法识别 → unknown（不再兜底今天）


def _td_is_junk(title):
    return any(re.search(p, title) for p in TD_JUNK_PATTERNS)


def _td_clean_title(raw):
    t = re.sub(r'<[^>]+>', '', raw or '')
    t = t.replace('&amp;', '&').replace('&quot;', '"').replace('&#39;', "'")
    return re.sub(r'\s+', ' ', t).strip()


def _td_parse_express(html, source_name, category, max_items=15):
    """快讯页: /expressPage/{id}/ + articleItemTime 精确时间戳。"""
    items = []
    pat = re.compile(
        r'href="(/expressPage/(\d+)/)"[^>]*>([\s\S]*?)</a>'
        r'[\s\S]{0,600}?articleItemTime">(\d{4}-\d{2}-\d{2})', re.DOTALL)
    for m in pat.finditer(html):
        if len(items) >= max_items:
            break
        href, iid, title_raw, date_str = m.groups()
        title = _td_clean_title(title_raw)
        if not title or len(title) < 6 or _td_is_junk(title):
            continue
        items.append({
            "date": date_str,
            "source": source_name,
            "category": category,
            "title": title,
            "url": f"https://www.traveldaily.cn/expressPage/{iid}/",
            "summary": "",
        })
    return items


def _td_parse_home(html, source_name, category, max_items=15):
    """首页: newsCard 新闻卡片 (/article/{id}/) — 卡片为原子单元，标题+摘要+时间。

    注意必须整卡解析(anchor 起到其 </a> 止)：轮播区 href 与正文 h3 不相邻，
    早期"href 后开窗找 h3"的写法会把相邻卡片标题错配。卡片内无嵌套 <a>。
    """
    by_id = {}
    order = []
    for m in re.finditer(r'<a[^>]*class="[^"]*newsCard[^"]*"[^>]*href="(/article/(\d+)/?)"[^>]*>', html):
        href, iid = m.groups()
        end = html.find('</a>', m.end())
        seg = html[m.end():end] if end > 0 else html[m.end():m.end() + 2500]
        tm = re.search(r'<h3[^>]*class="[^"]*title[^"]*"[^>]*>([\s\S]*?)</h3>', seg)
        if not tm:
            # 精选/轮播卡用 h2(titleOverlay) 或只有 img alt，没有 h3
            tm = re.search(r'<h2[^>]*>([\s\S]*?)</h2>', seg)
        if not tm:
            tm = re.search(r'alt="([^"]{6,200})"', seg)
        if not tm:
            continue
        title = _td_clean_title(tm.group(1))
        if not title or len(title) < 6 or _td_is_junk(title):
            continue
        sm = re.search(r'<p[^>]*class="[^"]*summary[^"]*"[^>]*title="([^"]*)"', seg)
        summary = _td_clean_title(sm.group(1)) if sm else ""
        tmm = re.search(r'data-icon="clock-circle"[\s\S]{0,800}?</svg></span>\s*([^<]{2,20}?)\s*</span>', seg)
        date_str = _td_parse_when(tmm.group(1) if tmm else "")
        item = {
            "date": date_str,
            "source": source_name,
            "category": category,
            "title": title,
            "url": f"https://www.traveldaily.cn/article/{iid}/",
            "summary": summary[:200],
        }
        if iid not in by_id:
            by_id[iid] = item
            order.append(iid)
        elif summary and not by_id[iid]["summary"]:
            by_id[iid]["summary"] = summary[:200]  # 轮播卡无摘要时用列表卡的补
    items = [by_id[i] for i in order]
    return items[:max_items]


# ====== Skift /news/ 列表页补充抓取 ======
# 背景(2026-08-18 用户反馈): skift.com/feed RSS 只给最近 10 条, /news/ 列表页能看到
# 更多条目; 列表页 /news/ + /news/page/2/ 每页约 7-8 张 c-tease 卡片, 与 RSS 按 URL 去重后并入。
SKIFT_NEWS_PAGES = ("https://skift.com/news/", "https://skift.com/news/page/2/")


def fetch_skift_newspage():
    """Skift /news/ 列表页补充抓取: c-tease 卡片 (链接 aria-label 标题, URL 路径含日期)。

    卡片无摘要, summary 留空 (标题足够)。与 RSS 条目的去重在 main() 里按 _norm_url 做。
    """
    items, seen = [], set()
    for page_url in SKIFT_NEWS_PAGES:
        try:
            page = safe_request(page_url, timeout=15)
            if not page:
                print(f"    skift page fetch failed: {page_url}")
                continue
        except Exception as e:
            print(f"    skift page error ({page_url}): {e}")
            continue
        got = 0
        for m in re.finditer(r'<article class="c-tease[^"]*"[^>]*>([\s\S]*?)</article>', page):
            seg = m.group(1)
            link = re.search(r'href="(https://skift\.com/(\d{4})/(\d{2})/(\d{2})/[^"#?]+/)"', seg)
            if not link:
                continue
            url = link.group(1)
            if url in seen:
                continue
            tm = re.search(r'aria-label="([^"]+)"', seg) or re.search(r'<h[23][^>]*>\s*(?:<a[^>]*>)?\s*([^<]{10,})', seg)
            if not tm:
                continue
            items.append({
                "date": f"{link.group(2)}-{link.group(3)}-{link.group(4)}",
                "source": "Skift",
                "category": "industry_news",
                "title": html_lib.unescape(tm.group(1)).strip(),
                "url": url,
                "summary": "",
            })
            seen.add(url)
            got += 1
        print(f"    skift {urlparse(page_url).path}: {got} cards")
        time.sleep(0.4)
    return items


# ── 官方 IR 新闻稿抓取（2026-08-18 新增: 3 家核心公司 IR 直采）──
# 这三个 IR 页面用 Q4/Web CMS 模板, 通用解析器即可提取 .module--press-release 卡片
def extract_ir_q4(page_text, base_url):
    """Q4 Inc. IR 模板通用提取器: 适用于 Booking Holdings / Expedia Group / Airbnb IR 页面。

    卡片结构: <a class="module--press-release__title" href="...">标题</a>
    日期: 同卡片内的 <span class="module--press-release__time"> 或 <time datetime="...">
    """
    items = []
    seen = set()
    # 通用: 链接带 .html 或 /press-release/ 或 /news/ 的 <a> 标签, 文本 ≥ 20 字
    # 模式1: Q4 module--press-release
    pat1 = re.compile(
        r'<a[^>]+class="[^"]*module--press-release__title[^"]*"[^>]+href="([^"]+)"[^>]*>([^<]{15,300})</a>',
        re.IGNORECASE)
    # 模式2: 简化兜底 - <article>/<li> 内的 press release 链接
    pat2 = re.compile(
        r'<a[^>]+href="(/?(?:news|press-releases|press-release)/[^"]+\.html?)"[^>]*>([^<]{15,300})</a>',
        re.IGNORECASE)
    # 日期匹配: <time datetime="2026-08-15"> 或 Sep 12, 2026 形式
    date_pat = re.compile(
        r'<time[^>]+datetime="(\d{4}-\d{2}-\d{2})"|>(\d{4}-\d{2}-\d{2})<|'
        r'>([A-Z][a-z]{2}\s+\d{1,2},\s*\d{4})<', re.IGNORECASE)

    # 遍历可能的卡片分隔（Q4 用 <article> 或 <li> 包裹）
    cards = re.split(r'<(?:article|li)[^>]*class="[^"]*(?:press|news)[^"]*"[^>]*>', page_text)
    for card in cards[1:]:  # 跳过首段
        m = pat1.search(card) or pat2.search(card)
        if not m:
            continue
        href = m.group(1)
        title = html_lib.unescape(m.group(2)).strip()
        if not title or len(title) < 15:
            continue
        # 构造绝对 URL
        if href.startswith("http"):
            url = href
        elif href.startswith("/"):
            url = "https://" + urlparse(base_url).netloc + href
        else:
            url = base_url.rstrip("/") + "/" + href.lstrip("/")
        if url in seen:
            continue
        seen.add(url)
        # 日期
        date_str = ""
        dm = date_pat.search(card)
        if dm:
            if dm.group(1):
                date_str = dm.group(1)
            elif dm.group(2):
                date_str = dm.group(2)
            elif dm.group(3):
                try:
                    dt = datetime.datetime.strptime(dm.group(3), "%b %d, %Y")
                    date_str = dt.strftime("%Y-%m-%d")
                except ValueError:
                    pass
        items.append({
            "date": date_str,
            "title": title,
            "url": url,
            "summary": "",
        })
    return items


def fetch_ir_press_releases():
    """抓取 BKNG/EXPE/ABNB 3 家官方 IR 新闻稿, 返回带 entity_id/company 标签的条目列表。
    
    2026-08-20: 改为 Google News RSS 源 (替代原 Q4 Inc. JS 渲染页面)。
    Q4 Inc. IR 页面内容通过 JS 动态加载, 简单 HTTP 请求拿不到新闻列表。
    """
    all_items = []
    for src in IR_SOURCES:
        try:
            print(f"    IR {src['name']}: fetching {src['url']}")
            
            if src.get("news_selector") == "google_news":
                # Google News RSS 模式
                content = safe_request(src["url"], timeout=12, retries=1)
                if not content:
                    mark_source(src["name"], "failed", item_count=0)
                    continue
                
                items = parse_rss(content, src["name"], "industry_news", max_items=10)
                
                # 清理 Google News 标题 (去掉 " - Source" 后缀)
                for it in items:
                    en = extract_google_news_source(it.get("title", ""), src["name"])
                    if en:
                        it["title"] = en["title"]
                        # 保持 src["name"] 作为来源 (IR 专用源名)
                    it["source"] = src["name"]
                    it["category"] = "industry_news"
                    it["entity_id"] = src["entity_id"]
                    it["company"] = src["entity_id"]
                    it["is_core_company"] = True
                    it["source_channel"] = "ir_official"
                    # 标记为 IR 来源, 避免被相关性过滤误杀
                    it["is_ir_source"] = True
                
                all_items.extend(items)
                mark_source(src["name"], "success", item_count=len(items))
                print(f"    IR {src['name']}: {len(items)} items (via Google News RSS)")
            else:
                # 兜底: 旧的 Q4 解析模式
                page = safe_request(src["url"], timeout=12, retries=1)
                if not page:
                    mark_source(src["name"], "failed", item_count=0)
                    continue
                items = extract_ir_q4(page, src["url"])
                for it in items:
                    it["source"] = src["name"]
                    it["category"] = "industry_news"
                    it["entity_id"] = src["entity_id"]
                    it["company"] = src["entity_id"]
                    it["is_core_company"] = True
                    it["source_channel"] = "ir_official"
                all_items.extend(items)
                mark_source(src["name"], "success", item_count=len(items))
                print(f"    IR {src['name']}: {len(items)} cards (via Q4)")
            
            time.sleep(0.5)
        except Exception as e:
            print(f"    IR {src['name']} error: {e}")
            mark_source(src["name"], "failed", item_count=0)
    return all_items


# ── 环球旅讯国内外分类 (2026-08-18 用户需求): 国内条目留 china_industry, 国际条目并入国际行业新闻 ──
# 判定顺序: 先国内品牌/监管(如"携程收购Skyscanner"仍是国内公司新闻), 再国际品牌/市场, 默认国内
# (环球旅讯以中国旅游业报道为主, 两边都没命中的大概率是国内行业新闻)
TD_DOMESTIC_MARKERS = [
    # OTA/平台
    '携程', '飞猪', '美团', '同程', '去哪儿', '马蜂窝', '穷游', '途牛', '小红书', '抖音', '豆包', '滴滴',
    # 酒店集团
    '华住', '锦江', '首旅', '如家', '亚朵', '君亭', '东呈', '尚美', '德胧', '开元', '万达', '复星',
    # 航司/机场
    '国航', '东航', '南航', '海航', '川航', '厦航', '山航', '深航', '吉祥航空', '春秋航空',
    '九元航空', '华夏航空', '成都航空', '首都机场', '浦东机场', '白云机场', '宝安机场', '大兴机场',
    # 监管/政策
    '民航局', '文旅部', '文化和旅游', '文旅厅', '发改委', '交通运输部', '移民局', '海关', '中消协',
    # 国内市场概念（含港澳台，防止标题同时含国际地名时误判国际）
    '出境游', '入境游', '国内游', '研学', '香港', '澳门', '台湾',
]
TD_INTL_MARKERS = [
    # OTA/科技
    'Booking', 'Expedia', 'Airbnb', 'Tripadvisor', 'TripAdvisor', '谷歌', '微软', '亚马逊', 'OpenAI',
    '苹果', 'Kayak', 'Agoda', 'Trivago', 'Hopper', 'GetYourGuide', 'Viator',
    # 差旅/融资常见国际公司（traveldaily 高频出现, 2026-08-18 分流漏判后补）
    'Faye', 'Entravel', 'BCD Travel', 'Amgine', '30 Sundays', 'BizAway', 'Uniglobe',
    'Options Travel', '欧铁', 'Eurail', '全球最大差旅',
    # 国际酒店集团
    '万豪', '希尔顿', '洲际', '凯悦', '雅高', '温德姆', '四季酒店', '文华东方', '丽笙',
    # 国际航司
    '达美', '美联航', '美国航空', '汉莎', '法航', '英航', '荷航', '阿联酋航空', '卡塔尔航空',
    '新加坡航空', '全日空', '日航', '大韩航空', '酷航', '瑞安航空', '易捷', '土耳其航空',
    # 品牌/市场
    '新秀丽', '迪士尼', '环球影城', '美国', '欧洲', '中东', '日本', '韩国', '东南亚', '泰国',
    '新加坡', '越南', '马来西亚', '印尼', '印度', '澳大利亚', '英国', '法国', '德国', '非洲', '拉美',
    '意大利', '荷兰', '西班牙', '加拿大', '瑞士', '迪拜',
]


def _td_is_domestic(title, summary=""):
    """环球旅讯条目是否算国内行业新闻: 先查国内标记, 再查国际标记, 默认国内。"""
    text = f"{title} {summary}"
    for kw in TD_DOMESTIC_MARKERS:
        if kw in text:
            return True
    for kw in TD_INTL_MARKERS:
        if kw in text:
            return False
    return True


def fetch_traveldaily(source):
    """环球旅讯: 快讯页 + 首页 + 频道页（§5: source_channel 记录抓取入口）。

    频道优先级: ota/distribute/traveltech/ai 为高优先级候选池, hotel/airline 条件抓取。
    注意 OTA 频道只是候选池——所有条目最终仍走统一筛选管道（硬排除+评分），非无条件保留。
    """
    name = source["name"]
    category = source["category"]
    all_items, seen_urls = [], set()
    entries = [
        (source.get("express_url", TD_EXPRESS_URL), _td_parse_express, "express"),
        (source["url"], _td_parse_home, "home"),
    ]
    # 频道页（与首页同为 newsCard 结构, 复用 _td_parse_home）
    entries += [(url, _td_parse_home, ch) for ch, url in TD_CHANNELS]
    for url, parser, channel in entries:
        try:
            html = safe_request(url, timeout=15)
            if not html:
                print(f"    traveldaily fetch failed ({channel}): {url}")
                continue
            got = parser(html, name, category)
            added = 0
            for it in got:
                if it["url"] in seen_urls:
                    continue
                it["source_channel"] = channel
                seen_urls.add(it["url"])
                all_items.append(it)
                added += 1
            print(f"    traveldaily {channel} ({urlparse(url).path or '/'}): {added} new items")
        except Exception as e:
            print(f"    traveldaily parse error ({channel}, {url}): {e}")
        time.sleep(0.5)
    all_items.sort(key=lambda x: (x.get("date") or ""), reverse=True)
    # 国内外分流: 国际条目改标 industry_news, 由 main() 路由到国际分区
    intl_n = 0
    for it in all_items:
        if not _td_is_domestic(it.get("title", ""), it.get("summary", "")):
            it["category"] = "industry_news"
            intl_n += 1
    if all_items:
        print(f"    traveldaily split: {len(all_items) - intl_n} domestic / {intl_n} international")
    return all_items


def fetch_domestic_news():
    """Fetch news from Chinese domestic websites（改造项④⑥: 分源状态+分源过滤）。"""
    all_items = []

    for source in DOMESTIC_WEB_SOURCES:
        name = source["name"]
        url = source["url"]
        category = source["category"]
        selector = source.get("news_selector", "general")

        print(f"  Fetching {name}...")

        try:
            if selector == "hkex":
                # HKEX 披露易需要 POST 检索，走专用函数（失败返回 None）
                items = fetch_hkex_filings(
                    stock_id=source.get("stock_id", ""),
                    stock_name=source.get("stock_name", ""),
                    category=category,
                )
                if items is None:
                    mark_source(name, "failed", error_code="fetch_failed")
                    items = []
                else:
                    mark_source(name, "success", item_count=len(items))
            elif selector == "traveldaily":
                # 环球旅讯专用: 快讯页+首页双入口抓取（自带质量筛选）
                items = fetch_traveldaily(source)
                # 双入口全失败时条数会很少; 正常路径 ≥5（与 --td-only 保护一致）
                if len(items) >= 5:
                    mark_source(name, "success", item_count=len(items))
                else:
                    mark_source(name, "failed", error_code="fetch_failed",
                                item_count=len(items))
            else:
                content = safe_request(url, timeout=12, source=name)
                if not content:
                    print(f"    Failed to fetch {name}")
                    if FETCH_STATUS["sources"].get(name, {}).get("status") != "failed":
                        mark_source(name, "failed", error_code="fetch_failed")
                    continue
                items = extract_news_from_html(content, name, category, url, selector)
                mark_source(name, "success", item_count=len(items))
        except Exception as e:
            print(f"    Error fetching {name}: {e}")
            mark_source(name, "failed", error_code=_classify_request_error(e))
            items = []

        # 分源过滤（改造项⑥: 文旅部/交通部/民航网独立 include/exclude + 统计）
        items = filter_domestic_items(name, items)
        # 明文 http 来源标记（改造项②: 页面状态可见）
        if str(url).startswith("http://"):
            for it in items:
                it.setdefault("transport_security", "http")

        all_items.extend(items)
        print(f"    Found {len(items)} items from {name}")
        time.sleep(0.5)

    # 国内公司新闻 RSS（东航、36氪等）
    for feed in CN_COMPANY_FEEDS:
        name = feed["name"]
        print(f"  Fetching company feed: {name}...")
        content = safe_request(feed["url"], timeout=12, source=name)
        if content:
            items = parse_rss(content, name, feed["category"], max_items=15)
            for it in items:
                # Google News 标题带 " - 来源" 后缀，抽取真实来源
                ext = extract_google_news_source(it["title"], name)
                if ext:
                    it["title"] = ext["title"]
                    it["source"] = ext["source"]
                # 仅当 feed 配置了 company 字段时才打公司标签（36氪无 company, 是来源而非公司）
                if feed.get("company"):
                    it["company"] = feed["company"]
            # 分源过滤（36氪 include/exclude 等）
            items = filter_domestic_items(name, items)
            all_items.extend(items)
            mark_source(name, "success", item_count=len(items))
            print(f"    Found {len(items)} items from {name}")
        else:
            if FETCH_STATUS["sources"].get(name, {}).get("status") != "failed":
                mark_source(name, "failed", error_code="fetch_failed")
            print(f"    Failed to fetch feed {name}")
        time.sleep(0.5)

    # 过滤统计并入来源状态（诊断/测试断言用）
    for name, stats in DOMESTIC_FILTER_STATS.items():
        rec = FETCH_STATUS["sources"].setdefault(name, {})
        rec["filter"] = dict(stats)

    return all_items


def extract_news_from_html(html, source_name, category, base_url, selector_type, max_items=10):
    """Extract news from HTML with category-specific parsing."""
    items = []
    
    try:
        # Clean HTML - remove scripts and styles
        html_clean = re.sub(r'<script[^>]*>.*?</script>', '', html, flags=re.DOTALL | re.IGNORECASE)
        html_clean = re.sub(r'<style[^>]*>.*?</style>', '', html_clean, flags=re.DOTALL | re.IGNORECASE)
        html_clean = re.sub(r'<!--.*?-->', '', html_clean, flags=re.DOTALL)
        
        if selector_type == 'gov_list':
            # 政府网站新闻列表（文旅部/交通运输部）
            items = extract_gov_list(html_clean, source_name, category, base_url, max_items)
        elif selector_type == 'caac':
            # CAAC News (中国民航网) - specific parser for caacnews.com.cn
            items = extract_caac_news(html_clean, source_name, category, base_url, max_items)
        elif selector_type == 'sina_search':
            # Sina search results - specific parser for search.sina.com.cn
            items = extract_sina_search_news(html_clean, source_name, category, base_url, max_items)
        else:
            # Generic news extraction
            items = extract_generic_news(html_clean, source_name, category, base_url, max_items)
        
    except Exception as e:
        print(f"    Parse error for {source_name}: {e}")
    
    return items


def extract_caac_news(html, source_name, category, base_url, max_items):
    """Parse CAAC News (caacnews.com.cn) and keep only 东航-related items.

    用于补充"东航官网新闻公告"：东航官网 IR 子站(wcm.ceair.com)已无法解析，
    改从行业权威源中国民航网筛选东航相关新闻，company 固定标注为 中国东航。
    """
    items = []
    parsed = urlparse(base_url)
    base_domain = f"{parsed.scheme}://{parsed.netloc}"

    # Find news links with URL patterns containing tYYYYMMDD_ID
    # e.g., /tt/202608/t20260805_1396558.html or ./tt/202608/t20260805_1396558.html
    news_pattern = r'<a[^>]*href=["\']([^"\']*t(\d{8})_(\d+)[^"\']*)["\'][^>]*>(.*?)</a>'
    matches = re.findall(news_pattern, html, re.IGNORECASE | re.DOTALL)

    seen_urls = set()
    
    for href, date_ymd, id_num, title_raw in matches:
        if len(items) >= max_items:
            break
        
        # Clean title
        title = re.sub(r'<[^>]+>', '', title_raw).strip()
        if not title or len(title) < 4:
            continue

        # 只保留东航相关新闻
        if not any(kw in title for kw in ("东航", "东方航空")):
            continue

        # Skip non-news links by title
        skip_titles = ['更多', '详细', '首页', '上一页', '下一页', '末页', '民航图书', '投稿信箱', '联系我们', '投 稿', '关于我们', '广告报价']
        if title in skip_titles or title.endswith('更多...'):
            continue
        
        # Skip non-news URL paths (check href before building full URL)
        skip_paths = ['/gywm/', '/ggbj/', '/gg/ztyx/', '/gg/xxfwpt/']
        if any(p in href for p in skip_paths):
            continue
        
        # Build URL
        if href.startswith('http'):
            url = href
        elif href.startswith('./'):
            url = base_domain + '/' + href[2:]
        elif href.startswith('/'):
            url = base_domain + href
        else:
            url = base_domain + '/' + href
        
        if url in seen_urls:
            continue
        seen_urls.add(url)
        
        # Parse date from URL: tYYYYMMDD_ID
        year = date_ymd[:4]
        month = date_ymd[4:6]
        day = date_ymd[6:8]
        
        try:
            date_str = f"{year}-{month}-{int(day):02d}"
        except ValueError:
            date_str = None
        
        # company 固定标注为 中国东航（本函数已按东航关键词过滤）
        company_tag = "中国东航"

        items.append({
            "date": date_str,
            "title": title,
            "url": url,
            "source": source_name,
            "category": category,
            "company": company_tag,
        })
    
    return items


def extract_sina_search_news(html, source_name, category, base_url, max_items):
    """Parse Sina search results page (search.sina.com.cn)."""
    items = []
    
    # Pattern for Sina search result items
    # Each result has: <h2><a href="URL" target="_blank">TITLE</a></h2>
    # followed by a snippet and a date like "2026-08-14 10:47:59" or "2026年08月14日..."
    
    # Find all result blocks - they typically have <h2> with links
    result_pattern = r'<h2[^>]*>\s*<a[^>]*href=["\']([^"\']+)["\'][^>]*target=["\']_blank["\'][^>]*>\s*([^<]+)\s*</a>\s*</h2>'
    matches = re.findall(result_pattern, html, re.IGNORECASE)
    
    if not matches:
        # Try alternative: some results use different structure
        result_pattern2 = r'<h2[^>]*>\s*<a[^>]*href=["\']([^"\']+)["\'][^>]*>\s*([^<]+)\s*</a>\s*</h2>'
        matches = re.findall(result_pattern2, html, re.IGNORECASE)
    
    # Also look for date patterns near each result
    # Sina typically shows dates like: "2026-08-14 10:47:59" or "2026-08-14"
    date_after_pattern = r'(\d{4}[-/]\d{1,2}[-/]\d{1,2}(?:\s+\d{1,2}:\d{2}:\d{2})?)'
    
    for i, (url, title_raw) in enumerate(matches):
        if i >= max_items:
            break
        
        # Clean title (remove HTML tags, especially em/strong tags from highlighting)
        title = re.sub(r'</?em[^>]*>', '', title_raw, flags=re.IGNORECASE)
        title = re.sub(r'</?strong[^>]*>', '', title, flags=re.IGNORECASE)
        title = title.strip()
        
        if not title or len(title) < 5:
            continue
        
        # Make URL absolute
        if url.startswith('//'):
            url = 'https:' + url
        elif url.startswith('/'):
            url = 'https://search.sina.com.cn' + url
        
        # Try to find a date near this result in the HTML
        # Look for the result position and search nearby
        date_str = ""
        
        # Search the HTML chunk around this match
        search_start = max(0, html.find(title_raw) - 50)
        search_end = min(len(html), html.find(title_raw) + 500)
        nearby_html = html[search_start:search_end]
        
        date_match = re.search(date_after_pattern, nearby_html)
        if date_match:
            date_str = date_match.group(1)
            # Normalize date format
            date_str = date_str.replace('/', '-')
            # Extract just the date part (YYYY-MM-DD)
            date_parts = date_str.split(' ')
            if date_parts:
                date_str = date_parts[0]
        
        if not date_str:
            date_str = None  # 未知日期交给 apply_date_fields
        
        # Clean up title - remove source suffix like " - 来源"
        title = re.sub(r'\s*[-–—]\s*[^-–—]+$', '', title)
        title = title.strip()
        
        items.append({
            "date": date_str,
            "title": title,
            "url": url,
            "source": source_name,
            "category": category,
            "company": "中国东航",
        })
    
    return items


def extract_generic_news(html, source_name, category, base_url, max_items):
    """Generic news extraction from Chinese websites."""
    items = []
    parsed = urlparse(base_url)
    base_domain = f"{parsed.scheme}://{parsed.netloc}"
    
    # Strategy 1: Find links with dates nearby (most reliable for news sites)
    # Look for patterns like: <a href="...">Title</a>\n<span>2024-01-15</span>
    date_link_patterns = [
        # Link followed by date in various formats
        r'<a[^>]*href=["\']([^"\']+)["\'][^>]*>\s*([^<]{8,200})\s*</a>\s*<[^>]*class="[^"]*date[^"]*"[^>]*>\s*(\d{4}[-/]\d{1,2}[-/]\d{1,2})',
        # Date before link
        r'(\d{4}[-/]\d{1,2}[-/]\d{1,2})\s*<a[^>]*href=["\']([^"\']+)["\'][^>]*>\s*([^<]{8,200})\s*</a>',
        # Link with date in title
        r'<a[^>]*href=["\']([^"\']+)["\'][^>]*title=["\']([^"\']{8,200})["\'][^>]*>\s*([^<]{8,200})\s*</a>',
    ]
    
    found_urls = set()
    
    for pattern in date_link_patterns:
        matches = re.findall(pattern, html, re.IGNORECASE | re.DOTALL)
        for match in matches:
            try:
                if len(match) == 3:
                    if re.search(r'\d{4}', match[0]):
                        # date, url, title
                        date_str, href, title = match
                    elif re.search(r'\d{4}', match[2]):
                        # url, title_with_date, extra
                        href = match[0]
                        title = match[1]
                        date_match = re.search(r'(\d{4}[-/]\d{1,2}[-/]\d{1,2})', match[1])
                        date_str = date_match.group(1) if date_match else None
                    else:
                        href = match[0]
                        title = match[1]
                        date_str = None  # 未知日期交给 apply_date_fields
                else:
                    continue
                
                title = title.strip()
                href = href.strip()
                
                if not title or len(title) < 6:
                    continue
                    
                # Normalize URL
                if href.startswith('/'):
                    href = f"{base_domain}{href}"
                elif not href.startswith('http'):
                    continue
                
                if href in found_urls:
                    continue
                    
                found_urls.add(href)
                date_str = date_str.replace('/', '-')
                
                items.append({
                    "date": date_str,
                    "source": source_name,
                    "category": category,
                    "title": title,
                    "url": href,
                    "summary": "",
                })
                
                if len(items) >= max_items:
                    return items
                    
            except (IndexError, ValueError):
                continue
    
    # Strategy 2: Find all links and filter by content quality
    if len(items) < 3:
        link_pattern = r'<a[^>]*href=["\']([^"\']+)["\'][^>]*>([^<]{6,200})</a>'
        all_links = re.findall(link_pattern, html, re.IGNORECASE)
        
        quality_keywords = ['通知', '公告', '新闻', '发布', '报告', '资讯', '动态', '政策', 
                           '意见', '办法', '规定', '条例', '计划', '方案', '指引',
                           'news', 'report', 'announcement', 'update']
        
        for href, title in all_links:
            title = title.strip()
            if len(title) < 6:
                continue
            
            # Skip navigation items
            nav_words = ['首页', '关于', '联系', '登录', '注册', '更多', '下一页', '上一页',
                        'index', 'javascript', 'mailto:', '#', 'search', 'login', 'about',
                        'copyright', '版权', 'ICP', '备案']
            
            if any(w in title.lower() for w in nav_words):
                continue
            
            # Check if link looks like a news article
            is_quality = any(kw in title.lower() for kw in quality_keywords)
            is_long = len(title) > 15
            
            if not is_quality and not is_long:
                continue
                
            # Normalize URL
            if href.startswith('/'):
                href = f"{base_domain}{href}"
            elif not href.startswith('http'):
                continue
            
            if href in found_urls:
                continue
            found_urls.add(href)
            
            # Try to find date near this link
            date_str = None  # 未找到发布日期 → unknown
            link_pos = html.find(href)
            if link_pos >= 0:
                context = html[max(0, link_pos - 300):link_pos + 100]
                date_match = re.search(r'(\d{4}[-/]\d{1,2}[-/]\d{1,2})', context)
                if date_match:
                    date_str = date_match.group(1).replace('/', '-')
            
            items.append({
                "date": date_str,
                "source": source_name,
                "category": category,
                "title": title,
                "url": href,
                "summary": "",
            })
            
            if len(items) >= max_items:
                break
    
    # Sort by date (unknown→'' 沉底)
    items.sort(key=lambda x: x.get('date') or '', reverse=True)
    return items


def fetch_hkex_filings(stock_id, stock_name, category, lookback_days=56, max_items=30):
    """Fetch filings from HKEX 披露易 via POST title search (tested working).

    接口: POST https://www1.hkexnews.hk/search/titlesearch.xhtml
    关键点: stockId 是披露易内部ID（非股票代码），需经 prefix.do 查询；
    日期字段必须用 JSF 命名 titleSearchByAllResult.dateFromUi/dateToUi (dd/MM/yyyy)
    才能生效，返回按发布时间倒序。
    """
    items = []
    if not stock_id:
        return items

    today = datetime.date.today()
    date_from = today - datetime.timedelta(days=lookback_days)

    form = {
        "lang": "ZH",
        "category": "0",
        "market": "SEHK",
        "stockId": stock_id,
        "documentType": "-1",
        "titleSearchByAllResult.dateFromUi": date_from.strftime("%d/%m/%Y"),
        "titleSearchByAllResult.dateToUi": today.strftime("%d/%m/%Y"),
        "titleSearchResultControl.searchByIndex": "0",
    }
    data = urllib.parse.urlencode(form).encode("utf-8")

    try:
        req = urllib.request.Request(
            "https://www1.hkexnews.hk/search/titlesearch.xhtml",
            data=data,
            headers={
                "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36",
                "Content-Type": "application/x-www-form-urlencoded",
                "Referer": "https://www1.hkexnews.hk/search/titlesearch.xhtml",
            },
        )
        with urlopen_safe(req, timeout=25) as resp:
            html = resp.read().decode("utf-8", errors="replace")
    except Exception as e:
        print(f"    HKEX request failed: {e}")
        return None  # 请求失败（区别于成功但 0 条公告）

    # 每条公告一个 <tr>，含 release-time / doc-link / headline
    for row in re.findall(r"<tr>(.*?)</tr>", html, re.DOTALL | re.IGNORECASE):
        if "/listedco/" not in row:
            continue

        m_time = re.search(r'(\d{2}/\d{2}/\d{4})\s+(\d{2}:\d{2})', row)
        if not m_time:
            continue
        try:
            dt = datetime.datetime.strptime(m_time.group(1), "%d/%m/%Y")
            date_iso = dt.strftime("%Y-%m-%d")
        except ValueError:
            continue
        # 超出保留窗口的直接跳过（列表按时间倒序，可提前终止）
        if (today - dt.date()).days > lookback_days:
            break

        m_link = re.search(r'<a[^>]+href="(/listedco/[^"]+)"[^>]*>(.*?)</a>', row, re.DOTALL)
        title = ""
        url = ""
        if m_link:
            url = "https://www1.hkexnews.hk" + m_link.group(1)
            title = re.sub(r"<[^>]+>", " ", m_link.group(2))
            title = re.sub(r"\s+", " ", title).strip()

        m_head = re.search(r'<div class="headline">(.*?)</div>', row, re.DOTALL)
        headline = ""
        if m_head:
            headline = re.sub(r"<[^>]+>", " ", m_head.group(1))
            headline = re.sub(r"\s+", " ", headline).strip()
            headline = headline.replace("公告及通告 -", "").strip(" []")

        if not title:
            continue

        items.append({
            "date": date_iso,
            "source": f"披露易·{stock_name}",
            "category": category,
            "company": stock_name,
            "title": title,
            "url": url,
            "summary": headline,
        })
        if len(items) >= max_items:
            break

    return items


def _gov_date_from_url(href):
    """政府站 URL 日期兜底: t20260814_12345.html → '2026-08-14'（无则 None）。"""
    m = re.search(r"t(\d{4})(\d{2})(\d{2})_\d+\.html?", href)
    if not m:
        return None
    try:
        datetime.date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
    except ValueError:
        return None
    return f"{m.group(1)}-{m.group(2)}-{m.group(3)}"


def extract_gov_list(html, source_name, category, base_url, max_items=15):
    """Parse government news list pages (文旅部 / 交通运输部).

    交通运输部: <a href="./202608/t20260814_x.html" class="news-link">
                <span class="news-title">标题</span><span class="news-date">2026-08-14</span>
    文旅部:     <a href="./202608/t20260805_x.htm" title="标题">..</a> 同行 <td class="bt_time">2026-08-05</td>

    日期优先级（改造项⑤, 2026-08-18）: 列表显式日期 → URL tYYYYMMDD → None(unknown)。
    历史问题: 列表结构变化时 span 日期抓不到就整批兜底成"今天"，
    曾出现交通运输部 10 条新闻日期集体错误。现在宁可 unknown 也不造假日期。
    """
    items = []
    parsed = urlparse(base_url)
    origin = f"{parsed.scheme}://{parsed.netloc}"
    # base_url 目录，用于解析相对路径
    base_dir = base_url.rsplit("/", 1)[0] + "/"

    def resolve(href):
        href = href.strip()
        if href.startswith("http"):
            return href
        if href.startswith("./"):
            return base_dir + href[2:]
        if href.startswith("/"):
            return origin + href
        return base_dir + href

    seen = set()
    # 模式1: 交通运输部 news-link 结构
    for m in re.finditer(
        r'<a[^>]+href="([^"]+)"[^>]*class="news-link"[^>]*>(.*?)</a>',
        html, re.DOTALL,
    ):
        href, block = m.group(1), m.group(2)
        t = re.search(r'<span[^>]*class="news-title"[^>]*>(.*?)</span>', block, re.DOTALL)
        d = re.search(r'<span[^>]*class="news-date"[^>]*>([\d\-]+)</span>', block, re.DOTALL)
        title = re.sub(r"<[^>]+>", "", t.group(1)).strip() if t else ""
        date = _valid_date_str(d.group(1).strip()) if d else None
        if not title or not re.search(r"t\d{8}_\d+\.html?", href):
            continue
        url = resolve(href)
        if url in seen:
            continue
        seen.add(url)
        items.append({
            "date": date or _gov_date_from_url(href),  # 列表日期 → URL日期 → None
            "source": source_name,
            "category": category,
            "title": title,
            "url": url,
            "summary": "",
        })
        if len(items) >= max_items:
            return items

    # 模式2: 文旅部 表格行结构（title 属性 + bt_time 日期列）
    for m in re.finditer(
        r'<a[^>]+href="([^"]*t20\d{6,8}_\d+\.html?)"[^>]*title="([^"]+)"[^>]*>.*?'
        r'(\d{4}-\d{2}-\d{2})',
        html, re.DOTALL,
    ):
        href, title, date = m.group(1), m.group(2).strip(), m.group(3)
        if not title:
            continue
        url = resolve(href)
        if url in seen:
            continue
        seen.add(url)
        items.append({
            "date": _valid_date_str(date) or _gov_date_from_url(href),
            "source": source_name,
            "category": category,
            "title": title,
            "url": url,
            "summary": "",
        })
        if len(items) >= max_items:
            break

    return items


# ── 缓存管理 ──

CACHE_BACKUP_DIR = os.path.join(os.path.dirname(OUTPUT), "news_cache_backups")
CACHE_MAX_BACKUPS = 3


def _rotate_backups():
    """Rotate backup files: keep last N, delete oldest."""
    os.makedirs(CACHE_BACKUP_DIR, exist_ok=True)
    backups = sorted([f for f in os.listdir(CACHE_BACKUP_DIR) if f.endswith('.json')])
    while len(backups) >= CACHE_MAX_BACKUPS:
        oldest = backups.pop(0)
        os.remove(os.path.join(CACHE_BACKUP_DIR, oldest))


def _backup_current_cache():
    """Backup current cache before overwrite (timestamped copy)."""
    if not os.path.exists(OUTPUT):
        return
    os.makedirs(CACHE_BACKUP_DIR, exist_ok=True)
    ts = time.strftime('%Y%m%d_%H%M%S')
    backup_path = os.path.join(CACHE_BACKUP_DIR, f'news_data_{ts}.json')
    try:
        shutil.copy2(OUTPUT, backup_path)
        _rotate_backups()
        backups = sorted([f for f in os.listdir(CACHE_BACKUP_DIR) if f.endswith('.json')])
        print(f"  Backup created: {backup_path} (kept {len(backups)} versions)")
    except Exception as e:
        print(f"  Backup failed (non-fatal): {e}")


def load_cache():
    try:
        if os.path.exists(OUTPUT):
            mtime = os.path.getmtime(OUTPUT)
            age_hours = (time.time() - mtime) / 3600
            with open(OUTPUT) as f:
                data = json.load(f)
            # Integrity check: must have both sections
            if not isinstance(data, dict):
                raise ValueError("Cache root is not a dict")
            if 'international' not in data and 'domestic' not in data:
                raise ValueError("Cache missing both international and domestic sections")
            # Check that at least one category has data
            total_items = 0
            for sec in ('international', 'domestic'):
                if sec in data and isinstance(data[sec], dict):
                    for cat, items in data[sec].items():
                        if isinstance(items, list):
                            total_items += len(items)
            if total_items == 0:
                raise ValueError("Cache has zero items across all categories")
            print(f"Loaded cache (age {age_hours:.1f}h, {total_items} total items)")
            return data, age_hours
    except json.JSONDecodeError as e:
        print(f"Cache corrupted (JSON decode error): {e}")
        # Try restore from latest backup
        restored = _restore_from_backup()
        if restored:
            return restored, 999
    except Exception as e:
        print(f"Cache load failed: {e}")
    print("No valid cache found, will do full fetch")
    return None, 999


def _restore_from_backup():
    """Try to restore latest backup when main cache is corrupted."""
    os.makedirs(CACHE_BACKUP_DIR, exist_ok=True)
    backups = sorted([f for f in os.listdir(CACHE_BACKUP_DIR) if f.endswith('.json')])
    for backup_file in reversed(backups):
        try:
            backup_path = os.path.join(CACHE_BACKUP_DIR, backup_file)
            with open(backup_path) as f:
                data = json.load(f)
            total = sum(len(v) for sec in data.values() if isinstance(sec, dict) for v in sec.values() if isinstance(v, list))
            if total > 0:
                print(f"  Restored from backup: {backup_file} ({total} items)")
                # Restore to main cache location
                with open(OUTPUT, 'w') as f:
                    json.dump(data, f, ensure_ascii=False, indent=2)
                return data
        except Exception:
            continue
    print("  No valid backup found, starting fresh")
    return None


def save_cache(data):
    try:
        _backup_current_cache()
        # Atomic write: write to temp file first, then rename
        tmp_path = OUTPUT + '.tmp'
        with open(tmp_path, 'w') as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        os.replace(tmp_path, OUTPUT)
        total = sum(len(v) for sec in data.values() if isinstance(sec, dict) for v in sec.values() if isinstance(v, list))
        print(f"Saved to cache: {OUTPUT}")
        print(f"File size: {os.path.getsize(OUTPUT):,} bytes, {total} total items")
    except Exception as e:
        print(f"Cache save failed: {e}")
        # Try to remove temp file if it exists
        if os.path.exists(OUTPUT + '.tmp'):
            os.remove(OUTPUT + '.tmp')


# 跟踪参数（去重时剥离）: utm_* 全家族 + 常见点击追踪参数
_TRACKING_PARAM_RE = re.compile(
    r'^(utm_[a-z0-9_]+|fbclid|gclid|gbraid|wbraid|msclkid|igshid|ref|source|mc_cid|mc_eid|spm|scm|vd_source|share_token)$',
    re.IGNORECASE,
)


def _norm_url(u):
    """归一化 URL 用于去重（改造项⑦, 2026-08-18）:

    1. 去掉 #fragment（纯锚点不改变文章）
    2. 剥离跟踪参数 utm_* / fbclid / gclid / spm 等（同一文章带不同投放参数）
    3. 去掉结尾斜杠（traveldaily /article/190541 与 /article/190541/）
    4. scheme+host 小写
    """
    if not u or not isinstance(u, str):
        return u or ""
    s = u.strip()
    # 去 fragment
    s = s.split('#', 1)[0]
    # 拆 query
    base, _, query = s.partition('?')
    if query:
        kept = []
        for kv in query.split('&'):
            if not kv:
                continue
            key = kv.split('=', 1)[0]
            if not _TRACKING_PARAM_RE.match(key):
                kept.append(kv)
        s = base + ('?' + '&'.join(kept) if kept else '')
    # scheme/host 小写
    m = re.match(r'^([a-zA-Z]+)://([^/]+)(.*)$', s)
    if m:
        s = f"{m.group(1).lower()}://{m.group(2).lower()}{m.group(3)}"
    return s.rstrip('/')


def _is_google_news_url(u):
    return bool(u) and 'news.google.com' in str(u)


# 来源权威度（同文/同事件裁决用; 数值越高越优先保留）
SOURCE_RANK_MAP = {
    "SEC EDGAR": 100,
    "Booking Holdings IR": 95, "Expedia Group IR": 95, "Airbnb IR": 95,
    "Bloomberg": 90, "Bloomberg Markets": 90, "Bloomberg Technology": 90,
    "Bloomberg Travel (GN)": 88, "Bloomberg Mobility (GN)": 88,
    "Wall Street Journal": 85, "WSJ": 85,
    "Financial Times": 80, "FT": 80,
    "Reuters": 78,
    "CNBC": 75,
    "Skift": 70, "PhocusWire": 70, "环球旅讯": 70,
    "Expedia": 72, "Booking.com": 72, "Airbnb": 72,
    "文旅部": 65, "交通运输部": 65, "民航网": 60, "披露易": 60,
    "Travel Weekly": 58,
}
# 官方公告/公司官方来源（同事件优先当主条目）
OFFICIAL_SOURCE_RE = re.compile(r'SEC|EDGAR|披露易|文旅部|交通运输部|民航网|官方网站|Newsroom|IR|Investor Relations|investors\.', re.IGNORECASE)


def _source_rank(item):
    src = str(item.get("source", "") or "")
    if src in SOURCE_RANK_MAP:
        rank = SOURCE_RANK_MAP[src]
    else:
        rank = 50
        for k, v in SOURCE_RANK_MAP.items():
            if k.lower() in src.lower():
                rank = max(rank, v)
        if OFFICIAL_SOURCE_RE.search(src):
            rank = max(rank, 80)
    # Google News 中转 URL 降权（原始出处链接优先）
    if _is_google_news_url(item.get("url")):
        rank -= 25
    return rank


def _norm_title(t):
    """标题归一化用于同文判定: HTML实体还原 + NFKC + 去标点/空白 + 小写。"""
    if not t:
        return ""
    t = html.unescape(str(t))
    t = unicodedata.normalize('NFKC', t)
    # 去掉常见来源后缀
    t = re.sub(r'\s*[-–—|]\s*(Bloomberg|Reuters|CNBC|WSJ|Skift|环球旅讯|民航网)\s*$', '', t, flags=re.IGNORECASE)
    t = re.sub(r'[^\w\u4e00-\u9fff]+', '', t, flags=re.UNICODE)
    return t.lower().strip()


def _dates_within(d1, d2, days=3):
    """两个 'YYYY-MM-DD' 间隔 ≤ days 天; 任一无效返回 None（无法判定）。"""
    try:
        a = datetime.datetime.strptime(d1, "%Y-%m-%d").date()
        b = datetime.datetime.strptime(d2, "%Y-%m-%d").date()
    except (ValueError, TypeError):
        return None
    return abs((a - b).days) <= days


def dedupe_same_article(items):
    """第二级去重: 同一篇文章的不同 URL（转载/Google News 中转/跟踪参数变体）。

    判定: 归一化标题完全一致 + 公司一致(或均无) + 发布日期间隔≤3天(或未知)。
    相隔>3天的同名标题视为不同文章（如东航周期性服务公告）各自保留。
    裁决: 官方/权威来源优先, 非 Google News URL 优先; 落选条目直接移除
    （同一文章不保留多条）, 主条目记录 merged_same_article 数量。
    """
    if len(items) <= 1:
        return items
    clusters = {}   # norm_title -> [items]
    order = []      # (key or None, item) 保持首现顺序
    for it in items:
        key = _norm_title(it.get("title", ""))
        if not key:
            order.append((None, it))
            continue
        if key not in clusters:
            clusters[key] = []
            order.append((key, it))
        join = True
        for member in clusters[key]:
            co_a = str(it.get("company", "") or "")
            co_b = str(member.get("company", "") or "")
            if co_a and co_b and co_a != co_b:
                continue
            if _dates_within(it.get("date") or "", member.get("date") or "", 3) is False:
                join = False
                break
        if join:
            clusters[key].append(it)
        else:
            order.append((None, it))  # 同名但时间相隔远 → 独立条目
    result = []
    emitted = set()
    for key, it in order:
        if key is None:
            result.append(it)
            continue
        if key in emitted:
            continue
        emitted.add(key)
        grp = clusters[key]
        if len(grp) == 1:
            result.append(it)
        else:
            primary = max(grp, key=_source_rank)
            primary["merged_same_article"] = len(grp) - 1
            result.append(primary)
    return result


def _title_similarity(a, b):
    if not a or not b:
        return 0.0
    return difflib.SequenceMatcher(None, a, b).ratio()


def group_same_events(items, window_hours=72, sim_threshold=0.72, ceair_aggressive=True):
    """第三级去重: 同一事件的多篇不同报道 → 折叠为主条目 + related_sources。

    判定: 归一化标题相似度≥0.72 且发布时间间隔≤72小时（双方日期已知）。
    处理: 不删除——非主条目标 folded_into=主条目URL（前端隐藏）,
    主条目携带 event_id + related_sources=[各来源名]。
    主条目裁决: 官方公告 > 权威媒体 > 行业媒体; 非 Google News URL 优先。

    ceair_aggressive (2026-08-20): True 时对东航(CEAIR)相关新闻启用更激进去重
    —— 多家国内媒体转载"东航14天免费退改"等同一事件时, 标题差异很小（前缀不同）,
    0.72 阈值可能漏过。此时额外用东航业务关键词归一化后相似度≥0.55 即折叠。
    """
    known = [it for it in items if _valid_date_str(it.get("date"))]
    if len(known) <= 1:
        return items
    # 解析日期为 date 对象
    def _d(it):
        return datetime.datetime.strptime(it["date"], "%Y-%m-%d").date()
    used = [False] * len(known)
    out = list(items)

    # 东航特定归一化（去掉来源前缀、统一"东航"）
    def _ceair_norm(t):
        if not t:
            return ""
        t = t.lower()
        # Step 1: 去掉"来源后缀"——必须是结尾的 [分隔符 + 来源名]
        # 之前用 .* 贪婪匹配导致第一个 :|— 之后所有内容都被吞了!
        # 正确做法: 从右向左扫, 只处理结尾形如 "...-新京报"、"...｜观察者网"
        suffix_srcs = ["新京报", "观察者网", "观察者", "中国科技网", "eeo.com.cn",
                       "经济观察报", "东方财富", "澎湃新闻", "界面新闻", "21世纪经济报道"]
        for s in suffix_srcs:
            # 结尾的 [—\-–｜|:：·空格]* + 源名 + 可能的"网/报"后缀
            pattern = r'[—\-–｜|:：·\s]*' + re.escape(s) + r'\s*$'
            new_t, n = re.subn(pattern, '', t)
            if n:
                t = new_t.strip()
        # Step 2: 去掉开头以来源名开头 + 分隔符的情况（例: "新京报：..."、"观察者|..."）
        for s in suffix_srcs:
            pattern = r'^' + re.escape(s) + r'[^a-zA-Z\u4e00-\u9fff]{0,5}'
            t = re.sub(pattern, '', t)
        # Step 3: "中国东航" → "东航"
        t = re.sub(r'^中国', '', t)
        # Step 4: 统一措辞
        t = t.replace('零手续费退改', '免费退改')
        t = t.replace('免费退改签', '免费退改')
        t = t.replace('全舱位14天', '14天')
        for ch in ['机票', '客票', '规则']:
            t = t.replace(ch, '')
        for sw in ['推行', '发布']:
            t = t.replace(sw, '推出')
        t = t.replace('按下……按钮', '')
        # 去掉标点符号
        t = re.sub(r'[^\w\u4e00-\u9fff]+', '', t, flags=re.UNICODE)
        return t.strip()

    for i in range(len(known)):
        if used[i]:
            continue
        cluster = [i]
        for j in range(i + 1, len(known)):
            if used[j]:
                continue
            hours = abs((_d(known[i]) - _d(known[j])).days) * 24
            if hours > window_hours:
                continue
            sim_base = _title_similarity(_norm_title(known[i].get("title", "")),
                                         _norm_title(known[j].get("title", "")))
            if sim_base >= sim_threshold:
                # PhocusWire Briefs 子条目不互相折叠
                if known[i].get("source") == "PhocusWire Briefs" and \
                   known[j].get("source") == "PhocusWire Briefs":
                    continue
                cluster.append(j)
                used[j] = True
                continue
            # CEAIR 激进去重: 东航同事件衍生报道（评论/热搜/二次报道）识别
            # 阈值从 0.55 下调到 0.30 —— "东航14天免费退改" 的衍生报道差异大:
            #   "网友喊话其他航司跟进" (sim≈0.36) / "冲上热搜" (≈0.52) / "民航服务内卷" (≈0.42)
            # 实际上都是围绕同一事件的社会评论/二次报道, 应折叠为主条目的 related_sources
            # 额外规则: 共享核心关键词组（免费+退改）直接判定同事件。
            if ceair_aggressive:
                ti = known[i].get("title", "")
                tj = known[j].get("title", "")
                if re.search(r'东航|东方航空|中国东航', ti) and re.search(r'东航|东方航空|中国东航', tj):
                    biz_re = re.compile(r'退改|退票|改签|免费|手续费|运力|航班|暑运|航线|客座率|机票|客票|规则|退改签|退改新规|退改按钮', re.I)
                    if biz_re.search(ti) and biz_re.search(tj):
                        ceair_sim = _title_similarity(_ceair_norm(ti), _ceair_norm(tj))
                        if ceair_sim >= 0.30:
                            cluster.append(j)
                            used[j] = True
                            continue
                        # 关键词覆盖: 都命中 "免费+退改" → 必然同一事件（即使 sim<0.30）
                        if ('免费' in ti and ('退改' in ti or '退改签' in ti or '退票' in ti or '改签' in ti)) and \
                           ('免费' in tj and ('退改' in tj or '退改签' in tj or '退票' in tj or '改签' in tj)):
                            cluster.append(j)
                            used[j] = True
                            continue
        if len(cluster) < 2:
            continue
        members = [known[k] for k in cluster]
        primary = max(members, key=_source_rank)
        event_id = "ev_" + hashlib.md5(
            (str(primary.get("url", "")) + "|" + _norm_title(primary.get("title", ""))).encode()
        ).hexdigest()[:10]
        related = []
        for m in members:
            m["event_id"] = event_id
            if m is primary:
                continue
            m["folded_into"] = primary.get("url", "")
            src = str(m.get("source", "") or "未知来源")
            if src not in related:
                related.append(src)
        primary.setdefault("related_sources", [])
        for src in related:
            if src not in primary["related_sources"]:
                primary["related_sources"].append(src)
    return out


def merge_with_cache(new_data, old_data):
    if not old_data:
        return new_data
    
    for section in ['international', 'domestic']:
        if section not in new_data:
            new_data[section] = {}
        if section not in old_data:
            continue
        
        for cat in list(new_data[section].keys()):
            if cat not in old_data[section]:
                continue
            
            # 新数据优先: 先保留所有新 items (含 AI 字段), 再补充旧 items 中独有的
            new_urls = {_norm_url(item['url']) for item in new_data[section][cat]}
            old_extras = [item for item in old_data[section][cat]
                         if _norm_url(item['url']) not in new_urls]
            
            combined = new_data[section][cat] + old_extras
            combined.sort(key=lambda x: x.get('date') or '', reverse=True)
            cap = MAX_ITEMS.get((section, cat), 50)
            new_data[section][cat] = combined[:cap]
    
    return new_data


# 保留期（天）：统一 14 天（用户要求只保留最近 2 周新闻）
# 注意: SEC 定期/重大报告 (10-K/10-Q/8-K/S-1 等) 仍保留 28 天（季度才出一次）
NEWS_RETENTION_DAYS = 14
# SEC 定期/重大报告保留更久（10-K/10-Q 等季度才出一次）
SEC_LONG_RETENTION_TYPES = {"10-K", "10-Q", "8-K", "S-1", "DEFA14A",
                            "SC 13D", "SC 13G", "20-F", "6-K", "DEF 14A"}
SEC_LONG_RETENTION_DAYS = 28
# 明显与旅游行业无关的来源（评分漏网的垃圾项）
SOURCE_BLOCKLIST = {
    "Miami Dolphins", "Chase Bank", "RSU by PriceLabs", "Refresh Miami",
    "WTVB", "The Boca Raton Tribune", "AI CERTs",
}
# 东航动态栏目只保留东航相关条目
CEAIR_ALIASES = ("中国东航", "中国东方航空", "东航")


# 各列表最大条数 (2026-08-20: 大幅提升上限, 避免截断 IR/Bloomberg 等重要源)
MAX_ITEMS = {
    ("international", "sec_filings"): 80,
    ("international", "industry_news"): 200,
    ("domestic", "china_industry"): 60,
    ("domestic", "regulatory"): 40,
    ("domestic", "company_news"): 60,
}


def prune_and_dedupe(news_data):
    """修剪 + 三级去重 + 排序 + 限量（改造项⑤⑦, 2026-08-18）。

    流程（每个分类内）:
      1. URL 去重（_norm_url: 剥 fragment/跟踪参数/结尾斜杠）
      2. 来源黑名单 / SEC INFO 占位过滤 / 东航栏目过滤
      3. 保留期修剪: 有发布日期按发布日期; unknown 按 fetched_at 日期部分
      4. 同文去重 dedupe_same_article（归一化标题+公司+±3天）
      5. 同事件折叠 group_same_events（相似度≥0.72 且 72h 内; folded_into 不删除）
      6. 排序: 已知日期倒序在前, unknown('') 沉底; 截断至 cap
    """
    today = datetime.date.today()
    for section in ("international", "domestic"):
        sec_data = news_data.get(section, {})
        for cat in list(sec_data.keys()):
            items = sec_data.get(cat, [])
            if not isinstance(items, list):
                continue
            retention = NEWS_RETENTION_DAYS
            cap = MAX_ITEMS.get((section, cat), 50)

            seen_urls = set()
            kept = []
            for item in items:
                # PhocusWire Briefs 子条目有意共享原文 URL, 跳过 URL 去重
                is_briefs_sub = item.get("source", "") == "PhocusWire Briefs"
                url = _norm_url(item.get("url", ""))
                if url and url in seen_urls and not is_briefs_sub:
                    continue
                if url and not is_briefs_sub:
                    seen_urls.add(url)

                # 来源黑名单（评分漏网的无关媒体）
                if item.get("source", "") in SOURCE_BLOCKLIST:
                    continue

                # SEC INFO 占位条目（抓取失败时的"去看EDGAR"链接）不进入列表
                if (section, cat) == ("international", "sec_filings") \
                        and str(item.get("type", "")) == "INFO":
                    continue

                # SEC：定期/重大报告(10-K/10-Q/8-K)保留 28 天, 常规 Form 4/144 等保留 14 天
                item_retention = retention
                if (section, cat) == ("international", "sec_filings"):
                    if str(item.get("type", "")).strip() in SEC_LONG_RETENTION_TYPES:
                        item_retention = SEC_LONG_RETENTION_DAYS

                # 东航动态栏目：只保留东航相关条目（清理旧缓存的错误标签数据）
                if (section, cat) == ("domestic", "company_news"):
                    co = str(item.get("company", ""))
                    title = str(item.get("title", ""))
                    if not any(a in co or a in title for a in CEAIR_ALIASES):
                        continue

                # 保留期: 有发布日期按发布日期; 无日期按抓取时间（不再永久保留）
                date_str = _valid_date_str(item.get("date"))
                anchor = None
                if date_str:
                    try:
                        anchor = datetime.datetime.strptime(date_str, "%Y-%m-%d").date()
                    except ValueError:
                        anchor = None
                if anchor is None:
                    fa = str(item.get("fetched_at", "") or "")[:10]
                    anchor = _valid_date_str(fa)
                    anchor = datetime.datetime.strptime(anchor, "%Y-%m-%d").date() if anchor else None
                # IR 官方新闻稿: 不再豁免，统一 14 天保留（用户要求）
                if anchor is not None and (today - anchor).days > item_retention:
                    continue
                kept.append(item)

            # SEC 列表不做标题级去重（同名"季度报告(10-Q)"靠日期+URL区分）
            if (section, cat) != ("international", "sec_filings"):
                kept = dedupe_same_article(kept)
                kept = group_same_events(kept)

            # 去重后重新按日期降序排列（去重可能打乱顺序）
            # 关键修复: 确保最新的新闻永远在最上面
            kept.sort(key=lambda x: x.get("date") or "", reverse=True)
            sec_data[cat] = kept[:cap]
    return news_data


# ── 主函数 ──

def refresh_traveldaily_only(cached_data):
    """[--td-only] 只重抓环球旅讯并整体替换 china_industry（该分类唯一来源）。

    用于解析器/质量规则调优后的定向刷新：整源替换而不是与旧缓存合并，
    避免低质量旧条目靠 28 天保留期继续滞留。抓取条数过少(<5)时放弃，
    防止站点临时不可用把现有列表误清空。save_cache 会先自动备份旧缓存。
    """
    src = next((s for s in DOMESTIC_WEB_SOURCES if s.get("news_selector") == "traveldaily"), None)
    if not src:
        print("  traveldaily source not configured")
        return 1
    print("=" * 60)
    print(f"Traveldaily-only refresh at {datetime.datetime.now():%Y-%m-%d %H:%M:%S}")
    print("=" * 60)
    if not cached_data:
        print("  No existing cache; run a full fetch first.")
        return 1
    new_items = fetch_traveldaily(src)
    print(f"  Fetched {len(new_items)} fresh traveldaily items")
    new_dom = [i for i in new_items if i.get("category") != "industry_news"]
    new_intl = [i for i in new_items if i.get("category") == "industry_news"]
    # 防误清空双保险（2026-08-18 实测事故: 首页入口超时只抓到快讯页 11 条国际旧闻,
    # 总数≥5 绕过保护 → china_industry 22 条被整源替换成 0 条, 靠备份恢复）:
    # 总条数与国内子集都必须≥5 —— 国内子集是 china_industry 的替换内容,
    # 入口部分失败时它最先不完整
    if len(new_items) < 5 or len(new_dom) < 5:
        print(f"  Too few items (total {len(new_items)}, domestic {len(new_dom)}); "
              "keeping existing lists (site may be down or entry unreachable).")
        return 1
    news_data = cached_data
    # 国内子集整源替换 china_industry
    news_data["domestic"]["china_industry"] = new_dom
    # 国际子集: 移除旧环球旅讯国际条目后换新批次
    intl = news_data.get("international", {}).get("industry_news", [])
    intl = [i for i in intl if i.get("source") != "环球旅讯"]
    tag_company_news(new_intl)
    intl.extend(new_intl)
    news_data["international"]["industry_news"] = intl
    print(f"  Split: {len(new_dom)} domestic (china_industry) / {len(new_intl)} international")
    apply_date_fields(new_dom); apply_date_fields(new_intl)
    mark_source("环球旅讯", "success", item_count=len(new_items))
    news_data = prune_and_dedupe(news_data)
    # 统一筛选管道: --td-only 替换进来的条目同样走硬排除+评分（与日更同一套规则）
    news_data = run_selection_pipeline(news_data)
    news_data["selection_report"]["quality"] = data_quality_check(news_data)
    news_data["last_updated"] = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    news_data["update_mode"] = "traveldaily-only"
    save_cache(news_data)
    kept = news_data["domestic"]["china_industry"]
    print(f"\n  china_industry now {len(kept)} items:")
    for it in kept:
        print(f"    {it.get('date','')} | {it.get('title','')[:62]}")
    intl_kept = [i for i in news_data["international"]["industry_news"] if i.get("source") == "环球旅讯"]
    print(f"\n  international 环球旅讯 items now {len(intl_kept)}:")
    for it in intl_kept:
        print(f"    {it.get('date','')} | {it.get('title','')[:62]}")
    return 0


def main(fast_mode=False):
    """主函数: 全量更新或快速更新。
    
    fast_mode=False: 全量更新 (RSS + AI 摘要/翻译/分类/去重/重点标记)
    fast_mode=True:  快速更新 (仅增量 + 基础去重 + 重点标记, 每2小时)
    """
    mode_label = "FAST" if fast_mode else "FULL"
    cache_max_age = CACHE_MAX_AGE_FAST_HOURS if fast_mode else CACHE_MAX_AGE_HOURS
    
    print("=" * 60)
    print(f"News fetch [{mode_label}] started at {datetime.datetime.now():%Y-%m-%d %H:%M:%S}")
    print(f"AI Module: {'available' if AI_MODULE_AVAILABLE else 'disabled'}")
    print("=" * 60)
    
    cached_data, cache_age = load_cache()
    # 来源状态: 本次尝试时间戳 + 继承旧缓存的 last_success_at（改造项④）
    FETCH_STATUS["attempted_at"] = _now_iso()
    seed_fetch_status_from_cache(cached_data)

    # 定向刷新: 只重抓环球旅讯（绕过新鲜度检查与全量抓取）
    if "--td-only" in sys.argv:
        return refresh_traveldaily_only(cached_data)

    force = "--force" in sys.argv
    if not force and cached_data and cache_age < cache_max_age:
        print(f"Cache is fresh ({cache_age:.1f}h < {cache_max_age}h), using cached data")
        print(f"To force refresh, run with --force")
        return 0
    
    print(f"Cache is stale (age {cache_age:.1f}h), fetching fresh data...")
    
    news_data = {
        "international": {
            "sec_filings": [],
            "industry_news": [],
        },
        "domestic": {
            "china_industry": [],
            "regulatory": [],
            "company_news": [],
        },
        "modules": {k: [] for k in MODULE_KEYS},
        "last_updated": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    }
    
    # ── 1. SEC EDGAR filings ──
    print("\n[1/3] Fetching SEC EDGAR filings...")
    try:
        sec_filings = fetch_all_sec_filings()
        news_data["international"]["sec_filings"] = sec_filings
        print(f"  Total SEC filings: {len(sec_filings)}")
    except Exception as e:
        print(f"  SEC fetch failed: {e}")
        if cached_data:
            news_data["international"]["sec_filings"] = cached_data.get("international", {}).get("sec_filings", [])
    
    # ── 2. International RSS feeds ──
    print("\n[2/3] Fetching international RSS feeds...")
    try:
        intl_news = fetch_rss_feeds(INTL_RSS_FEEDS, max_items_per_feed=12)
        print(f"  Raw international news: {len(intl_news)}")

        # 2a0. Skift /news/ 列表页补充 (RSS 只含最近 10 条, 2026-08-18 用户反馈漏新闻)
        skift_page = fetch_skift_newspage()
        if skift_page:
            have = {_norm_url(i.get("url", "")) for i in intl_news}
            added = [i for i in skift_page if _norm_url(i.get("url", "")) not in have]
            intl_news.extend(added)
            print(f"  Skift /news/ pages: +{len(added)} items beyond RSS")

        # 2a0b. 官方 IR 新闻稿（BKNG/EXPE/ABNB IR 直采，2026-08-18 新增）
        ir_items = fetch_ir_press_releases()
        if ir_items:
            have = {_norm_url(i.get("url", "")) for i in intl_news}
            added = [i for i in ir_items if _norm_url(i.get("url", "")) not in have]
            intl_news.extend(added)
            print(f"  IR press releases: +{len(added)} items (BKNG/EXPE/ABNB)")

        # 2a. 严格行业相关性过滤 (仅保留 OTA/旅游/酒店/航空相关新闻)
        intl_news = filter_travel_relevance(intl_news)
        print(f"  After relevance filter: {len(intl_news)} items")

        # 2b. 打公司新闻标签
        intl_news = tag_company_news(intl_news)

        # 2c. Paywall 标记 (付费墙源仅标题)
        if AI_MODULE_AVAILABLE and not fast_mode:
            intl_news = mark_paywall_sources(intl_news)

        # 2d. AI 全流程处理 (仅全量模式)
        if AI_MODULE_AVAILABLE and not fast_mode:
            # 2026-08-20: 移除 80 条上限, 处理所有幸存条目 (之前 Bloomberg/IR 条目被截断)
            intl_news = process_news_pipeline(intl_news, options={"max_items": len(intl_news)})
            # 回退: AI翻译不可用时, 用 Google Translate 兜底
            intl_news = translate_news_items(intl_news)
        else:
            # 传统处理路径 (快速模式或无 AI)
            intl_news = translate_news_items(intl_news)
            intl_news = filter_and_rank_news(intl_news)
            print(f"  After traditional filtering: {len(intl_news)} items")

        # 2d. 快速模式: 轻量处理
        if fast_mode and AI_MODULE_AVAILABLE:
            intl_news = process_news_fast(intl_news)
        elif fast_mode and not AI_MODULE_AVAILABLE:
            intl_news = filter_and_rank_news(intl_news)
            print(f"  After fast filtering: {len(intl_news)} items")

        news_data["international"]["industry_news"] = intl_news
    except Exception as e:
        print(f"  International RSS failed: {e}")
        if cached_data:
            news_data["international"]["industry_news"] = cached_data.get("international", {}).get("industry_news", [])
    
    # ── 3. Domestic websites ──
    print("\n[3/3] Fetching domestic news...")
    try:
        domestic_items = fetch_domestic_news()
        intl_extra = []
        for item in domestic_items:
            cat = item.get("category", "china_industry")
            if cat == "industry_news":
                # 环球旅讯的国际条目 → 国际行业新闻 (中文原文无需翻译, 打公司标签)
                intl_extra.append(item)
                continue
            if cat not in news_data["domestic"]:
                news_data["domestic"][cat] = []
            news_data["domestic"][cat].append(item)
        if intl_extra:
            tag_company_news(intl_extra)
            news_data["international"]["industry_news"].extend(intl_extra)
            print(f"  Traveldaily intl items → international industry_news: {len(intl_extra)}")
        print(f"  Total domestic news: {len(domestic_items)}")
    except Exception as e:
        print(f"  Domestic news fetch failed: {e}")
        if cached_data:
            for cat in cached_data.get("domestic", {}):
                if cat in news_data["domestic"]:
                    existing_urls = {i['url'] for i in news_data["domestic"][cat]}
                    for old_item in cached_data["domestic"][cat]:
                        if old_item['url'] not in existing_urls:
                            news_data["domestic"][cat].append(old_item)
    
    # ── Merge with cache ──
    if cached_data:
        news_data = merge_with_cache(news_data, cached_data)

    # 缓存中的旧条目也必须经过当前国内分源规则，不能因缓存合并绕过过滤。
    news_data = refilter_cached_domestic(news_data)

    # ── 合并后重过滤：清理旧缓存中相关性过滤上线前的遗留噪音 ──
    intl_list = news_data.get("international", {}).get("industry_news", [])
    intl_clean = filter_travel_relevance(intl_list)
    if len(intl_clean) < len(intl_list):
        print(f"  [Legacy Cleanup] Removed {len(intl_list) - len(intl_clean)} pre-filter legacy items after merge")
    news_data["international"]["industry_news"] = intl_clean

    # ── 日期字段规范（改造项⑤）: published_at/fetched_at/date/date_status ──
    apply_date_fields(news_data.get("international", {}).get("sec_filings", []))
    apply_date_fields(news_data.get("international", {}).get("industry_news", []))
    for cat, lst in news_data.get("domestic", {}).items():
        if isinstance(lst, list):
            apply_date_fields(lst)

    # ── 保留期修剪 + 三级去重（改造项⑦）──
    news_data = prune_and_dedupe(news_data)

    # ── 公开详情页摘要补充（先于筛选, 让证据质量评分看到补充后的摘要）──
    news_data = enrich_public_summaries(news_data)

    # ── 统一筛选管道（§9, 2026-08-18）: 实体识别→硬排除→重点公司→基本面评分 ──
    # 新抓取 + 保留期内旧缓存合并后全量执行同一套规则; 被拒条目移出列表并写诊断JSON。
    news_data = run_selection_pipeline(news_data)

    # ── 摘要证据字段补齐（§12: 标题重复守卫在 backfill 内）──
    news_data = backfill_summary_fields(news_data)

    # ── 模块路由（2026-08-18 新增: 把原分区条目分流到 5 个展示模块）──
    # 新抓取 + 旧缓存合并后全量执行同一套路由规则；旧 modules 数据先清空再重新路由
    news_data = route_to_modules(news_data)
    print(f"\n  [Modules] " + " | ".join(f"{k}={len(v)}" for k, v in news_data["modules"].items()))

    # ── 数据质量检查 ──
    news_data["selection_report"]["quality"] = data_quality_check(news_data)

    # ── 来源状态汇总（改造项④）──
    status = overall_status() or "failed"
    news_data["update_status"] = status
    FETCH_STATUS["status"] = status
    news_data["fetch_status"] = json.loads(json.dumps(FETCH_STATUS, ensure_ascii=False))
    if status == "success":
        FETCH_STATUS["last_success_at"] = _now_iso()
        news_data["fetch_status"]["last_success_at"] = FETCH_STATUS["last_success_at"]

    # ── Update timestamp ──
    news_data["last_updated"] = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    news_data["update_mode"] = mode_label.lower()

    # ── 退出码（改造项④）: 0=全部成功 / 2=部分失败(缓存兜底, 可部署需披露) / 1=彻底失败(无可用数据) ──
    total_items = sum(len(v) for sec in ("international", "domestic")
                      for v in (news_data.get(sec) or {}).values() if isinstance(v, list))
    total_modules = sum(len(v) for v in (news_data.get("modules") or {}).values() if isinstance(v, list))
    if status == "failed" and total_items == 0:
        # 彻底失败且无任何可用数据: 不写缓存(避免清空现有缓存/破坏完整性校验), 不重建不部署
        print("FATAL: all sources failed and no cached data available")
        return 1
    exit_code = 0 if status == "success" else 2

    # ── 清理输出 JSON 中遗留的 summary_basis 字段（2026-08-18 用户要求彻底删除）──
    def _strip_summary_basis(items):
        if not isinstance(items, list):
            return
        for it in items:
            if isinstance(it, dict):
                it.pop("summary_basis", None)
    for sec in ("international", "domestic"):
        for cat, lst in (news_data.get(sec) or {}).items():
            if isinstance(lst, list):
                _strip_summary_basis(lst)
    for mk, lst in (news_data.get("modules") or {}).items():
        if isinstance(lst, list):
            _strip_summary_basis(lst)

    # ── Save（非致命路径才落盘）──
    save_cache(news_data)

    # Print summary
    print("\n" + "=" * 60)
    print(f"SUMMARY [{mode_label}] (update_status={status}, exit_code={exit_code}):")
    for section in ["international", "domestic"]:
        print(f"\n  [{section}]")
        for cat, items in news_data.get(section, {}).items():
            if isinstance(items, list):
                featured_count = sum(1 for i in items if i.get("featured"))
                paywall_count = sum(1 for i in items if i.get("paywall"))
                unknown_dates = sum(1 for i in items if i.get("date_status") == "unknown")
                extra = ""
                if featured_count:
                    extra += f", {featured_count} featured"
                if paywall_count:
                    extra += f", {paywall_count} paywall"
                if unknown_dates:
                    extra += f", {unknown_dates} 日期未知"
                print(f"    {cat}: {len(items)} items{extra}")
    failed_sources = [n for n, r in FETCH_STATUS["sources"].items()
                      if r.get("status") == "failed"]
    if failed_sources:
        print(f"\n  Failed sources: {', '.join(failed_sources)}")
    print(f"\n  Last updated: {news_data['last_updated']}")
    print(f"  Update mode: {news_data['update_mode']}")
    print("=" * 60)

    return exit_code


if __name__ == "__main__":
    fast = "--fast" in sys.argv
    sys.exit(main(fast_mode=fast))
