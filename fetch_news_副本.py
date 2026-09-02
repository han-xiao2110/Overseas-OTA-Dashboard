#!/usr/bin/env python3
"""
fetch_news_副本.py - 自动抓取新闻和 SEC 文件
分为两类: 国外 (daily) 和 国内 (weekly)

输出: news_data_副本.json
"""

import json, os, sys, time, datetime, re, shutil, subprocess, tempfile, glob
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
REJECTED_OUTPUT = os.path.join(SCRIPT_DIR, "news_rejected_副本.json")
MANUAL_LABELS_PATH = os.path.join(SCRIPT_DIR, "news_screening_labels_副本.json")
TRANSLATION_CACHE_PATH = os.path.join(SCRIPT_DIR, "translation_cache_副本.json")
REVIEW_WORKBOOK_HELPER = os.path.join(SCRIPT_DIR, "news_review_workbook_副本.mjs")
POLICY_VERSION = "2026-08-30-v4"
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
    # Core-company action watches.  The broad company feeds above are often
    # dominated by price commentary, promotions and destination listicles;
    # limiting those feeds to their first 12 results therefore missed actual
    # product/partnership/management events.  These 14-day queries widen only
    # acquisition coverage; the common screening rules still reject ads,
    # opinions and non-substantive mentions.
    {"name": "Core BKNG Watch", "url": "https://news.google.com/rss/search?q=(%22Booking.com%22+OR+Agoda+OR+%22KAYAK+travel%22+OR+OpenTable+OR+Priceline)+(launches+OR+partnership+OR+partners+OR+acquires+OR+acquisition+OR+expands+OR+appoints+OR+introduces)+when:14d&hl=en-US&gl=US&ceid=US:en", "category": "industry_news", "translate": True, "max_items": 40},
    {"name": "Core EXPE Watch", "url": "https://news.google.com/rss/search?q=(%22Expedia+Group%22+OR+Expedia+OR+Vrbo+OR+%22Hotels.com%22)+(launches+OR+partnership+OR+partners+OR+acquires+OR+acquisition+OR+expands+OR+appoints+OR+reorganization)+when:14d&hl=en-US&gl=US&ceid=US:en", "category": "industry_news", "translate": True, "max_items": 40},
    {"name": "Core ABNB Watch", "url": "https://news.google.com/rss/search?q=Airbnb+(launches+OR+partnership+OR+partners+OR+acquires+OR+acquisition+OR+expands+OR+appoints+OR+introduces)+when:14d&hl=en-US&gl=US&ceid=US:en", "category": "industry_news", "translate": True, "max_items": 40},
    # Google News RSS - Bloomberg (travel/mobility sections)
    {"name": "Bloomberg Travel (GN)", "url": "https://news.google.com/rss/search?q=bloomberg+travel+hotel+airline&hl=en-US&gl=US&ceid=US:en", "category": "industry_news", "translate": True},
    {"name": "Bloomberg Mobility (GN)", "url": "https://news.google.com/rss/search?q=bloomberg+mobility+autonomous+robotaxi&hl=en-US&gl=US&ceid=US:en", "category": "industry_news", "translate": True},
]

# ── 官方 IR 新闻稿源：直接读取 Q4 页面自身使用的公开 feed ──
# 不再依赖 Google News 是否及时收录官网。
IR_SOURCES = [
    {"entity_id": "BKNG", "name": "Booking Holdings IR",
     "url": "https://ir.bookingholdings.com/news/default.aspx",
     "api_url": "https://ir.bookingholdings.com/feed/PressRelease.svc/GetPressReleaseList"},
    {"entity_id": "EXPE", "name": "Expedia Group IR",
     "url": "https://ir.expediagroup.com/news-and-events/news/default.aspx",
     "api_url": "https://ir.expediagroup.com/feed/PressRelease.svc/GetPressReleaseList"},
    {"entity_id": "ABNB", "name": "Airbnb IR",
     "url": "https://investors.airbnb.com/press-releases/default.aspx",
     "api_url": "https://investors.airbnb.com/feed/PressRelease.svc/GetPressReleaseList"},
]

# Google News RSS items should have source overridden to original source
GOOGLE_NEWS_SOURCES = {"PhocusWire", "Travel Weekly", "Skyscanner", "Klook", "MakeMyTrip",
                        "Traveloka", "Agoda", "Trip.com", "Booking.com", "Expedia", "Airbnb", "Tripadvisor",
                        "Core BKNG Watch", "Core EXPE Watch", "Core ABNB Watch",
                        "Bloomberg Travel (GN)", "Bloomberg Mobility (GN)"}

# ── 翻译配置 ──
TRANSLATE_SOURCES = {"Skift", "PhocusWire", "Bloomberg Markets", "Bloomberg Technology", "Bloomberg",
                     "Travel Weekly", "Skyscanner", "Klook", "MakeMyTrip",
                     "Traveloka", "Agoda", "Trip.com", "Booking.com", "Expedia", "Airbnb", "Tripadvisor",
                     "WebInTravel", "Travel Pulse", "Hospitality Net", "Breaking Travel News",
                     "TTG Asia", "Simply Wall St", "Seeking Alpha", "Yahoo Finance", "CNBC"}
def _load_translation_cache():
    try:
        with open(TRANSLATION_CACHE_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError, TypeError):
        return {}


TRANSLATE_CACHE = _load_translation_cache()
_TRANSLATE_CACHE_DIRTY = False

# 公司名是品牌专名，不属于需要翻译的普通词。翻译前用稳定 token 保护，
# 翻译后再恢复。顺序从长名到短名，避免 Expedia Group 被 Expedia 先匹配。
_COMPANY_NAME_TOKENS = (
    (re.compile(r"Booking\s+Holdings", re.I), "ZXQBKNGQXZ", "Booking Holdings"),
    (re.compile(r"Booking\.com", re.I), "ZXQBOOKINGCOMQXZ", "Booking.com"),
    (re.compile(r"Expedia\s+Group", re.I), "ZXQEXPEQXZ", "Expedia Group"),
    (re.compile(r"Expedia", re.I), "ZXQEXPEDIAQXZ", "Expedia"),
    (re.compile(r"Airbnb", re.I), "ZXQABNBQXZ", "Airbnb"),
    (re.compile(r"Agoda", re.I), "ZXQAGODAQXZ", "Agoda"),
    (re.compile(r"Trip\.com", re.I), "ZXQTRIPCOMQXZ", "Trip.com"),
    (re.compile(r"Klook", re.I), "ZXQKLOOKQXZ", "Klook"),
    (re.compile(r"Skyscanner", re.I), "ZXQSKYSCANNERQXZ", "Skyscanner"),
    (re.compile(r"Make\s*My\s*Trip", re.I), "ZXQMAKEMYTRIPQXZ", "MakeMyTrip"),
    (re.compile(r"Traveloka", re.I), "ZXQTRAVELOKAQXZ", "Traveloka"),
    (re.compile(r"Tripadvisor", re.I), "ZXQTRIPADVISORQXZ", "Tripadvisor"),
    (re.compile(r"Vrbo", re.I), "ZXQVRBOQXZ", "Vrbo"),
    (re.compile(r"KAYAK", re.I), "ZXQKAYAKQXZ", "KAYAK"),
    (re.compile(r"Priceline", re.I), "ZXQPRICELINEQXZ", "Priceline"),
    (re.compile(r"OpenTable", re.I), "ZXQOPENTABLEQXZ", "OpenTable"),
)


def _protect_company_names(text):
    protected = str(text or "")
    for pattern, token, _canonical in _COMPANY_NAME_TOKENS:
        protected = pattern.sub(token, protected)
    return protected


def normalize_company_names(text):
    """恢复并统一核心公司的英文原名，包括历史机翻产物。"""
    normalized = str(text or "")
    for _pattern, token, canonical in _COMPANY_NAME_TOKENS:
        normalized = re.sub(r"\s*".join(map(re.escape, token)), canonical,
                            normalized, flags=re.I)
    replacements = (
        (r"预订控股(?:公司|集团)?|缤客控股(?:公司|集团)?|Booking控股(?:公司|集团)?", "Booking Holdings"),
        (r"Expedia\s*(?:集团|公司)", "Expedia Group"),
        (r"爱彼迎", "Airbnb"),
    )
    for pattern, canonical in replacements:
        normalized = re.sub(pattern, canonical, normalized, flags=re.I)
    return normalized


def _brand_names_in_text(text):
    """返回文本中的受保护品牌集合，用于验证翻译前后专名不丢失。"""
    value = str(text or "")
    return {canonical for pattern, _token, canonical in _COMPANY_NAME_TOKENS
            if pattern.search(value)}


def _translation_preserves_brands(original, translated):
    """翻译不得删除、新增或改写任何受保护品牌。"""
    return _brand_names_in_text(original) == _brand_names_in_text(translated)


def _has_sufficient_chinese(text):
    """识别已经是中文的标题/摘要，即使其中保留 Agoda 等英文品牌名。"""
    value = str(text or "")
    zh_count = len(re.findall(r"[\u4e00-\u9fff]", value))
    if zh_count < 4:
        return False
    # 英文品牌不应被当成「尚未翻译的英文内容」。
    without_brands = value
    for pattern, _token, _canonical in _COMPANY_NAME_TOKENS:
        without_brands = pattern.sub("", without_brands)
    latin_count = len(re.findall(r"[A-Za-z]", without_brands))
    return latin_count <= 8 or zh_count >= latin_count


_EMOJI_RE = re.compile(
    "["
    "\U0001F1E6-\U0001F1FF"
    "\U0001F300-\U0001FAFF"
    "\u2300-\u23FF\u2600-\u27BF"
    "\u2B00-\u2BFF"
    "]"
)


def strip_title_emoji(text):
    """清理新闻标题中的 emoji，同时保留普通中英文标点。"""
    cleaned = _EMOJI_RE.sub("", str(text or ""))
    cleaned = re.sub(r"[\u200d\ufe0e\ufe0f\U0001F3FB-\U0001F3FF]", "", cleaned)
    return re.sub(r"\s{2,}", " ", cleaned).strip()


def save_translation_cache():
    """持久化成功译文，避免14天缓存内的同一内容每日重复请求公共翻译端点。"""
    global _TRANSLATE_CACHE_DIRTY
    if not _TRANSLATE_CACHE_DIRTY:
        return
    tmp = TRANSLATION_CACHE_PATH + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(TRANSLATE_CACHE, f, ensure_ascii=False, sort_keys=True, indent=2)
    os.replace(tmp, TRANSLATION_CACHE_PATH)
    _TRANSLATE_CACHE_DIRTY = False


def remember_translation(original, translated):
    """把已确认的中文译文写入持久缓存候选。"""
    global _TRANSLATE_CACHE_DIRTY
    original = str(original or "").strip()
    translated = str(translated or "").strip()
    if not original or not translated or original == translated:
        return
    if not re.search(r"[A-Za-z]{2}", original) or not re.search(r"[\u4e00-\u9fff]", translated):
        return
    key = hashlib.md5(original.encode()).hexdigest()
    if TRANSLATE_CACHE.get(key) != translated:
        TRANSLATE_CACHE[key] = translated
        _TRANSLATE_CACHE_DIRTY = True

_TRANSLATE_FAILS = 0  # 连续失败计数，超过阈值临时熔断避免限流


def _translate_chunk(text):
    """Translate a single chunk (one sentence) using deep-translator.
    Returns None on failure. Applies a circuit-breaker after too many
    consecutive failures (Google 429 throttle) to avoid waiting forever."""
    global _TRANSLATE_FAILS
    if not text or not text.strip():
        return None
    # Use the public no-key endpoint first with an explicit timeout.  The
    # deep-translator Google client does not pass a timeout to requests and can
    # hang indefinitely behind the local proxy; that previously blocked the
    # whole daily refresh after screening had already succeeded.
    try:
        query = urllib.parse.urlencode({"q": text, "langpair": "en|zh-CN"})
        req = urllib.request.Request(
            "https://api.mymemory.translated.net/get?" + query,
            headers={"User-Agent": "OTA-Dashboard/1.0"})
        with urlopen_safe(req, timeout=8) as resp:
            payload = json.loads(resp.read().decode("utf-8"))
        r = str((payload.get("responseData") or {}).get("translatedText") or "").strip()
        if payload.get("responseStatus") == 200 and r and r != text \
                and not re.search(r"MYMEMORY WARNING|PLEASE SELECT", r, re.I):
            _TRANSLATE_FAILS = 0
            return html_lib.unescape(r)
    except Exception:
        pass

    # Short-timeout Google fallback.  HTTP 429 and network failures fall
    # through to the circuit breaker instead of stalling the workflow.
    if _TRANSLATE_FAILS < 8:
        try:
            query = urllib.parse.urlencode({
                "client": "gtx", "sl": "en", "tl": "zh-CN", "dt": "t", "q": text})
            req = urllib.request.Request(
                "https://translate.googleapis.com/translate_a/single?" + query,
                headers={"User-Agent": "Mozilla/5.0"})
            with urlopen_safe(req, timeout=5) as resp:
                payload = json.loads(resp.read().decode("utf-8"))
            r = "".join(str(part[0]) for part in (payload[0] or []) if part and part[0]).strip()
            if r and r != text:
                _TRANSLATE_FAILS = 0
                return r
        except Exception:
            pass

    # 第三路：使用 requirements.txt 中安装的 deep-translator。它与上面
    # 两个直连端点的请求形式不同，可以覆盖部分临时限流/解析失败。
    try:
        proc = subprocess.run(
            [sys.executable, "-c",
             "from deep_translator import GoogleTranslator; import sys; "
             "print(GoogleTranslator(source='en', target='zh-CN').translate(sys.argv[1]) or '')",
             text], capture_output=True, text=True, timeout=8)
        r = proc.stdout.strip() if proc.returncode == 0 else ""
        if r and r != text and re.search(r"[\u4e00-\u9fff]", r):
            _TRANSLATE_FAILS = 0
            return r
    except Exception:
        pass
    _TRANSLATE_FAILS += 1
    return None


