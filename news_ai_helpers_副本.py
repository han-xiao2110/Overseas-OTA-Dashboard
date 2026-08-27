#!/usr/bin/env python3
"""
news_ai_helpers_副本.py - AI 增强新闻处理模块
功能: AI 摘要生成、同事件语义去重、重点标记、GPT 翻译、AI 分层分类

支持多种 AI 提供商:
  - 阿里云 DashScope (默认): DASHSCOPE_API_KEY
  - OpenRouter: OPENROUTER_API_KEY
  - Groq: GROQ_API_KEY
  - 通用兼容: AI_API_KEY + AI_BASE_URL (如 https://api.deepseek.com)

当无 API Key 时, 自动降级为启发式规则模式 (仍可提升质量)。
"""

import json
import os
import re
import time
import hashlib
import urllib.request
import urllib.parse
import urllib.error
from collections import defaultdict

# ── 配置 ──

AI_API_KEY = os.environ.get("AI_API_KEY", "")
AI_PROVIDER = os.environ.get("AI_PROVIDER", "dashscope")

# 提供商配置: base_url + model
AI_PROVIDERS = {
    "dashscope": {
        "base": "https://dashscope.aliyuncs.com/api/v1/services/aigc/text-generation/generation",
        "model": "qwen-turbo",
        "key_env": "DASHSCOPE_API_KEY",
    },
    "openrouter": {
        "base": "https://openrouter.ai/api/v1/chat/completions",
        "model": "qwen/qwen-turbo",
        "key_env": "OPENROUTER_API_KEY",
    },
    "groq": {
        "base": "https://api.groq.com/openapi/v1/chat/completions",
        "model": "llama-3.1-8b-instant",
        "key_env": "GROQ_API_KEY",
    },
    "deepseek": {
        "base": "https://api.deepseek.com/v1/chat/completions",
        "model": "deepseek-chat",
        "key_env": "DEEPSEEK_API_KEY",
    },
}

# 付费墙源列表: 仅展示标题和链接, 不生成摘要
# （改造项③, 2026-08-18）Bloomberg 系全部移除 —— 我们只消费其公开 RSS/索引标题+摘要片段,
# 片段本身是发行方主动公开的营销摘要, 不属于绕过付费墙; 摘要状态按
# summary_status 标注（见 fetch_news backfill_summary_fields）。
# 保留 WSJ/FT/Reuters: 这些源我们没有任何公开片段输入渠道, 仅标题呈现。
PAYWALL_SOURCES = {
    "Wall Street Journal", "WSJ", "Financial Times", "FT",
    "Reuters",
}

# 缓存目录
CACHE_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".ai_cache")

# 内存缓存 (避免重复调用)
_SUMMARY_CACHE = {}
_TRANSLATE_CACHE = {}
_CATEGORY_CACHE = {}

# ── HTTP 工具 ──

def _call_ai(system_prompt, user_prompt, temperature=0.3, max_tokens=500):
    """统一 AI 调用入口, 支持多提供商。"""
    # 确定使用的提供商
    provider = AI_PROVIDER
    key = AI_API_KEY or os.environ.get(AI_PROVIDERS[provider]["key_env"], "")
    
    if not key:
        return None  # 无 key, 降级
    
    cfg = AI_PROVIDERS.get(provider, AI_PROVIDERS["dashscope"])
    url = cfg["base"]
    model = cfg["model"]
    
    try:
        if provider == "dashscope":
            # DashScope 格式
            payload = {
                "model": model,
                "input": {
                    "messages": [
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": user_prompt},
                    ]
                },
                "parameters": {
                    "result_format": "message",
                    "temperature": temperature,
                    "max_tokens": max_tokens,
                },
            }
            data = json.dumps(payload).encode("utf-8")
            req = urllib.request.Request(
                url,
                data=data,
                headers={
                    "Authorization": f"Bearer {key}",
                    "Content-Type": "application/json",
                },
            )
            with urllib.request.urlopen(req, timeout=15) as resp:
                result = json.loads(resp.read().decode("utf-8"))
                return result.get("output", {}).get("choices", [{}])[0].get("message", {}).get("content", "")
        else:
            # OpenRouter / Groq / DeepSeek 格式
            payload = {
                "model": model,
                "messages": [
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt},
                ],
                "temperature": temperature,
                "max_tokens": max_tokens,
            }
            data = json.dumps(payload).encode("utf-8")
            req = urllib.request.Request(
                url,
                data=data,
                headers={
                    "Authorization": f"Bearer {key}",
                    "Content-Type": "application/json",
                },
            )
            with urllib.request.urlopen(req, timeout=15) as resp:
                result = json.loads(resp.read().decode("utf-8"))
                return result.get("choices", [{}])[0].get("message", {}).get("content", "")
    except Exception as e:
        print(f"  [AI call failed] {provider}: {e}")
        return None


