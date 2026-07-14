#!/usr/bin/env bash
# 检查评审报告结论
# 返回: 0=通过(✅), 1=有条件通过(⚠️), 2=不通过(❌), 3=未找到
# 输出: 结论文本

REVIEW_DIR="doc/review"

if [ ! -d "$REVIEW_DIR" ]; then
  echo "❌ 评审目录不存在"
  exit 3
fi

# 找最新的评审报告（使用 null 分隔符处理含空格文件名）
LATEST=$(find "$REVIEW_DIR" -type f \( -name "*评审报告*" -o -name "*review*" \) -print0 | xargs -0 ls -t 2>/dev/null | head -1)
if [ -z "$LATEST" ]; then
  echo "❌ 未找到评审报告"
  exit 3
fi

echo "报告: $(basename "$LATEST")"

# 提取评审结论行 (格式: "| 评审结论 | ✅ 通过 |")
LINE=$(grep -i "评审结论" "$LATEST" 2>/dev/null | head -1)
if [ -z "$LINE" ]; then
  echo "❌ 未找到评审结论行"
  exit 3
fi

echo "原始行: $LINE"

# 提取结论 (取第二个 | 分隔的字段，去空格)
CONCLUSION=$(echo "$LINE" | awk -F'|' '{print $3}' | sed 's/^[[:space:]]*//;s/[[:space:]]*$//')
echo "结论: $CONCLUSION"

case "$CONCLUSION" in
  *"❌"*|*"不通过"*)
    echo "判定: ❌ 不通过"
    exit 2
    ;;
  *"⚠️"*|*"有条件"*)
    echo "判定: ⚠️ 有条件通过"
    exit 1
    ;;
  *"✅"*|*"通过"*)
    echo "判定: ✅ 通过"
    exit 0
    ;;
  *)
    echo "判定: ⚠️ 未知结论，视为有条件通过"
    exit 1
    ;;
esac
