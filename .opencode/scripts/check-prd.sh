#!/usr/bin/env bash
# 检查 PRD 产出物
# 返回: 0=通过, 1=失败

PRD_DIR="doc/prd"
ERRORS=0

if [ ! -d "$PRD_DIR" ]; then
  echo "❌ PRD 目录不存在: $PRD_DIR"
  exit 1
fi

# 收集文件列表
FILES=()
while IFS= read -r -d '' f; do
  FILES+=("$f")
done < <(find "$PRD_DIR" -name "*.md" -print0 2>/dev/null)

if [ ${#FILES[@]} -eq 0 ]; then
  echo "❌ PRD 目录下没有 .md 文件"
  exit 1
fi

for f in "${FILES[@]}"; do
  SIZE=$(wc -c < "$f")
  if [ "$SIZE" -lt 100 ]; then
    echo "⚠️ 文件过小(＜100B): $f"
    ERRORS=$((ERRORS + 1))
  else
    echo "✅ $(basename "$f") ($SIZE bytes)"
  fi
done

# 检查关键章节
for f in "${FILES[@]}"; do
  if ! grep -q "## " "$f" 2>/dev/null; then
    echo "⚠️ 缺少 Markdown 章节标题: $f"
    ERRORS=$((ERRORS + 1))
  fi
done

[ "$ERRORS" -eq 0 ] && echo "✅ PRD 检查通过" || echo "⚠️ PRD 检查完成，$ERRORS 个问题"
exit $([ "$ERRORS" -eq 0 ] && echo 0 || echo 1)
