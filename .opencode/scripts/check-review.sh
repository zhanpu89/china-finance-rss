#!/usr/bin/env bash
# 检查评审报告结论
# 标准退出码：0=通过(✅)，1=有条件(⚠️)，2=阻断(❌)
# 输出: 结论文本
# 用法: check-review.sh [--name PATTERN]  — PATTERN 过滤目标报告（如 "代码评审"/"需求评审"），
#        否则取最新报告。多 Phase 累积报告时必须传 --name 精确定位本 Phase 的评审报告。

REVIEW_DIR="doc/review"
NAME_FILTER=""

while [ $# -gt 0 ]; do
  case "$1" in
    --name)
      NAME_FILTER="$2"
      shift 2
      ;;
    *)
      shift
      ;;
  esac
done

if [ ! -d "$REVIEW_DIR" ]; then
  echo "❌ 评审目录不存在"
  exit 2
fi

# 带 name 过滤时按过滤条件找，否则取最新报告
# 注意：find -printf '\0' + sort -z + head 无法正确处理（head 按换行读），先 tr NUL 为换行再排序
if [ -n "$NAME_FILTER" ]; then
  LATEST=$(find "$REVIEW_DIR" -type f -name "*$NAME_FILTER*" -printf '%T@ %p\0' 2>/dev/null | tr '\0' '\n' | sort -rn | head -1 | cut -d' ' -f2-)
  [ -n "$LATEST" ] && echo "报告(按 $NAME_FILTER 过滤): $(basename "$LATEST")"
else
  LATEST=$(find "$REVIEW_DIR" -type f \( -name "*评审报告*" -o -name "*review*" -o -name "*报告*" \) -printf '%T@ %p\0' 2>/dev/null | tr '\0' '\n' | sort -rn | head -1 | cut -d' ' -f2-)
  [ -n "$LATEST" ] && echo "报告: $(basename "$LATEST")"
fi

if [ -z "$LATEST" ]; then
  echo "❌ 未找到评审报告"
  exit 2
fi

# ---- 提取评审结论 ----
# 支持多种格式:
#   格式A: | 评审结论 | ✅ 通过 |                  (表格)
#   格式B: **评审结论：** ✅ 通过                   (强调)
#   格式C: 评审结论：✅ 通过                       (纯文本)
#   格式D: ✅ 通过（结论行直接含 emoji）           (直接)

LINE=""

# 尝试格式A: Markdown 表格行
LINE=$(grep -i "评审结论" "$LATEST" 2>/dev/null | grep -v "^[[:space:]]*$" | head -1)

# 尝试格式B/C: 行内 **结论文本** 或 结论文本：
if [ -z "$LINE" ]; then
  LINE=$(grep -iE "^\*{0,2}\s*(评审结论|结论|判定)" "$LATEST" 2>/dev/null | head -1)
fi

# 尝试格式D: 仅含 emoji 判定符号的行
if [ -z "$LINE" ]; then
  LINE=$(grep -E "[✅⚠️❌]" "$LATEST" 2>/dev/null | grep -v "^[[:space:]]*$" | head -1)
fi

if [ -z "$LINE" ]; then
  echo "❌ 未找到评审结论行（支持表格/强调/纯文本/emoji 格式）"
  exit 2
fi

echo "原始行: $LINE"

# ---- 判定函数 ----
# 从行内容中提取结论（支持表格和文本格式）
determine_conclusion() {
  local raw="$1"
  local combined

  # 表格格式: 取第二个 | 分隔的字段
  if echo "$raw" | grep -q "|"; then
    combined=$(echo "$raw" | awk -F'|' '{print $3}')
  else
    combined="$raw"
  fi

  # 分离 emoji 和文字判断
  if echo "$combined" | grep -q "❌"; then
    echo "❌"
  elif echo "$combined" | grep -q "⚠️"; then
    echo "⚠️"
  elif echo "$combined" | grep -q "✅"; then
    echo "✅"
  elif echo "$combined" | grep -qiE "(不通过|失败|拒绝)"; then
    echo "❌"
  elif echo "$combined" | grep -qiE "(有条件|部分通过|警告)"; then
    echo "⚠️"
  elif echo "$combined" | grep -qiE "(通过|成功|合格)"; then
    echo "✅"
  else
    echo "⚠️"  # 未知默认警告
  fi
}

CONCLUSION=$(determine_conclusion "$LINE")
echo "判定: $CONCLUSION"

case "$CONCLUSION" in
  "❌")
    echo "结论: ❌ 不通过"
    exit 2
    ;;
  "⚠️")
    echo "结论: ⚠️ 有条件通过"
    exit 1
    ;;
  "✅")
    echo "结论: ✅ 通过"
    exit 0
    ;;
esac
