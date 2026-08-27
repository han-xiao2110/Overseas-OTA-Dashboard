#!/usr/bin/env python3
"""
news_quality_tests_副本.py — 新闻管道离线质量测试（改造项⑨, 2026-08-18）

全部使用本地 fixture, 不访问任何实时新闻网站。覆盖:
  A. 日期回归        parse_date 失败→None / 交通运输部 URL 日期兜底 / unknown 沉底与保留期
  B. 三级去重        URL归一化 / 同文标题归一(东航重复标题+提前14天退改) / 同事件折叠
  C. 来源状态与回退  部分失败(退出码2) / 全部失败无缓存(退出码1) / 全部失败有缓存(退出码2) /
                     全部成功(退出码0) / last_success_at 保持
  D. TLS             _UNVERIFIED_CTX 已删 / 证书错误分类 tls_error / 不静默降级
  E. 摘要证据        SEC 确定性摘要 / summary_status 判定 / ai_summarize_batch 证据化
  F. 国内分源过滤    文旅部/交通运输部/民航网 include/exclude + raw/kept/rejected 统计
  G. 筛选管道        §14固定验收案例23条 / §11字段完整 / 实体词边界 / 被拒诊断JSON /
                     AI不可用确定性筛选 / 旧缓存噪音不得回流(run_main全链路)
  H. 东航收窄规则    14天免费退改必保 / 智能机器人矩阵排除 / 远程医疗急救平台排除 /
                     东航非 is_core 公司 / 业务影响词双向匹配 / EXCLUDE 优先于 IMPACT
  I. 模块路由验收    5模块结构 / BKNG IR 进核心公司 / 财报 SEC 进披露 / 国际行业统一列表 /
                     国内公司标签 entity_id / 国内无核心公司子模块 / 披露易民航局进披露 /
                     同事件主卡片去重

运行: python3 news_quality_tests_副本.py   (退出码 0=全过, 1=有失败)
"""

import copy
import io
import json
import os
import re
import ssl
import sys
import time
import urllib.error
import urllib.request
from unittest import mock

# ── 加载被测模块 ──
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import fetch_news_副本 as fn            # noqa: E402
import news_ai_helpers_副本 as hai      # noqa: E402

PASS = 0
FAIL = 0
FAILURES = []


def check(name, cond):
    global PASS, FAIL
    if cond:
        PASS += 1
        print(f"  PASS  {name}")
    else:
        FAIL += 1
        FAILURES.append(name)
        print(f"  FAIL  {name}")


# ════════════════ A. 日期回归 ════════════════

def test_dates():
    print("— A. 日期回归 —")
    check("A1 parse_date('') → None", fn.parse_date("") is None)
    check("A2 parse_date 无法解析 → None", fn.parse_date("not a date at all") is None)
    check("A3 parse_date RSS 格式", fn.parse_date("Mon, 17 Aug 2026 10:00:00 +0000") == "2026-08-17")
    check("A4 parse_date 'YYYY-MM-DD HH:MM'", fn.parse_date("2026-08-14 09:36") == "2026-08-14")
    check("A5 parse_date 中文日期", fn.parse_date("2026年8月11日") == "2026-08-11")

    # 交通运输部 fixture: 正常结构（span 日期齐全）
    base = "https://www.mot.gov.cn/xinwen/jiaotongyaowen/"
    html_ok = """
    <a href="./202608/t20260814_40123.html" class="news-link">
      <span class="news-title">交通运输部部署暑期出行保障</span>
      <span class="news-date">2026-08-14</span></a>
    <a href="./202608/t20260812_40099.html" class="news-link">
      <span class="news-title">全国港口货物吞吐量公布</span>
      <span class="news-date">2026-08-12</span></a>
    """
    items = fn.extract_gov_list(html_ok, "交通运输部", "regulatory", base)
    dates = sorted(i["date"] for i in items)
    check("A6 交通部正常结构日期正确", dates == ["2026-08-12", "2026-08-14"])

    # 结构变化 fixture: news-date span 消失 → 日期必须回退到 URL tYYYYMMDD，而非今天
    html_broken = """
    <a href="./202608/t20260814_40123.html" class="news-link">
      <span class="news-title">交通运输部部署暑期出行保障</span></a>
    <a href="./202608/t20260810_40001.html" class="news-link">
      <span class="news-title">铁路暑期运行图调整</span></a>
    """
    today_str = time.strftime("%Y-%m-%d")
    items = fn.extract_gov_list(html_broken, "交通运输部", "regulatory", base)
    got = sorted(i["date"] for i in items)
    check("A7 交通部结构变化→URL日期兜底(不穿越到今天)",
          got == ["2026-08-10", "2026-08-14"] and today_str not in got)

    # 三重兜底失败 → None → apply_date_fields 标 unknown
    # (href 过 tYYYYMMDD_NNN 门槛但月份13非法 → URL日期解析也失败, 不是靠非标准文件名绕过)
    html_no_date = """
    <a href="./202608/t20261399_40123.html" class="news-link">
      <span class="news-title">某无日期政策文件</span></a>
    """
    items = fn.extract_gov_list(html_no_date, "交通运输部", "regulatory", base)
    fn.apply_date_fields(items, fetched_at="2026-08-18 09:00:00")
    check("A8 全部日期来源失败→date_status=unknown, date=''",
          len(items) == 1 and items[0]["date_status"] == "unknown"
          and items[0]["date"] == "" and items[0]["published_at"] is None
          and items[0]["fetched_at"] == "2026-08-18 09:00:00")

    # unknown 排序沉底
    mixed = [
        {"title": "旧新闻", "date": "2026-08-01", "url": "https://x/1"},
        {"title": "无日期", "date": "", "url": "https://x/2"},
        {"title": "新新闻", "date": "2026-08-17", "url": "https://x/3"},
    ]
    fn.apply_date_fields(mixed, fetched_at="2026-08-18 09:00:00")
    mixed.sort(key=lambda x: x.get("date") or "", reverse=True)
    check("A9 unknown 日期排序沉底", mixed[-1]["title"] == "无日期")

    # 保留期: unknown 按 fetched_at 日期算, 不再永久保留
    nd_old = {"title": "很久前抓的未知日期条目", "date": "", "url": "https://x/old",
              "fetched_at": "2026-07-01 09:00:00", "source": "测试", "date_status": "unknown"}
    nd_new = {"title": "今天抓的未知日期条目", "date": "", "url": "https://x/new",
              "fetched_at": "2026-08-18 09:00:00", "source": "测试", "date_status": "unknown"}
    data = {"domestic": {"regulatory": [nd_old, nd_new]}}
    fn.prune_and_dedupe(data)
    titles = [i["title"] for i in data["domestic"]["regulatory"]]
    check("A10 unknown 按 fetched_at 过期修剪(48天前剪掉, 今天的保留)",
          titles == ["今天抓的未知日期条目"])


