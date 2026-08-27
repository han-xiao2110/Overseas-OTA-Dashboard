#!/usr/bin/env python3
"""
fetch_bloomberg_副本.py - 使用 Playwright 爬取 Bloomberg 新闻
通过浏览器内置的 Bypass Paywalls 能力绕过付费墙

输出: bloomberg_news_副本.json
"""

import json
import os
import sys
import re
import time
import datetime

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
OUTPUT = os.path.join(SCRIPT_DIR, "bloomberg_news_副本.json")

# Bloomberg 新闻页面 (不依赖 RSS, 直接爬取页面)
BLOOMBERG_SECTIONS = [
    {
        "name": "Bloomberg Travel/Mobility",
        "url": "https://www.bloomberg.com/mobility",
        "category": "industry_news",
    },
    {
        "name": "Bloomberg Technology",
        "url": "https://www.bloomberg.com/technology",
        "category": "industry_news",
    },
    {
        "name": "Bloomberg Markets",
        "url": "https://www.bloomberg.com/markets",
        "category": "industry_news",
    },
]

# 旅游/OTA 相关关键词 (用于在 Bloomberg 页面中筛选)
TRAVEL_KEYWORDS = [
    'travel', 'tourism', 'hotel', 'airline', 'flight', 'airport',
    'booking', 'expedia', 'airbnb', 'tripadvisor', 'skyscanner',
    'vacation', 'trip', 'mobility', 'ride-hailing', 'robotaxi',
    'autonomous', 'self-driving', 'uber', 'lyft',
    'hospitality', 'lodging', 'resort',
    'cross-border', 'overseas',
]


def fetch_bloomberg_with_playwright():
    """使用 Playwright 爬取 Bloomberg 新闻标题和链接。"""
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        print("Playwright not installed. Run: pip3 install playwright && python3 -m playwright install chromium")
        return []

    all_articles = []

    with sync_playwright() as p:
        # 启动 Chromium (headless 模式)
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(
            user_agent="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            viewport={"width": 1920, "height": 1080},
        )
        page = context.new_page()

        for section in BLOOMBERG_SECTIONS:
            print(f"  Fetching Bloomberg section: {section['name']}...")
            try:
                page.goto(section['url'], timeout=20000)
                page.wait_for_timeout(3000)

                # 提取所有文章链接
                articles = page.evaluate("""
                    () => {
                        const results = [];
                        const links = document.querySelectorAll('a[href*="/news/articles/"]');
                        const seen = new Set();

                        links.forEach(link => {
                            const href = link.getAttribute('href') || '';
                            // 规范化 URL
                            let url = href;
                            if (url.startsWith('/')) {
                                url = 'https://www.bloomberg.com' + url;
                            }
                            // 移除追踪参数
                            url = url.split('?')[0];

                            if (seen.has(url)) return;
                            seen.add(url);

                            const title = link.textContent.trim();
                            if (title && title.length > 5) {
                                results.push({
                                    title: title,
                                    url: url,
                                });
                            }
                        });

                        return results.slice(0, 30);
                    }
                """)

                for article in articles:
                    title = article['title']
                    url = article['url']

                    # 检查是否与旅游/OTA 相关
                    title_lower = title.lower()
                    is_travel_related = any(kw in title_lower for kw in TRAVEL_KEYWORDS)

                    # 尝试从 URL 解析日期
                    date_match = re.search(r'/(\d{4}-\d{2}-\d{2})/', url)
                    if date_match:
                        article_date = date_match.group(1)
                    else:
                        article_date = datetime.date.today().isoformat()

                    all_articles.append({
                        "date": article_date,
                        "source": f"Bloomberg ({section['name'].split(' ')[-1]})",
                        "category": section["category"],
                        "title": title,
                        "url": url,
                        "summary": "",
                        "paywall": True,
                        "travel_related": is_travel_related,
                    })

                print(f"    Found {len(articles)} articles, {sum(1 for a in articles if any(kw in a['title'].lower() for kw in TRAVEL_KEYWORDS))} travel-related")

            except Exception as e:
                print(f"    Error fetching {section['name']}: {e}")
                continue

            time.sleep(1)

        browser.close()

    # 去重 (按 URL)
    seen_urls = set()
    unique_articles = []
    for article in all_articles:
        if article['url'] not in seen_urls:
            seen_urls.add(article['url'])
            unique_articles.append(article)

    # 排序: 旅游相关的优先, 然后按日期
    unique_articles.sort(key=lambda x: (not x['travel_related'], x['date']), reverse=False)
    unique_articles.sort(key=lambda x: x['date'], reverse=True)

    # 移除辅助字段
    for article in unique_articles:
        del article['travel_related']

    return unique_articles


def main():
    print("=" * 60)
    print("Bloomberg News Fetcher (Playwright)")
    print("=" * 60)

    articles = fetch_bloomberg_with_playwright()

    if articles:
        # 保存到 JSON
        with open(OUTPUT, 'w', encoding='utf-8') as f:
            json.dump(articles, f, ensure_ascii=False, indent=2)

        print(f"\n✓ Saved {len(articles)} articles to {OUTPUT}")

        # 显示预览
        travel_count = sum(1 for a in articles if any(kw in a['title'].lower() for kw in TRAVEL_KEYWORDS))
        print(f"  Travel-related: {travel_count}/{len(articles)}")
        print(f"\n  Top articles:")
        for a in articles[:5]:
            print(f"    [{a['date']}] {a['title'][:70]}")
            print(f"    {a['url']}")
    else:
        print("No articles found.")

    return 0


if __name__ == "__main__":
    sys.exit(main())