def _ai_available():
    """检查 AI 是否可用。"""
    key = AI_API_KEY or os.environ.get(AI_PROVIDERS.get(AI_PROVIDER, AI_PROVIDERS["dashscope"])["key_env"], "")
    return bool(key)


# ── 1. AI 摘要生成 ──

def ai_generate_summary(title, source="", max_chars=120):
    """为新闻生成 AI 摘要 (中文, 关键信息提炼)。"""
    cache_key = hashlib.md5(f"summary:{title}:{source}".encode()).hexdigest()
    if cache_key in _SUMMARY_CACHE:
        return _SUMMARY_CACHE[cache_key]
    
    # 付费墙源: 不生成摘要
    if any(pw in source for pw in PAYWALL_SOURCES):
        _SUMMARY_CACHE[cache_key] = ""
        return ""
    
    if _ai_available():
        system_prompt = (
            "你是一名金融科技分析师, 请用中文为以下新闻标题生成简洁摘要。"
            "要求: 1) 一句话概括核心信息; 2) 不超过120字; 3) 保留关键数据和公司名; 4) 不要出现'据悉'、'据报道'等不确定表述。"
        )
        user_prompt = f"来源: {source}\n标题: {title}\n\n请生成摘要:"
        result = _call_ai(system_prompt, user_prompt, temperature=0.2, max_tokens=200)
        if result:
            summary = result.strip()
            if len(summary) > max_chars:
                summary = summary[:max_chars] + "..."
            _SUMMARY_CACHE[cache_key] = summary
            return summary
    
    # 降级: 启发式规则
    summary = _heuristic_summary(title)
    _SUMMARY_CACHE[cache_key] = summary
    return summary


def _heuristic_summary(title):
    """基于规则的摘要生成 (无 AI 时的降级方案)。"""
    # 清理标题
    clean = re.sub(r'\s*[-–—]\s*(Bloomberg|Reuters|CNBC|WSJ|FT|Skift|PhocusWire|Travel Weekly|Bloomberg Markets|Bloomberg Technology|Bloomberg Mobility)', '', title)
    clean = clean.strip()
    
    # 如果标题太短, 直接作为摘要
    if len(clean) <= 80:
        return ""  # 短标题不需要摘要
    
    # 提取关键信息: 时间、数字、公司名
    key_entities = re.findall(
        r'(?:\d+(?:\.\d+)?%|\d+(?:\.\d+)?(?:bn|mn|m|k|million|billion|trillion)?|'
        r'(?:Q[1-4]\s?\d{4}|\d{4}年|\d{1,2}月|\d{1,2}日)|'
        r'Airbnb|Booking\.com|Expedia|Skyscanner|Trip\.com|Klook|MakeMyTrip|Traveloka|Tripadvisor|Agoda|'
        r'BKNG|EXPE|ABNB|booking holdings|expedia group)',
        clean, re.IGNORECASE
    )
    
    if key_entities:
        entities_str = ', '.join(key_entities[:5])
        return f"涉及 {entities_str}"
    
    return ""