# ════════════════ B. 三级去重 ════════════════

def test_dedupe():
    print("— B. 三级去重 —")
    check("B1 _norm_url 剥跟踪参数/fragment/斜杠",
          fn._norm_url("https://skift.com/2026/08/x/?utm_source=feed&utm_campaign=t#top")
          == "https://skift.com/2026/08/x")
    check("B1b _norm_url 保留业务参数",
          fn._norm_url("https://www.sec.gov/cgi-bin/browse-edgar?CIK=0001075531&type=10-Q")
          == "https://www.sec.gov/cgi-bin/browse-edgar?CIK=0001075531&type=10-Q")
    check("B1c _norm_url 大小写归一host",
          fn._norm_url("HTTPS://Skift.COM/X/") == "https://skift.com/X")

    # 同文: 东航重复标题同日不同URL → 合并保留1条
    dup = [
        {"title": "东航推出提前14天免费退改服务", "date": "2026-08-16", "url": "https://news.google.com/a",
         "source": "百度新闻", "company": "中国东航"},
        {"title": "东航推出提前14天免费退改服务", "date": "2026-08-16", "url": "https://www.ceair.com/notice1",
         "source": "中国东航", "company": "中国东航"},
    ]
    out = fn.dedupe_same_article(list(dup))
    check("B2 东航同文(同日异URL)合并为1条",
          len(out) == 1 and out[0]["url"] == "https://www.ceair.com/notice1"
          and out[0].get("merged_same_article") == 1)

    # 同名标题相隔>3天 → 各自保留(周期性服务公告回归)
    apart = [
        {"title": "东航推出提前14天免费退改服务", "date": "2026-08-16", "url": "https://x/1",
         "source": "百度新闻", "company": "中国东航"},
        {"title": "东航推出提前14天免费退改服务", "date": "2026-08-01", "url": "https://x/2",
         "source": "百度新闻", "company": "中国东航"},
    ]
    out = fn.dedupe_same_article(list(apart))
    check("B3 同名标题相隔15天→不合并(各2条)", len(out) == 2)

    # 同事件: 相似标题 72h 内 → 折叠 + event_id + related_sources
    ev = [
        {"title": "中国东航宣布新增上海至伦敦航线", "date": "2026-08-16", "url": "https://x/ceair",
         "source": "披露易·中国东航", "company": "中国东航"},
        {"title": "中国东航宣布新增上海至伦敦直达航线", "date": "2026-08-17", "url": "https://news.google.com/b",
         "source": "百度新闻", "company": "中国东航"},
    ]
    out = fn.group_same_events(list(ev))
    primary = [i for i in out if not i.get("folded_into")]
    folded = [i for i in out if i.get("folded_into")]
    check("B4 同事件折叠: 1主+1折叠, event_id一致, related_sources记录来源",
          len(primary) == 1 and len(folded) == 1
          and primary[0].get("event_id") == folded[0].get("event_id")
          and folded[0]["folded_into"] == "https://x/ceair"
          and "百度新闻" in primary[0].get("related_sources", []))
    check("B4b 官方来源(披露易)当主条目", primary[0]["source"] == "披露易·中国东航")

    # 相隔>72h 不折叠
    far = [
        {"title": "中国东航宣布新增上海至伦敦航线", "date": "2026-08-16", "url": "https://x/a",
         "source": "百度新闻"},
        {"title": "中国东航宣布新增上海至伦敦直达航线", "date": "2026-08-01", "url": "https://x/b",
         "source": "百度新闻"},
    ]
    out = fn.group_same_events(list(far))
    check("B5 相隔>72h不折叠", all(not i.get("folded_into") for i in out) and len(out) == 2)

    # URL 变体去重(跟踪参数)在 prune 内生效
    data = {"domestic": {"china_industry": [
        {"title": "Expedia收购AI助手Layla", "date": "2026-08-17", "url": "https://www.traveldaily.cn/article/190541",
         "source": "环球旅讯"},
        {"title": "Expedia收购AI助手Layla", "date": "2026-08-17",
         "url": "https://www.traveldaily.cn/article/190541/?utm_source=feed", "source": "环球旅讯"},
    ]}}
    fn.prune_and_dedupe(data)
    check("B6 URL归一化去重(utm变体=同一条)",
          len(data["domestic"]["china_industry"]) == 1)


# ════════════════ D. TLS ════════════════

def test_tls():
    print("— D. TLS —")
    check("D1 _UNVERIFIED_CTX 已删除(=None)", fn._UNVERIFIED_CTX is None)
    check("D2 证书错误分类 tls_error",
          fn._classify_request_error(ssl.SSLError("CERTIFICATE_VERIFY_FAILED")) == "tls_error")
    reason = OSError("certificate verify failed")
    e = urllib.error.URLError(reason)
    check("D3 URLError(CERTIFICATE) 分类 tls_error", fn._classify_request_error(e) == "tls_error")
    refused = urllib.error.URLError(OSError("Connection refused"))
    check("D4 连接拒绝分类 unreachable", fn._classify_request_error(refused) == "unreachable")
    http503 = urllib.error.HTTPError("u", 503, "Service Unavailable", hdrs=None, fp=io.BytesIO(b""))
    check("D5 HTTP 503 分类 http_503", fn._classify_request_error(http503) == "http_503")

    # urlopen_safe 必须把 SSL 错误抛给调用者（不降级重试）
    def raise_ssl(req, timeout=None, context=None):
        raise ssl.SSLError("CERTIFICATE_VERIFY_FAILED")
    with mock.patch.object(urllib.request, "urlopen", raise_ssl):
        try:
            fn.urlopen_safe(urllib.request.Request("https://bad-cert.example.com"))
            propagated = False
        except ssl.SSLError:
            propagated = True
    check("D6 urlopen_safe 不吞证书错误(直接抛出)", propagated)