def translate_text(text, max_chars=500):
    """Translate English text to Chinese using deep-translator (Google Translate free API).
    Splits text by sentence and translates each chunk separately to avoid the
    'No translation was found' failure on long multi-clause inputs.
    Falls back to original text on total failure."""
    if not text or not text.strip():
        return text
    if _has_sufficient_chinese(text):
        return normalize_company_names(text)
    if not re.search(r'[a-zA-Z]{2}', text):
        return text
    cache_key = hashlib.md5(text.encode()).hexdigest()
    if cache_key in TRANSLATE_CACHE:
        cached = normalize_company_names(TRANSLATE_CACHE[cache_key])
        if _translation_preserves_brands(text, cached):
            return cached
        # 历史机翻曾把 Agoda 改成「安可达」。品牌不一致的缓存必须失效，
        # 否则错误会在每次日更中被持续复用。
        global _TRANSLATE_CACHE_DIRTY
        TRANSLATE_CACHE.pop(cache_key, None)
        _TRANSLATE_CACHE_DIRTY = True

    snippet = _protect_company_names(text[:max_chars])
    # Split by sentence, preserve trailing punctuation; translate each chunk.
    parts = re.split(r'(?<=[.!?])\s+', snippet)
    parts = [p.strip() for p in parts if p.strip()]
    if not parts:
        parts = [snippet]

    out_chunks = []
    all_success = True
    for chunk in parts:
        r = _translate_chunk(chunk)
        if r is not None:
            out_chunks.append(r)
            time.sleep(0.25)  # gentle pacing to avoid 500 errors
        else:
            out_chunks.append(chunk)  # keep original on per-chunk failure
            all_success = False
            time.sleep(0.15)

    # 摘要必须整体翻译，不缓存「中英混合」或失败原文。
    translated = normalize_company_names(' '.join(out_chunks)) if all_success else text
    if translated != text and not _translation_preserves_brands(text, translated):
        translated = text
        all_success = False
    if translated != text and re.search(r"[\u4e00-\u9fff]", translated):
        TRANSLATE_CACHE[cache_key] = translated
        _TRANSLATE_CACHE_DIRTY = True
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
NEWS_MAX_PER_SOURCE = None  # v2: 不在统一筛选前按来源截断

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


def reclassify_cached_traveldaily(news_data):
    """按当前规则重分环球旅讯缓存，避免旧 category 永久锁定错误国内外归属。"""
    intl = (news_data.get("international") or {}).setdefault("industry_news", [])
    dom = (news_data.get("domestic") or {}).setdefault("china_industry", [])
    others_intl = [x for x in intl if not str(x.get("source", "") or "").startswith("环球旅讯")]
    others_dom = [x for x in dom if not str(x.get("source", "") or "").startswith("环球旅讯")]
    td_items = [x for x in intl + dom if str(x.get("source", "") or "").startswith("环球旅讯")]
    seen = set()
    td_intl, td_dom = [], []
    for item in td_items:
        key = _norm_url(item.get("url", "")) or _norm_title(item.get("title", ""))
        if key and key in seen:
            continue
        if key:
            seen.add(key)
        route_title = " ".join(x for x in (
            item.get("title", ""), item.get("title_original", "")) if x)
        domestic = _td_is_domestic(route_title, item.get("summary", ""),
                                   item.get("source_channel", ""))
        item["category"] = "china_industry" if domestic else "industry_news"
        (td_dom if domestic else td_intl).append(item)
    news_data["international"]["industry_news"] = others_intl + td_intl
    news_data["domestic"]["china_industry"] = others_dom + td_dom
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
    if host and host.endswith("sec.gov"):
        # SEC要求自动访问明确标识应用和联系邮箱；浏览器伪装UA会被Archives端点403。
        headers["User-Agent"] = "OTA-Dashboard/1.0 byhanxiaoo@gmail.com"
        headers["Accept-Encoding"] = "identity"

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
            elif e.code == 403 and host and host.endswith("sec.gov") and attempt < retries - 1:
                time.sleep(1.0 + attempt)
                continue
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
        f"category=custom&start=0&rows=100"
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
                    "accession": adsh,
                    "sec_items": items if isinstance(items, list) else [],
                    "file_description": file_desc,
                })
    
    # If search returned nothing, try without entity filter
    if not filings:
        search_url2 = (
            f"https://efts.sec.gov/LATEST/search-index?"
            f"q=%22{encoded_name}%22&dateRange=custom&"
            f"startdt={one_year_ago.isoformat()}&enddt={today.isoformat()}&"
            f"forms={forms_filter}&"
            f"category=custom&start=0&rows=100"
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
                    file_desc = src.get('file_description', '')
                    items = src.get('items', [])
                    
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
                        "accession": adsh,
                        "sec_items": items if isinstance(items, list) else [],
                        "file_description": file_desc,
                    })
    
    # 始终合并 submissions API：全文搜索偶尔少返回某些表单，
    # submissions 可补齐公司本身的定期/重大披露；后面按URL去重。
    if True:
        sub_url = f"https://data.sec.gov/submissions/CIK{cik}.json"
        sub_data = safe_request(sub_url, source=f"SEC EDGAR {ticker}")
        
        if sub_data and isinstance(sub_data, dict) and 'filings' in sub_data:
            recent = sub_data.get('filings', {}).get('recent', {})
            forms = recent.get('form', [])
            dates = recent.get('filingDate', [])
            accession = recent.get('accessionNumber', [])
            primary = recent.get('primaryDocument', [])
            report_dates = recent.get('reportDate', [])
            descriptions = recent.get('primaryDocDescription', [])
            
            important_forms = set(SEC_FILING_TYPES.keys())
            
            count = min(len(forms), 100)
            for i in range(count):
                form_type = forms[i] if i < len(forms) else ""
                filing_date = dates[i] if i < len(dates) else ""
                acc = accession[i] if i < len(accession) else ""
                doc = primary[i] if i < len(primary) else ""
                report_date = report_dates[i] if i < len(report_dates) else ""
                description = descriptions[i] if i < len(descriptions) else ""
                
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
                    "accession": acc,
                    "primary_document": doc,
                    "report_date": report_date,
                    "file_description": description,
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
    # 不在抓取层按每家公司截断。保留期由后续 14 天规则统一处理，
    # 否则 Form 4 较多时会把同期 Rule 144 挤掉。
    filings = unique[:100]
    
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


SEC_DETAIL_SUMMARY_VERSION = 3

SEC_8K_ITEM_LABELS = {
    "1.01": "签订重大协议",
    "1.02": "终止重大协议",
    "2.01": "完成资产收购或处置",
    "2.02": "公布经营业绩或财务状况",
    "2.03": "新增重大直接财务义务",
    "2.05": "计提退出或处置相关成本",
    "2.06": "确认重大资产减值",
    "3.02": "未注册证券销售",
    "5.02": "董事或高管变动及薪酬安排",
    "5.03": "修订公司章程",
    "5.07": "披露股东表决结果",
    "7.01": "按Regulation FD披露信息",
    "8.01": "披露其他重大事项",
    "9.01": "提交财务报表或附件",
}

SEC_8K_HEADER_LABELS = {
    "results of operations and financial condition": "2.02",
    "regulation fd disclosure": "7.01",
    "other events": "8.01",
    "financial statements and exhibits": "9.01",
}


def _sec_local_name(tag):
    return str(tag or "").rsplit("}", 1)[-1]


def _sec_nodes(node, name):
    return [x for x in node.iter() if _sec_local_name(x.tag) == name]


def _sec_text(node, name, default=""):
    for elem in node.iter():
        if _sec_local_name(elem.tag) != name:
            continue
        raw = "".join(elem.itertext()).strip()
        if raw:
            return html_lib.unescape(re.sub(r"\s+", " ", raw))
    return default


def _sec_number(raw):
    try:
        return float(str(raw or "").replace(",", "").strip())
    except (TypeError, ValueError):
        return None


def _sec_count(value):
    if value is None:
        return ""
    if abs(value - round(value)) < 1e-6:
        return f"{int(round(value)):,}"
    return f"{value:,.2f}".rstrip("0").rstrip(".")


def _sec_money_cn(value):
    if value is None:
        return ""
    if value >= 100_000_000:
        return f"约{value / 100_000_000:.2f}亿美元".replace(".00", "")
    if value >= 10_000:
        return f"约{value / 10_000:.1f}万美元".replace(".0万", "万")
    return f"约{value:,.0f}美元"


def _sec_security_cn(raw):
    text = str(raw or "").strip()
    replacements = (
        (r"Class\s+A\s+Common\s+Stock", "A类普通股"),
        (r"Class\s+B\s+Common\s+Stock", "B类普通股"),
        (r"Class\s+A", "A类股"),
        (r"Class\s+B", "B类股"),
        (r"Common\s+Stock", "普通股"),
    )
    for pattern, repl in replacements:
        text = re.sub(pattern, repl, text, flags=re.I)
    return text or "股票"


def _sec_officer_title_cn(raw):
    title = str(raw or "").strip()
    mappings = (
        (r"Chief Executive Officer|\bCEO\b", "首席执行官"),
        (r"Chief Financial Officer|\bCFO\b", "首席财务官"),
        (r"Chief Legal Officer", "首席法务官"),
        (r"Chief Strategy Officer", "首席战略官"),
        (r"Chief Technology Officer|\bCTO\b", "首席技术官"),
        (r"Chief Accounting Officer", "首席会计官"),
        (r"President", "总裁"),
        (r"Secretary|Sec'y", "公司秘书"),
    )
    found = [zh for pattern, zh in mappings if re.search(pattern, title, re.I)]
    return "兼".join(dict.fromkeys(found)) or (title if title else "高管")


def _sec_owner_description(root):
    owner = _sec_text(root, "rptOwnerName") or _sec_text(
        root, "nameOfPersonForWhoseAccountTheSecuritiesAreToBeSold")
    roles = []
    officer_title = _sec_text(root, "officerTitle")
    if officer_title or _sec_text(root, "isOfficer").lower() in ("1", "true", "yes"):
        roles.append(_sec_officer_title_cn(officer_title))
    if _sec_text(root, "isDirector").lower() in ("1", "true", "yes"):
        roles.append("董事")
    if _sec_text(root, "isTenPercentOwner").lower() in ("1", "true", "yes"):
        roles.append("10%以上股东")
    for rel in _sec_nodes(root, "relationshipToIssuer"):
        rel_text = "".join(rel.itertext()).strip().lower()
        if rel_text == "officer":
            roles.append("高管")
        elif rel_text == "director":
            roles.append("董事")
        elif rel_text:
            roles.append(rel_text)
    roles = list(dict.fromkeys(roles))
    return owner or "申报人", "、".join(roles)


def summarize_sec_form4(xml_text, filing=None):
    """从SEC Form 4原始XML提取申报人、角色和实际交易明细。"""
    try:
        root = ET.fromstring(xml_text)
    except (ET.ParseError, TypeError):
        return ""
    if _sec_text(root, "documentType") not in ("4", "4/A"):
        return ""
    owner, roles = _sec_owner_description(root)
    symbol = _sec_text(root, "issuerTradingSymbol") or str((filing or {}).get("company", ""))
    txns = _sec_nodes(root, "nonDerivativeTransaction")
    if not txns:
        txns = _sec_nodes(root, "derivativeTransaction")
    grouped = {}
    for txn in txns:
        code = _sec_text(txn, "transactionCode").upper()
        shares = _sec_number(_sec_text(txn, "transactionShares"))
        price = _sec_number(_sec_text(txn, "transactionPricePerShare"))
        security = _sec_security_cn(_sec_text(txn, "securityTitle"))
        after = _sec_number(_sec_text(txn, "sharesOwnedFollowingTransaction"))
        nature = _sec_text(txn, "directOrIndirectOwnership").upper()
        if not code or shares is None:
            continue
        rec = grouped.setdefault(code, {"shares": 0.0, "prices": [], "security": security,
                                        "after": None, "nature": nature})
        rec["shares"] += shares
        if price is not None:
            rec["prices"].append(price)
        if after is not None:
            rec["after"] = after
        if nature:
            rec["nature"] = nature
    if not grouped:
        return ""
    action_names = {
        "S": "出售", "P": "买入", "A": "获得", "M": "行权取得",
        "F": "为履行税务义务处置", "G": "赠与", "C": "转换取得",
        "D": "处置", "J": "其他方式变动",
    }
    preferred = [c for c in ("C", "M", "A", "P", "S", "F", "G", "D", "J") if c in grouped]
    details = []
    for code in preferred[:3]:
        rec = grouped[code]
        phrase = f"{action_names.get(code, '变动')}{_sec_count(rec['shares'])}股{rec['security']}"
        if rec["prices"] and max(rec["prices"]) > 0:
            low, high = min(rec["prices"]), max(rec["prices"])
            price_text = f"{low:,.2f}" if abs(high - low) < 0.005 else f"{low:,.2f}–{high:,.2f}"
            phrase += f"（申报价{price_text}美元/股）"
        if rec["after"] is not None and code in ("S", "P", "A", "M", "F"):
            ownership = "间接" if rec["nature"] == "I" else "直接"
            phrase += f"，交易后{ownership}持有{_sec_count(rec['after'])}股"
        details.append(phrase)
    role_text = f"（{roles}）" if roles else ""
    report_date = _sec_text(root, "periodOfReport")
    prefix = f"{owner}{role_text}于{report_date}" if report_date else f"{owner}{role_text}"
    subject = f"{symbol}股票变动：" if symbol else ""
    summary = prefix + "申报" + subject + "；".join(details) + "。"
    if _sec_text(root, "aff10b5One").lower() in ("1", "true", "yes"):
        summary += "文件标注交易依据10b5-1计划执行。"
    return summary[:360]