def ai_summarize_batch(items, max_items=None):
    """批量为新闻列表处理摘要（改造项⑧: 摘要必须基于证据）。

    规则:
    - 付费墙源(WSJ/FT/Reuters): paywall=True, 摘要留空, summary_status=generated（仅标题呈现）
    - 已有摘要(≥10字, 来自 RSS/列表页公开片段): 原样保留 —— 片段即证据
    - 无摘要: 不再从标题编造摘要（旧版启发式"涉及 X, Y"已移除）,
      留空由 fetch_news.backfill_summary_fields 标记 insufficient_evidence,
      前端显示"来源未提供足够公开信息"占位。
    """
    items_to_process = items if max_items is None else items[:max_items]
    evidence_kept = 0
    for item in items_to_process:
        title = item.get("title", "")
        source = item.get("source", "")
        existing_summary = item.get("summary", "")

        # 付费墙源: 标记, 仅标题呈现（不生成/不展示摘要）
        if any(pw in source for pw in PAYWALL_SOURCES):
            item["paywall"] = True
            item["summary"] = ""
            item["summary_status"] = "generated"
            item["summary_generated_at"] = time.strftime("%Y-%m-%d %H:%M:%S")
            continue

        # 已有公开片段 → 保留（证据充分, 后续翻译环节正常处理）
        if existing_summary and len(existing_summary) >= 10:
            evidence_kept += 1
            continue

        # 无证据 → 不编造, 留空待 backfill 标记
        item["summary"] = ""

    print(f"  [AI Summary] {evidence_kept} evidence-backed snippets kept, "
          f"no fabrication for the rest")
    return items


# ── 2. 同事件语义去重 ──

def deduplicate_semantic(items):
    """基于语义的同事件去重: 将描述同一事件的多条新闻合并, 保留最权威来源。"""
    if len(items) <= 1:
        return items
    
    # 第一步: 标题归一化 (去除来源后缀、标点、统一小写)
    normalized_groups = defaultdict(list)
    
    for idx, item in enumerate(items):
        title = item.get("title", "").lower()
        # 去除常见的来源后缀
        title_clean = re.sub(r'\s*[-–—]\s*(bloomberg|reuters|cnbc|wsj|ft|skift|phocuswire|travel weekly|bloomberg markets|bloomberg technology)', '', title)
        # 去除标点和多余空格
        title_clean = re.sub(r'[^\w\s]', '', title_clean)
        title_clean = re.sub(r'\s+', ' ', title_clean).strip()
        
        # 生成 key: 取标题前5个实词
        words = title_clean.split()
        if len(words) >= 3:
            key = ' '.join(sorted(words[:5]))  # 排序以避免词序影响
        else:
            key = title_clean
        
        normalized_groups[key].append((idx, item))
    
    # 第二步: 合并同组, 保留最权威来源
    result = []
    removed_count = 0
    used_indices = set()
    
    for key, group in normalized_groups.items():
        if len(group) == 1:
            idx, item = group[0]
            if idx not in used_indices:
                result.append(item)
                used_indices.add(idx)
        else:
            # 同组内选最佳来源
            best_item = _pick_best_source([g[1] for g in group])
            # 添加"同事件"标签
            best_item["same_event_sources"] = [
                g[1].get("source", "") for g in group 
                if g[1].get("source") != best_item.get("source")
            ]
            result.append(best_item)
            removed_count += len(group) - 1
            for g_idx, _ in group:
                used_indices.add(g_idx)
    
    if removed_count > 0:
        print(f"  [AI Dedupe] Merged {removed_count} duplicate event groups")
    
    return result


def _pick_best_source(items):
    """从同一事件的多个来源中选最权威的。"""
    # 来源权威度排序
    source_rank = {
        "SEC EDGAR": 100,
        "Bloomberg": 90, "Bloomberg Markets": 90, "Bloomberg Technology": 90,
        "Wall Street Journal": 85, "WSJ": 85,
        "Financial Times": 80, "FT": 80,
        "Reuters": 78,
        "CNBC": 75,
        "Skift": 70, "PhocusWire": 70,
        "Travel Weekly": 65,
    }
    
    def rank(item):
        src = item.get("source", "")
        # 精确匹配
        if src in source_rank:
            return source_rank[src]
        # 模糊匹配
        for key, val in source_rank.items():
            if key.lower() in src.lower():
                return val
        return 50  # 默认分
    
    return max(items, key=rank)


def ai_deduplicate_batch(items, batch_size=20):
    """批量语义去重 (分批调用 AI, 最后用启发式补充)。"""
    # 先用启发式去重 (快速、零成本)
    result = deduplicate_semantic(items)
    
    # 再用 AI 检查边界情况 (仅在可用时)
    if _ai_available() and len(result) > batch_size:
        result = _ai_refine_dedupe(result, batch_size)
    
    return result