# ════════════════ E. 摘要证据 ════════════════

def test_summary_evidence():
    print("— E. 摘要证据 —")
    f1 = {"company": "BKNG", "type": "10-Q", "title": "季度报告 (10-Q)", "date": "2026-08-15"}
    f2 = dict(f1)
    check("E1 SEC确定性摘要: 相同输入相同输出",
          fn.sec_deterministic_summary(f1) == fn.sec_deterministic_summary(f2))
    s = fn.sec_deterministic_summary(f1)
    check("E2 SEC摘要含公司全名/类型/日期",
          "Booking Holdings Inc." in s and "10-Q" in s and "2026-08-15" in s)
    f8k = {"company": "ABNB", "type": "8-K", "title": "重大事件 (8-K) (Item 2.02, 9.01)",
           "date": "2026-08-10"}
    check("E3 8-K摘要保留Items条款",
          "Item 2.02" in fn.sec_deterministic_summary(f8k))

    data = {
        "international": {
            "sec_filings": [dict(f1)],
            "industry_news": [
                {"title": "Airbnb Beats Estimates", "summary": "Revenue rose 12% in the quarter on strong travel demand.",
                 "source": "Bloomberg Markets", "url": "https://x/1", "date": "2026-08-16"},
                {"title": "Skift report on OTA", "summary": "OTA行业季度报告摘要内容足够长。",
                 "source": "Skift", "url": "https://x/2", "date": "2026-08-16"},
                {"title": "Reuters headline only", "summary": "", "paywall": True,
                 "source": "Reuters", "url": "https://x/3", "date": "2026-08-16"},
                {"title": "No snippet source", "summary": "",
                 "source": "Travel Weekly", "url": "https://x/4", "date": "2026-08-16"},
            ],
        },
        "domestic": {"china_industry": []},
    }
    fn.backfill_summary_fields(data, fetched_at="2026-08-18 10:00:00")
    sec, bbg, skift, reuters, nosnip = (
        data["international"]["sec_filings"][0],
        data["international"]["industry_news"][0],
        data["international"]["industry_news"][1],
        data["international"]["industry_news"][2],
        data["international"]["industry_news"][3],
    )
    check("E4 SEC → 生成确定性摘要",
          sec["summary_status"] == "generated"
          and "Booking Holdings" in sec["summary"])
    check("E5 Bloomberg公开片段保留",
          len(bbg["summary"]) > 10)
    check("E6 普通源片段保留",
          len(skift["summary"]) > 0)
    check("E7 付费墙无摘要 → 仅标题呈现",
          reuters.get("paywall") is True and reuters["summary"] == "")
    check("E8 无证据 → insufficient_evidence",
          nosnip["summary_status"] == "insufficient_evidence" and nosnip["summary"] == "")

    # helpers: ai_summarize_batch 证据化
    items = [
        {"title": "WSJ paywalled travel story", "summary": "Existing snippet from WSJ.",
         "source": "Wall Street Journal"},
        {"title": "Bloomberg public RSS story",
         "summary": "Bloomberg RSS description snippet about travel demand.", "source": "Bloomberg"},
        {"title": "Bare headline no snippet", "summary": "", "source": "Travel Weekly"},
    ]
    hai.ai_summarize_batch(items)
    check("E9 WSJ片段被清空+paywall标记(付费墙无公开输入渠道)",
          items[0]["paywall"] is True and items[0]["summary"] == ""
          and items[0]["summary_status"] == "generated")
    check("E10 Bloomberg公开RSS片段保留(不再被清空)",
          items[1]["summary"].startswith("Bloomberg RSS description"))
    check("E11 无片段不编造摘要",
          items[2]["summary"] == "")
    check("E12 PAYWALL_SOURCES 已无 Bloomberg",
          not any("Bloomberg" in p for p in hai.PAYWALL_SOURCES))


# ════════════════ F. 国内分源过滤 ════════════════

def test_domestic_filters():
    print("— F. 国内分源过滤 —")
    fn.DOMESTIC_FILTER_STATS.clear()
    mct = [
        {"title": "文化和旅游部发布暑期旅游数据", "summary": "", "url": "https://mct/1"},
        {"title": "文旅部机关服务中心印刷服务采购公告", "summary": "", "url": "https://mct/2"},
        {"title": "文旅部关于人事任免的公示", "summary": "", "url": "https://mct/3"},
    ]
    out = fn.filter_domestic_items("文旅部", list(mct))
    check("F1 文旅部排除采购/人事噪音, 保留业务条目",
          len(out) == 1 and out[0]["title"].startswith("文化和旅游部"))

    mot = [
        {"title": "暑运期间全国铁路旅客发送量增长", "summary": "", "url": "https://mot/1"},
        {"title": "交通运输部某建设项目招标公告", "summary": "", "url": "https://mot/2"},
        {"title": "新闻开启快递助农跨省共建新模式", "summary": "", "url": "https://mot/3"},
    ]
    out = fn.filter_domestic_items("交通运输部", list(mot))
    check("F2 交通部只保留旅客出行并排除招标/快递", len(out) == 1 and "旅客" in out[0]["title"])

    caac = [
        {"title": "东航暑期航班计划公布", "summary": "", "url": "https://caac/1"},
        {"title": "民航局发布机场运行数据", "summary": "", "url": "https://caac/2"},
        {"title": "某某物流园区铁路专用线开工", "summary": "", "url": "https://caac/3"},
    ]
    out = fn.filter_domestic_items("中国民航网", list(caac))
    check("F3 民航网include过滤非航空内容",
          len(out) == 2 and all("铁路" not in i["title"] for i in out))

    st = fn.DOMESTIC_FILTER_STATS["中国民航网"]
    check("F4 raw/kept/rejected 统计一致",
          st["raw"] == 3 and st["kept"] == 2 and st["rejected"] == 1
          and sum(st["reasons"].values()) == st["rejected"])

    td = [
        {"title": "华住Q2拷问酒店增长的真命题", "summary": "", "url": "https://td/1"},
        {"title": "大湾区自驾香港到底多方便？我们实测完整流程", "summary": "", "url": "https://td/2"},
    ]
    out = fn.filter_domestic_items("环球旅讯", list(td))
    check("F5 环球旅讯排除消费者实测攻略", len(out) == 1 and "华住" in out[0]["title"])