def summarize_sec_form144(xml_text, filing=None):
    """从SEC Rule 144原始XML提取拟出售人、股数、估值、日期和经纪商。"""
    try:
        root = ET.fromstring(xml_text)
    except (ET.ParseError, TypeError):
        return ""
    if _sec_text(root, "submissionType") != "144":
        return ""
    owner, roles = _sec_owner_description(root)
    infos = _sec_nodes(root, "securitiesInformation")
    total_units = 0.0
    total_value = 0.0
    sale_dates = []
    securities = []
    brokers = []
    for info in infos:
        units = _sec_number(_sec_text(info, "noOfUnitsSold"))
        value = _sec_number(_sec_text(info, "aggregateMarketValue"))
        if units is not None:
            total_units += units
        if value is not None:
            total_value += value
        date = _sec_text(info, "approxSaleDate")
        if date:
            try:
                date = datetime.datetime.strptime(date, "%m/%d/%Y").strftime("%Y-%m-%d")
            except ValueError:
                pass
            sale_dates.append(date)
        security = _sec_security_cn(_sec_text(info, "securitiesClassTitle"))
        if security:
            securities.append(security)
        broker = _sec_text(info, "name")
        if broker:
            brokers.append(broker)
    if not infos or total_units <= 0:
        return ""
    role_text = f"（{roles}）" if roles else ""
    date_text = min(sale_dates) if sale_dates else str((filing or {}).get("date", ""))
    security_text = "、".join(dict.fromkeys(securities)) or "股票"
    summary = f"{owner}{role_text}拟于{date_text}出售{_sec_count(total_units)}股{security_text}"
    if total_value:
        summary += f"，申报总市值{_sec_money_cn(total_value)}"
    if brokers:
        summary += f"，经纪商为{'、'.join(dict.fromkeys(brokers))}"
    summary += "。"
    return summary[:360]


def summarize_sec_report_document(document_text, filing):
    """从8-K/10-Q/10-K官方正文提取条款或报告期，再生成简短事实摘要。"""
    raw = str(document_text or "")
    form = str(filing.get("type", "") or "")
    if not raw:
        return ""
    if form == "8-K":
        plain = html_lib.unescape(re.sub(r"<[^>]+>", " ", raw))
        items = re.findall(r"\bITEM\s+(\d+\.\d+)\b", plain, re.I)
        if not items:
            items = re.findall(r"\bItem\s+(\d+\.\d+)\b", raw, re.I)
        if not items:
            header_items = re.findall(r"ITEM\s+INFORMATION\s*:\s*([^\r\n<]+)", plain, re.I)
            items = [SEC_8K_HEADER_LABELS.get(x.strip().lower(), "") for x in header_items]
            items = [x for x in items if x]
        if items:
            filing["sec_items"] = list(dict.fromkeys(items))
            return sec_metadata_summary(filing)
        return ""
    if form not in ("10-Q", "10-K"):
        return ""
    period = ""
    for pattern in (
        r"DocumentPeriodEndDate[^>]*>\s*(\d{4}-\d{2}-\d{2})",
        r"name=[\"']dei:DocumentPeriodEndDate[\"'][^>]*>\s*(?:<[^>]+>)*\s*(\d{4}-\d{2}-\d{2})",
        r"CONFORMED\s+PERIOD\s+OF\s+REPORT\s*:\s*(\d{8})",
    ):
        match = re.search(pattern, raw, re.I)
        if not match:
            continue
        period = match.group(1)
        if re.fullmatch(r"\d{8}", period):
            period = f"{period[:4]}-{period[4:6]}-{period[6:]}"
        break
    if not period:
        human_period = re.search(
            r"DocumentPeriodEndDate[^>]*>\s*([^<]{4,40})<", raw, re.I)
        if human_period:
            try:
                period = datetime.datetime.strptime(
                    html_lib.unescape(human_period.group(1)).strip(), "%B %d, %Y"
                ).strftime("%Y-%m-%d")
            except ValueError:
                period = ""
    if period:
        filing["report_date"] = period
        return sec_metadata_summary(filing)
    return ""


def _sec_items_from_filing(filing):
    items = filing.get("sec_items") or []
    if isinstance(items, str):
        items = re.findall(r"\d+\.\d+", items)
    if not items:
        items = re.findall(r"\b(?:Item\s*)?(\d+\.\d+)\b", str(filing.get("title", "")), re.I)
    return list(dict.fromkeys(str(x).replace("Item", "").strip() for x in items if x))


def sec_metadata_summary(f):
    """结构化正文不可用时，按表单元数据生成有业务含义的摘要。"""
    ticker = str(f.get("company", "") or "")
    comp = COMPANIES.get(ticker, {}).get("name") or ticker or "该公司"
    form = str(f.get("type", "") or "")
    date = str(f.get("date", "") or "")
    report_date = str(f.get("report_date", "") or "")
    if form == "8-K":
        items = _sec_items_from_filing(f)
        meanings = [SEC_8K_ITEM_LABELS[x] for x in items if x in SEC_8K_ITEM_LABELS]
        if meanings:
            return f"{comp}于{date}提交8-K，涉及{'、'.join(meanings)}（Item {', '.join(items)}）。"
    if form == "10-Q":
        period = f"截至{report_date}的" if report_date else ""
        return f"{comp}于{date}提交{period}季度报告，包含当季财务报表、经营情况及风险披露。"
    if form == "10-K":
        period = f"截至{report_date}的" if report_date else ""
        return f"{comp}于{date}提交{period}年度报告，包含全年财务报表、业务回顾及风险披露。"
    if form in ("SC 13D", "SC 13G"):
        return f"{comp}于{date}提交大股东持仓申报，披露申报方的持股及受益所有权情况。"
    if form == "DEFA14A":
        return f"{comp}于{date}提交补充代理征集材料，内容与股东大会或股东表决事项有关。"
    if form == "S-1":
        return f"{comp}于{date}提交证券注册声明，披露拟发行证券及相关业务、财务与风险信息。"
    return ""


def _sec_raw_document_url(filing):
    url = str(filing.get("url", "") or "")
    if not url.startswith("https://www.sec.gov/Archives/edgar/data/"):
        return ""
    url = re.sub(r"/xsl[^/]+/", "/", url, flags=re.I)
    if not url.endswith("/"):
        return url
    index = safe_request(url + "index.json", timeout=10, retries=2)
    if not isinstance(index, dict):
        return ""
    entries = (index.get("directory") or {}).get("item") or []
    names = [str(x.get("name", "")) for x in entries if isinstance(x, dict)]
    form = str(filing.get("type", "") or "")
    preferred = []
    if form in ("4", "4/A"):
        preferred = [n for n in names if re.search(r"(?:ownership|doc4).*\.xml$", n, re.I)]
    elif form == "144":
        preferred = [n for n in names if re.search(r"primary_doc\.xml$", n, re.I)]
    if not preferred:
        candidates = [x for x in entries if isinstance(x, dict) and re.search(r"\.(?:xml|html?|txt)$", str(x.get("name", "")), re.I)
                      and not re.search(r"index|headers", str(x.get("name", "")), re.I)]
        candidates.sort(key=lambda x: int(x.get("size") or 0), reverse=True)
        preferred = [str(x.get("name", "")) for x in candidates]
    return url + preferred[0] if preferred else ""


def enrich_sec_filing_summaries(filings, max_fetches=50):
    """读取SEC官方原始文件，为每张披露卡片生成具体、可回归的事实摘要。"""
    fetched = detailed = 0
    for filing in filings or []:
        if not isinstance(filing, dict) or filing.get("type") == "INFO":
            continue
        if filing.get("sec_summary_version") == SEC_DETAIL_SUMMARY_VERSION and filing.get("summary"):
            continue
        summary = ""
        form = str(filing.get("type", "") or "")
        document_forms = ("4", "4/A", "144", "8-K", "10-Q", "10-K")
        if form in document_forms and fetched < max_fetches:
            raw_url = _sec_raw_document_url(filing)
            if raw_url:
                raw = safe_request(raw_url, timeout=10, retries=2)
                fetched += 1
                if isinstance(raw, str):
                    if form in ("4", "4/A"):
                        summary = summarize_sec_form4(raw, filing)
                    elif form == "144":
                        summary = summarize_sec_form144(raw, filing)
                    else:
                        summary = summarize_sec_report_document(raw, filing)
                    if summary:
                        filing["sec_detail_url"] = raw_url
        if not summary:
            summary = sec_metadata_summary(filing)
        if summary:
            filing["summary"] = summary
            filing["summary_status"] = "generated"
            filing["summary_generated_at"] = _now_iso()
            filing["sec_summary_version"] = SEC_DETAIL_SUMMARY_VERSION
            filing["sec_summary_kind"] = "document_detail" if filing.get("sec_detail_url") \
                else "metadata_detail"
            detailed += 1
        time.sleep(0.11)
    print(f"  SEC detail summaries: {detailed}/{len(filings or [])} ready, {fetched} documents fetched")
    return filings


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
            if (t and not item.get("summary_translated")
                    and difflib.SequenceMatcher(None, s, t).ratio() >= 0.85):
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
    # 全部新闻与披露统一保留 14 天。
    "intl_core_company": 14,
    "intl_industry": 14,
    "intl_disclosures": 14,
    "dom_industry": 14,
    "dom_disclosures": 14,
}

# 披露类 content_type（财报/股东信/业绩演示/监管文件统一进入披露模块）
DISCLOSURE_CONTENT_TYPES = {"earnings", "operating_data", "governance_legal", "regulation"}

# 披露类来源（即使 content_type 未归类，来源命中即视为披露）
DISCLOSURE_SOURCE_KEYWORDS = (
    "SEC EDGAR", "披露易", "民航局", "文旅部", "交通运输部",
    "Booking Holdings IR", "Expedia Group IR", "Airbnb IR",
)
IR_SOURCE_KEYWORDS = ("Booking Holdings IR", "Expedia Group IR", "Airbnb IR")


