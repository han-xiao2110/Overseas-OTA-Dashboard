#!/usr/bin/env bash
# =============================================================
# deploy_local.sh —— 一键本地部署到 Surge
#
# 流程：
#   1. git pull 拉取 GitHub Actions 最新抓取的股价 / 新闻
#   2. python generate_副本.py   ← 使用你本地 Excel 生成 dashboard
#   3. surge ./deploy 上线
#
# 使用：
#   cd "/Users/feifei/Documents/BKNG-EXPE-ABNB业绩"
#   bash deploy_local.sh
# =============================================================
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$SCRIPT_DIR"

echo ""
echo "╔══════════════════════════════════════════════════╗"
echo "║  BKNG / EXPE / ABNB Dashboard — 本地一键部署    ║"
echo "╚══════════════════════════════════════════════════╝"
echo ""

# ── 1. 依赖检查 ──────────────────────────────────────────
echo "[1/4] 依赖检查..."
for cmd in python3 npx; do
  if ! command -v "$cmd" >/dev/null 2>&1; then
    echo "  ✗ 未找到 '$cmd'，请先安装"
    exit 1
  fi
done
echo "  ✓ python3: $(python3 --version 2>&1)"
echo "  ✓ npx:     $(npx --version 2>&1)"

# Excel 必须存在（财务数据只在本地）
XLSX_COUNT=$(find "$SCRIPT_DIR" -maxdepth 1 -name "*.xlsx" | wc -l | tr -d ' ')
if [ "$XLSX_COUNT" -eq 0 ]; then
  echo ""
  echo "  ✗ 错误：当前目录未找到 Excel 财务数据文件（.xlsx）"
  echo "    财务数据不应提交到 GitHub，请把原始 .xlsx 放回该目录后再运行。"
  exit 1
fi
echo "  ✓ Excel 文件存在（${XLSX_COUNT} 个，财务数据仅在本机）"

# ── 2. 拉取最新数据 ──────────────────────────────────────
echo ""
echo "[2/4] 拉取 GitHub 上最新抓取的股价 + 新闻..."
if [ ! -d ".git" ]; then
  echo "  ! 未初始化 git 仓库；跳过 pull（直接使用本地现有 stock_prices_副本.json / news_data_副本.json）"
else
  # 先保证本地没有未提交的改动（数据文件等），避免 pull 冲突
  if ! git diff --quiet || ! git diff --cached --quiet; then
    echo "  ! 本地有未提交改动，stash 后 pull"
    git stash push -u -m "pre-deploy-local stash $(date +%Y%m%d-%H%M%S)" || true
  fi
  git pull --ff-only || {
    echo "  ✗ git pull 失败，请检查网络或手动解决冲突后重跑"
    exit 1
  }
  echo "  ✓ 已同步到最新"
fi

# ── 3. 生成 Dashboard（需要本地 Excel）───────────────────
echo ""
echo "[3/4] 生成 dashboard HTML..."
if ! python3 generate_副本.py 2>&1 | tail -20; then
  echo "  ✗ generate_副本.py 失败，中止部署"
  exit 1
fi
echo "  ✓ dashboard 生成完成"

# ── 4. 部署到 Surge ─────────────────────────────────────
echo ""
echo "[4/4] 部署到 Surge.sh (bkng-expe-abnb-1q26.surge.sh)..."
DEPLOY_DIR="$SCRIPT_DIR/deploy"
if [ ! -d "$DEPLOY_DIR" ]; then
  echo "  ✗ deploy/ 目录不存在，generate 步骤可能失败，中止"
  exit 1
fi

# 需要 surge CLI；找不到就 npx 安装临时用
if command -v surge >/dev/null 2>&1; then
  SURGE_CMD="surge"
else
  SURGE_CMD="npx --yes surge"
fi

if ! $SURGE_CMD "$DEPLOY_DIR" bkng-expe-abnb-1q26.surge.sh 2>&1 | tail -10; then
  echo ""
  echo "  ✗ surge 部署失败（可能需要登录：先执行 $SURGE_CMD login）"
  exit 1
fi

echo ""
echo "✅ 部署完成：https://bkng-expe-abnb-1q26.surge.sh/"
echo "   本地时间：$(date '+%Y-%m-%d %H:%M:%S')"
echo ""