def _ai_refine_dedupe(items, batch_size):
    """用 AI 进一步去重 (仅处理启发式无法判断的边界情况)。"""
    # 只处理最近 48 小时内的新闻 (更可能重复)
    recent = [i for i in items if _is_recent(i.get("date", ""), days=2)]
    older = [i for i in items if i not in recent]
    
    if len(recent) <= batch_size:
        return items
    
    # 分批用 AI 检查
    refined = []
    for batch_start in range(0, len(recent), batch_size):
        batch = recent[batch_start:batch_start + batch_size]
        batch_titles = [f"{i.get('source', '')}: {i.get('title', '')[:80]}" for i in batch]
        
        system_prompt = (
            "以下是一组新闻标题, 请判断哪些是同一事件的不同报道。"
            "用 JSON 格式返回: {\"groups\": [[0,2], [1,3]], \"keep\": 0, 1}"
            "其中 groups 是同事件的索引对, keep 是每组中建议保留的索引 (选权威来源)。"
        )
        user_prompt = "\n".join(f"[{i}] {t}" for i, t in enumerate(batch_titles))
        
        result = _call_ai(system_prompt, user_prompt, temperature=0.1, max_tokens=1000)
        
        if result:
            try:
                # 尝试解析 JSON
                json_match = re.search(r'\{.*\}', result, re.DOTALL)
                if json_match:
                    parsed = json.loads(json_match.group())
                    keep_indices = set()
                    for group in parsed.get("groups", []):
                        keep_idx = parsed.get("keep", group[0] if group else 0)
                        if keep_idx < len(batch):
                            keep_indices.add(keep_idx)
                    if not keep_indices:
                        keep_indices = set(range(len(batch)))
                    refined.extend([batch[i] for i in keep_indices])
                else:
                    refined.extend(batch)
            except (json.JSONDecodeError, IndexError):
                refined.extend(batch)
        else:
            refined.extend(batch)
        
        time.sleep(0.3)
    
    return older + refined


def _is_recent(date_str, days=2):
    """检查日期是否在最近 N 天内。"""
    try:
        from datetime import datetime, date, timedelta
        dt = datetime.strptime(date_str, "%Y-%m-%d")
        return (date.today() - dt.date()).days <= days
    except (ValueError, TypeError):
        return True  # 日期无法解析视为近期


# ── 3. 重点标记 ──

def mark_featured(items, max_featured=5):
    """标记重点新闻 (AI 或启发式判断)。"""
    if not items:
        return items
    
    scored_items = []
    
    for item in items:
        score = _compute_importance_score(item)
        item["importance_score"] = score
        scored_items.append(item)
    
    # 按分数排序
    scored_items.sort(key=lambda x: x.get("importance_score", 0), reverse=True)
    
    # 标记前 N 条为重点
    for i, item in enumerate(scored_items):
        item["featured"] = i < max_featured
        if item["featured"]:
            item["featured_label"] = _featured_label(item)
    
    # 移除辅助字段
    for item in scored_items:
        if "importance_score" in item:
            del item["importance_score"]
    
    featured_count = sum(1 for i in scored_items if i.get("featured"))
    print(f"  [AI Featured] Marked {featured_count} items as featured")
    
    return scored_items


