#!/usr/bin/env python3
"""
Agent 自动翻译桥接脚本 — 把管道里未翻译的英文新闻交给 agent 直接翻译并写回缓存。

背景（2026-08-18）: 管道原生翻译走 Google 免费接口(translate.googleapis.com)，
国内需代理；每日 5:30 的 QoderWork cron 本身就是 agent 任务，所以翻译环节改由
agent 自己完成：本脚本只做"提取"和"写回"两件机械工作，翻译本身由 agent 填写。

用法:
  python3 agent_translate_副本.py --export              # 提取未翻译条目 → pending_translations.json
  python3 agent_translate_副本.py --apply [file]        # 把填好的 title_zh/summary_zh 写回新闻缓存
                                                         (file 缺省即 pending_translations.json)
  可选 --cache PATH 覆盖缓存路径（测试用）

工作流（cron agent / 手动均适用）:
  1. --export 输出 pending: N；N=0 则无事可做
  2. agent 编辑 pending_translations.json，为每条填 title_zh（必填，须含中文）
     和 summary_zh（原 summary 为英文时填，≤200字）；翻译要求新闻标题风格，
     数字/品牌/公司名保留准确原文
  3. --apply 校验后写回（自动备份到 news_cache_backups/，原子替换），
     之后重建部署: python3 generate_副本.py && cd deploy && npx --yes surge . bkng-expe-abnb-1q26.surge.sh
"""
import datetime
import json
import os
import re
import shutil
import sys

BASE = os.path.dirname(os.path.abspath(__file__))
CACHE = os.path.join(BASE, "news_data_副本.json")
PENDING = os.path.join(BASE, "pending_translations.json")

HAS_CJK = re.compile(r"[\u4e00-\u9fff]")
EN_IN_TITLE = re.compile(r"[A-Za-z]{2}")
EN_IN_SUMMARY = re.compile(r"[A-Za-z]{4}")
# SEC 附件代码（EX-32.1 / EX-99.1 (Item 2.02, ...) 等）不是可翻译文本，管道历来原样保留
SEC_EXHIBIT_CODE = re.compile(r"^\s*EX[-\s]?\d")


def _norm(u):
    return (u or "").strip().rstrip("/")


def load_cache(path):
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def save_cache_with_backup(data, path):
    backup_dir = os.path.join(os.path.dirname(os.path.abspath(path)), "news_cache_backups")
    os.makedirs(backup_dir, exist_ok=True)
    stamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    shutil.copy2(path, os.path.join(backup_dir, f"news_data_{stamp}.json"))
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=1)
    os.replace(tmp, path)


def iter_items(data):
    for section in ("international", "domestic"):
        for cat, items in data.get(section, {}).items():
            if isinstance(items, list):
                for it in items:
                    yield section, cat, it


def cmd_export(cache_path):
    data = load_cache(cache_path)
    pending = []
    for _section, cat, it in iter_items(data):
        url = (it.get("url") or "").strip()
        title = (it.get("title") or "").strip()
        summary = (it.get("summary") or "").strip()
        if not title or not url:
            continue
        if SEC_EXHIBIT_CODE.match(title) and not summary:
            continue
        need_title = bool(EN_IN_TITLE.search(title)) and not HAS_CJK.search(title)
        need_summary = bool(summary) and bool(EN_IN_SUMMARY.search(summary)) and not HAS_CJK.search(summary)
        if need_title or need_summary:
            pending.append({
                "url": url,
                "category": cat,
                "source": it.get("source", ""),
                "title": title,
                "summary": summary[:400],
                "title_zh": "",
                "summary_zh": "",
            })
    with open(PENDING, "w", encoding="utf-8") as f:
        json.dump(pending, f, ensure_ascii=False, indent=1)
    print(f"pending: {len(pending)} -> {os.path.basename(PENDING)}")
    for p in pending[:10]:
        print(f"  - [{p['category']}] {p['title'][:70]}")
    if len(pending) > 10:
        print(f"  ... and {len(pending) - 10} more")
    return len(pending)


def cmd_apply(path, cache_path):
    with open(path, encoding="utf-8") as f:
        pending = json.load(f)
    by_url = {}
    invalid = 0
    for p in pending:
        t = (p.get("title_zh") or "").strip()
        s = (p.get("summary_zh") or "").strip()
        if not t or not HAS_CJK.search(t):
            invalid += 1
            continue
        by_url[_norm(p.get("url"))] = (t, s if s and HAS_CJK.search(s) else None)
    if not by_url:
        print("apply: nothing to do (every entry needs non-empty Chinese title_zh)")
        return 0
    data = load_cache(cache_path)
    applied = 0
    for _section, _cat, it in iter_items(data):
        u = _norm(it.get("url"))
        if u in by_url:
            t, s = by_url[u]
            if it.get("title") and not it.get("title_original"):
                it["title_original"] = it["title"]
            it["title"] = t
            if s:
                if it.get("summary") and not it.get("summary_original"):
                    it["summary_original"] = it["summary"][:200]
                it["summary"] = s[:200]
            applied += 1
    save_cache_with_backup(data, cache_path)
    print(f"applied: {applied}/{len(by_url)} items"
          + (f" ({invalid} invalid entries skipped)" if invalid else "")
          + f" -> {os.path.basename(cache_path)} (backup in news_cache_backups/)")
    return applied


def main():
    args = sys.argv[1:]
    cache_path = CACHE
    if "--cache" in args:
        i = args.index("--cache")
        cache_path = args[i + 1]
    if "--export" in args:
        cmd_export(cache_path)
    elif "--apply" in args:
        i = args.index("--apply")
        path = args[i + 1] if i + 1 < len(args) and not args[i + 1].startswith("--") else PENDING
        cmd_apply(path, cache_path)
    else:
        print(__doc__)


if __name__ == "__main__":
    main()