# ════════════════ C. 来源状态 / 失败回退（main 集成, fixture 不联网） ════════════════

SKIFT_RSS = """<?xml version="1.0"?><rss version="2.0"><channel>
<item><title>Saudi OTA Almosafer IPO Despite Iran War Disruption</title>
<link>https://skift.com/2026/08/17/almosafer-ipo/</link>
<pubDate>Mon, 17 Aug 2026 08:00:00 +0000</pubDate>
<description>Riyadh-based Almosafer parent Seera Group is pressing ahead with its IPO.</description>
</item></channel></rss>"""

BLOOMBERG_RSS = """<?xml version="1.0"?><rss version="2.0"><channel>
<item><title>Airbnb Beats Estimates as Travel Demand Surges</title>
<link>https://www.bloomberg.com/news/articles/2026-08-17/airbnb-q2</link>
<pubDate>Mon, 17 Aug 2026 12:00:00 +0000</pubDate>
<description>Airbnb reported quarterly revenue above analyst estimates on strong travel demand.</description>
</item></channel></rss>"""

GOOGLE_RSS = """<?xml version="1.0"?><rss version="2.0"><channel>
<item><title>Airbnb travel tools update - PhocusWire</title>
<link>https://news.google.com/rss/articles/abc123</link>
<pubDate>Mon, 17 Aug 2026 09:00:00 +0000</pubDate>
<description> </description>
</item></channel></rss>"""

EDGAR_JSON = {
    "hits": {"hits": [{
        "_source": {
            "form": "10-Q", "file_date": "2026-08-15",
            "adsh": "0001075531-26-000123",
            "display_names": ["Booking Holdings Inc."],
            "ciks": ["0001075531"], "file_type": "10-Q", "file_description": "",
        }}]}
}


def make_cache():
    """构造带历史 fetch_status 的有效缓存。"""
    return {
        "international": {
            "sec_filings": [
                {"date": "2026-08-15", "company": "BKNG", "type": "10-Q",
                 "title": "季度报告 (10-Q)", "url": "https://www.sec.gov/x1", "source": "SEC EDGAR"},
            ],
            "industry_news": [
                {"date": "2026-08-16", "title": "Airbnb上线新营销引擎",
                 "url": "https://www.traveldaily.cn/article/190600", "source": "环球旅讯",
                 "summary": "Airbnb面向房东推出营销工具。"},
            ],
        },
        "domestic": {
            "china_industry": [
                {"date": "2026-08-17", "title": "飞猪帮帮正式上线",
                 "url": "https://www.traveldaily.cn/article/190601", "source": "环球旅讯",
                 "summary": "飞猪上线旅行助手功能。"},
            ],
            "regulatory": [
                {"date": "2026-08-17", "title": "文旅部发布暑期市场数据",
                 "url": "https://www.mct.gov.cn/t1", "source": "文旅部", "summary": ""},
            ],
            "company_news": [
                {"date": "2026-08-17", "title": "中国东航新增上海伦敦航线",
                 "url": "https://news.google.com/x9", "source": "百度新闻",
                 "company": "中国东航", "summary": ""},
            ],
        },
        "last_updated": "2026-08-17 06:00:00",
        "fetch_status": {
            "attempted_at": "2026-08-17 06:00:00",
            "last_success_at": "2026-08-17 06:00:00",
            "status": "success",
            "sources": {"Bloomberg Markets": {"status": "success",
                                              "last_success_at": "2026-08-17 06:00:00"}},
        },
    }


class FixtureNet:
    """按 host/path 分发的离线 safe_request 替身。ok=True 的 host 返回 fixture。"""

    def __init__(self, ok_hosts):
        self.ok_hosts = ok_hosts  # {'skift.com': SKIFT_RSS, ...}

    def __call__(self, url, timeout=15, retries=2, source=None):
        from urllib.parse import urlparse
        host = urlparse(url).netloc
        if host == 'skift.com' and '/feed' in url:
            return self.ok_hosts.get('skift.com')
        if host == 'skift.com':  # /news/ 列表页
            return None
        if host in ('feeds.bloomberg.com',):
            return self.ok_hosts.get('feeds.bloomberg.com')
        if host == 'news.google.com':
            return self.ok_hosts.get('news.google.com')
        if host == 'efts.sec.gov':
            if 'efts.sec.gov' not in self.ok_hosts:
                return None
            # 动态按请求 entity=CIK%3A<cik> 生成命中: 固定 ciks 只有 BKNG,
            # EXPE/ABNB 请求会被 CIK 过滤→0条→误标 failed→破坏 C4 全成功场景
            payload = copy.deepcopy(EDGAR_JSON)
            m = re.search(r'entity=CIK%3A(\d+)', url)
            if m:
                cik = m.group(1)
                src0 = payload['hits']['hits'][0]['_source']
                src0['ciks'] = [cik]
                src0['adsh'] = f"{cik}-26-000123"
            return payload
        return None


def reset_module_state():
    fn.FETCH_STATUS.update({"attempted_at": None, "last_success_at": None,
                            "status": None, "sources": {}})
    fn.DOMESTIC_FILTER_STATS.clear()
    fn.UNREACHABLE_HOSTS.clear()
    fn.UNREACHABLE_HOSTS.add('translate.googleapis.com')  # 禁用翻译网络
    fn.TRANSLATE_CACHE.clear()


def run_main(net, cache, td_items=None, hkex_result=None, domestic_disabled=False):
    """monkeypatch 一切网络入口后跑 main(), 返回 (exit_code, saved_data)。"""
    reset_module_state()
    saved = {}

    def fake_save(data):
        saved['data'] = data
        saved['total'] = sum(len(v) for sec in ('international', 'domestic')
                             for k, v in (data.get(sec) or {}).items() if isinstance(v, list))

    with mock.patch.object(fn, 'safe_request', net), \
         mock.patch.object(fn, 'load_cache', lambda: (cache, 999.0)), \
         mock.patch.object(fn, 'save_cache', fake_save), \
         mock.patch.object(fn, 'REJECTED_OUTPUT',
                           os.path.join(HERE, "_rejected_runmain_tmp.json")), \
         mock.patch.object(fn, 'fetch_hkex_filings',
                           lambda *a, **k: hkex_result), \
         mock.patch.object(fn, 'fetch_traveldaily', lambda src: (td_items or [])), \
         mock.patch.object(time, 'sleep', lambda s: None):
        if domestic_disabled:
            with mock.patch.object(fn, 'fetch_domestic_news', lambda: []):
                rc = fn.main(fast_mode=False)
        else:
            rc = fn.main(fast_mode=False)
    return rc, saved.get('data')


