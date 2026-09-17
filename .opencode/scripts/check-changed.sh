#!/usr/bin/env bash
# 按变更范围选择验证命令 —— 避免"改了工具/文档却跑业务全量测试"
#
# 用法: bash .opencode/scripts/check-changed.sh [base]
#   base 默认 HEAD（即未提交改动）。改动已提交时显式传基线，如 HEAD~1 / origin/main。
# 退出码: 0=通过, 1=验证失败
#
# 范围规则（唯一权威）:
#   业务代码  china_finance_rss/*  tests/*        → py_compile + unittest 全量
#   工具/配置 opencode.json  .opencode/*           → check-opencode.sh 自检
#   纯文档    *.md  doc/*                           → 不额外跑测试
#   任意                                            → git diff --check

set -u

PROJECT_DIR="$(cd "$(dirname "$0")/../.." && pwd)"
cd "$PROJECT_DIR" || exit 1

BASE="${1:-HEAD}"

if ! git rev-parse --verify --quiet "$BASE^{commit}" >/dev/null; then
  echo "❌ 无效的 base 版本: $BASE"
  exit 1
fi

CHANGED="$(
  { git diff --name-only "$BASE" 2>/dev/null || true
    git ls-files --others --exclude-standard 2>/dev/null || true
  } | sed '/^$/d' | sort -u
)"

if [ -z "$CHANGED" ]; then
  echo "无变更（base=$BASE）— 跳过验证"
  exit 0
fi

echo "=== 按变更范围验证 (base=$BASE) ==="
echo "$CHANGED" | sed 's/^/  - /'

HAS_CODE=0
HAS_TOOL=0
while IFS= read -r f; do
  case "$f" in
    china_finance_rss/*|tests/*) HAS_CODE=1 ;;
    opencode.json|.opencode/*)   HAS_TOOL=1 ;;
  esac
done <<< "$CHANGED"

FAIL=0

if [ "$HAS_CODE" -eq 1 ]; then
  echo "--- 业务代码变更 → 编译 + 全量测试 ---"
  python -m py_compile china_finance_rss/*.py tests/*.py || FAIL=1
  python -m unittest discover -s tests -v || FAIL=1
else
  echo "--- 无业务代码变更 → 跳过 py_compile / unittest ---"
fi

if [ "$HAS_TOOL" -eq 1 ]; then
  echo "--- 工具/配置变更 → 工具自检 ---"
  bash .opencode/scripts/check-opencode.sh || FAIL=1
fi

echo "--- 通用 ---"
git diff --check || FAIL=1

if [ "$FAIL" -eq 0 ]; then
  echo "✅ 范围匹配验证通过"
else
  echo "❌ 范围匹配验证失败"
fi
exit "$FAIL"