def _compute_importance_score(item):
    """计算新闻重要性分数 (0-100)。"""
    score = 0.0
    title = item.get("title", "").lower()
    summary = item.get("summary", "").lower()
    text = f"{title} {summary}"
    source = item.get("source", "")
    
    # 1. 来源权威度 (0-30)
    source_scores = {
        "SEC EDGAR": 30,
        "Bloomberg": 25, "Bloomberg Markets": 25, "Bloomberg Technology": 25,
        "Wall Street Journal": 22, "WSJ": 22,
        "Financial Times": 20, "FT": 20,
        "Reuters": 18,
        "CNBC": 15,
        "Skift": 12, "PhocusWire": 12,
        "Travel Weekly": 10,
    }
    for src, val in source_scores.items():
        if src.lower() in source.lower():
            score += val
            break
    else:
        score += 5
    
    # 2. 公司重要性 (0-20)
    company = item.get("company", "")
    if company in ("BKNG", "Booking Holdings"):
        score += 20  # Booking 市值最大, 影响最大
    elif company in ("EXPE", "Expedia Group"):
        score += 15
    elif company in ("ABNB", "Airbnb"):
        score += 12
    
    # 3. 内容关键词 (0-25)
    high_impact = [
        "earnings", "revenue", "profit", "loss", "guidance", "forecast",
        "acquisition", "merger", "ipo", "delisting",
        "bankruptcy", "default", "downgrade", "upgrade",
        "ceo", "cfo", "executive", "leadership",
        "regulatory", "lawsuit", "investigation", "fraud",
        "privatization", "buyout", "takeover",
    ]
    medium_impact = [
        "expansion", "partnership", "launch", "rollout",
        "technology", "ai", "automation", "robotics",
        "travel demand", "recovery", "growth", "record",
        "quarterly", "annual", "results", "performance",
    ]
    
    for kw in high_impact:
        if kw in text:
            score += 8
            break
    for kw in medium_impact:
        if kw in text:
            score += 4
            break
    
    # 4. 时效性 (0-15)
    date_str = item.get("date", "")
    days_old = _days_old(date_str)
    if days_old is not None:
        if days_old == 0:
            score += 15  # 今天
        elif days_old <= 1:
            score += 12
        elif days_old <= 3:
            score += 8
        elif days_old <= 7:
            score += 4
    
    # 5. 数据密度 (0-10)
    numbers = re.findall(r'\d+(?:\.\d+)?%?', text)
    if len(numbers) >= 3:
        score += 10  # 包含较多数据
    elif len(numbers) >= 1:
        score += 5
    
    # 6. AI 判断 (可选, +0-20)
    if _ai_available() and score >= 30:  # 只对高分候选做 AI 微调
        ai_score = _ai_importance_score(item)
        if ai_score is not None:
            score = score * 0.7 + ai_score * 0.3  # 融合
        
    return min(score, 100)


def _ai_importance_score(item):
    """AI 微调重要性分数。"""
    title = item.get("title", "")
    summary = item.get("summary", "")
    source = item.get("source", "")
    company = item.get("company", "")
    
    system_prompt = "你是一名资深股票分析师, 请评估以下新闻对 OTA 行业 (BKNG/EXPE/ABNB) 投资者的重要性。"
    user_prompt = f"来源: {source}\n公司: {company}\n标题: {title}\n摘要: {summary}\n\n请给出 0-100 的重要性评分, 仅输出数字:"
    
    result = _call_ai(system_prompt, user_prompt, temperature=0.1, max_tokens=10)
    if result:
        try:
            score = float(result.strip().replace("%", ""))
            return max(0, min(100, score))
        except ValueError:
            pass
    return None


def _featured_label(item):
    """为重点新闻生成标签。"""
    company = item.get("company", "")
    text = f"{item.get('title', '')} {item.get('summary', '')}".lower()
    
    if company in ("BKNG", "Booking Holdings"):
        return "Booking 重点"
    elif company in ("EXPE", "Expedia Group"):
        return "Expedia 重点"
    elif company in ("ABNB", "Airbnb"):
        return "Airbnb 重点"
    
    if any(kw in text for kw in ["earnings", "revenue", "quarterly", "annual"]):
        return "业绩重点"
    elif any(kw in text for kw in ["acquisition", "merger", "buyout"]):
        return "并购重点"
    elif any(kw in text for kw in ["regulatory", "lawsuit", "investigation"]):
        return "监管重点"
    elif any(kw in text for kw in ["ai", "automation", "technology"]):
        return "技术重点"
    
    return "行业重点"


def _days_old(date_str):
    """计算距今天数。"""
    try:
        from datetime import datetime, date
        dt = datetime.strptime(date_str, "%Y-%m-%d")
        return (date.today() - dt.date()).days
    except (ValueError, TypeError):
        return None


def ai_mark_featured_batch(items, max_featured_per_category=3):
    """按类别分别标记重点。"""
    by_category = defaultdict(list)
    for item in items:
        cat = item.get("category", "general")
        by_category[cat].append(item)
    
    result = []
    for cat, cat_items in by_category.items():
        marked = mark_featured(cat_items, max_featured=max_featured_per_category)
        result.extend(marked)
    
    return result


# ── 4. GPT 翻译 (替换 Google Translate) ──