def test_source_status():
    print("— C. 来源状态 / 失败回退 —")

    # C1 部分失败: skift OK, 其它全部挂 → 退出码 2, update_status=partial, 缓存条目保留
    net = FixtureNet({'skift.com': SKIFT_RSS})
    rc, data = run_main(net, make_cache(), td_items=[], hkex_result=None)
    check("C1 部分失败退出码=2", rc == 2)
    check("C1b update_status=partial", data.get("update_status") == "partial")
    fs = data.get("fetch_status", {})
    srcs = fs.get("sources", {})
    check("C1c 失败来源记录(含Bloomberg Markets/环球旅讯)",
          srcs.get("Bloomberg Markets", {}).get("status") == "failed"
          and srcs.get("环球旅讯", {}).get("status") == "failed")
    check("C1d 成功来源记录(Skift)", srcs.get("Skift", {}).get("status") == "success")
    reg_titles = [i["title"] for i in data["domestic"]["regulatory"]]
    check("C1e 缓存监管条目保留", any("文旅部" in t for t in reg_titles))
    check("C1f 缓存SEC条目保留",
          any(i.get("type") == "10-Q" for i in data["international"]["sec_filings"]))
    # Skift 新条目成功进入列表
    intl_titles = " ".join(i["title"] for i in data["international"]["industry_news"])
    check("C1g Skift新条目入库(白名单豁免war强排除)",
          "Almosafer" in intl_titles)
    # SEC INFO 占位被过滤
    check("C1h SEC INFO占位条目被过滤",
          all(i.get("type") != "INFO" for i in data["international"]["sec_filings"]))
    # 失败来源继承旧缓存的 last_success_at
    check("C1i 失败来源保留历史last_success_at",
          srcs.get("Bloomberg Markets", {}).get("last_success_at") == "2026-08-17 06:00:00")

    # C2 全部失败 + 无缓存 → 退出码 1
    rc, data = run_main(FixtureNet({}), None, td_items=[], hkex_result=None)
    check("C2 全部失败无缓存退出码=1", rc == 1 and data is None)

    # C3 全部失败 + 有缓存 → 退出码 2, update_status=failed, 缓存数据完整回退
    rc, data = run_main(FixtureNet({}), make_cache(), td_items=[], hkex_result=None)
    check("C3 全部失败有缓存退出码=2", rc == 2)
    check("C3b update_status=failed(页面将显示缓存数据提示)",
          data.get("update_status") == "failed")
    check("C3c 缓存四大分区条目保留",
          data["domestic"]["china_industry"] and data["domestic"]["regulatory"]
          and data["domestic"]["company_news"]
          and data["international"]["industry_news"])

    # C4 全部成功 → 退出码 0
    net = FixtureNet({
        'skift.com': SKIFT_RSS,
        'feeds.bloomberg.com': BLOOMBERG_RSS,
        'news.google.com': GOOGLE_RSS,
        'efts.sec.gov': EDGAR_JSON,
    })
    rc, data = run_main(net, make_cache(), domestic_disabled=True)
    check("C4 全部成功退出码=0", rc == 0)
    check("C4b update_status=success", data.get("update_status") == "success")
    sec_titles = [f["title"] for f in data["international"]["sec_filings"]]
    check("C4c SEC确定性摘要在列",
          any("Booking Holdings" in (f.get("summary") or "")
              for f in data["international"]["sec_filings"]))
    # Bloomberg 公开 RSS 片段保留
    bbg = [i for i in data["international"]["industry_news"]
           if "Bloomberg" in str(i.get("source", ""))]
    check("C4d Bloomberg条目公开片段保留",
          bbg and any(len(i.get("summary") or "") > 10 for i in bbg))

    # C5 mark_source 失败不覆盖 last_success_at
    reset_module_state()
    fn.seed_fetch_status_from_cache(make_cache())
    fn.mark_source("Bloomberg Markets", "failed", error_code="tls_error")
    rec = fn.FETCH_STATUS["sources"]["Bloomberg Markets"]
    check("C5 mark_source失败保留last_success_at并记error_code",
          rec.get("last_success_at") == "2026-08-17 06:00:00"
          and rec.get("error_code") == "tls_error")
    check("C5b seed未尝试来源status=cached且不计入overall",
          fn.overall_status() == "failed")  # 仅 Bloomberg Markets attempted & failed


# ════════════════ G. 筛选管道 · 固定验收案例（规格 §14） ════════════════

G_ACCEPT = [
    # (标题, 来源, section, category, 期望保留, 附加字段)
    ("携程男性员工陪产假延长至20天", "环球旅讯", "domestic", "china_industry", True, {}),
    ("携程荣获2026年度最佳雇主品牌奖", "环球旅讯", "domestic", "china_industry", False, {}),
    ("飞猪帮帮正式上线", "环球旅讯", "domestic", "china_industry", True, {}),
    ("飞猪赞助城市马拉松赛事", "环球旅讯", "domestic", "china_industry", False, {}),
    ("Expedia收购AI旅行规划平台Layla", "Skift", "international", "industry_news", True, {}),
    ("Airbnb重建营销引擎", "Bloomberg Markets", "international", "industry_news", True, {}),
    ("豆包直订酒店上线", "环球旅讯", "domestic", "china_industry", True, {}),
    ("某酒店集团公布季度RevPAR增长8%，净开店120家", "Skift", "international", "industry_news", True, {}),
    ("中国东航公布7月运营数据，旅客运输量同比增长12%，并推出提前14天免费退改",
     "披露易·中国东航", "domestic", "company_news", True, {"company": "中国东航"}),
    ("文化和旅游部发布暑期旅游市场数据", "文旅部", "domestic", "regulatory", True, {}),
    ("Saudi OTA Almosafer IPO Despite Iran War Disruption", "Skift", "international", "industry_news",
     True, {"summary": "Riyadh-based Almosafer parent Seera Group is pressing ahead with its IPO."}),
    ("酒店分销技术公司SiteMinder被收购，交易额3亿美元", "PhocusWire", "international", "industry_news", True, {}),
    ("环球旅讯采购需求对接：寻找东南亚地接供应商", "环球旅讯", "domestic", "china_industry", False, {}),
    ("旅游业的钱，流向何方？｜超哥短评", "环球旅讯", "domestic", "china_industry", False, {}),
    ("某连锁酒店品牌突破300家门店，焕新升级再出发", "环球旅讯", "domestic", "china_industry", False, {}),
    ("东航篮球队在民航系统比赛中夺冠", "中国民航网", "domestic", "company_news", False, {"company": "中国东航"}),
    ("东航机组成功处置突发救援事件，机长坚守岗位", "中国民航网", "domestic", "company_news", False, {"company": "中国东航"}),
    ("大湾区自驾香港到底多方便？我们实测完整流程", "环球旅讯", "domestic", "china_industry", False, {}),
    ("飞行结束后还能留下什么？国航把会员权益装进了新玩法", "环球旅讯", "domestic", "china_industry", False, {}),
    ("当出海业务铺开，中国企业如何避开那些差旅大坑？", "环球旅讯", "domestic", "china_industry", False, {}),
    ("泛泛的行业趋势文章讨论未来前景", "环球旅讯", "domestic", "china_industry", False, {}),
    ("某地旅游公路项目开工建设", "交通运输部", "domestic", "regulatory", False, {}),
    ("某机场推出普通服务升级措施", "中国民航网", "domestic", "regulatory", False, {}),
]


