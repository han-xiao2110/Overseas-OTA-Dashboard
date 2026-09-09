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
import datetime
import email.utils
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

# 离线 fixture 不得读写生产翻译缓存，否则同一标题在不同机器上会得到
# 「已翻译/未翻译」两种测试结果。
TEST_TRANSLATION_CACHE_PATH = os.path.join(HERE, "_translation_cache_test_tmp.json")
fn.TRANSLATION_CACHE_PATH = TEST_TRANSLATION_CACHE_PATH
fn.TRANSLATE_CACHE.clear()
fn._TRANSLATE_CACHE_DIRTY = False

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
    today = datetime.date.today()
    nd_old = {"title": "很久前抓的未知日期条目", "date": "", "url": "https://x/old",
              "fetched_at": f"{today - datetime.timedelta(days=48):%Y-%m-%d} 09:00:00",
              "source": "测试", "date_status": "unknown"}
    nd_new = {"title": "今天抓的未知日期条目", "date": "", "url": "https://x/new",
              "fetched_at": f"{today:%Y-%m-%d} 09:00:00",
              "source": "测试", "date_status": "unknown"}
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
    recent_date = (datetime.date.today() - datetime.timedelta(days=1)).isoformat()
    data = {"domestic": {"china_industry": [
        {"title": "Expedia收购AI助手Layla", "date": recent_date, "url": "https://www.traveldaily.cn/article/190541",
         "source": "环球旅讯"},
        {"title": "Expedia收购AI助手Layla", "date": recent_date,
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

    form4_xml = """<?xml version="1.0"?><ownershipDocument>
      <documentType>4</documentType><periodOfReport>2026-08-24</periodOfReport>
      <issuer><issuerTradingSymbol>EXPE</issuerTradingSymbol></issuer>
      <reportingOwner><reportingOwnerId><rptOwnerName>Example Officer</rptOwnerName></reportingOwnerId>
      <reportingOwnerRelationship><isOfficer>1</isOfficer><officerTitle>Chief Financial Officer</officerTitle>
      </reportingOwnerRelationship></reportingOwner><aff10b5One>true</aff10b5One>
      <nonDerivativeTable><nonDerivativeTransaction><securityTitle><value>Common Stock</value></securityTitle>
      <transactionCoding><transactionCode>S</transactionCode></transactionCoding>
      <transactionAmounts><transactionShares><value>1004</value></transactionShares>
      <transactionPricePerShare><value>335</value></transactionPricePerShare></transactionAmounts>
      <postTransactionAmounts><sharesOwnedFollowingTransaction><value>104331</value>
      </sharesOwnedFollowingTransaction></postTransactionAmounts><ownershipNature>
      <directOrIndirectOwnership><value>D</value></directOrIndirectOwnership></ownershipNature>
      </nonDerivativeTransaction></nonDerivativeTable></ownershipDocument>"""
    form4_summary = fn.summarize_sec_form4(form4_xml, {"company": "EXPE"})
    check("E13 Form 4摘要含申报人/职位/股数/价格/交易后持股/10b5-1",
          all(x in form4_summary for x in (
              "Example Officer", "首席财务官", "1,004股", "335.00美元/股",
              "104,331股", "10b5-1")))

    form144_xml = """<?xml version="1.0"?><edgarSubmission xmlns="http://www.sec.gov/edgar/ownership">
      <headerData><submissionType>144</submissionType></headerData><formData><issuerInfo>
      <nameOfPersonForWhoseAccountTheSecuritiesAreToBeSold>Example Seller</nameOfPersonForWhoseAccountTheSecuritiesAreToBeSold>
      <relationshipsToIssuer><relationshipToIssuer>Director</relationshipToIssuer></relationshipsToIssuer>
      </issuerInfo><securitiesInformation><securitiesClassTitle>Class A</securitiesClassTitle>
      <brokerOrMarketmakerDetails><name>Fidelity Brokerage Services LLC</name></brokerOrMarketmakerDetails>
      <noOfUnitsSold>57160</noOfUnitsSold><aggregateMarketValue>10901033.25</aggregateMarketValue>
      <approxSaleDate>08/28/2026</approxSaleDate></securitiesInformation></formData></edgarSubmission>"""
    form144_summary = fn.summarize_sec_form144(form144_xml, {"company": "ABNB"})
    check("E14 Rule 144摘要含拟售人/日期/股数/市值/经纪商",
          all(x in form144_summary for x in (
              "Example Seller", "2026-08-28", "57,160股", "1090.1万美元", "Fidelity")))

    metadata_summary = fn.sec_metadata_summary({
        "company": "BKNG", "type": "8-K", "date": "2026-08-05",
        "sec_items": ["2.02", "9.01"]})
    check("E15 8-K摘要把Item编号解释为具体事项",
          "公布经营业绩或财务状况" in metadata_summary and "提交财务报表或附件" in metadata_summary)

    sec_fixture = [{"company": "EXPE", "type": "4", "date": "2026-08-25",
                    "url": "https://www.sec.gov/Archives/edgar/data/1/2/doc4.xml"}]
    with mock.patch.object(fn, "safe_request", return_value=form4_xml), \
         mock.patch.object(fn.time, "sleep", return_value=None):
        fn.enrich_sec_filing_summaries(sec_fixture)
    check("E16 SEC详情补抓写入版本/类型/详情URL",
          sec_fixture[0].get("sec_summary_version") == fn.SEC_DETAIL_SUMMARY_VERSION and
          sec_fixture[0].get("sec_summary_kind") == "document_detail" and
          sec_fixture[0].get("sec_detail_url", "").endswith("doc4.xml"))

    report_8k = """<html><body><b>Item 2.02 Results of Operations and Financial Condition</b>
      <b>Item 9.01 Financial Statements and Exhibits</b></body></html>"""
    report_8k_filing = {"company": "EXPE", "type": "8-K", "date": "2026-08-05"}
    report_8k_summary = fn.summarize_sec_report_document(report_8k, report_8k_filing)
    check("E17 8-K正文提取Item并解释事项",
          report_8k_filing.get("sec_items") == ["2.02", "9.01"] and
          "公布经营业绩或财务状况" in report_8k_summary and
          "提交财务报表或附件" in report_8k_summary)

    report_8k_header = """CONFORMED SUBMISSION TYPE: 8-K
      ITEM INFORMATION: Results of Operations and Financial Condition
      ITEM INFORMATION: Regulation FD Disclosure
      ITEM INFORMATION: Other Events
      ITEM INFORMATION: Financial Statements and Exhibits"""
    report_8k_header_filing = {"company": "EXPE", "type": "8-K", "date": "2026-08-05"}
    report_8k_header_summary = fn.summarize_sec_report_document(
        report_8k_header, report_8k_header_filing)
    check("E17b 8-K完整提交文本的ITEM INFORMATION可解析",
          report_8k_header_filing.get("sec_items") == ["2.02", "7.01", "8.01", "9.01"] and
          "Regulation FD" in report_8k_header_summary and "其他重大事项" in report_8k_header_summary)

    report_10q = """<html><body><dei:DocumentPeriodEndDate contextRef="d">2026-06-30
      </dei:DocumentPeriodEndDate></body></html>"""
    report_10q_filing = {"company": "BKNG", "type": "10-Q", "date": "2026-08-04"}
    report_10q_summary = fn.summarize_sec_report_document(report_10q, report_10q_filing)
    check("E18 10-Q正文提取报告期",
          report_10q_filing.get("report_date") == "2026-06-30" and
          "截至2026-06-30的季度报告" in report_10q_summary)

    report_10q_human = """<ix:nonNumeric name="dei:DocumentPeriodEndDate"
      format="ixt:date-monthname-day-year-en">June 30, 2026</ix:nonNumeric>"""
    report_10q_human_filing = {"company": "EXPE", "type": "10-Q", "date": "2026-08-06"}
    fn.summarize_sec_report_document(report_10q_human, report_10q_human_filing)
    check("E18b 10-Q人类可读日期转换为ISO报告期",
          report_10q_human_filing.get("report_date") == "2026-06-30")


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

    hkex = {s.get("stock_name"): s.get("stock_id") for s in fn.DOMESTIC_WEB_SOURCES
            if s.get("news_selector") == "hkex"}
    check("F6 披露易仅抓取携程/同程/嘀嗒出行",
          hkex == {"携程": "1000090312", "同程": "205645", "嘀嗒出行": "1000226331"})
    company_feeds = {f.get("company") for f in fn.CN_COMPANY_FEEDS if f.get("company")}
    check("F7 Google News定向源为携程/同程/嘀嗒出行",
          company_feeds == {"携程", "同程", "嘀嗒出行"})

    caac_html = ('<a href="/tt/202609/t20260903_10001.html">国航新增北京至新加坡航线</a>'
                 '<a href="/tt/202609/t20260903_10002.html">东航调整国内航线燃油附加费</a>')
    caac_items = fn.extract_caac_news(caac_html, "中国民航网", "company_news",
                                      "http://www.caacnews.com.cn/", 10)
    check("F8 中国民航网解析不再只限东航",
          len(caac_items) == 2 and any("国航" in x["title"] for x in caac_items))

    ir_sources = {s["name"]: s for s in fn.DOMESTIC_IR_SOURCES}
    check("F9 国内三家公司IR入口齐全",
          set(ir_sources) == {"Trip.com Group IR", "同程旅行 IR", "嘀嗒出行 IR"} and
          any("quarterly-results" in u for u in ir_sources["Trip.com Group IR"]["pages"]) and
          any("financials" in u for u in ir_sources["同程旅行 IR"]["pages"]) and
          any("ir_ann" in u for u in ir_sources["嘀嗒出行 IR"]["pages"]))

    check("F10 Trip.com SEC CIK及重点表格已配置",
          fn.COMPANIES.get("TCOM", {}).get("cik") == "0001269238" and
          all(form in fn.SEC_FILING_TYPES for form in
              ("6-K", "20-F", "F-3", "424B5", "SC 13D/A", "SC 13G/A")))

    recent_ir_date = (datetime.date.today() - datetime.timedelta(days=1)).isoformat()
    ir_html = f'''<div class="news-item"><span>{recent_ir_date}</span>
      <a href="/zh-hans/news-releases/news-release-details/q2-results">
      携程集团将公布2026年第二季度财务业绩</a></div>
      <div><span>{recent_ir_date}</span><a href="/news-center/strategic-partnership">
      同程旅行宣布与铁路平台达成战略合作</a></div>'''
    trip_src = ir_sources["Trip.com Group IR"]
    ir_items = fn.extract_domestic_ir_page(
        ir_html, trip_src, "https://investors.trip.com/zh-hans")
    check("F11 国内IR解析保留日期、官方URL和实体",
          len(ir_items) == 2 and ir_items[0]["date"] == recent_ir_date and
          ir_items[0]["url"].startswith("https://investors.trip.com/") and
          all(x.get("entity_id") == "TCOM" and x.get("is_ir_source") for x in ir_items))
    check("F12 国内IR业绩与战略新闻分流",
          ir_items[0]["ir_release_kind"] == "earnings_disclosure" and
          ir_items[1]["ir_release_kind"] == "core_action" and
          fn._route_single_item(ir_items[0], "domestic", "regulatory") == "dom_disclosures" and
          fn._route_single_item(ir_items[1], "domestic", "company_news") == "dom_industry")

    tcom_sec = {"date": "2026-09-02", "company": "TCOM", "entity_id": "TCOM",
                "type": "6-K", "title": "境外发行人报告 (6-K)",
                "url": "https://www.sec.gov/Archives/tcom-6k", "source": "SEC EDGAR"}
    sec_kept, _ = fn.select_news_item(tcom_sec, "domestic", "regulatory")
    check("F13 Trip.com SEC文件进国内披露且强制保留",
          sec_kept and fn._route_single_item(tcom_sec, "domestic", "regulatory") == "dom_disclosures")

    caac_official = [
        {"title": "中国民航局发布7月旅客运输量和客座率", "summary": ""},
        {"title": "某航空公司引进三架宽体机扩充机队", "summary": ""},
    ]
    caac_kept = fn.filter_domestic_items("中国民用航空局", caac_official)
    check("F14 民航局保留明确流量数据并排除机队宽体机",
          len(caac_kept) == 1 and "客座率" in caac_kept[0]["title"])

    media_names = {f["name"] for f in fn.CN_COMPANY_FEEDS}
    check("F15 行业与财经媒体发现源已覆盖",
          {"中国旅游报", "品橙旅游", "旅界", "Reuters 中国旅游",
           "Bloomberg 中国旅游", "财新", "第一财经", "证券时报", "上海证券报",
           "21世纪经济报道", "界面新闻", "澎湃新闻"}.issubset(media_names))

    overseas_cn_media = {"title": "亚洲航空与飞马航空在伊斯坦布尔达成代码共享",
                         "summary": "为亚欧之间开辟新航线"}
    check("F16 中文媒体的海外事件仍判为国际",
          fn._td_region(overseas_cn_media["title"], overseas_cn_media["summary"], "") == "international")

    media_financial = {"title": "携程发布季度业绩", "summary": "营收同比增长",
                       "source": "第一财经", "entity_id": "TCOM", "content_type": "earnings"}
    check("F17 媒体财报报道不进官方披露",
          fn._route_single_item(media_financial, "domestic", "company_news") == "dom_industry")

    source_by_name = {s["name"]: s for s in fn.DOMESTIC_WEB_SOURCES}
    check(
        "F18 监管首页使用非JS跳转落地页",
        source_by_name["交通运输部·政府信息公开"]["url"].endswith("/zhengce/")
        and source_by_name["中国民用航空局"]["url"].endswith("/index.html")
        and source_by_name["交通运输部·统计数据"]["news_selector"] == "generic"
        and source_by_name["中国民用航空局"]["news_selector"] == "gov_list",
    )

    mot_stats_html = '''
      <div class="stat-item"><a href="https://xxgk.mot.gov.cn/jigou/zhghs/202609/t20260903_4229999.html">
        2026年1-8月公路水路旅客运输量
      </a></div>
    '''
    mot_stats_items = fn.extract_news_from_html(
        mot_stats_html, "交通运输部·统计数据", "regulatory",
        "https://www.mot.gov.cn/shuju/", "generic", 10,
    )
    check(
        "F19 交通部统计链接从URL恢复日期",
        len(mot_stats_items) == 1 and mot_stats_items[0].get("date") == "2026-09-03",
    )

    mct_suffix_kept = fn.filter_domestic_items(
        "文旅部·统计信息",
        [{"title": "全国博物馆藏品管理办法", "summary": ""}],
        record_stats=False,
    )
    caac_stats_kept = fn.filter_domestic_items(
        "中国民用航空局·统计数据",
        [{"title": "中国民航2026年7月份主要生产指标统计", "summary": ""}],
        record_stats=False,
    )
    check(
        "F20 栏目后缀继承母来源过滤规则",
        not mct_suffix_kept and len(caac_stats_kept) == 1,
    )


# ════════════════ C. 来源状态 / 失败回退（main 集成, fixture 不联网） ════════════════

RECENT_FIXTURE_DATE = datetime.date.today() - datetime.timedelta(days=1)
RECENT_FIXTURE_RSS_DATE = email.utils.format_datetime(datetime.datetime.combine(
    RECENT_FIXTURE_DATE, datetime.time(12, 0), tzinfo=datetime.timezone.utc))

SKIFT_RSS = f"""<?xml version="1.0"?><rss version="2.0"><channel>
<item><title>Saudi OTA Almosafer IPO Despite Iran War Disruption</title>
<link>https://skift.com/2026/08/17/almosafer-ipo/</link>
<pubDate>{RECENT_FIXTURE_RSS_DATE}</pubDate>
<description>Riyadh-based Almosafer parent Seera Group is pressing ahead with its IPO.</description>
</item></channel></rss>"""

BLOOMBERG_RSS = f"""<?xml version="1.0"?><rss version="2.0"><channel>
<item><title>Airbnb Beats Estimates as Travel Demand Surges</title>
<link>https://www.bloomberg.com/news/articles/2026-08-17/airbnb-q2</link>
<pubDate>{RECENT_FIXTURE_RSS_DATE}</pubDate>
<description>Airbnb reported quarterly revenue above analyst estimates on strong travel demand.</description>
</item></channel></rss>"""

GOOGLE_RSS = f"""<?xml version="1.0"?><rss version="2.0"><channel>
<item><title>Airbnb travel tools update - PhocusWire</title>
<link>https://news.google.com/rss/articles/abc123</link>
<pubDate>{RECENT_FIXTURE_RSS_DATE}</pubDate>
<description> </description>
</item></channel></rss>"""

EDGAR_JSON = {
    "hits": {"hits": [{
        "_source": {
            "form": "10-Q", "file_date": RECENT_FIXTURE_DATE.isoformat(),
            "adsh": "0001075531-26-000123",
            "display_names": ["Booking Holdings Inc."],
            "ciks": ["0001075531"], "file_type": "10-Q", "file_description": "",
        }}]}
}


def make_cache():
    """构造带历史 fetch_status 的有效缓存。"""
    recent = (fn.datetime.date.today() - fn.datetime.timedelta(days=1)).isoformat()
    return {
        "international": {
            "sec_filings": [
                {"date": recent, "company": "BKNG", "type": "10-Q",
                 "title": "季度报告 (10-Q)", "url": "https://www.sec.gov/x1", "source": "SEC EDGAR"},
            ],
            "industry_news": [
                {"date": recent, "title": "Airbnb上线新营销引擎",
                 "url": "https://www.traveldaily.cn/article/190600", "source": "环球旅讯",
                 "summary": "Airbnb面向房东推出营销工具。"},
            ],
        },
        "domestic": {
            "china_industry": [
                {"date": recent, "title": "飞猪帮帮正式上线",
                 "url": "https://www.traveldaily.cn/article/190601", "source": "环球旅讯",
                 "summary": "飞猪上线旅行助手功能。"},
            ],
            "regulatory": [
                {"date": recent, "title": "文旅部发布暑期市场数据",
                 "url": "https://www.mct.gov.cn/t1", "source": "文旅部", "summary": ""},
            ],
            "company_news": [
                {"date": recent, "title": "中国东航新增上海伦敦航线",
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
        if host in ('ir.bookingholdings.com', 'ir.expediagroup.com',
                    'investors.airbnb.com') and '/feed/PressRelease' in url:
            if 'ir_q4' not in self.ok_hosts:
                return None
            return {"GetPressReleaseListResult": [{
                "PressReleaseDate": "08/26/2026 09:00:00",
                "Headline": "Company to Present at Investor Conference",
                "LinkToDetailPage": "/news/news-details/2026/conference/default.aspx",
                "ShortDescription": "Official investor event",
            }]}
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
        'ir_q4': True,
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
          bbg and any(len(i.get("summary_original") or i.get("summary") or "") > 10
                      for i in bbg))

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
    ("某酒店集团公布季度RevPAR增长8%，净开店120家", "Skift", "international", "industry_news", False, {}),
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
    check("G3b 英文公司名紧邻中文仍命中相关性",
          any(p.search("Expedia集团任命新任首席财务官")
              for p in fn.TRAVEL_KEYWORD_PATTERNS)
          and any(p.search("Agoda推出AI客房选择工具")
                  for p in fn.TRAVEL_KEYWORD_PATTERNS))

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

    # G7 v2主题规则固定案例
    cases = [
        ("Google’s Agentic Hotel Booking Tool Comes to AI Mode", "Skift", True),
        ("Ixigo Tests Packaged Tours for Trains, Uber Becomes a New Distribution Engine", "Skift", True),
        ("Marriott Heading for 100 Cities in India", "Skift", False),
        ("Expedia Executive Sells 3,133 Shares for $1 Million", "Expedia", True),
        ("Airbnb And Expedia Stocks Are Riding High. Here's Why.", "Expedia", False),
        ("Get $180 Back After Spending $300 at Expedia With Capital One Shopping [Targeted]", "Expedia", False),
        ("Why boutique hotel founders eventually sell", "Skift", False),
        ("Skift 全球论坛前瞻：维珍航空首席执行官谈人工智能", "Skift", False),
        ("案例与合作伙伴征集｜2026下半年AI旅游应用洞察报告", "环球旅讯", False),
        ("Expedia 集团公司 尽管当天亏损，但该股的表现仍优于竞争对手", "Expedia", False),
        ("Expedia Launches Autumn Travel Sale with Up to 30% Off Hotels", "TRAICY Global", False),
        ("Trip.com unveils 9.9 Mega Sale travel deals", "Trip.com", False),
        ("Vrbo Product Rollout Tests Expedia Stock Bull Case", "Simply Wall St", False),
        ("Raymond James upgrades Airbnb stock rating on AI growth potential", "Investing.com", False),
        ("嘉宾访谈 | 携程集团目的地合作部副总经理：助力入境旅游市场提质扩容", "商业媒体", False),
        ("AI驱动差旅管理新范式：携程商旅AI开放平台差异化优势与企业适配分析", "中宏网", False),
    ]
    case_results = []
    for title, source, expected in cases:
        item = _sel_item(title, source, "international", "industry_news")
        if "Google" in title:
            item["summary"] = "Google launched an agentic AI hotel booking tool for travelers."
        if "Ixigo" in title:
            item["summary"] = "The travel platform launched packaged tours and a new Uber distribution channel."
        kept, _ = fn.select_news_item(item, "international", "industry_news")
        case_results.append(kept == expected)
    translated_promo = _sel_item(
        "两天，超级优惠：Trip.com 9月销售土地，澳大利亚国内航班$29",
        "Trip.com", "international", "industry_news")
    translated_promo["title_original"] = (
        "Two Days, Mega Savings: Trip.com's September Sale Lands with $29 Domestic Flights "
        "and Up to 50% Off Travel Deals in Australia")
    translated_promo_kept, _ = fn.select_news_item(
        translated_promo, "international", "industry_news")
    case_results.append(not translated_promo_kept)
    check("G7 v6保留事实新闻并排除Hotel扩张、股价评论、促销和观点", all(case_results))

    # G8 取消统一筛选前的每来源10条上限
    many = [_sel_item(f"Travel platform launches booking product {i}", "Skift",
                      "international", "industry_news") for i in range(12)]
    check("G8 filter_and_rank_news 默认不再按来源截断10条",
          len(fn.filter_and_rank_news(many)) == 12)

    # G9 环球旅讯跨境科技交易分流
    td_cases = [
        ("差旅管理公司eTravel收购罗马尼亚同行Accent Travel & Events多数股权", "distribute"),
        ("度假租赁宾客服务平台VayKLife收购Xplorie", "traveltech"),
        ("差旅平台Spotnana收购会议管理平台Troop", "traveltech"),
    ]
    check("G9 环球旅讯三条海外交易识别为国际",
          all(fn._td_is_domestic(t, "", ch) is False for t, ch in td_cases))
    check("G9a 海外交易即使来自express入口也进国际",
          fn._td_is_domestic(td_cases[0][0], "", "express") is False and
          fn._td_is_domestic(td_cases[2][0], "", "express") is False)
    airasia_title = "亚洲航空与土耳其领先低成本航空公司飞马航空达成划时代代码共享合作，并计划将伊斯坦布尔航班增至每日一班"
    check("G9b 亚洲航空与飞马航空代码共享识别为国际",
          fn._td_region(airasia_title, "双方将在亚欧之间开辟100余条新航线", "airline") == "international" and
          fn._td_is_domestic(airasia_title, "", "airline") is False)
    check("G9c 无地域证据的环球旅讯条目不再默认国内",
          fn._td_region("旅游平台发布新功能", "", "express") == "unknown" and
          fn._td_is_domestic("旅游平台发布新功能", "", "express") is False)
    vayk = _sel_item(td_cases[1][0], "环球旅讯", "international", "industry_news")
    vayk["summary"] = "度假租赁宾客服务平台VayKLife完成对旅游科技平台Xplorie的收购。"
    vayk_kept, _ = fn.select_news_item(vayk, "international", "industry_news")
    check("G9d 两条人工样本确认后排除度假租赁宾客服务并购", not vayk_kept)

    # G10 人工标注校验与精确覆盖结构
    sample_rows = [{"标题": "Test", "来源": "Skift", "日期": "2026-08-28",
                    "URL": "https://example.com/a", "用户标注": "保留",
                    "排除原因": "", "备注": "边界样本"}]
    payload, imported = fn._validate_and_merge_labels(sample_rows,
        labels_path=os.path.join(HERE, "_labels_missing.json"))
    check("G10 人工标注生成精确URL覆盖记录",
          imported == 1 and payload["labels"][0]["label"] == "保留"
          and payload["labels"][0]["key"].startswith("url:"))
    bad_label_ok = conflict_ok = missing_ok = False
    try:
        fn._validate_and_merge_labels([{**sample_rows[0], "用户标注": "通过"}],
                                      labels_path=os.path.join(HERE, "_labels_missing.json"))
    except ValueError:
        bad_label_ok = True
    try:
        fn._validate_and_merge_labels([sample_rows[0], {**sample_rows[0], "用户标注": "排除"}],
                                      labels_path=os.path.join(HERE, "_labels_missing.json"))
    except ValueError:
        conflict_ok = True
    try:
        fn._validate_and_merge_labels([{**sample_rows[0], "URL": ""}],
                                      labels_path=os.path.join(HERE, "_labels_missing.json"))
    except ValueError:
        missing_ok = True
    check("G10b 导入拒绝非法标签、重复冲突和关键字段缺失",
          bad_label_ok and conflict_ok and missing_ok)
    normalized, normalized_count = fn._validate_and_merge_labels([
        {**sample_rows[0], "用户标注": "排除", "排除原因": "这里是评论性内容"},
        {**sample_rows[0], "URL": "https://example.com/b", "用户标注": "",
         "排除原因": "其实和上一条是同一新闻，所以只要一个"},
    ], labels_path=os.path.join(HERE, "_labels_missing.json"))
    normalized_rows = {x["url"]: x for x in normalized["labels"]}
    check("G10c 自由文本原因标准化且重复事件备注可隐式排除",
          normalized_count == 2
          and normalized_rows["https://example.com/a"]["reason"] == "评论观点"
          and normalized_rows["https://example.com/b"]["label"] == "排除")

    # G11 30条边界清单稳定且单一来源不超过5条
    rows = fn.build_review_candidates(size=30)
    source_counts = {}
    for row in rows:
        source_counts[row["source"]] = source_counts.get(row["source"], 0) + 1
    check("G11 标注候选为30条且每来源最多5条",
          len(rows) == 30 and max(source_counts.values()) <= 5)

    # G12 所有已确认人工标签必须成为精确回归样本；不确定只留档。
    confirmed = [x for x in fn.load_manual_labels().values()
                 if x.get("label") in ("保留", "排除")]
    label_results = []
    for labeled in confirmed:
        item = {"date": labeled.get("date", "2026-08-28"),
                "title": labeled.get("title", ""), "summary": "",
                "source": labeled.get("source", ""), "url": labeled.get("url", "")}
        category = "sec_filings" if "SEC EDGAR" in item["source"] else "industry_news"
        kept, _ = fn.select_news_item(item, "international", category)
        label_results.append(kept == (labeled.get("label") == "保留"))
    check("G12 全部确认标注维持精确回归一致", bool(confirmed) and all(label_results))

    # G13 旧缓存翻译失败后，下次日更必须重试，不能永久留英文。
    old_translate = fn.translate_text
    old_translate_fails = fn._TRANSLATE_FAILS
    try:
        fn._TRANSLATE_FAILS = 0
        fn.translate_text = lambda text, max_chars=500: "VayKLife收购Xplorie，整合度假租赁配套与活动"
        retry_item = {"title": "VayKLife acquires Xplorie to combine vacation rental amenities and activities",
                      "summary": "", "source": "PhocusWire"}
        fn.retry_cached_translations([retry_item])
    finally:
        fn.translate_text = old_translate
        fn._TRANSLATE_FAILS = old_translate_fails
    check("G13 缓存中未翻译英文标题会在后续日更重试", "收购" in retry_item["title"])

    # 清理临时诊断文件
    for tmpf in ("_rejected_runmain_tmp.json", "_rejected_test_tmp.json"):
        p = os.path.join(HERE, tmpf)
        if os.path.exists(p):
            os.remove(p)


# ════════════════ H. 东航收窄规则回归（2026-08-18） ════════════════
def test_ceair_narrowing():
    """所有航司/航空新闻只保留六类 OTA 机票业务影响主题。"""
    print("\n— H. 航司/航空新闻统一收窄规则 —")

    def _select(title, summary="", source="中国民航网", section="domestic"):
        item = {"title": title, "summary": summary, "source": source}
        category = "company_news" if section == "domestic" else "industry_news"
        return fn.select_news_item(item, section, category)

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

    # H5: 无六类业务影响词 → 拒绝
    for title in ("东航升级机上餐饮服务", "东航推出特色旅游产品", "达美航空宣布新的品牌形象"):
        kept, _ = _select(title)
        check(f"H5 无业务影响词拒绝: {title[:20]}",
              kept is False)

    # H6: 国内外航司命中六类业务影响词 → 保留
    for title in (
        "东航调整国内航线燃油附加费",
        "达美航空上调托运行李收费",
        "新加坡航空公布月度运力、旅客量和客座率",
        "美联航调整OTA渠道代理佣金政策",
        "英航复航伦敦至北京航线",
        "汉莎航空因天气取消部分航线并启动特殊退改",
    ):
        kept, _ = _select(title, source="PhocusWire", section="international")
        check(f"H6 业务影响词保留: {title[:20]}",
              kept is True)

    kept, _ = _select("国航新增北京至新加坡航线")
    check("H6b 中国民航网的其他航司合格新闻可保留", kept is True)

    for title in (
        "中国东航亚洲最大宽体机维修机库投运",
        "美联航公布2026年第二季度财报与净利润",
        "某航空公司发布月度经营数据",
        "达美航空扩大机队规模",
    ):
        kept, _ = _select(title, source="Skift", section="international")
        check(f"H6c 航空低价值主题排除: {title[:20]}", kept is False)

    # H7: 排除词优先级高于业务影响词
    # "东航机器人矩阵提升客座率" 虽含"客座率"但应被 EXCLUDE_RE 拒绝
    kept, _ = _select("东航机器人矩阵提升客座率")
    check("H7 AIRLINE_EXCLUDE_RE 优先于 AIRLINE_IMPACT_RE",
          kept is False)

    water_item = {"title": "19个典型案例入选国内水路旅游客运精品航线", "summary": "",
                  "source": "交通运输部"}
    kept, _ = fn.select_news_item(water_item, "domestic", "regulatory")
    check("H8 水路客运航线不被误当作航空新闻", kept is True)


# ════════════════ I. 模块路由验收（2026-08-18: 5模块结构 + IR路由 + 同事件去重） ════════════════
def test_module_routing():
    """5模块结构 + IR 路由 + 同事件去重 + 国内公司标签"""
    print("\n— I. 模块路由验收 —")
    recent = (fn.datetime.date.today() - fn.datetime.timedelta(days=1)).isoformat()

    # 构造 fixture: 覆盖5个模块的所有路径
    fixture = {
        "international": {
            "sec_filings": [
                {"date": recent, "title": "Booking Holdings 10-Q 季度报告",
                 "company": "BKNG", "type": "10-Q", "url": "https://sec.gov/1",
                 "source": "SEC EDGAR", "entity_id": "BKNG", "selection_score": 100,
                 "selection_status": "kept", "summary": "Booking Holdings于2026-08-15向SEC提交10-Q",
                 "event_id": "ev_earnings_bkng_q2"},
                {"date": recent, "title": "Booking Holdings Q2 财报新闻稿",
                 "url": "https://ir.bookingholdings.com/q2", "source": "Booking Holdings IR",
                 "entity_id": "BKNG", "selection_score": 95, "selection_status": "kept",
                 "summary": "Q2 营收 55 亿美元", "event_id": "ev_earnings_bkng_q2",
                 "content_type": "earnings"},
            ],
            "industry_news": [
                # BKNG 实质动态 → intl_core_company
                {"date": recent, "title": "Booking Holdings 收购 AI 初创公司",
                 "url": "https://skift.com/1", "source": "Skift",
                 "entity_id": "BKNG", "is_core_company": True,
                 "substantive_company_change": True,
                 "selection_score": 78, "selection_status": "kept",
                 "content_type": "ma_funding"},
                # 媒体财报新闻（BKNG）→ intl_disclosures（不应进核心公司）
                {"date": recent, "title": "Booking Q2 财报超预期",
                 "url": "https://skift.com/2", "source": "Skift",
                 "entity_id": "BKNG", "selection_score": 85, "selection_status": "kept",
                 "content_type": "earnings", "event_id": "ev_earnings_bkng_q2"},
                # 国际行业（酒店）
                {"date": recent, "title": "Marriott announces new luxury hotel brand",
                 "url": "https://skift.com/3", "source": "Skift",
                 "selection_score": 65, "selection_status": "kept",
                 "content_type": "hotel"},
                # 国际行业（航空）
                {"date": recent, "title": "Delta reports monthly traffic data",
                 "url": "https://phocuswire.com/1", "source": "PhocusWire",
                 "selection_score": 60, "selection_status": "kept",
                 "content_type": "airline"},
            ],
        },
        "domestic": {
            "china_industry": [
                # 携程动态 → dom_industry（公司标签）
                {"date": recent, "title": "携程发布 2026 Q2 财报",
                 "url": "https://traveldaily.cn/1", "source": "环球旅讯",
                 "entity_id": "TCOM", "company": "携程",
                 "selection_score": 80, "selection_status": "kept",
                 "content_type": "earnings"},
                # 飞猪动态 → dom_industry
                {"date": recent, "title": "飞猪帮帮正式上线",
                 "url": "https://traveldaily.cn/2", "source": "环球旅讯",
                 "entity_id": "FLIGGY", "company": "飞猪",
                 "selection_score": 70, "selection_status": "kept"},
                # 东航（命中业务影响词）→ dom_industry（不进核心公司，因国内无此模块）
                {"date": recent, "title": "东航调整国内航线燃油附加费",
                 "url": "https://caacnews.com.cn/1", "source": "中国民航网",
                 "entity_id": "CEAIR", "company": "中国东航",
                 "selection_score": 60, "selection_status": "kept"},
            ],
            "regulatory": [
                # 披露易公告 → dom_disclosures
                {"date": recent, "title": "中国东航 2026 年 7 月运营数据公告",
                 "url": "https://hkex.com/1", "source": "披露易",
                 "entity_id": "CEAIR", "company": "中国东航",
                 "selection_score": 90, "selection_status": "kept",
                 "content_type": "operating_data"},
                # 民航局旅客量数据 → dom_disclosures
                {"date": recent, "title": "民航局 7 月旅客量统计",
                 "url": "https://caac.gov.cn/1", "source": "民航局",
                 "selection_score": 85, "selection_status": "kept",
                 "content_type": "operating_data"},
            ],
            "company_news": [
                {"date": recent, "title": "东航国内客票提前14天免费退改",
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
          any("Delta" in i.get("title", "") or "达美" in i.get("title", "") for i in intl_ind))
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

    # I9 媒体财报/普通媒体经营稿不能成为披露卡片
    media = {"date": "2026-08-18", "title": "Airline revenue rises after new routes",
             "source": "Skift", "content_type": "earnings", "selection_score": 70}
    routed_media = fn._route_single_item(media, "international", "industry_news")
    check("I9 普通媒体财务报道不进入官方披露", routed_media == "intl_industry")
    check("I9a 国际披露卡片仅来自SEC或官方IR",
          all(i.get("source") == "SEC EDGAR" or
              any(k in str(i.get("source", "")) for k in fn.IR_SOURCE_KEYWORDS)
              for i in intl_disc))
    media_cn = {"date": "2026-08-18", "title": "Expedia公布季度营收增长8%",
                "summary": "媒体报道Expedia最新季度经营结果。", "source": "环球旅讯",
                "content_type": "earnings", "entity_id": "EXPE",
                "substantive_company_change": True, "selection_score": 70}
    routed_media_cn = fn._route_single_item(media_cn, "domestic", "china_industry")
    check("I9b 国内媒体财报报道不进入官方披露", routed_media_cn == "intl_core_company")
    sale = {"date": "2026-08-29", "title": "Expedia insider sells 2,000 shares",
            "summary": "A disclosed insider transaction.", "source": "Travel Weekly",
            "content_type": "management_org", "entity_id": "EXPE",
            "substantive_company_change": False, "selection_score": 60}
    check("I9c 媒体高管售股事实进入国际行业而非核心动态",
          fn._route_single_item(sale, "international", "industry_news") == "intl_industry")
    stock_fact = {"date": "2026-08-29", "title": "Expedia该股表现优于竞争对手",
                  "summary": "报道当日股价表现。", "source": "MarketWatch",
                  "content_type": "earnings", "entity_id": "EXPE",
                  "substantive_company_change": True, "selection_score": 60}
    check("I9d 人工保留的股价事实只进国际行业",
          fn._route_single_item(stock_fact, "international", "industry_news") == "intl_industry")
    sec_144 = {"date": "2026-08-29", "title": "证券出售登记 (Rule 144)",
               "summary": "某董事拟出售10,000股。", "source": "SEC EDGAR",
               "type": "144", "company": "ABNB"}
    check("I9e SEC Rule 144优先进披露而非国际行业",
          fn._route_single_item(sec_144, "international", "sec_filings") == "intl_disclosures")

    # I10 核心公司同一AI重组事件7天内折叠
    core_dupes = []
    for date, title, source in [
        ("2026-08-26", "Expedia Cuts Eight Executives as AI Reshapes Its Travel Business", "Expedia"),
        ("2026-08-23", "Expedia Cuts Eight Tech Leaders in AI-Driven Reorganization", "Expedia"),
        ("2026-08-21", "Expedia Group makes AI-motivated leadership cuts", "PhocusWire"),
        ("2026-08-20", "Expedia reorganizes around AI and cuts eight executives", "Skift"),
    ]:
        item = {"date": date, "title": title, "summary": title, "source": source,
                "entity_id": "EXPE", "content_type": "management_org",
                "selection_score": 75, "substantive_company_change": True}
        core_dupes.append(item)
    folded = fn.group_core_company_events(core_dupes)
    check("I10 EXPE同一AI重组事件7天内只留一张卡片",
          len([x for x in folded if not x.get("folded_into")]) == 1)

    # I11: official IR acquisition must return its accumulated records to the
    # caller.  A historical `return 0` made all three successful fetches vanish.
    ir_feed = {"GetPressReleaseListResult": [{
        "PressReleaseDate": "08/26/2026 09:00:00",
        "Headline": "Company launches product",
        "LinkToDetailPage": "/news/news-details/2026/product/default.aspx",
        "ShortDescription": "Official product release",
    }]}
    with mock.patch.object(fn, "safe_request", return_value=copy.deepcopy(ir_feed)), \
         mock.patch.object(fn.time, "sleep", return_value=None):
        ir_items = fn.fetch_ir_press_releases()
    check("I11 IR抓取结果返回主管线而非丢弃",
          isinstance(ir_items, list) and len(ir_items) == len(fn.IR_SOURCES) and
          {x.get("entity_id") for x in ir_items} == {"BKNG", "EXPE", "ABNB"})
    check("I11a IR直读Q4官方feed并保留官网URL",
          all(x.get("source_channel") == "ir_official_q4" and
              x.get("url", "").startswith(("https://ir.", "https://investors."))
              for x in ir_items))
    check("I11b IR业绩/投资者活动/战略动作分类",
          fn.classify_ir_release("Airbnb Announces Second Quarter 2026 Results") == "earnings_disclosure" and
          fn.classify_ir_release("Booking Holdings to Present at the Citi TMT Conference") == "investor_event" and
          fn.classify_ir_release("Expedia Group acquires Layla, accelerating its AI strategy") == "core_action")
    ir_earnings = {"source": "Airbnb IR", "entity_id": "ABNB",
                   "ir_release_kind": "earnings_disclosure", "content_type": "earnings"}
    ir_event = {"source": "Expedia Group IR", "entity_id": "EXPE",
                "ir_release_kind": "investor_event", "content_type": "general"}
    ir_strategy = {"source": "Expedia Group IR", "entity_id": "EXPE",
                   "ir_release_kind": "core_action", "content_type": "ma_investment"}
    check("I11c IR业绩进披露，参会及战略运营进核心动态",
          fn._route_single_item(ir_earnings, "international", "industry_news") == "intl_disclosures" and
          fn._route_single_item(ir_event, "international", "industry_news") == "intl_core_company" and
          fn._route_single_item(ir_strategy, "international", "industry_news") == "intl_core_company")

    authority_items = [
        {"date": "2026-08-26", "title": "Expedia Group将参加高盛Communacopia大会",
         "summary": "", "url": "https://ir.expediagroup.com/event", "source": "Expedia Group IR",
         "entity_id": "EXPE", "ir_release_kind": "investor_event", "selection_score": 60},
        {"date": "2026-08-27", "title": "Expedia Group参加高盛Communacopia大会",
         "summary": "Bloomberg detailed report", "url": "https://bloomberg.example/event", "source": "Bloomberg",
         "entity_id": "EXPE", "selection_score": 80},
        {"date": "2026-08-27", "title": "Expedia出席高盛Communacopia大会",
         "summary": "Skift report", "url": "https://skift.example/event", "source": "Skift",
         "entity_id": "EXPE", "selection_score": 80},
        {"date": "2026-08-27", "title": "Expedia出席高盛Communacopia大会",
         "summary": "环球旅讯转载", "url": "https://traveldaily.example/event", "source": "环球旅讯",
         "entity_id": "EXPE", "selection_score": 80},
    ]
    fn.group_core_company_events(authority_items)
    authority_primary = [x for x in authority_items if not x.get("folded_into")]
    check("I11c2 同事件优先官方IR而非较新或摘要更长的媒体稿",
          len(authority_primary) == 1 and authority_primary[0].get("source") == "Expedia Group IR")
    check("I11c3 来源权威度顺序为IR > Bloomberg > Skift > 环球旅讯",
          fn._source_rank(authority_items[0]) > fn._source_rank(authority_items[1]) >
          fn._source_rank(authority_items[2]) > fn._source_rank(authority_items[3]))

    old_date = (datetime.date.today() - datetime.timedelta(days=15)).isoformat()
    recent_date = (datetime.date.today() - datetime.timedelta(days=14)).isoformat()
    retention_fixture = {"international": {"sec_filings": [
        {"date": old_date, "type": "10-Q", "company": "BKNG", "source": "SEC EDGAR",
         "title": "季度报告", "url": "https://sec.example/old"},
        {"date": recent_date, "type": "144", "company": "ABNB", "source": "SEC EDGAR",
         "title": "Rule 144", "url": "https://sec.example/recent"},
    ], "industry_news": []}, "domestic": {}}
    fn.route_to_modules(retention_fixture)
    retained_disclosures = retention_fixture["modules"]["intl_disclosures"]
    check("I11d 披露统一14天保留期",
          len(retained_disclosures) == 1 and retained_disclosures[0].get("type") == "144")

    same_accession = "000196430626000389"
    sec_duplicates = [
        {"accession": "0001964306-26-000389", "url":
         f"https://www.sec.gov/Archives/edgar/data/1075531/{same_accession}/",
         "summary": "目录摘要"},
        {"url": f"https://www.sec.gov/Archives/edgar/data/1075531/{same_accession}/xsl144X01/primary_doc.xml",
         "summary": "具体申报人、数量与计划出售日期摘要", "sec_summary_kind": "document_detail"},
    ]
    sec_deduped = fn.dedupe_sec_accessions(sec_duplicates)
    check("I11e SEC同一accession的目录与正文只留详细版",
          len(sec_deduped) == 1 and sec_deduped[0].get("sec_summary_kind") == "document_detail")

    ir_fixture_today = datetime.date.today()
    multi_company_ir = [
        {"date": (ir_fixture_today - datetime.timedelta(days=1)).isoformat(),
         "title": "Expedia Group to Participate in Goldman Sachs Communacopia Conference",
         "url": "https://ir.expedia/a", "source": "Expedia Group IR", "entity_id": "EXPE"},
        {"date": (ir_fixture_today - datetime.timedelta(days=2)).isoformat(),
         "title": "Airbnb to Participate in Goldman Sachs Communacopia Conference",
         "url": "https://investors.airbnb/b", "source": "Airbnb IR", "entity_id": "ABNB"},
    ]
    fn.group_same_events(multi_company_ir)
    check("I11f 同一大会的不同公司IR公告不跨公司折叠",
          all(not x.get("folded_into") for x in multi_company_ir))
    for item in multi_company_ir:
        item.update({"event_id": "legacy_shared_event", "is_ir_source": True,
                     "ir_release_kind": "investor_event", "display_ready": True,
                     "selection_status": "kept"})
    routed_ir = {"international": {"sec_filings": [], "industry_news": multi_company_ir},
                 "domestic": {}}
    fn.route_to_modules(routed_ir)
    check("I11f2 旧缓存共享event_id也不会折叠不同公司IR",
          len(routed_ir["modules"]["intl_core_company"]) == 2)

    ir_display_fixture = {"international": {"industry_news": [{
        "title": "Booking Holdings Inc. to Present at the Citi 2026 Global TMT Conference",
        "summary": "Booking Holdings announced that its CEO will participate in the conference.",
        "source": "Booking Holdings IR", "entity_id": "BKNG", "is_ir_source": True,
        "ir_release_kind": "investor_event",
    }]}, "domestic": {}}
    fn.prepare_chinese_news_display(ir_display_fixture)
    ir_display = ir_display_fixture["international"]["industry_news"][0]
    check("I11g IR翻译端点失败时仍有中文标题与摘要",
          ir_display.get("display_ready") is True and
          re.search(r"[\u4e00-\u9fff]", ir_display.get("title", "")) and
          re.search(r"[\u4e00-\u9fff]", ir_display.get("summary", "")))

    noise_cases = [
        ("How Expedia's fifth straight beat will impact Expedia investors", "股价/估值评论"),
        ("Heartland Bank & Trust Co Acquires Shares of Expedia Group EXPE", "被动机构持仓变动"),
        ("Beyond Border appoints former Airbnb executives as advisors", "前高管在第三方公司履新"),
        ("Agency Appointed Global Creative Agency of Record for Booking.com", "品牌营销代理宣传"),
    ]
    for idx, (title, expected_reason) in enumerate(noise_cases, 1):
        candidate = {"date": "2026-08-28", "title": title, "summary": title,
                     "source": "Google News", "category": "industry_news"}
        ok, reason = fn.select_news_item(candidate, "international", "industry_news")
        check(f"I12.{idx} 核心定向源噪音不进核心动态", not ok and reason == expected_reason)

    regulation = {"date": "2026-08-20",
                  "title": "Airbnb crackdown: Penang introduces new licensing laws for short-term rentals",
                  "summary": "Government licensing rules affect short-term rentals.",
                  "source": "Yahoo", "entity_id": "ABNB", "content_type": "product",
                  "substantive_company_change": True, "selection_score": 60}
    check("I13 外部监管行动进国际行业而非核心公司",
          fn._route_single_item(regulation, "international", "industry_news") == "intl_industry")

    portal_dupes = [
        {"date": "2026-08-18", "title": "Agoda launches refreshed Partner Portal for accommodation partners",
         "summary": "Agoda launches a refreshed partner portal.", "source": "TTG Asia",
         "entity_id": "BKNG", "content_type": "product", "selection_score": 70},
        {"date": "2026-08-16", "title": "Agoda Unveils Agoda Partner Portal as Platform Role Expands",
         "summary": "Agoda unveils the partner portal.", "source": "Yahoo Finance",
         "entity_id": "BKNG", "content_type": "product", "selection_score": 65},
    ]
    portal_folded = fn.group_core_company_events(portal_dupes)
    check("I14 Agoda Partner Portal同事件7天内折叠",
          len([x for x in portal_folded if not x.get("folded_into")]) == 1)

    abnb_fee = {"date": "2026-08-30",
                "title": "Airbnb is testing lower service fees for hosts who bring their own guests",
                "summary": "Airbnb is testing a lower fee policy.", "source": "Skift"}
    fee_kept, _ = fn.select_news_item(abnb_fee, "international", "industry_news")
    check("I15a ABNB测试降低服务费识别为核心公司动作",
          fee_kept and abnb_fee.get("substantive_company_change") and
          fn._route_single_item(abnb_fee, "international", "industry_news") == "intl_core_company")

    expe_cuts = {"date": "2026-08-21",
                 "title": "Expedia Group makes AI-motivated leadership cuts",
                 "summary": "Expedia Group cuts leaders during an AI reorganization.", "source": "PhocusWire"}
    cuts_kept, _ = fn.select_news_item(expe_cuts, "international", "industry_news")
    check("I15b EXPE leadership cuts识别为管理层动作并进核心动态",
          cuts_kept and expe_cuts.get("content_type") == "management_org" and
          fn._route_single_item(expe_cuts, "international", "industry_news") == "intl_core_company")

    display_fixture = {"international": {"industry_news": [
        {"title": "Google’s Agentic Hotel Booking Tool Comes to AI Mode",
         "summary": "English-only summary", "source": "Skift"},
        {"title": "Untranslated future news title", "summary": "English summary", "source": "Skift"},
    ]}, "domestic": {}}
    fn.prepare_chinese_news_display(display_fixture)
    ready, pending = display_fixture["international"]["industry_news"]
    check("I16a 已知重要英文标题有确定性中文展示",
          ready.get("display_ready") is True and "谷歌" in ready.get("title", "") and
          re.search(r"[\u4e00-\u9fff]", ready.get("summary", "")))
    check("I16b 翻译失败标题标记pending且不泄漏英文摘要",
          pending.get("display_ready") is False and pending.get("translation_status") == "pending_summary" and
          pending.get("summary") == "")
    no_summary_fixture = {"international": {"industry_news": [
        {"title": "Expedia集团任命新任首席财务官", "summary": "", "source": "Example"},
    ]}, "domestic": {}}
    fn.prepare_chinese_news_display(no_summary_fixture)
    title_only = no_summary_fixture["international"]["industry_news"][0]
    check("I16c 无公开摘要时留空且不生成标题占位摘要",
          title_only.get("display_ready") is True and title_only.get("summary") == "" and
          not title_only.get("summary_from_title"))
    fallback_fixture = {"international": {"industry_news": [
        {"title": "Expedia集团推出新预订工具", "summary": "English summary failed to translate.",
         "source": "Example"},
    ]}, "domestic": {}}
    fn.prepare_chinese_news_display(fallback_fixture)
    fallback = fallback_fixture["international"]["industry_news"][0]
    check("I16d 摘要翻译失败保留原文待重试且不生成占位摘要",
          fallback.get("display_ready") is True and
          fallback.get("translation_status") == "pending_summary" and
          fallback.get("summary") == "" and
          not fallback.get("summary_from_title") and
          fallback.get("summary_original") == "English summary failed to translate.")

    legacy_fixture = {"international": {"industry_news": [
        {"title": "Expedia集团任命新任首席财务官",
         "summary": "公开信息显示，Expedia集团任命新任首席财务官。",
         "summary_from_title": True, "source": "Example"},
    ]}, "domestic": {}}
    fn.prepare_chinese_news_display(legacy_fixture)
    legacy = legacy_fixture["international"]["industry_news"][0]
    check("I16e 清理缓存中已有的标题占位摘要",
          legacy.get("summary") == "" and not legacy.get("summary_from_title"))

    naming_fixture = {"international": {"industry_news": [
        {"title": "🏨 预订控股公司与Expedia集团扩大合作 🚀",
         "summary": "爱彼迎也参与了此次合作。", "source": "Example"},
    ]}, "domestic": {}}
    fn.prepare_chinese_news_display(naming_fixture)
    named = naming_fixture["international"]["industry_news"][0]
    check("I16f 核心公司名保留英文原名",
          named.get("title") == "Booking Holdings与Expedia Group扩大合作" and
          named.get("summary") == "Airbnb也参与了此次合作。")
    check("I16g 新闻标题清除emoji",
          not fn._EMOJI_RE.search(named.get("title", "")))

    protected_calls = []
    old_chunk = fn._translate_chunk
    try:
        fn._translate_chunk = lambda text: protected_calls.append(text) or "ZXQBKNGQXZ宣布与ZXQABNBQXZ合作"
        protected_translation = fn.translate_text(
            "Booking Holdings announces a partnership with Airbnb.")
    finally:
        fn._translate_chunk = old_chunk
    check("I16h 翻译请求保护公司专名并恢复原名",
          protected_calls and "Booking Holdings" not in protected_calls[0] and
          protected_translation == "Booking Holdings宣布与Airbnb合作")

    mixed_zh = "Agoda与菲律宾旅游部合作推动2026年旅游业增长"
    mixed_calls = []
    old_chunk = fn._translate_chunk
    try:
        fn._translate_chunk = lambda text: mixed_calls.append(text) or text
        mixed_result = fn.translate_text(mixed_zh)
    finally:
        fn._translate_chunk = old_chunk
    check("I16i 已含足够中文的标题不因Agoda被二次翻译",
          mixed_result == mixed_zh and not mixed_calls)

    protected_brands = "Agoda Booking.com Trip.com Klook Skyscanner MakeMyTrip Traveloka"
    protected_value = fn._protect_company_names(protected_brands)
    check("I16j OTA品牌全部纳入专名保护并可恢复",
          not any(x in protected_value for x in protected_brands.split()) and
          fn.normalize_company_names(protected_value) == protected_brands)

    bad_original = "Agoda partners with the Philippines Department of Tourism"
    bad_key = __import__('hashlib').md5(bad_original.encode()).hexdigest()
    fn.TRANSLATE_CACHE[bad_key] = "安可达与菲律宾旅游部合作"
    old_chunk = fn._translate_chunk
    try:
        fn._translate_chunk = lambda text: None
        rejected_cache_result = fn.translate_text(bad_original)
    finally:
        fn._translate_chunk = old_chunk
        fn.TRANSLATE_CACHE.pop(bad_key, None)
    check("I16k 品牌不一致的异常译文不得从缓存返回",
          rejected_cache_result == bad_original and bad_key not in fn.TRANSLATE_CACHE)


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
    try:
        os.unlink(TEST_TRANSLATION_CACHE_PATH)
    except OSError:
        pass
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