GLOSSARY = {
    "take rate": "抽成率",
    "gross bookings": "总预订额",
    "room nights": "间夜量",
    "ADR": "日均房价",
    "RevPAR": "每间可售房收入",
    "occupancy rate": "入住率",
    "vacation rental": "假期租赁",
    "short-term rental": "短租",
    "peer-to-peer": "点对点",
    "marketplace": "市场平台",
    "two-sided": "双边市场",
    "network effect": "网络效应",
    "unit economics": "单位经济模型",
    "CAC": "客户获取成本",
    "LTV": "生命周期价值",
    "gross margin": "毛利率",
    "operating margin": "营业利润率",
    "net income": "净利润",
    "EBITDA": "EBITDA (息税折旧摊销前利润)",
    "guidance": "业绩指引",
    "forecast": "业绩预测",
    "outlook": "前景展望",
    "sec filing": "SEC 文件",
    "8-K": "8-K 重大事件报告",
    "10-Q": "10-Q 季度报告",
    "10-K": "10-K 年度报告",
    "Form 4": "Form 4 董事/高管交易",
    "institutional investor": "机构投资者",
    "retail investor": "散户投资者",
    "analyst rating": "分析师评级",
    "price target": "目标价",
    "overweight": "增持",
    "underweight": "减持",
    "neutral": "中性",
    "outperform": "跑赢大盘",
    "underperform": "跑输大盘",
    "buy": "买入",
    "sell": "卖出",
    "hold": "持有",
}


def ai_translate_text(text, source_lang="en", target_lang="zh-CN"):
    """用 AI 翻译文本 (支持术语表)。"""
    if not text or not text.strip():
        return text
    
    cache_key = hashlib.md5(f"translate:{source_lang}:{target_lang}:{text[:200]}".encode()).hexdigest()
    if cache_key in _TRANSLATE_CACHE:
        return _TRANSLATE_CACHE[cache_key]
    
    # 无 AI 时直接返回
    if not _ai_available():
        _TRANSLATE_CACHE[cache_key] = text
        return text
    
    # 构建术语表提示
    glossary_hint = "、".join(f"{k}={v}" for k, v in list(GLOSSARY.items())[:15])
    
    system_prompt = (
        f"你是一名金融专业翻译, 将{source_lang}翻译成{target_lang}。"
        f"严格遵循以下术语表: {glossary_hint}。"
        "要求: 1) 保持专业术语准确; 2) 数字和百分比保持原样; 3) 公司名不翻译; 4) 自然流畅。"
    )
    user_prompt = text[:500]  # 限制长度
    
    result = _call_ai(system_prompt, user_prompt, temperature=0.1, max_tokens=500)
    
    if result:
        translated = result.strip()
        _TRANSLATE_CACHE[cache_key] = translated
        return translated
    
    _TRANSLATE_CACHE[cache_key] = text
    return text


def ai_translate_batch(items, source_names=None):
    """批量翻译新闻标题和摘要。"""
    translated = 0
    for item in items:
        source = item.get("source", "")
        if source_names and source not in source_names:
            continue
        
        # 翻译标题
        title = item.get("title", "")
        if title and re.search(r'[a-zA-Z]{2}', title):
            original = title
            item["title_original"] = title
            translated_title = ai_translate_text(title)
            if translated_title != title:
                item["title"] = translated_title
                translated += 1
        
        # 翻译摘要
        summary = item.get("summary", "")
        if summary and re.search(r'[a-zA-Z]{4}', summary):
            item["summary_original"] = summary[:300]
            translated_summary = ai_translate_text(summary[:300])
            if translated_summary:
                item["summary"] = translated_summary
    
    if translated > 0:
        print(f"  [AI Translate] Translated {translated} items")
    return items


# ── 5. AI 分层分类 ──

CATEGORY_LABELS = {
    "company_news": "公司新闻",
    "industry_trend": "行业趋势",
    "regulatory_policy": "监管政策",
    "macro_economy": "宏观经济",
    "competitive_dynamic": "竞争动态",
    "technology": "科技创新",
    "investment": "投资动态",
}


def ai_categorize_item(item):
    """用 AI 为单条新闻进行分层分类。"""
    title = item.get("title", "")
    summary = item.get("summary", "")
    source = item.get("source", "")
    company = item.get("company", "")
    
    cache_key = hashlib.md5(f"categorize:{title}:{source}".encode()).hexdigest()
    if cache_key in _CATEGORY_CACHE:
        cat = _CATEGORY_CACHE[cache_key]
        item["ai_category"] = cat
        return item
    
    category = _heuristic_categorize(title, summary, source, company)
    
    # 如果 AI 可用且启发式结果不确定, 用 AI 确认
    if _ai_available() and category == "industry_trend":  # 最常见的不确定类别
        result = _ai_categorize(title, summary, source, company)
        if result:
            category = result
    
    _CATEGORY_CACHE[cache_key] = category
    item["ai_category"] = category
    item["ai_category_label"] = CATEGORY_LABELS.get(category, category)
    return item