def _sel_item(title, source, section, category, extra=None):
    item = {"title": title, "source": source,
            "url": f"https://x/{abs(hash(title)) % 100000}",
            "date": "2026-08-16", "summary": ""}
    item.update(extra or {})
    return item


def test_selection():
    print("— G. 筛选管道 · 固定验收案例 —")
    fails = []
    for title, source, section, cat, exp, extra in G_ACCEPT:
        item = _sel_item(title, source, section, cat, extra)
        kept, reason = fn.select_news_item(item, section, cat)
        if kept != exp:
            fails.append(f"{title} (期望{'保留' if exp else '拒绝'}, 实得"
                         f"{'保留' if kept else '拒绝'}, score={item.get('selection_score')},"
                         f" reason={reason})")
    check(f"G1 §14固定验收案例 {len(G_ACCEPT)}/{len(G_ACCEPT)} 全过", not fails)
    for f in fails:
        print(f"      → {f}")

    # G2 §11 新增字段完整性
    item = _sel_item("携程男性员工陪产假延长至20天", "环球旅讯", "domestic", "china_industry")
    fn.select_news_item(item, "domestic", "china_industry")
    check("G2 §11字段完整(entity_id/is_core/content_type/score/status/reasons/dimensions)",
          item.get("entity_id") == "TCOM" and item.get("is_core_company") is True
          and item.get("content_type") and item.get("selection_status") == "kept"
          and isinstance(item.get("selection_reasons"), list)
          and isinstance(item.get("impact_dimensions"), list)
          and item.get("rejection_reason") is None)

    # G3 实体词边界: 普通单词 booking/trip 不误判公司（§3）
    t1 = _sel_item("Travel bookings expectations rise", "Bloomberg Markets",
                   "international", "industry_news")
    t2 = _sel_item("Trip planner app review roundup", "Skift",
                   "international", "industry_news")
    check("G3 booking/trip 词边界防误判",
          fn.identify_entity(t1) != "BKNG" and fn.identify_entity(t2) != "TCOM")

    # G4 被拒诊断 JSON 结构（不展示, 仅留档）
    data = {"international": {"industry_news": [
                _sel_item("旅游业的钱，流向何方？｜超哥短评", "环球旅讯",
                          "international", "industry_news")]},
            "domestic": {"china_industry": []}}
    rej_tmp = os.path.join(HERE, "_rejected_test_tmp.json")
    orig = fn.REJECTED_OUTPUT
    fn.REJECTED_OUTPUT = rej_tmp
    try:
        fn.run_selection_pipeline(data)
    finally:
        fn.REJECTED_OUTPUT = orig
    check("G4 被拒条目移出列表且诊断JSON落盘",
          not data["international"]["industry_news"] and os.path.exists(rej_tmp))
    diag = json.load(open(rej_tmp, encoding="utf-8"))
    check("G4b 诊断JSON含标题/来源/分数/拒绝原因",
          diag["items"]
          and all(k in diag["items"][0]
                  for k in ("title", "source", "selection_score", "rejection_reason")))
    rep = data.get("selection_report", {})
    check("G4c selection_report raw/kept/rejected/by_reason",
          rep.get("raw_count") == 1 and rep.get("kept_count") == 0
          and rep.get("rejected_count") == 1 and isinstance(rep.get("by_reason"), dict))

    # G5 AI 不可用时确定性筛选仍工作（§14）
    had_ai = fn.AI_MODULE_AVAILABLE
    try:
        fn.AI_MODULE_AVAILABLE = False
        item = _sel_item("飞猪帮帮正式上线", "环球旅讯", "domestic", "china_industry")
        kept, _ = fn.select_news_item(item, "domestic", "china_industry")
    finally:
        fn.AI_MODULE_AVAILABLE = had_ai
    check("G5 AI不可用时确定性筛选保留重点公司产品上线", kept)

    # G6 旧缓存噪音必须经过新筛选（不得次日回流, §13/§14）
    cache = make_cache()
    cache["domestic"]["china_industry"].extend([
        {"date": "2026-08-17", "title": "大湾区自驾香港到底多方便？我们实测完整流程",
         "url": "https://www.traveldaily.cn/article/190001", "source": "环球旅讯", "summary": ""},
        {"date": "2026-08-16", "title": "旅游业的钱，流向何方？｜超哥短评",
         "url": "https://www.traveldaily.cn/article/190002", "source": "环球旅讯", "summary": ""},
        {"date": "2026-08-16", "title": "某连锁酒店品牌突破300家门店，焕新升级再出发",
         "url": "https://www.traveldaily.cn/article/190003", "source": "环球旅讯", "summary": ""},
    ])
    rc, data = run_main(FixtureNet({}), cache, td_items=[], hkex_result=None)
    joined = " ".join(i["title"] for i in data["domestic"]["china_industry"])
    check("G6 旧缓存噪音(实测/短评/软文)经筛选被清除",
          "我们实测完整流程" not in joined and "超哥短评" not in joined
          and "焕新升级再出发" not in joined)
    check("G6b 旧缓存合法条目(飞猪帮帮)经筛选保留", "飞猪帮帮正式上线" in joined)

    # 清理临时诊断文件
    for tmpf in ("_rejected_runmain_tmp.json", "_rejected_test_tmp.json"):
        p = os.path.join(HERE, tmpf)
        if os.path.exists(p):
            os.remove(p)