def _route_single_item(item, section, category):
    """根据 item 的 section/category/entity_id/content_type/source 决定其归属的展示模块 key。

    返回 MODULE_KEYS 之一；若条目不属于任何模块（如测试噪音）返回 None。
    """
    text = _sel_text(item)
    src = str(item.get("source", "") or "")
    ctype = str(item.get("content_type", "") or "")
    entity_id = str(item.get("entity_id", "") or "")
    is_core = entity_id in ("BKNG", "EXPE", "ABNB")
    # modules 每次都从原始分区重建，先清掉上一轮路由留下的展示标记，
    # 避免条目由行业转入核心后仍错误隐藏公司徽章。
    item.pop("suppress_core_badge", None)

    # SEC 官方备案必须先于“媒体高管售股”规则路由。
    # 历史错误：Rule 144 摘要含“出售”后被送进国际行业新闻，
    # 又被行业模块的同事件折叠，导致披露区缺失。
    if section == "international" and category == "sec_filings":
        return "intl_disclosures"

    # 媒体高管售股属于市场事实，不作为公司经营动作或官方披露。
    if MEDIA_INSIDER_SALE_RE.search(text) or STOCK_MARKET_FACT_RE.search(text):
        item["suppress_core_badge"] = True
        return "intl_industry"

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
            # 媒体财报报道不属于官方披露；有明确新经营事实时作为核心公司动态，
            # 否则进入国际行业。SEC/官方 IR 已在各自分支处理。
            if ctype in ("ma_investment", "management_org", "product", "partnership",
                         "employee_policy", "strategy_marketing", "earnings", "operating_data") or \
                    item.get("substantive_company_change"):
                return "intl_core_company"
            return "intl_industry"
        # 非官方源但标题明确是政府数据/公告转发（如"民航局X月旅客量统计"被中国民航网转载）→ 进披露
        if re.search(r"^民航局|^文旅部|^交通运输部|运营数据公告|月度统计|旅客量统计|客座率统计|航班量统计", text):
            return "dom_disclosures"
        # 其余国内条目（含行业媒体的公司财报新闻/服务升级/产品发布）→ 国内行业, 带公司标签
        return "dom_industry"

    # 国际分区
    # 官方 IR：只有财报/运营披露/治理文件进入披露；官方产品、并购、高管等
    # 实质动态仍进入核心公司。媒体财报和普通行业稿一律不进入披露。
    if any(k in src for k in IR_SOURCE_KEYWORDS):
        release_kind = str(item.get("ir_release_kind", "") or "")
        if release_kind == "earnings_disclosure":
            return "intl_disclosures"
        if release_kind in ("investor_event", "core_action"):
            return "intl_core_company"
        if ctype in DISCLOSURE_CONTENT_TYPES or re.search(
                r"财报|季报|年报|业绩|营收|盈利|股东信|8-K|10-K|10-Q|earnings|revenue|results|"
                r"shareholder letter|investor|guidance", text, re.I):
            return "intl_disclosures"
        if is_core and item.get("substantive_company_change"):
            return "intl_core_company"
        # 能通过硬排除和评分的官方 IR 其他事实，作为公司动态展示，
        # 不再丢到普通行业新闻。
        return "intl_core_company"
    # 外部监管机构对公司/短租市场采取的行动是行业环境事件，
    # 不是公司自身动作。
    if ctype == "regulation" or re.search(
            r"crackdown|licensing laws?|regulator|government.{0,18}(?:rules?|orders?|bans?)|"
            r"监管|新规|许可法|政府.{0,8}(?:要求|禁止|出台)", text, re.I):
        item["suppress_core_badge"] = True
        return "intl_industry"
    # BKNG/EXPE/ABNB 实质动态 → 核心公司动态
    if is_core and item.get("substantive_company_change"):
        return "intl_core_company"
    # 其余国际条目 → 国际行业
    if is_core:
        item["suppress_core_badge"] = True
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
        if mk in ("intl_core_company", "intl_industry", "dom_industry") \
                and item.get("display_ready") is False:
            continue
        # 跨模块同事件去重
        eid = item.get("event_id")
        # 同一大会的多家公司可能从旧缓存沿用相同 event_id；
        # 核心公司事件必须加公司维度，只折叠同一公司的多来源报道。
        event_entity = str(item.get("entity_id", "") or "")
        event_key = (eid, event_entity) if eid and event_entity in ("BKNG", "EXPE", "ABNB") else eid
        if event_key:
            owner = event_owner.get(event_key)
            if owner:
                owner_mk, owner_item = owner
                if MODULE_PRIORITY.get(mk, 0) > MODULE_PRIORITY.get(owner_mk, 0):
                    # 当前条目优先级更高 → 成为新主，原主条目降级为 related_source
                    related = list(owner_item.get("related_sources") or [])
                    if owner_item.get("source") and owner_item["source"] not in related:
                        related.append(owner_item["source"])
                    item.setdefault("related_sources", [])
                    item["related_sources"] = list(item.get("related_sources") or []) + related
                    event_owner[event_key] = (mk, item)
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
                event_owner[event_key] = (mk, item)
        modules[mk].append(item)

    # 保留期修剪 + 排序 + 限量
    for mk in MODULE_KEYS:
        items = modules[mk]
        retention = MODULE_RETENTION_DAYS.get(mk, 14)
        cap = MODULE_MAX_ITEMS.get(mk, 50)
        kept = []
        for it in items:
            if it.get("folded_into"):
                continue  # 渲染层过滤：被折叠条目不进入模块列表
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
        # 排序：纯按日期降序（最新在上），不再按 selection_score 优先
        # 用户要求: 最新新闻永远在最上面，越往下越旧
        kept.sort(key=lambda x: x.get("date") or "9999", reverse=True)
        # 2026-08-20: 模块内再跑一次同事件折叠（prune_and_dedupe 跑在 selection 之前,
        # 选择后不同分区路由过来的条目可能再次重复, 如"东航14天免费退改"被5家媒体报道）
        if mk in ("dom_industry", "dom_disclosures", "intl_industry", "intl_core_company"):
            kept = dedupe_same_article(kept)
            kept = group_same_events(kept)
            if mk == "intl_core_company":
                kept = group_core_company_events(kept, window_days=7)
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
TRAVEL_KEYWORD_PATTERNS = [
    re.compile(r'(?<![A-Za-z0-9])' + re.escape(kw) + r'(?![A-Za-z0-9])', re.IGNORECASE)
    for kw in TRAVEL_STRICT_KEYWORDS
]
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
        if max_per is None or src_count < max_per:
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
        if _TRANSLATE_FAILS >= 10:
            if not breaker_triggered:
                breaker_triggered = True
                print(f"    [translate] Circuit breaker tripped at item {idx}/{total}. "
                      f"Keeping original English for remaining {total - idx + 1} items.")
            # Preserve originals for a later daily retry, but do not call either
            # translation endpoint again in this run.  Previously the loop still
            # translated both title and summary after announcing the breaker,
            # which could turn a 300-item refresh into a multi-hour timeout.
            title = item.get('title', '')
            summary = item.get('summary', '')
            if title and re.search(r'[a-zA-Z]{2}', title):
                item['title_original'] = title
                skipped += 1
            if summary and re.search(r'[a-zA-Z]{4}', summary):
                item['summary_original'] = summary[:200]
            continue
        title = item.get('title', '')
        if title and re.search(r'[a-zA-Z]{2}', title) and not _has_sufficient_chinese(title):
            original = title
            item.setdefault('title_original', title)
            item['title'] = translate_text(title)
            if item['title'] != original:
                translated += 1
            else:
                skipped += 1
        summary = item.get('summary', '')
        if summary and re.search(r'[a-zA-Z]{4}', summary) and not _has_sufficient_chinese(summary):
            item.setdefault('summary_original', summary[:200])
            item['summary'] = translate_text(summary[:200])
    if breaker_triggered:
        print(f"    Translated {translated} items, kept English for {skipped} "
              f"(breaker tripped — Google 429 throttle)")
    else:
        print(f"    Translated {translated} items from English to Chinese ({skipped} unchanged)")
    return items


# Deterministic display translations for current high-value regression items.
# They also protect the dashboard when public translation endpoints are throttled.
DISPLAY_ZH_TRANSLATIONS = {
    "Booking Holdings vs. Expedia in B2B: Bombshell Estimate Says Booking Leads in Room Nights":
        "Booking Holdings与Expedia的B2B业务对比：估算显示Booking间夜量领先",
    "Booking Holdings vs Expedia in B2B: Bombshell Estimate Says Booking Leads in Room Nights":
        "Booking Holdings与Expedia的B2B业务对比：估算显示Booking间夜量领先",
    "What Hotelbeds’ Shrinking Margins Mean for Hotel Distribution":
        "Hotelbeds利润率收窄对酒店分销意味着什么",
    "Google’s Agentic Hotel Booking Tool Comes to AI Mode":
        "谷歌智能体酒店预订工具上线AI Mode",
    "Delta plans NDC solution launch by year-end":
        "达美航空计划年底前推出NDC解决方案",
    "Expedia Executive Sells 3,133 Shares for $1 Million":
        "Expedia高管出售3,133股，套现100万美元",
    "Expedia Group makes AI-motivated leadership cuts":
        "Expedia集团因AI转型调整领导层",
    "Airbnb crackdown: Penang introduces new licensing laws for short-term rentals":
        "槟城出台短租许可新规，收紧Airbnb监管",
}

# 翻译端点限流时的确定性回退：只翻译已抓取到的公开摘要。
DISPLAY_ZH_SUMMARIES = {
    "Booking Holdings与Expedia的B2B业务对比：估算显示Booking间夜量领先":
        "无论如何解读这些数据，Booking Holdings的B2B业务规模似乎都远超旅游业此前的认知，其正在推进的重组也可能产生显著影响。",
    "Agoda与菲律宾旅游部合作，推动2026年旅游业增长":
        "Agoda与菲律宾旅游部建立合作，以推动2026年旅游业增长。",
    "Expedia集团因AI转型调整领导层":
        "Expedia集团因AI转型需要对领导层进行了调整。",
    "Agoda与新加坡旅游局扩大合作，推动旅游需求和技术转型":
        "Agoda与新加坡旅游局扩大合作，以提升旅游需求并推动行业技术转型。",
    "Agoda为住宿合作伙伴推出新版Partner Portal":
        "Agoda为住宿合作伙伴推出了改版后的Partner Portal。",
    "Hotelbeds利润率收窄对酒店分销意味着什么":
        "Hotelbeds曾凭借规模成为主要的独立床位库，但其最新业绩显示，规模已不再能单独保护该业务的经济性。",
    "谷歌智能体酒店预订工具上线AI Mode":
        "谷歌首次预告该功能九个月后，智能体酒店预订功能正式上线AI Mode。",
    "达美航空计划年底前推出NDC解决方案":
        "达美航空计划在年底前推出NDC解决方案。",
    "Expedia高管出售3,133股，套现100万美元":
        "Expedia一名高管出售3,133股公司股票，交易金额约100万美元。",
    "锦江酒店与携程签署战略谅解备忘录，深化东盟合作":
        "锦江酒店与携程签署战略谅解备忘录，将进一步深化东盟市场合作。",
    "特斯拉、Uber 和 Waymo 均获准在内华达州运营数千辆机器人出租车":
        "特斯拉、Uber和Waymo均已获准在内华达州运营数千辆机器人出租车。",
    "槟城出台短租许可新规，收紧Airbnb监管":
        "槟城针对Airbnb等短期租赁业务推出新的许可制度。",
}


IR_ENTITY_NAMES_ZH = {
    "BKNG": "Booking Holdings",
    "EXPE": "Expedia Group",
    "ABNB": "Airbnb",
}


def _prepare_ir_chinese_display(item):
    """为官方 IR 公告提供不依赖免费翻译端点的中文回退。"""
    if not item.get("is_ir_source"):
        return
    title = str(item.get("title", "") or "").strip()
    original = str(item.get("title_original", "") or title).strip()
    entity = str(item.get("entity_id", "") or "")
    company = IR_ENTITY_NAMES_ZH.get(entity, entity or "公司")
    kind = str(item.get("ir_release_kind", "") or "")

    if not re.search(r"[\u4e00-\u9fff]", title):
        translated = ""
        if kind == "investor_event":
            conference = "投资者大会"
            if re.search(r"Goldman Sachs.*Communacopia", original, re.I):
                conference = "高盛Communacopia + Technology大会"
            elif re.search(r"Citi.*Global TMT", original, re.I):
                year = re.search(r"\b(20\d{2})\b", original)
                conference = f"花旗{year.group(1) if year else ''}全球TMT大会"
            translated = f"{company}将参加{conference}"
        elif kind == "earnings_disclosure":
            quarter_map = {
                "first": "第一季度", "second": "第二季度",
                "third": "第三季度", "fourth": "第四季度",
            }
            quarter = next((zh for en, zh in quarter_map.items()
                            if re.search(rf"\b{en}\b", original, re.I)), "")
            year = re.search(r"\b(20\d{2})\b", original)
            translated = f"{company}发布{year.group(1) if year else ''}年{quarter}业绩"
        if translated:
            item.setdefault("title_original", original)
            item["title"] = translated

    summary = str(item.get("summary", "") or "").strip()
    if not summary or not re.search(r"[\u4e00-\u9fff]", summary):
        if summary:
            item.setdefault("summary_original", summary[:400])
        if kind == "investor_event":
            item["summary"] = f"{company}公告将参加相关投资者大会，并披露了参会安排。"
            item["summary_translated"] = True
            item["summary_status"] = "deterministic_ir_summary"
        elif kind == "earnings_disclosure":
            item["summary"] = f"{company}官方 IR 发布了该期业绩及相关披露材料。"
            item["summary_translated"] = True
            item["summary_status"] = "deterministic_ir_summary"


def prepare_chinese_news_display(news_data):
    """Guarantee Chinese-facing news modules without discarding raw cache items.

    Titles that still lack meaningful Chinese after translation are marked as
    pending and omitted only from display modules; they remain in the raw cache
    so a later daily run can retry translation. A source summary must also be
    Chinese before display. If the source summary is absent or its translation
    fails, leave the display summary empty and retain the original for retry;
    never synthesize a title-based placeholder summary.
    """
    for section in ("international", "domestic"):
        for category, items in (news_data.get(section) or {}).items():
            if not isinstance(items, list):
                continue
            for item in items:
                item["title"] = strip_title_emoji(normalize_company_names(item.get("title", "")))
                if item.get("title_original"):
                    item["title_original"] = strip_title_emoji(item["title_original"])
                if item.get("summary"):
                    item["summary"] = normalize_company_names(item["summary"])
                if category == "sec_filings":
                    continue
                _prepare_ir_chinese_display(item)
                title = str(item.get("title", "") or "").strip()
                original = str(item.get("title_original", "") or "").strip()
                translated = DISPLAY_ZH_TRANSLATIONS.get(original) or DISPLAY_ZH_TRANSLATIONS.get(title)
                if translated:
                    if not original and title != translated:
                        item["title_original"] = title
                    item["title"] = strip_title_emoji(normalize_company_names(translated))
                    title = item["title"]
                    remember_translation(original, title)
                zh_count = len(re.findall(r"[\u4e00-\u9fff]", title))
                en_count = len(re.findall(r"[A-Za-z]", title))
                item["display_ready"] = bool(zh_count >= 4 or (zh_count >= 1 and en_count <= 12))
                item["translation_status"] = "ready" if item["display_ready"] else "pending"
                summary = str(item.get("summary", "") or "").strip()
                legacy_placeholder = f"公开信息显示，{title.rstrip('。！？!?')}。"
                if item.pop("summary_from_title", False) or summary == legacy_placeholder:
                    item["summary"] = ""
                    item.pop("summary_status", None)
                    item.pop("summary_generated_at", None)
                    summary = ""
                mapped_summary = (DISPLAY_ZH_SUMMARIES.get(title) or
                                  DISPLAY_ZH_SUMMARIES.get(str(translated or "")))
                if mapped_summary:
                    item["summary"] = normalize_company_names(mapped_summary)
                    item["summary_translated"] = True
                    item["summary_status"] = "generated"
                    summary = item["summary"]
                    remember_translation(item.get("summary_original"), summary)
                if summary and not re.search(r"[\u4e00-\u9fff]", summary):
                    item.setdefault("summary_original", summary[:200])
                    item["summary"] = ""
                    item["translation_status"] = "pending_summary"
    return news_data