def _heuristic_categorize(title, summary, source, company):
    """启发式分类 (无 AI 时的降级)。"""
    text = f"{title} {summary}".lower()
    
    # 公司新闻: 指定公司或 ticker
    if company:
        return "company_news"
    if any(t in text for t in ["bkng", "expe", "abnb", "booking holdings", "expedia group", "airbnb"]):
        return "company_news"
    
    # 监管政策
    if any(kw in text for kw in [
        "regulation", "regulatory", "lawsuit", "investigation", "compliance",
        "privacy", "gdpr", "data protection", "consumer protection",
        "antitrust", "competition law", "licensing", "permit",
    ]):
        return "regulatory_policy"
    
    # 宏观经济
    if any(kw in text for kw in [
        "gdp", "inflation", "interest rate", "fed", "federal reserve",
        "recession", "economic", "economy", "consumer spending",
        "currency", "exchange rate", "forex",
    ]):
        return "macro_economy"
    
    # 竞争动态
    if any(kw in text for kw in [
        "competitor", "competition", "rival", "market share",
        "pricing", "price war", "discount", "promotion",
        "launch", "new product", "feature", "update",
    ]):
        return "competitive_dynamic"
    
    # 科技创新
    if any(kw in text for kw in [
        "artificial intelligence", "ai ", "machine learning", "automation",
        "blockchain", "crypto", "virtual reality", "vr", "augmented reality",
        "robot", "drone", "autonomous",
    ]):
        return "technology"
    
    # 投资动态
    if any(kw in text for kw in [
        "investment", "investor", "funding", "venture capital", "vc",
        "ipo", "acquisition", "merger", "buyout", "takeover",
        "stock", "share", "equity", "bond", "debt",
    ]):
        return "investment"
    
    # 默认: 行业趋势
    return "industry_trend"


def _ai_categorize(title, summary, source, company):
    """AI 分类 (仅在启发式不确定时调用)。"""
    system_prompt = (
        "你是一名行业分析师, 请将新闻分类到以下类别之一:\n"
        "company_news (公司新闻), industry_trend (行业趋势), "
        "regulatory_policy (监管政策), macro_economy (宏观经济), "
        "competitive_dynamic (竞争动态), technology (科技创新), investment (投资动态)\n"
        "仅输出类别代码 (英文)。"
    )
    user_prompt = f"来源: {source}\n公司: {company or '无'}\n标题: {title}\n摘要: {summary}\n\n类别:"
    
    result = _call_ai(system_prompt, user_prompt, temperature=0.0, max_tokens=20)
    if result:
        cat = result.strip().lower()
        valid_cats = set(CATEGORY_LABELS.keys())
        # 提取有效类别
        for valid in valid_cats:
            if valid in cat:
                return valid
    return None


def ai_categorize_batch(items):
    """批量 AI 分类。"""
    for item in items:
        ai_categorize_item(item)
    
    # 统计
    cat_counts = defaultdict(int)
    for item in items:
        cat_counts[item.get("ai_category", "unknown")] += 1
    print(f"  [AI Category] Distribution: {dict(cat_counts)}")
    
    return items


# ── 6. 付费墙源标记 ──

def mark_paywall_sources(items):
    """标记付费墙源: 仅展示标题和链接, 不生成摘要。"""
    marked = 0
    for item in items:
        source = item.get("source", "")
        is_paywall = any(pw in source for pw in PAYWALL_SOURCES)
        
        if is_paywall:
            item["paywall"] = True
            # 付费墙源: 清空摘要 (如果之前已生成)
            if item.get("summary") and len(item.get("summary", "")) > 50:
                # 保留很短的原始摘要, 但长摘要标记为付费
                item["summary"] = "（付费内容，仅展示标题）"
            marked += 1
        else:
            item["paywall"] = False
    
    if marked > 0:
        print(f"  [Paywall] Marked {marked} items from paywall sources")
    
    return items


# ── 7. 全流程管道 ──