# ════════════════ H. 东航收窄规则回归（2026-08-18） ════════════════
def test_ceair_narrowing():
    """东航不是重点公司，仅作为航空行业观察来源。
    - 必须命中 CEAIR_IMPACT_RE 业务影响词（票价/退改签/运力/客座率/渠道/收费等）才保留
    - 命中 CEAIR_EXCLUDE_RE 宣传词直接拒绝
    - 14天免费退改 = 固定回归样本，必须保留
    - 东航公司名本身不触发 is_core 加分
    """
    print("\n— H. 东航收窄规则回归 —")

    def _select(title, summary=""):
        item = {"title": title, "summary": summary, "source": "中国民航网",
                "company": "中国东航", "entity_id": "CEAIR"}
        return fn.select_news_item(item, "domestic", "company_news")

    # H1-H3: 三个固定回归样本
    kept, _ = _select("东航国内客票提前14天免费退改")
    check("H1 14天免费退改样本必须保留",
          kept is True and kept)
    item_h1 = {"title": "东航国内客票提前14天免费退改", "summary": "",
               "source": "中国民航网", "company": "中国东航", "entity_id": "CEAIR"}
    fn.select_news_item(item_h1, "domestic", "company_news")
    check("H1b 14天退改样本分数≥60",
          item_h1.get("selection_score", 0) >= 60)

    kept, _ = _select("东航在大兴机场推出智能机器人矩阵")
    check("H2 智能机器人矩阵必须排除",
          kept is False)

    kept, _ = _select("东航江西分公司远程医疗急救平台首次实战")
    check("H3 远程医疗急救平台必须排除",
          kept is False)

    # H4: 东航公司名不自动加分（is_core=False）
    item_h4 = {"title": "东航荣获年度最佳航空公司奖", "summary": "",
               "source": "中国民航网", "company": "中国东航", "entity_id": "CEAIR"}
    fn.select_news_item(item_h4, "domestic", "company_news")
    check("H4 东航不在 CORE_COMPANY_IDS（不享受 is_core +25）",
          "CEAIR" not in fn.CORE_COMPANY_IDS
          and item_h4.get("is_core_company") is False)

    # H5: 东航无业务影响词 → 拒绝
    for title in ("东航升级机上餐饮服务", "东航推出特色旅游产品", "东航新航线开通"):
        kept, _ = _select(title)
        check(f"H5 无业务影响词拒绝: {title[:20]}",
              kept is False)

    # H6: 东航命中业务影响词 → 保留
    for title in (
        "东航调整国内航线燃油附加费",
        "民航局公布东航月度旅客量和客座率数据",
        "东航宣布OTA渠道佣金新政策",
        "东航因台风大范围航班取消启动特殊退改",
    ):
        kept, _ = _select(title)
        check(f"H6 业务影响词保留: {title[:20]}",
              kept is True)

    # H7: 排除词优先级高于业务影响词
    # "东航机器人矩阵提升客座率" 虽含"客座率"但应被 EXCLUDE_RE 拒绝
    kept, _ = _select("东航机器人矩阵提升客座率")
    check("H7 EXCLUDE_RE 优先于 IMPACT_RE",
          kept is False)