def retry_cached_translations(items):
    """Retry all-English fields that previously fell back after a translation failure."""
    if _TRANSLATE_FAILS >= 10:
        print("  [Translation retry] skipped because the translation circuit breaker is open")
        return items
    retried = translated = 0
    for item in items:
        source = str(item.get("source", "") or "")
        if source not in TRANSLATE_SOURCES:
            continue
        item_retried = False
        for field, original_field, max_chars in (
                ("title", "title_original", 500), ("summary", "summary_original", 200)):
            value = str(item.get(field, "") or "").strip()
            if not value or re.search(r"[\u4e00-\u9fff]", value) or not re.search(r"[A-Za-z]{3}", value):
                continue
            retried += 1
            item_retried = True
            item.setdefault(original_field, value[:max_chars])
            result = translate_text(value[:max_chars], max_chars=max_chars)
            if result and result != value:
                item[field] = result
                translated += 1
        if item_retried:
            item["translation_status"] = "translated" if re.search(
                r"[\u4e00-\u9fff]", str(item.get("title", ""))) else "pending_retry"
    if retried:
        print(f"  [Translation retry] {translated}/{retried} cached English fields translated")
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

# 人工标注仅做精确 URL / 归一化标题覆盖，不自动泛化为新正则。
_MANUAL_LABEL_CACHE = None
_MANUAL_LABEL_CACHE_MTIME = None


def _manual_label_key(item):
    url = _norm_url(item.get("url", "")) if "_norm_url" in globals() else str(item.get("url", "") or "").rstrip("/")
    if url:
        return "url:" + url
    title = _norm_title(item.get("title", "")) if "_norm_title" in globals() else re.sub(
        r"\W+", "", str(item.get("title", "") or "").lower())
    return "title:" + title if title else ""


def load_manual_labels(path=None):
    """读取版本化人工标注；文件缺失/损坏时安全回退为空，不影响日更。"""
    global _MANUAL_LABEL_CACHE, _MANUAL_LABEL_CACHE_MTIME
    path = path or MANUAL_LABELS_PATH
    try:
        mtime = os.path.getmtime(path)
    except OSError:
        mtime = None
    if path == MANUAL_LABELS_PATH and _MANUAL_LABEL_CACHE is not None \
            and mtime == _MANUAL_LABEL_CACHE_MTIME:
        return _MANUAL_LABEL_CACHE
    labels = {}
    try:
        with open(path, "r", encoding="utf-8") as f:
            payload = json.load(f)
        for row in payload.get("labels", []) if isinstance(payload, dict) else []:
            if not isinstance(row, dict) or row.get("label") not in ("保留", "排除", "不确定"):
                continue
            key = row.get("key") or _manual_label_key(row)
            if key:
                labels[key] = row
    except (OSError, ValueError, TypeError):
        labels = {}
    if path == MANUAL_LABELS_PATH:
        _MANUAL_LABEL_CACHE = labels
        _MANUAL_LABEL_CACHE_MTIME = mtime
    return labels


def _manual_label_for(item):
    return load_manual_labels().get(_manual_label_key(item))


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
    (r"活动报名|参会报名|观众登记|专业观众|报名通道|参会指南|会议预告|峰会预告|论坛预告|论坛前瞻|展会预告|"
     r"(?:案例|合作伙伴|嘉宾|讲者|参展商).{0,8}征集|征集.{0,8}(?:案例|合作伙伴|嘉宾|讲者|参展商)", "活动报名/会议预告"),
    (r"采购需求|旅业采购|寻找供应商|供应商对接|采购对接|寻.*地接社|地接社.*合作", "采购对接"),
    (r"入群|扫码加入|加入社群|广告招商|招商合作|投稿信箱|广告报价", "社群广告"),
    (r"实测|亲测|打卡|攻略|怎么玩|保级升卡|会员升级指南|自驾.*(实测|流程|多方便)|路线推荐|避坑指南|省钱秘籍", "消费者攻略/实测"),
    (r"篮球|足球赛|集体婚礼|庆典|颁奖|荣获|斩获|摘得.{0,4}奖|获评|获奖|公益|慈善|捐赠|志愿服务|爱心助考", "体育赞助/庆典/获奖/公益"),
    (r"救援故事|紧急救援|机上救援|成功救援|备降救人|坚守岗位|高温坚守|防汛抗|人物故事|员工故事|劳模|最美.{0,6}人|暖心故事|走红|紧急救助|旅客.{0,6}突发疾病", "救援/员工个人故事/坚守"),
    (r"短评|随笔|行业鸡汤|流向何方|趋势漫谈|超哥|闲话|漫谈", "无新事实短评"),
    (r"如何避开|差旅大坑|踩坑指南|如何避坑|有哪些坑", "泛观点/攻略型长文"),
    (r"新玩法|满分口碑|深度好眠|种草|安利|宝藏|天花板|绝绝子|焕新出发|重磅升级|荣耀启程|网红", "品牌软文"),
    (r"一周要闻|新闻合集|本周速览|行业动态合集|周报盘点|每日速览|投融资动态|这\d+笔交易|\d+笔交易值得关注|"
     r"travel tech news briefs|^newsroom\s*[-–—]", "新闻合集/无具体事件页"),
    (r"investors? raise the bar|ai trip planning is outpacing|ai transformation in travel\s*:|"
     r"destinations? rethink marketing amid", "观点评论/趋势展望"),
    (r"股票股价|股价行情|_股价_|行情_讨论|股吧", "社群广告"),
    (r"返现|返还\s*\d+|消费满.{0,12}(?:返|减)|满\s*\d+.{0,8}(?:返|减)|优惠券|折扣码|"
     r"限时优惠|会员促销|targeted|cash\s*back|get\s*\$?\d+\s*back|promo\s*code|"
     r"best\s+hotels?|top\s+\d+|according\s+to\s+reviews", "软广/优惠促销/榜单"),
    (r"股价.{0,12}(?:走高|上涨|下跌|跑赢|表现)|(?:该股|股票).{0,12}(?:走高|上涨|下跌|跑赢|表现)|(?:stock|shares?).{0,20}(?:rise|rally|gain|fall|"
     r"outperform)|估值讨论|投资建议|分析师.{0,8}(?:上调|下调|评级|目标价)|"
     r"wall street.{0,12}(?:believe|bullish|bearish)|how investors? (?:are )?reacting|"
     r"how .{0,90} will impact .{0,24}investors?", "股价/估值评论"),
    (r"(?:bank|trust|management|capital|fund|holdings?).{0,45}(?:acquires?|buys?|purchases?|adds?)"
     r".{0,30}(?:shares?|stake|position).{0,45}(?:BKNG|EXPE|ABNB|Booking Holdings|Expedia Group|Airbnb)|"
     r"(?:acquires?|buys?|purchases?|adds?).{0,20}(?:shares?|stake|position).{0,45}"
     r"(?:BKNG|EXPE|ABNB|Booking Holdings|Expedia Group|Airbnb)", "被动机构持仓变动"),
    (r"Airbnb\.org.{0,50}(?:emergency housing|disaster|donat|relief|wildfire|fire)|"
     r"(?:emergency housing|disaster relief).{0,50}Airbnb\.org", "公益/救灾宣传"),
    (r"(?:creative|advertising|media) agency of record|创意代理商|广告代理商", "品牌营销代理宣传"),
    (r"appoints?.{0,45}former (?:Airbnb|Expedia|Booking(?: Holdings|\.com)?).{0,30}"
     r"(?:executives?|advisors?|officers?)|former (?:Airbnb|Expedia|Booking(?: Holdings|\.com)?)"
     r".{0,35}(?:executives?|officers?).{0,35}(?:joins?|appointed|advisor)", "前高管在第三方公司履新"),
    # 名人/运动员投资非核心项目(2026-08-20 新增: 用户指定 Derek Jeter 投资大学城酒店品牌不重要)
    (r"德里克·杰特|Derek Jeter|运动员|体育明星|球星|明星.{0,4}(?:投资|入股|收购)|(?:投资|入股|收购).{0,4}(?:运动员|体育明星|球星)", "名人/运动员投资非核心项目"),
    # 箱包皮具类收购(2026-08-20 新增: 新秀丽收购Béis属于箱包行业, 非OTA/旅游业核心)
    # 仅排除箱包行业内部并购, 不影响航司行李政策等合法旅游新闻
    (r"(?:箱包皮具|行李箱|duffel|backpack|新秀丽|Samsonite).{0,8}(?:收购|并购|投资|入股|融资|acquir|merger|invest|raises)", "箱包皮具类并购(非旅行核心业务)"),
]
HARD_EXCLUDE_COMPILED = [(re.compile(p, re.IGNORECASE), label) for p, label in HARD_EXCLUDE_PATTERNS]


def hard_exclude_reason(item, content_type=None):
    """硬排除判定: 返回拒绝原因标签或 None。"""
    title_only = str(item.get("title", "") or "")
    if re.search(r"[?？]\s*$", title_only):
        return "无新事实短评"
    text = "{} {}".format(title_only, item.get("summary", "") or "")
    for pat, label in HARD_EXCLUDE_COMPILED:
        if pat.search(text):
            return label
    # 内容类型优先级保证“新产品/交易/政策事实 + 为什么”先归事实类型；只有最终仍为
    # opinion 的条目才按用户规则整体排除。
    if content_type == "opinion":
        return "观点评论/泛分析"
    return None


# ── 内容类型分类器（确定性; 优先级即列表顺序） ──
CONTENT_TYPE_RULES = [
    ("earnings", r"财报|季报|年报|业绩|营收|盈利|亏损|净利润|利润|业绩指引|指引|guidance|earnings|revenue|profit|beat estimates|beat expectations"),
    ("operating_data", r"运营数据|经营数据|旅客量|客座率|运力|间夜|room ?nights?|revpar|\badr\b|出租率|入住率|净增|净开店|新开店|门店数|吞吐量|航班量|游客量|旅游收入|接待游客"),
    ("ma_investment", r"收购|并购|投资|融资|入股|合资|合并|出售|剥离|分拆|上市|ipo|acquisition|acquire|to acquire|invest|raises|funding"),
    ("employee_policy", r"陪产假|产假|育儿假|员工福利|员工.{0,6}制度|福利政策|薪酬|股权激励|人才战略|员工关怀|人才争夺|争夺.{0,6}人才|AI\s*人才|人才战"),
    ("product", r"上线|推出|发布|开放|新功能|新产品|直订|服务升级|帮帮|launch|unveil|introduce|roll ?out|debuts?|brings?\s+ai"),
    ("policy_commission", r"佣金|退改签|退票|改签|价格政策|商家政策|履约|手续费|commission|refund|cancel|service fees?|lower fees?"),
    ("management_org", r"任命|履新|离任|辞任|辞职|ceo|cfo|总裁|高管|管理层|组织架构|重组|裁员|appoint(?:s|ed|ment)?|steps down|leadership cuts?|cuts?.{0,18}(?:executives?|leaders?)"),
    ("ai_application", r"\bai\b|人工智能|大模型|智能体|生成式|agent|artificial intelligence"),
    ("expansion", r"扩张|进军|进入.{0,6}市场|开业|拓展|出海|国际化|新增.{0,6}航线|开通|expansion|enters?"),
    ("regulation", r"监管|处罚|约谈|整改|立法|法规|政策|办法|规定|统计|通报"),
    ("governance_legal", r"诉讼|调查|和解|庭审|起诉|指控|回购|分红|治理|lawsuit|settlement|probe|sued"),
    ("partnership", r"合作|战略协议|签约|联盟|携手|partner|partnership"),
    ("strategy_marketing", r"营销|品牌战略|广告|推广|marketing|brand"),
    ("opinion", r"观点|观察|评论|解读|专访|对话|思考|前瞻|展望|如何|为何|为什么|浅析|探讨|浅谈"),
]

FORMAL_POLICY_TYPES = {"employee_policy", "management_org", "policy_commission", "governance_legal"}

# v2 主题边界：Hotel 默认排除；只有直接改变 OTA 预订、分销、佣金、直订竞争、
# 平台合作或相关监管时例外保留。
HOTEL_TOPIC_RE = re.compile(
    r"酒店|hotel|hotels|hospitality|lodging|resort|住宿|民宿|度假租赁|vacation rental|"
    r"marriott|hilton|hyatt|ihg|accor|wyndham|万豪|希尔顿|凯悦|洲际|雅高|温德姆|锦江|华住|首旅|亚朵",
    re.IGNORECASE)
OTA_DIRECT_IMPACT_RE = re.compile(
    r"ota|在线旅游|online travel|booking platform|travel platform|预订平台|"
    r"booking\.com|booking holdings|expedia|airbnb|trip\.com|携程|同程|飞猪|美团酒旅|agoda|kayak|"
    r"分销|distribution|渠道|佣金|commission|直订|direct booking|直连|api|"
    r"预订入口|booking tool|agentic.{0,8}(?:booking|预订)|ai.{0,8}(?:booking|预订)|"
    r"(?:booking|预订).{0,8}(?:ai|人工智能|智能体)|平台合作|平台监管",
    re.IGNORECASE)
