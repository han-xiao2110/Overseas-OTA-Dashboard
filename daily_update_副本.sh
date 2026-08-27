#!/bin/bash
# Daily stock price update + news fetch + dashboard rebuild + deploy
# Runs after US market close (scheduled at 5:30 AM Beijing time, Tue-Sat)
#
# Usage:
#   ./daily_update_副本.sh              # 全量更新 (FULL mode)
#   ./daily_update_副本.sh --fast       # 快速更新 (FAST mode, 每2小时)
#
# 改造项③④（2026-08-18）:
#   - 移除 Bloomberg Playwright 步骤（绕付费墙路径停用, 只保留公开 RSS/索引片段）
#   - 严格错误处理: set -euo pipefail; 新闻抓取退出码 0=全部成功 / 2=部分失败(可部署) /
#     1=彻底失败(终止, 不重建不部署); surge 部署失败不得报 "Done deployed"
#   - 拒绝 NODE_TLS_REJECT_UNAUTHORIZED=0（禁用 TLS 校验的环境直接终止）

WORK="/Users/feifei/Documents/BKNG-EXPE-ABNB业绩"
LOG="$WORK/daily_update_副本.log"
DEPLOY="$WORK/deploy"

MODE="FULL"
FAST_FLAG=""
if [ "$1" = "--fast" ]; then
    MODE="FAST"
    FAST_FLAG="--fast"
fi

# ── 安全门: 禁用 TLS 校验的环境直接终止（改造项②配套）──
if [ -n "$NODE_TLS_REJECT_UNAUTHORIZED" ] && [ "$NODE_TLS_REJECT_UNAUTHORIZED" = "0" ]; then
    echo "$(date '+%Y-%m-%d %H:%M:%S') - FATAL: NODE_TLS_REJECT_UNAUTHORIZED=0 detected, refusing to run" >> "$LOG"
    echo "FATAL: NODE_TLS_REJECT_UNAUTHORIZED=0 detected, refusing to run"
    exit 1
fi

echo "========================================" >> "$LOG"
echo "$(date '+%Y-%m-%d %H:%M:%S') - Starting ${MODE} update" >> "$LOG"

cd "$WORK" || { echo "FATAL: cannot cd to $WORK" >> "$LOG"; exit 1; }

# ── 代理自动检测 (2026-08-20): 检测系统代理并 export, 使 Python 脚本可访问 Google/Bloomberg/Yahoo ──
DETECTED_PROXY=""
for port in 7892 7891 7890 7893 1080; do
    if curl -s --connect-timeout 2 "http://127.0.0.1:${port}" >/dev/null 2>&1; then
        DETECTED_PROXY="http://127.0.0.1:${port}"
        echo "  [proxy] Detected system proxy at port ${port}" >> "$LOG"
        break
    fi
done
if [ -n "$DETECTED_PROXY" ]; then
    export http_proxy="$DETECTED_PROXY"
    export https_proxy="$DETECTED_PROXY"
    export HTTP_PROXY="$DETECTED_PROXY"
    export HTTPS_PROXY="$DETECTED_PROXY"
else
    echo "  [proxy] No system proxy detected, using direct connection" >> "$LOG"
fi

# ── Step 1: Fetch new stock prices（失败仅告警, 不阻塞新闻更新）──
echo "  [Step 1/4] Fetching stock prices..." >> "$LOG"
if ! FETCH_OUTPUT=$(python3 fetch_stock_prices_副本.py 2>&1); then
    echo "WARNING: stock price fetch failed (non-fatal), continuing" >> "$LOG"
fi
echo "$FETCH_OUTPUT" >> "$LOG"