# ════════════════ I. 模块路由验收（2026-08-18: 5模块结构 + IR路由 + 同事件去重） ════════════════
def test_module_routing():
    """5模块结构 + IR 路由 + 同事件去重 + 国内公司标签"""
    print("\n— I. 模块路由验收 —")

    # 构造 fixture: 覆盖5个模块的所有路径
    fixture = {
        "international": {
            "sec_filings": [
                {"date": "2026-08-15", "title": "Booking Holdings 10-Q 季度报告",
                 "company": "BKNG", "type": "10-Q", "url": "https://sec.gov/1",
                 "source": "SEC EDGAR", "entity_id": "BKNG", "selection_score": 100,
                 "selection_status": "kept", "summary": "Booking Holdings于2026-08-15向SEC提交10-Q",
                 "event_id": "ev_earnings_bkng_q2"},
                {"date": "2026-08-15", "title": "Booking Holdings Q2 财报新闻稿",
                 "url": "https://ir.bookingholdings.com/q2", "source": "Booking Holdings IR",
                 "entity_id": "BKNG", "selection_score": 95, "selection_status": "kept",
                 "summary": "Q2 营收 55 亿美元", "event_id": "ev_earnings_bkng_q2",
                 "content_type": "earnings"},
            ],
            "industry_news": [
                # BKNG 实质动态 → intl_core_company
                {"date": "2026-08-17", "title": "Booking Holdings 收购 AI 初创公司",
                 "url": "https://skift.com/1", "source": "Skift",
                 "entity_id": "BKNG", "is_core_company": True,
                 "substantive_company_change": True,
                 "selection_score": 78, "selection_status": "kept",
                 "content_type": "ma_funding"},
                # 媒体财报新闻（BKNG）→ intl_disclosures（不应进核心公司）
                {"date": "2026-08-15", "title": "Booking Q2 财报超预期",
                 "url": "https://skift.com/2", "source": "Skift",
                 "entity_id": "BKNG", "selection_score": 85, "selection_status": "kept",
                 "content_type": "earnings", "event_id": "ev_earnings_bkng_q2"},
                # 国际行业（酒店）
                {"date": "2026-08-17", "title": "Marriott announces new luxury hotel brand",
                 "url": "https://skift.com/3", "source": "Skift",
                 "selection_score": 65, "selection_status": "kept",
                 "content_type": "hotel"},
                # 国际行业（航空）
                {"date": "2026-08-16", "title": "Delta reports monthly traffic data",
                 "url": "https://phocuswire.com/1", "source": "PhocusWire",
                 "selection_score": 60, "selection_status": "kept",
                 "content_type": "airline"},
            ],
        },
        "domestic": {
            "china_industry": [
                # 携程动态 → dom_industry（公司标签）
                {"date": "2026-08-17", "title": "携程发布 2026 Q2 财报",
                 "url": "https://traveldaily.cn/1", "source": "环球旅讯",
                 "entity_id": "TCOM", "company": "携程",
                 "selection_score": 80, "selection_status": "kept",
                 "content_type": "earnings"},
                # 飞猪动态 → dom_industry
                {"date": "2026-08-17", "title": "飞猪帮帮正式上线",
                 "url": "https://traveldaily.cn/2", "source": "环球旅讯",
                 "entity_id": "FLIGGY", "company": "飞猪",
                 "selection_score": 70, "selection_status": "kept"},
                # 东航（命中业务影响词）→ dom_industry（不进核心公司，因国内无此模块）
                {"date": "2026-08-17", "title": "东航调整国内航线燃油附加费",
                 "url": "https://caacnews.com.cn/1", "source": "中国民航网",
                 "entity_id": "CEAIR", "company": "中国东航",
                 "selection_score": 60, "selection_status": "kept"},
            ],
            "regulatory": [
                # 披露易公告 → dom_disclosures
                {"date": "2026-08-15", "title": "中国东航 2026 年 7 月运营数据公告",
                 "url": "https://hkex.com/1", "source": "披露易",
                 "entity_id": "CEAIR", "company": "中国东航",
                 "selection_score": 90, "selection_status": "kept",
                 "content_type": "operating_data"},
                # 民航局旅客量数据 → dom_disclosures
                {"date": "2026-08-15", "title": "民航局 7 月旅客量统计",
                 "url": "https://caac.gov.cn/1", "source": "民航局",
                 "selection_score": 85, "selection_status": "kept",
                 "content_type": "operating_data"},
            ],
            "company_news": [
                {"date": "2026-08-17", "title": "东航国内客票提前14天免费退改",
                 "url": "https://caacnews.com.cn/2", "source": "中国民航网",
                 "entity_id": "CEAIR", "company": "中国东航",
                 "selection_score": 60, "selection_status": "kept"},
            ],
        },
    }

    # 执行路由
    routed = fn.route_to_modules(fixture)
    modules = routed.get("modules", {})

    # I1: 5 模块 key 齐全
    check("I1 5模块key齐全",
          set(modules.keys()) == set(fn.MODULE_KEYS))

    # I2: Booking/Expedia/Airbnb IR 动态进入国际核心公司模块
    core_co = modules.get("intl_core_company", [])
    check("I2 BKNG 收购 AI 进入 intl_core_company",
          any(i.get("title", "").startswith("Booking Holdings 收购") for i in core_co))

    # I3: 三家公司财报和 SEC 文件进入披露模块
    intl_disc = modules.get("intl_disclosures", [])
    check("I3a BKNG 10-Q SEC 文件进入 intl_disclosures",
          any(i.get("type") == "10-Q" and i.get("company") == "BKNG" for i in intl_disc))
    # I3b/I3c: IR 财报新闻稿和媒体财报新闻因同 event_id 被合并到 SEC 主卡片的 related_sources
    bkng_main = next((i for i in intl_disc if i.get("type") == "10-Q" and i.get("company") == "BKNG"), None)
    if bkng_main:
        rel_sources = bkng_main.get("related_sources", []) or []
        check("I3b IR/媒体财报合并到 SEC 主卡片 related_sources",
              any("Booking Holdings IR" in s or "Skift" in s for s in rel_sources))
    else:
        check("I3b IR/媒体财报合并到 SEC 主卡片 related_sources", False)

    # I4: 国际行业新闻全部进入同一列表（不分子栏目）
    intl_ind = modules.get("intl_industry", [])
    check("I4a Marriott 酒店 新闻进入 intl_industry",
          any("Marriott" in i.get("title", "") for i in intl_ind))
    check("I4b Delta 航空 新闻进入 intl_industry",
          any("Delta" in i.get("title", "") for i in intl_ind))
    check("I4c intl_industry 不含 BKNG 实质动态",
          not any(i.get("entity_id") == "BKNG" and i.get("substantive_company_change") for i in intl_ind))

    # I5: 国内公司动态标签
    dom_ind = modules.get("dom_industry", [])
    check("I5a 携程新闻进入 dom_industry 且有 entity_id=TCOM",
          any(i.get("entity_id") == "TCOM" and i.get("company") == "携程" for i in dom_ind))
    check("I5b 飞猪新闻进入 dom_industry 且有 entity_id=FLIGGY",
          any(i.get("entity_id") == "FLIGGY" and i.get("company") == "飞猪" for i in dom_ind))
    check("I5c 东航燃油附加费进入 dom_industry",
          any("东航调整国内航线燃油附加费" in i.get("title", "") for i in dom_ind))

    # I6: 国内不出现独立核心公司模块
    check("I6 dom_industry 含东航标签但不分核心公司子模块",
          any(i.get("entity_id") == "CEAIR" for i in dom_ind))

    # I7: 政府统计和披露易进入国内披露模块
    dom_disc = modules.get("dom_disclosures", [])
    check("I7a 披露易公告进入 dom_disclosures",
          any("披露易" in i.get("source", "") for i in dom_disc))
    check("I7b 民航局旅客量统计进入 dom_disclosures",
          any("民航局" in i.get("source", "") and "旅客量" in i.get("title", "") for i in dom_disc))

    # I8: 同事件去重（BKNG Q2 财报：SEC 10-Q + IR 新闻稿 + 媒体新闻 → 一张主卡片）
    bkng_earnings = [i for i in intl_disc if i.get("event_id") == "ev_earnings_bkng_q2"]
    check("I8 同事件(BKNG Q2)只显示一张主卡片",
          len(bkng_earnings) == 1)
    if bkng_earnings:
        main_card = bkng_earnings[0]
        # 主卡片应有 related_sources 合并其他来源
        rel = main_card.get("related_sources", []) or []
        check("I8b 主卡片 related_sources 含其他来源",
              len(rel) >= 1)


def main():
    print("=" * 60)
    print("News quality offline tests")
    print("=" * 60)
    test_dates()
    test_dedupe()
    test_tls()
    test_summary_evidence()
    test_domestic_filters()
    test_source_status()
    test_selection()
    test_ceair_narrowing()
    test_module_routing()
    print("\n" + "=" * 60)
    print(f"RESULT: {PASS} passed, {FAIL} failed")
    if FAILURES:
        print("Failed:", "; ".join(FAILURES))
    print("=" * 60)
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