MEDIA_INSIDER_SALE_RE = re.compile(
    r"(?:高管|executive|insider).{0,24}(?:出售|售出|减持|sells?|sold|cash out).{0,24}(?:股|share|stock)|"
    r"(?:出售|售出|减持|sells?|sold|cash out).{0,24}(?:股|share|stock).{0,24}(?:高管|executive|insider)",
    re.IGNORECASE)
STOCK_MARKET_FACT_RE = re.compile(
    r"股价|该股|股票表现|shares?.{0,18}(?:rise|rally|gain|fall|outperform)|"
    r"stock.{0,18}(?:rise|rally|gain|fall|outperform)|wall street|分析师.{0,8}(?:评级|目标价)",
    re.IGNORECASE)
ALLOWED_VERTICAL_THEME_RE = re.compile(
    r"ota|在线旅游|online travel|travel tech|travel technology|booking platform|travel platform|"
    r"预订平台|分销|distribution|佣金|commission|直订|direct booking|直连|api|"
    r"预订入口|booking tool|agentic|人工智能|\bai\b|智能体|"
    r"收购|并购|融资|合并|ipo|acquisition|acquir|merger|funding|raises|"
    r"监管|法规|政策|regulation|policy|"
    r"上线|推出|发布|launch|unveil|introduce|合作|partner|partnership|"
    r"gross bookings|room nights|take rate|gbv|gmv|交易额|订单|获客成本|取消率",
    re.IGNORECASE)
VERTICAL_SOURCE_RE = re.compile(r"Skift|PhocusWire|Travel Weekly|环球旅讯", re.IGNORECASE)
CORE_ACTION_CTYPES = {
    "earnings", "operating_data", "ma_investment", "employee_policy", "product",
    "policy_commission", "management_org", "ai_application", "expansion",
    "regulation", "governance_legal", "partnership", "strategy_marketing",
}

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
    r"acquir|launch|unveil|introduc|report|announce|expand|partner|appoint|invest|rais|"
    r"brings?\s+ai|\btest(?:s|ing)?\b|lower fees?|leadership cuts?|cuts?.{0,18}(?:executives?|leaders?)",
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
    r"航班取消|大范围取消|特殊退改|复航|新增.{0,8}航线|航线.{0,4}调整|调整.{0,4}航线|机队|宽体机|"
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
    matched_rule_ids = []

    entity_id = identify_entity(item) or item.get("entity_id")
    is_core = entity_id in CORE_COMPANY_IDS
    ctype = classify_content_type(text)
    item["entity_id"] = entity_id
    item["is_core_company"] = is_core
    item.setdefault("source_channel", item.get("source_channel") or "")
    item["content_type"] = ctype
    item["policy_version"] = POLICY_VERSION
    item["matched_rule_ids"] = matched_rule_ids
    manual = _manual_label_for(item)
    item["manual_label"] = manual.get("label") if manual else None

    def _finalize(kept, score, rejection_reason):
        item["selection_score"] = int(max(0, min(100, score)))
        item["selection_status"] = "kept" if kept else "rejected"
        item["selection_reasons"] = reasons
        item["matched_rule_ids"] = matched_rule_ids
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
        matched_rule_ids.append("official.sec.filing")
        return _finalize(True, 100, None)

    # 1. 硬排除（§6）: 活动/采购/攻略/赞助/人物稿/软文/合集/短评
    hr = hard_exclude_reason(item, ctype)
    if hr:
        item["substantive_company_change"] = False
        reasons.append(f"硬排除: {hr}")
        matched_rule_ids.append("exclude.hard." + re.sub(r"\W+", "_", hr).strip("_"))
        if manual and manual.get("label") == "保留":
            reasons.append("人工标注保留覆盖硬排除")
            matched_rule_ids.append("manual.keep")
        else:
            return _finalize(False, 0, hr)

    # 1b. Hotel 默认排除，仅 OTA 直接影响例外。
    is_hotel_topic = bool(HOTEL_TOPIC_RE.search(text))
    hotel_ota_exception = bool(OTA_DIRECT_IMPACT_RE.search(text))
    if is_hotel_topic:
        matched_rule_ids.append("topic.hotel")
        if hotel_ota_exception:
            matched_rule_ids.append("topic.hotel.ota_direct_exception")
        elif not (manual and manual.get("label") == "保留"):
            item["substantive_company_change"] = False
            reasons.append("Hotel默认排除：未直接影响OTA")
            return _finalize(False, 0, "Hotel非OTA相关")
        else:
            reasons.append("人工标注保留覆盖Hotel默认排除")
            matched_rule_ids.append("manual.keep")

    if manual and manual.get("label") == "排除":
        reasons.append("人工标注排除")
        matched_rule_ids.append("manual.reject")
        return _finalize(False, 0, "人工标注排除")

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
    media_insider_sale = bool(MEDIA_INSIDER_SALE_RE.search(text))
    substantive = (bool(ACTION_MARKER_RE.search(text)) and ctype in CORE_ACTION_CTYPES
                   and not media_insider_sale)
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

    # v2: 垂直媒体不再仅凭来源保底。只有命中允许主题才保底到60；未命中则按
    # 原始五维分数正常淘汰。Hotel 默认排除和观点/软广硬排除已在上游执行。
    vertical_allowed = bool(VERTICAL_SOURCE_RE.search(source) and ALLOWED_VERTICAL_THEME_RE.search(text))
    if vertical_allowed:
        matched_rule_ids.append("vertical.allowed_theme")
        if score < CORE_KEEP_THRESHOLD:
            reasons.append("垂直媒体允许主题保底60")
        score = max(score, CORE_KEEP_THRESHOLD)

    # 两条人工样本均确认媒体高管售股事实可保留，但它不是公司经营动作：
    # 只按国际行业事实展示，不进入核心公司动态。
    if media_insider_sale:
        matched_rule_ids.append("market.insider_sale_fact")
        reasons.append("媒体高管售股事实保留（非核心公司动态）")
        score = max(score, CORE_KEEP_THRESHOLD)

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

    if manual and manual.get("label") == "保留":
        if score < CORE_KEEP_THRESHOLD:
            reasons.append("人工标注保留覆盖评分")
        matched_rule_ids.append("manual.keep")
        score = max(score, CORE_KEEP_THRESHOLD)

    kept = score >= CORE_KEEP_THRESHOLD
    if not kept:
        reasons.append("低于准入分60")
    return _finalize(kept, score, None if kept else "评分低于60且无保底资格")


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
                        "title_original": item.get("title_original", ""),
                        "summary": item.get("summary", ""),
                        "source": item.get("source", ""),
                        "date": item.get("date", ""),
                        "url": item.get("url", ""),
                        "section": section,
                        "category": cat,
                        "entity_id": item.get("entity_id"),
                        "content_type": item.get("content_type"),
                        "selection_score": item.get("selection_score", 0),
                        "selection_reasons": item.get("selection_reasons", []),
                        "matched_rule_ids": item.get("matched_rule_ids", []),
                        "policy_version": item.get("policy_version", POLICY_VERSION),
                        "manual_label": item.get("manual_label"),
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
        "policy_version": POLICY_VERSION,
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


def classify_ir_release(title, url=""):
    """将官方 IR 消息分为业绩披露、投资者活动或经营/战略动作。"""
    text = f"{title} {url}"
    if re.search(
            r"financial results?|quarterly results?|quarter.{0,20}results?|"
            r"full[- ]year results?|earnings|"
            r"annual reports?|quarterly reports?|shareholder letters?|guidance|"
            r"webcast.{0,30}(?:results?|earnings)|results?.{0,30}webcast",
            text, re.I):
        return "earnings_disclosure"
    if re.search(
            r"participate in|present at|investor day|investor conference|"
            r"technology conference|TMT conference|fireside chat|communacopia",
            text, re.I):
        return "investor_event"
    if re.search(
            r"acquir|merger|partner|agreement|launch|unveil|introduc|appoint|"
            r"leadership|reorgani[sz]|strategy|expand|authorization|platform|"
            r"product|service|operations?|research finds?",
            text, re.I):
        return "core_action"
    return "other"


def parse_q4_ir_feed(data, src):
    """解析 Q4 官方 PressRelease feed，只保留 IR 新闻/披露页。"""
    if not isinstance(data, dict):
        return []
    rows = data.get("GetPressReleaseListResult") or []
    items, seen = [], set()
    for row in rows:
        if not isinstance(row, dict):
            continue
        title = html_lib.unescape(str(row.get("Headline", "") or "")).strip()
        link = str(row.get("LinkToDetailPage", "") or row.get("LinkToUrl", "") or "").strip()
        # Expedia IR feed 也混入第三方 media 稿，不属于公司经营/战略披露。
        if not title or not link or "/media/media-details/" in link.lower():
            continue
        url = urljoin(src["url"], link)
        key = _norm_url(url)
        if key in seen:
            continue
        seen.add(key)
        date_raw = str(row.get("PressReleaseDate", "") or "").strip()
        date_str = ""
        for fmt in ("%m/%d/%Y %H:%M:%S", "%m/%d/%Y"):
            try:
                date_str = datetime.datetime.strptime(date_raw, fmt).strftime("%Y-%m-%d")
                break
            except ValueError:
                continue
        summary = str(row.get("ShortDescription", "") or row.get("ShortBody", "") or "")
        summary = html_lib.unescape(re.sub(r"<[^>]+>", " ", summary))
        summary = re.sub(r"\s+", " ", summary).strip()[:400]
        kind = classify_ir_release(title, url)
        items.append({
            "date": date_str,
            "title": title,
            "url": url,
            "summary": summary,
            "source": src["name"],
            "category": "industry_news",
            "entity_id": src["entity_id"],
            "company": src["entity_id"],
            "is_core_company": True,
            "source_channel": "ir_official_q4",
            "is_ir_source": True,
            "ir_release_kind": kind,
            "content_type": "earnings" if kind == "earnings_disclosure" else "general",
        })
    items.sort(key=lambda x: x.get("date") or "", reverse=True)
    return items


def fetch_ir_press_releases():
    """直接抓取 BKNG/EXPE/ABNB 官方 IR 页面使用的 Q4 公开 feed。"""
    all_items = []
    for src in IR_SOURCES:
        try:
            query = urllib.parse.urlencode({
                "LanguageId": 1, "pageSize": 50, "pageNumber": 0,
                "tagList": "", "includeTags": "true",
                "year": datetime.date.today().year, "excludeSelection": 1,
                "bodyType": 3, "pressReleaseDateFilter": 1,
                "categoryId": "00000000-0000-0000-0000-000000000000",
            })
            api_url = f"{src['api_url']}?{query}"
            print(f"    IR {src['name']}: fetching official Q4 feed")
            data = safe_request(api_url, timeout=20, retries=2)
            items = parse_q4_ir_feed(data, src)
            if not items:
                mark_source(src["name"], "failed", item_count=0, error_code="empty_q4_feed")
                continue
            all_items.extend(items)
            mark_source(src["name"], "success", item_count=len(items))
            print(f"    IR {src['name']}: {len(items)} items (official Q4 feed)")
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


def _td_is_domestic(title, summary="", source_channel=""):
    """环球旅讯国内外分流：显式国内优先，海外/跨境科技交易进入国际。"""
    text = f"{title} {summary}"
    for kw in TD_DOMESTIC_MARKERS:
        if kw in text:
            return True
    for kw in TD_INTL_MARKERS:
        if kw in text:
            return False
    # traveltech/distribute 频道常见海外初创公司并购，标题可能只有英文公司名而无国家词。
    # 至少两个英文专名 + 交易动作时按国际处理；避免再次把 eTravel/Accent、
    # VayKLife/Xplorie、Spotnana/Troop 默认归为国内。
    if re.search(r"收购|并购|融资|合并|投资|acquir|merger|funding", text, re.I):
        names = [n for n in re.findall(r"(?<![A-Za-z])[A-Za-z][A-Za-z0-9.&-]{2,}", title)
                 if n.lower() not in {"ota", "ai", "travel", "events", "group"}]
        if len(set(n.lower() for n in names)) >= 2:
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
        if not _td_is_domestic(it.get("title", ""), it.get("summary", ""), it.get("source_channel", "")):
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
    # 一手文件/官方公告
    "SEC EDGAR": 110,
    "披露易": 108, "文旅部": 105, "交通运输部": 105,
    "Booking Holdings IR": 100, "Expedia Group IR": 100, "Airbnb IR": 100,
    # 通讯社/主流财经媒体
    "Reuters": 96,
    "Bloomberg": 94, "Bloomberg Markets": 94, "Bloomberg Technology": 94,
    "Bloomberg Travel (GN)": 94, "Bloomberg Mobility (GN)": 94,
    "Wall Street Journal": 91, "WSJ": 91,
    "Financial Times": 90, "FT": 90,
    "CNBC": 86,
    # 公司 newsroom 和垂直行业媒体
    "Expedia": 85, "Booking.com": 85, "Airbnb": 85,
    "Skift": 76, "PhocusWire": 73, "Travel Weekly": 70,
    "环球旅讯": 65, "民航网": 64,
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
    # Google News 中转 URL 轻度降权；不应让 Bloomberg 等高权威源
    # 仅因链接经过聚合器就跌到垂直媒体之后。
    if _is_google_news_url(item.get("url")):
        rank -= 5
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
            # 同一大会上不同核心公司的官方 IR 公告是独立记录，不跨公司折叠。
            entity_i = str(known[i].get("entity_id", "") or "")
            entity_j = str(known[j].get("entity_id", "") or "")
            if entity_i in ("BKNG", "EXPE", "ABNB") and \
                    entity_j in ("BKNG", "EXPE", "ABNB") and entity_i != entity_j:
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