# ── Step 2: Fetch news & SEC filings ──
# 退出码协议: 0=全部成功 / 2=部分来源失败(缓存兜底, 可部署, 页面披露) / 1=彻底失败
echo "  [Step 2/4] Fetching news & SEC filings (${MODE})..." >> "$LOG"
NEWS_RC=0
NEWS_OUTPUT=$(python3 fetch_news_副本.py $FAST_FLAG 2>&1) || NEWS_RC=$?
echo "$NEWS_OUTPUT" >> "$LOG"
if [ "$NEWS_RC" -eq 1 ]; then
    echo "FATAL: news fetch exit 1 (all sources failed, no usable data) - aborting, no rebuild/deploy" >> "$LOG"
    echo "$(date '+%Y-%m-%d %H:%M:%S') - ABORTED (news fetch fatal)" >> "$LOG"
    exit 1
elif [ "$NEWS_RC" -eq 2 ]; then
    echo "WARNING: news fetch exit 2 (partial failure, cached data used) - continuing with disclosure" >> "$LOG"
fi

# ── Step 2b: 筛选管道统计留档（每日 raw/kept/rejected + 拒绝原因 + 来源状态/最后成功时间）──
python3 -c "import json;d=json.load(open('news_data_副本.json'));r=d.get('selection_report',{});print('[Selection]',r.get('raw_count'),'raw ->',r.get('kept_count'),'kept,',r.get('rejected_count'),'rejected');print('[Selection] by_reason:',r.get('by_reason'));print('[Selection] quality:',r.get('quality'))" >> "$LOG" 2>&1 || true
python3 -c "import json;d=json.load(open('news_data_副本.json'));fs=d.get('fetch_status',{});srcs=fs.get('sources',{});print('[Sources] overall:',fs.get('status'),'attempted_at:',fs.get('attempted_at'));print('[Sources] failed:',{k:(v.get('error_code') or 'n/a') for k,v in srcs.items() if v.get('status')=='failed'});print('[Sources] last_success_at:',{k:v.get('last_success_at') for k,v in srcs.items() if v.get('status')!='cached'})" >> "$LOG" 2>&1 || true

# ── Step 3: Rebuild dashboard ──
echo "  [Step 3/4] Rebuilding dashboard..." >> "$LOG"
if ! python3 generate_副本.py >> "$LOG" 2>&1; then
    echo "FATAL: generate_副本.py failed - aborting, no deploy" >> "$LOG"
    echo "$(date '+%Y-%m-%d %H:%M:%S') - ABORTED (generate failed)" >> "$LOG"
    exit 1
fi

# Check if there were actual updates worth deploying
NEEDS_DEPLOY=true
if echo "$FETCH_OUTPUT" | grep -q "No changes\|already up to date\|hasn't closed yet"; then
    if echo "$NEWS_OUTPUT" | grep -q "Cache is fresh"; then
        NEEDS_DEPLOY=false
    fi
fi

# ── Step 4: Deploy ──
if [ "$NEEDS_DEPLOY" = true ]; then
    echo "  [Step 4/4] Deploying to surge.sh..." >> "$LOG"
    cp "$WORK/dashboard.html" "$DEPLOY/index.html"
    SURGE_RC=0
    (cd "$DEPLOY" && npx --yes surge . bkng-expe-abnb-1q26.surge.sh) >> "$LOG" 2>&1 || SURGE_RC=$?
    if [ "$SURGE_RC" -ne 0 ]; then
        echo "ERROR: surge deploy failed (rc=$SURGE_RC) - dashboard.html/deploy 已重建但线上未更新" >> "$LOG"
        echo "$(date '+%Y-%m-%d %H:%M:%S') - FAILED (surge deploy rc=$SURGE_RC)" >> "$LOG"
        exit 1
    fi
    echo "$(date '+%Y-%m-%d %H:%M:%S') - Done (${MODE} updated & deployed)" >> "$LOG"
else
    echo "  [Step 4/4] No changes detected, skipping deploy" >> "$LOG"
    echo "$(date '+%Y-%m-%d %H:%M:%S') - Done (${MODE}, no new data)" >> "$LOG"
fi