def process_news_pipeline(items, options=None):
    """全流程 AI 新闻处理管道。
    
    Options:
        - summarize: 是否生成摘要 (默认 True)
        - deduplicate: 是否去重 (默认 True)
        - mark_featured: 是否标记重点 (默认 True)
        - translate: 是否 AI 翻译 (默认 True, 仅英文源)
        - categorize: 是否 AI 分类 (默认 True)
        - paywall: 是否标记付费墙 (默认 True)
        - max_items: 每类别最大处理数 (默认 80)
    """
    options = options or {}
    do_summarize = options.get("summarize", True)
    do_deduplicate = options.get("deduplicate", True)
    do_featured = options.get("mark_featured", True)
    do_translate = options.get("translate", True)
    do_categorize = options.get("categorize", True)
    do_paywall = options.get("paywall", True)
    max_items = options.get("max_items", 80)
    
    print(f"\n{'='*50}")
    print(f"AI News Pipeline: {len(items)} items")
    print(f"AI Provider: {AI_PROVIDER} ({'available' if _ai_available() else 'fallback'})")
    print(f"{'='*50}")
    
    if not items:
        return items
    
    # 限制处理数量
    items = items[:max_items]
    
    # Step 1: 付费墙标记 (最先执行, 影响后续步骤)
    if do_paywall:
        print("\n[Step 1] Marking paywall sources...")
        items = mark_paywall_sources(items)
    
    # Step 2: AI 摘要
    if do_summarize:
        print("\n[Step 2] Generating AI summaries...")
        items = ai_summarize_batch(items)
    
    # Step 3: AI 语义去重
    if do_deduplicate:
        print("\n[Step 3] Deduplicating same events...")
        items = ai_deduplicate_batch(items)
    
    # Step 4: AI 翻译
    if do_translate and _ai_available():
        print("\n[Step 4] AI Translating...")
        # 只翻译指定英文源
        eng_sources = {"Skift", "Bloomberg Markets", "Bloomberg Technology", "Bloomberg",
                      "PhocusWire", "Travel Weekly", "Skyscanner", "Klook", "MakeMyTrip",
                      "Traveloka", "Agoda", "Trip.com", "Booking.com", "Expedia", "Airbnb", "Tripadvisor",
                      "Bloomberg Travel (GN)", "Bloomberg Mobility (GN)",
                      "Booking Holdings IR", "Expedia Group IR", "Airbnb IR"}
        items = ai_translate_batch(items, source_names=eng_sources)
    elif do_translate:
        print("\n[Step 4] AI Translate skipped (no API key, using existing translation)")
    
    # Step 5: AI 分层分类
    if do_categorize:
        print("\n[Step 5] AI Categorizing...")
        items = ai_categorize_batch(items)
    
    # Step 6: 重点标记
    if do_featured:
        print("\n[Step 6] Marking featured items...")
        items = ai_mark_featured_batch(items)
    
    # 打印总结
    featured_count = sum(1 for i in items if i.get("featured"))
    paywall_count = sum(1 for i in items if i.get("paywall"))
    print(f"\n{'='*50}")
    print(f"Pipeline complete: {len(items)} items")
    print(f"  Featured: {featured_count}")
    print(f"  Paywall: {paywall_count}")
    print(f"{'='*50}")
    
    return items


# ── 快速模式 (高频更新, 轻量处理) ──

def process_news_fast(items):
    """快速模式: 仅去重 + 重点标记 (用于每2小时的增量更新)。"""
    print("\n[Fast Mode] Lightweight processing...")
    
    if not items:
        return items
    
    # 1. 基础去重 (启发式, 快速)
    items = deduplicate_semantic(items)
    
    # 2. 标记重点 (启发式)
    items = mark_featured(items, max_featured=3)
    
    return items


# ── 使用说明 ──

if __name__ == "__main__":
    print("news_ai_helpers_副本.py - AI News Processing Module")
    print(f"AI Available: {_ai_available()}")
    print(f"AI Provider: {AI_PROVIDER}")
    print(f"Paywall Sources: {len(PAYWALL_SOURCES)} configured")
    print(f"Glossary Terms: {len(GLOSSARY)} configured")
    print("\nUsage:")
    print("  from news_ai_helpers_副本 import process_news_pipeline, process_news_fast")
    print("  result = process_news_pipeline(items)  # 全处理")
    print("  result = process_news_fast(items)      # 快速模式")