def _core_event_key(item):
    """只为高置信核心公司事件生成跨标题指纹，避免把同周不同事件误折叠。"""
    entity = str(item.get("entity_id", "") or "")
    if entity not in ("BKNG", "EXPE", "ABNB"):
        return None
    text = _sel_text(item).lower()
    ctype = str(item.get("content_type", "") or "")
    if ctype == "management_org":
        if re.search(r"裁员|裁减|领导层削减|高管.{0,8}(?:离职|出局)|重组|"
                     r"cuts?.{0,12}(?:executive|leader)|leadership cuts|executives? out|reorganiz", text, re.I):
            ai = "ai" if re.search(r"人工智能|\bai\b|artificial intelligence", text, re.I) else "general"
            return f"{entity}|management_org|restructure_cuts|{ai}"
        if re.search(r"任命|履新|appointment|named.{0,8}(?:ceo|cfo|president)", text, re.I):
            return f"{entity}|management_org|appointment|{_norm_title(item.get('title', ''))[:36]}"
    if ctype == "product" and entity == "BKNG" and \
            re.search(r"agoda.{0,35}partner portal|partner portal.{0,35}agoda", text, re.I):
        return "BKNG|product|agoda_partner_portal"
    # 官方 IR 与媒体对同一投资者大会的报道只展示一条，
    # 主条目由来源权威度决定。
    if str(item.get("ir_release_kind", "") or "") == "investor_event" or re.search(
            r"communacopia|global tmt conference|investor conference|investor day|"
            r"投资者大会|投资者日|路演", text, re.I):
        if re.search(r"communacopia", text, re.I):
            event = "goldman_communacopia"
        elif re.search(r"global tmt|\btmt\b", text, re.I):
            event = "global_tmt"
        else:
            event = _norm_title(item.get("title", ""))[:48]
        return f"{entity}|investor_event|{event}"
    return None


def group_core_company_events(items, window_days=7):
    """核心公司高置信同事件折叠；用于跨越72小时的连续报道。"""
    groups = {}
    for item in items:
        if item.get("folded_into"):
            continue
        key = _core_event_key(item)
        if key:
            groups.setdefault(key, []).append(item)
    for key, members in groups.items():
        members.sort(key=lambda x: x.get("date") or "")
        clusters = []
        for item in members:
            placed = False
            for cluster in clusters:
                if _dates_within(item.get("date") or "", cluster[-1].get("date") or "", window_days) is not False:
                    cluster.append(item)
                    placed = True
                    break
            if not placed:
                clusters.append([item])
        for cluster in clusters:
            if len(cluster) < 2:
                continue
            primary = max(cluster, key=lambda x: (
                _source_rank(x),
                1 if str(x.get("summary", "") or "").strip() else 0,
                x.get("date") or "",
                int(x.get("selection_score", 0) or 0),
            ))
            event_id = "ev_core_" + hashlib.md5(key.encode()).hexdigest()[:10]
            related = list(primary.get("related_sources") or [])
            for item in cluster:
                item["event_id"] = event_id
                if item is primary:
                    continue
                item["folded_into"] = primary.get("url") or "core_event"
                src = str(item.get("source", "") or "未知来源")
                if src not in related:
                    related.append(src)
            primary["related_sources"] = related
    return items


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


# 保留期（天）：新闻、SEC 和 IR 披露全部统一 14 天。
NEWS_RETENTION_DAYS = 14
SEC_LONG_RETENTION_TYPES = set()
SEC_LONG_RETENTION_DAYS = NEWS_RETENTION_DAYS
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


def _sec_accession_key(item):
    """从 SEC 记录或 EDGAR URL 中提取稳定 accession。"""
    accession = re.sub(r"[^0-9]", "", str(item.get("accession", "") or ""))
    if len(accession) >= 18:
        return accession
    url = str(item.get("url", "") or "")
    match = re.search(r"/Archives/edgar/data/\d+/(\d{18,20})(?:/|$)", url, re.I)
    return match.group(1) if match else ""


def dedupe_sec_accessions(items):
    """同一 accession 只保留证据最完整的 SEC 记录。"""
    groups, order = {}, []
    for item in items:
        key = _sec_accession_key(item) or ("url:" + _norm_url(item.get("url", "")))
        if key not in groups:
            groups[key] = []
            order.append(key)
        groups[key].append(item)
    result = []
    for key in order:
        members = groups[key]
        best = max(members, key=lambda x: (
            x.get("sec_summary_kind") == "document_detail",
            len(str(x.get("summary", "") or "")),
            not str(x.get("url", "") or "").endswith("/"),
            str(x.get("fetched_at", "") or ""),
        ))
        if not best.get("accession") and key.isdigit():
            best["accession"] = key
        result.append(best)
    return result


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
            if (section, cat) == ("international", "sec_filings"):
                items = dedupe_sec_accessions(items)
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

                # 全部 SEC/IR 与新闻统一保留 14 天。
                item_retention = retention

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


# ── 按需人工标注清单（不接入每日任务）────────────────────────────────────

def _load_json_file(path, default):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError, TypeError):
        return default


def _review_module_map(news_data):
    result = {}
    for module, items in (news_data.get("modules") or {}).items():
        if not isinstance(items, list):
            continue
        for item in items:
            key = _manual_label_key(item)
            if key:
                result[key] = module
    return result


def build_review_candidates(news_data=None, rejected_data=None, size=30):
    """从已保留与已拒绝新闻中分层抽取边界样本，返回稳定、可审计的行数据。"""
    news_data = news_data or _load_json_file(OUTPUT, {})
    rejected_data = rejected_data or _load_json_file(REJECTED_OUTPUT, {})
    module_map = _review_module_map(news_data)
    pool = []
    seen = set()

    for section in ("international", "domestic"):
        for category, items in (news_data.get(section) or {}).items():
            if not isinstance(items, list):
                continue
            for item in items:
                row = dict(item)
                row["section"] = section
                row["category"] = category
                row["current_decision"] = "保留"
                pool.append(row)
    for item in rejected_data.get("items", []) if isinstance(rejected_data, dict) else []:
        if isinstance(item, dict):
            row = dict(item)
            row["current_decision"] = "排除"
            pool.append(row)

    scored = []
    for original in pool:
        key = _manual_label_key(original)
        if not key or key in seen:
            continue
        seen.add(key)
        proposal = json.loads(json.dumps(original, ensure_ascii=False))
        ok, reason = select_news_item(
            proposal, proposal.get("section", "international"),
            proposal.get("category", "industry_news"))
        text = _sel_text(proposal)
        current_score = int(original.get("selection_score", 0) or 0)
        tags = []
        priority = 0
        if HOTEL_TOPIC_RE.search(text):
            tags.append("Hotel")
            priority += 30
            if OTA_DIRECT_IMPACT_RE.search(text):
                tags.append("OTA直接影响")
                priority += 8
        hard_reason = hard_exclude_reason(proposal, proposal.get("content_type"))
        if hard_reason:
            tags.append(hard_reason)
            priority += 28
        if proposal.get("entity_id") in ("BKNG", "EXPE", "ABNB"):
            tags.append("核心公司")
            priority += 20
        if 45 <= current_score <= 75:
            tags.append("临界分数")
            priority += 16
        current_module = module_map.get(key, "未展示")
        td_should_domestic = None
        if str(proposal.get("source", "") or "").startswith("环球旅讯"):
            td_should_domestic = _td_is_domestic(
                proposal.get("title", ""), proposal.get("summary", ""),
                proposal.get("source_channel", ""))
            if (current_module == "dom_industry" and not td_should_domestic) or \
                    (current_module == "intl_industry" and td_should_domestic):
                tags.append("国内外分类冲突")
                priority += 35
        if current_module == "intl_disclosures" and not (
                proposal.get("category") == "sec_filings" or
                any(k in str(proposal.get("source", "") or "") for k in IR_SOURCE_KEYWORDS)):
            tags.append("媒体误入披露")
            priority += 35
        if (original.get("current_decision") == "保留") != ok:
            tags.append("新旧规则冲突")
            priority += 40
        row = {
            "date": proposal.get("date", ""),
            "title": proposal.get("title", ""),
            "summary": proposal.get("summary", ""),
            "source": proposal.get("source", ""),
            "current_module": current_module,
            "current_decision": original.get("current_decision", ""),
            "proposed_decision": "保留" if ok else "排除",
            "current_score": current_score,
            "proposed_score": int(proposal.get("selection_score", 0) or 0),
            "matched_rules": "；".join(proposal.get("matched_rule_ids", []) or []),
            "selection_reasons": "；".join(proposal.get("selection_reasons", []) or []),
            "review_tags": "；".join(dict.fromkeys(tags)),
            "url": proposal.get("url", ""),
            "section": proposal.get("section", ""),
            "category": proposal.get("category", ""),
            "rejection_reason": reason or "",
            "priority": priority,
        }
        scored.append(row)

    scored.sort(key=lambda x: (x["priority"], x.get("date") or "", x.get("proposed_score", 0)),
                reverse=True)
    selected, source_counts = [], {}
    for row in scored:
        source = row.get("source") or "未知来源"
        if source_counts.get(source, 0) >= 5:
            continue
        selected.append(row)
        source_counts[source] = source_counts.get(source, 0) + 1
        if len(selected) >= max(1, int(size)):
            break
    return selected


def export_policy_diff(path, news_data=None, rejected_data=None):
    """用当前缓存重放新规则，输出新增、删除、换模块和折叠差异。"""
    news_data = news_data or _load_json_file(OUTPUT, {})
    rejected_data = rejected_data or _load_json_file(REJECTED_OUTPUT, {})
    current_modules = _review_module_map(news_data)
    pool, seen = [], set()
    for section in ("international", "domestic"):
        for category, items in (news_data.get(section) or {}).items():
            if not isinstance(items, list):
                continue
            for item in items:
                row = json.loads(json.dumps(item, ensure_ascii=False))
                row.update(section=section, category=category, current_decision="保留")
                pool.append(row)
    for item in rejected_data.get("items", []) if isinstance(rejected_data, dict) else []:
        if isinstance(item, dict):
            row = json.loads(json.dumps(item, ensure_ascii=False))
            row.setdefault("section", "international")
            row.setdefault("category", "industry_news")
            row["current_decision"] = "排除"
            pool.append(row)

    replay = {"international": {"sec_filings": [], "industry_news": []}, "domestic": {}}
    additions, removals, provisional_moves = [], [], []
    for original in pool:
        key = _manual_label_key(original)
        if not key or key in seen:
            continue
        seen.add(key)
        item = json.loads(json.dumps(original, ensure_ascii=False))
        item.pop("folded_into", None)
        section = item.get("section", "international")
        category = item.get("category", "industry_news")
        if str(item.get("source", "") or "").startswith("环球旅讯"):
            route_title = " ".join(x for x in (
                item.get("title", ""), item.get("title_original", "")) if x)
            is_domestic = _td_is_domestic(route_title, item.get("summary", ""),
                                          item.get("source_channel", ""))
            section, category = (("domestic", "china_industry") if is_domestic
                                 else ("international", "industry_news"))
        kept, reason = select_news_item(item, section, category)
        base = {"date": item.get("date", ""), "title": item.get("title", ""),
                "source": item.get("source", ""), "url": item.get("url", "")}
        if original.get("current_decision") == "排除" and kept:
            additions.append({**base, "new_module": _route_single_item(item, section, category)})
        if original.get("current_decision") == "保留" and not kept:
            removals.append({**base, "old_module": current_modules.get(key, "未展示"),
                             "reason": reason or item.get("rejection_reason", "")})
        if not kept:
            continue
        replay.setdefault(section, {}).setdefault(category, []).append(item)
        old_module = current_modules.get(key, "未展示")
        new_module = _route_single_item(item, section, category)
        if original.get("current_decision") == "保留" and old_module != new_module:
            provisional_moves.append({**base, "old_module": old_module, "new_module": new_module})

    route_to_modules(replay)
    proposed_modules = _review_module_map(replay)
    moves = []
    for row in provisional_moves:
        key = _manual_label_key(row)
        final_module = proposed_modules.get(key, row.get("new_module", "未展示"))
        if row.get("old_module") != final_module:
            moves.append({**row, "new_module": final_module})
    folds, folded_keys = [], set()
    for section in ("international", "domestic"):
        for items in (replay.get(section) or {}).values():
            if not isinstance(items, list):
                continue
            for item in items:
                if item.get("folded_into"):
                    folded_keys.add(_manual_label_key(item))
                    folds.append({"date": item.get("date", ""), "title": item.get("title", ""),
                                  "source": item.get("source", ""), "url": item.get("url", ""),
                                  "folded_into": item.get("folded_into", "")})
    moves = [row for row in moves if _manual_label_key(row) not in folded_keys]
    before_counts = {k: len(v) for k, v in (news_data.get("modules") or {}).items()
                     if isinstance(v, list)}
    after_counts = {k: len(v) for k, v in (replay.get("modules") or {}).items()
                    if isinstance(v, list)}
    report = {
        "generated_at": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "policy_version": POLICY_VERSION,
        "scope": "当前新闻缓存与拒绝诊断的离线重放；未联网抓取，不代表部署后最终数量",
        "summary": {"新增": len(additions), "删除": len(removals),
                    "换模块": len(moves), "折叠": len(folds)},
        "module_counts_before": before_counts,
        "module_counts_after_replay": after_counts,
        "新增": additions, "删除": removals, "换模块": moves, "折叠": folds,
    }
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2)
    print(f"Policy diff exported: {path} {report['summary']}")
    # The caller merges these official items into the international candidate
    # pool before screening/routing.  Returning ``0`` here silently discarded
    # every BKNG/EXPE/ABNB IR item and left core-company coverage dependent on
    # incidental media hits only.
    return all_items


def _find_artifact_runtime():
    node_modules_candidates = [
        os.environ.get("CODEX_WORKSPACE_NODE_MODULES", ""),
        os.path.expanduser("~/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules"),
    ]
    node_modules_candidates.extend(glob.glob(os.path.expanduser(
        "~/.cache/codex-runtimes/*/dependencies/node/node_modules")))
    node_modules = next((p for p in node_modules_candidates
                         if p and os.path.isdir(os.path.join(p, "@oai", "artifact-tool"))), None)
    if not node_modules:
        raise RuntimeError("未找到 Codex workspace artifact-tool 运行时；请在 Codex 桌面环境中执行标注命令")
    node_candidates = [
        os.environ.get("CODEX_WORKSPACE_NODE", ""),
        os.path.join(os.path.dirname(node_modules), "bin", "node"),
        shutil.which("node") or "",
    ]
    node = next((p for p in node_candidates if p and os.path.isfile(p) and os.access(p, os.X_OK)), None)
    if not node:
        raise RuntimeError("未找到可用 Node.js 运行时")
    return node, node_modules


def _run_review_workbook_helper(mode, input_path, output_path):
    node, node_modules = _find_artifact_runtime()
    if not os.path.exists(REVIEW_WORKBOOK_HELPER):
        raise RuntimeError(f"缺少工作簿助手: {REVIEW_WORKBOOK_HELPER}")
    with tempfile.TemporaryDirectory(prefix="ota_review_") as tmpdir:
        os.symlink(node_modules, os.path.join(tmpdir, "node_modules"), target_is_directory=True)
        helper = os.path.join(tmpdir, "news_review_workbook.mjs")
        shutil.copy2(REVIEW_WORKBOOK_HELPER, helper)
        proc = subprocess.run(
            [node, helper, mode, os.path.abspath(input_path), os.path.abspath(output_path)],
            cwd=tmpdir, text=True, capture_output=True)
        if proc.returncode != 0:
            raise RuntimeError((proc.stderr or proc.stdout or "工作簿处理失败").strip())
        return proc.stdout.strip()


def export_review_xlsx(path, size=30):
    rows = build_review_candidates(size=size)
    if len(rows) < int(size):
        raise RuntimeError(f"候选新闻不足：需要 {size} 条，实际 {len(rows)} 条")
    payload = {
        "generated_at": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "policy_version": POLICY_VERSION,
        "review_size": int(size),
        "rows": rows,
    }
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    with tempfile.NamedTemporaryFile("w", suffix=".json", encoding="utf-8", delete=False) as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)
        payload_path = f.name
    try:
        _run_review_workbook_helper("export", payload_path, path)
    finally:
        try:
            os.unlink(payload_path)
        except OSError:
            pass
    print(f"Review workbook exported: {path} ({len(rows)} rows, policy={POLICY_VERSION})")
    return 0


def _validate_and_merge_labels(rows, labels_path=None):
    labels_path = labels_path or MANUAL_LABELS_PATH
    allowed_labels = {"保留", "排除", "不确定", ""}
    allowed_reasons = {"Hotel非OTA相关", "软广", "评论观点", "低价值", "分类错误", "其他", ""}
    imported = {}
    for idx, row in enumerate(rows, 2):
        label = str(row.get("用户标注", "") or "").strip()
        reason = str(row.get("排除原因", "") or "").strip()
        notes = str(row.get("备注", "") or "").strip()
        if label not in allowed_labels:
            raise ValueError(f"第 {idx} 行用户标注无效: {label}")
        # 用户可能在“排除原因”列补充自然语言。明确写明“同一新闻只要一个”时，
        # 即使未点下拉，也按重复事件排除；其他自由文本保存在备注并映射到标准原因。
        if not label and reason and re.search(r"同一(?:新闻|事件)|重复", reason) \
                and re.search(r"只要一个|重复", reason):
            label = "排除"
        if reason and reason not in allowed_reasons:
            notes = "；".join(x for x in (notes, f"用户说明：{reason}") if x)
            if re.search(r"软广|优惠|促销", reason, re.I):
                reason = "软广"
            elif re.search(r"评论|观点", reason, re.I):
                reason = "评论观点"
            elif re.search(r"hotel|酒店", reason, re.I):
                reason = "Hotel非OTA相关"
            elif re.search(r"分类", reason):
                reason = "分类错误"
            elif re.search(r"低价值|单个机场|航司.*表现", reason):
                reason = "低价值"
            else:
                reason = "其他"
        if not label:
            continue
        if label != "排除" and reason:
            notes = "；".join(x for x in (notes, f"用户所填原因：{reason}") if x)
            reason = ""
        for field in ("标题", "来源", "URL"):
            if not str(row.get(field, "") or "").strip():
                raise ValueError(f"第 {idx} 行缺少关键字段: {field}")
        item = {"url": row.get("URL", ""), "title": row.get("标题", "")}
        key = _manual_label_key(item)
        if not key:
            raise ValueError(f"第 {idx} 行缺少 URL 和标题")
        if key in imported and imported[key]["label"] != label:
            raise ValueError(f"第 {idx} 行与前述记录标签冲突: {key}")
        imported[key] = {
            "key": key,
            "url": str(row.get("URL", "") or ""),
            "title": str(row.get("标题", "") or ""),
            "source": str(row.get("来源", "") or ""),
            "date": str(row.get("日期", "") or ""),
            "label": label,
            "reason": reason,
            "notes": notes,
            "policy_version": POLICY_VERSION,
            "updated_at": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        }
    existing_payload = _load_json_file(labels_path, {"version": 1, "labels": []})
    existing = {}
    for row in existing_payload.get("labels", []) if isinstance(existing_payload, dict) else []:
        if isinstance(row, dict):
            key = row.get("key") or _manual_label_key(row)
            if key:
                existing[key] = row
    existing.update(imported)
    payload = {
        "version": 1,
        "policy_version": POLICY_VERSION,
        "updated_at": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "labels": sorted(existing.values(), key=lambda x: (x.get("date", ""), x.get("title", "")), reverse=True),
    }
    return payload, len(imported)


def import_review_xlsx(path, labels_path=None):
    with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as f:
        rows_path = f.name
    try:
        _run_review_workbook_helper("import", path, rows_path)
        rows = _load_json_file(rows_path, [])
    finally:
        try:
            os.unlink(rows_path)
        except OSError:
            pass
    payload, count = _validate_and_merge_labels(rows, labels_path)
    target = labels_path or MANUAL_LABELS_PATH
    tmp = target + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)
    os.replace(tmp, target)
    global _MANUAL_LABEL_CACHE
    _MANUAL_LABEL_CACHE = None
    print(f"Imported {count} labeled rows into {target}")
    # Default project annotations should affect the live cache immediately.
    # Previously the labels were saved while modules remained stale until a
    # later successful network fetch.
    if labels_path is None and os.path.exists(OUTPUT):
        reprocess_cached_news()
    return 0


def reprocess_cached_news(retry_translation=False):
    """Apply current deterministic rules to cached + previously rejected items."""
    news_data = _load_json_file(OUTPUT, {})
    if not news_data:
        raise RuntimeError(f"新闻缓存不存在或已损坏: {OUTPUT}")

    # Re-introduce the rejection pool so a later manual KEEP can restore an item.
    rejected = _load_json_file(REJECTED_OUTPUT, {})
    existing = set()
    for section in ("international", "domestic"):
        for items in (news_data.get(section) or {}).values():
            if isinstance(items, list):
                for item in items:
                    item.pop("folded_into", None)
                    key = _manual_label_key(item)
                    if key:
                        existing.add(key)
    for item in rejected.get("items", []) if isinstance(rejected, dict) else []:
        if not isinstance(item, dict):
            continue
        key = _manual_label_key(item)
        if not key or key in existing:
            continue
        section = item.get("section") if item.get("section") in ("international", "domestic") else "international"
        category = item.get("category") or ("industry_news" if section == "international" else "china_industry")
        news_data.setdefault(section, {}).setdefault(category, []).append(dict(item))
        existing.add(key)

    news_data = prune_and_dedupe(news_data)
    news_data = refilter_cached_domestic(news_data)
    news_data = reclassify_cached_traveldaily(news_data)
    intl = news_data.get("international", {}).get("industry_news", [])
    news_data["international"]["industry_news"] = filter_travel_relevance(intl)
    if retry_translation:
        news_data["international"]["industry_news"] = retry_cached_translations(
            news_data["international"]["industry_news"])
    enrich_sec_filing_summaries(news_data.get("international", {}).get("sec_filings", []))
    news_data = run_selection_pipeline(news_data)
    news_data = prepare_chinese_news_display(news_data)
    save_translation_cache()
    news_data = backfill_summary_fields(news_data)
    news_data = route_to_modules(news_data)
    news_data["selection_report"]["quality"] = data_quality_check(news_data)
    news_data["policy_version"] = POLICY_VERSION
    news_data["policy_reprocessed_at"] = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    save_cache(news_data)
    print("  [Cache reprocess] " + " | ".join(
        f"{k}={len(v)}" for k, v in news_data.get("modules", {}).items()))
    return news_data


# ── 主函数 ──

def refresh_traveldaily_only(cached_data):
    """[--td-only] 只重抓环球旅讯并整体替换 china_industry（该分类唯一来源）。

    用于解析器/质量规则调优后的定向刷新：整源替换而不是与旧缓存合并，
    避免低质量旧条目靠 14 天保留期继续滞留。抓取条数过少(<5)时放弃，
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
            # Translation is deferred until after cache merge, retention,
            # selection and dedupe.  Screening rules are bilingual, so there is
            # no reason to translate hundreds of candidates that will be rejected.
            print(f"  Translation deferred until after final screening: {len(intl_news)} candidates")

        # 2d. 快速模式: 轻量处理
        if fast_mode and AI_MODULE_AVAILABLE:
            intl_news = process_news_fast(intl_news)
        elif fast_mode and not AI_MODULE_AVAILABLE:
            print(f"  Fast mode keeps full candidate pool for unified selection: {len(intl_news)} items")

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
    news_data = reclassify_cached_traveldaily(news_data)

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

    # SEC披露卡片读取官方原始文件：Form 4/Rule 144提取交易人、股数、价格等，
    # 其他表单按8-K条款或报告期生成有业务含义的确定性摘要。
    enrich_sec_filing_summaries(news_data.get("international", {}).get("sec_filings", []))

    # ── 保留期修剪 + 三级去重（改造项⑦）──
    news_data = prune_and_dedupe(news_data)

    # ── 公开详情页摘要补充（先于筛选, 让证据质量评分看到补充后的摘要）──
    news_data = enrich_public_summaries(news_data)

    # ── 统一筛选管道（§9, 2026-08-18）: 实体识别→硬排除→重点公司→基本面评分 ──
    # 新抓取 + 保留期内旧缓存合并后全量执行同一套规则; 被拒条目移出列表并写诊断JSON。
    news_data = run_selection_pipeline(news_data)

    # Translate only final retained international news.  This also retries
    # English cache fallbacks on later daily runs without spending calls on
    # rejected ads/opinions/noise.
    retained_intl = news_data.get("international", {}).get("industry_news", [])
    translate_news_items(retained_intl)
    news_data = prepare_chinese_news_display(news_data)
    save_translation_cache()

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
    def _cli_value(flag, default=None):
        try:
            return sys.argv[sys.argv.index(flag) + 1]
        except (ValueError, IndexError):
            return default

    try:
        if "--export-review-xlsx" in sys.argv:
            out_path = _cli_value("--export-review-xlsx")
            if not out_path:
                raise ValueError("--export-review-xlsx 需要输出路径")
            review_size = int(_cli_value("--review-size", "30"))
            sys.exit(export_review_xlsx(out_path, review_size))
        if "--import-review-xlsx" in sys.argv:
            in_path = _cli_value("--import-review-xlsx")
            if not in_path:
                raise ValueError("--import-review-xlsx 需要输入路径")
            sys.exit(import_review_xlsx(in_path))
        if "--export-policy-diff" in sys.argv:
            out_path = _cli_value("--export-policy-diff")
            if not out_path:
                raise ValueError("--export-policy-diff 需要输出路径")
            sys.exit(export_policy_diff(out_path))
        if "--reprocess-cache" in sys.argv:
            reprocess_cached_news(retry_translation="--retry-translation" in sys.argv)
            sys.exit(0)
        fast = "--fast" in sys.argv
        sys.exit(main(fast_mode=fast))
    except (ValueError, RuntimeError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        sys.exit(1)
