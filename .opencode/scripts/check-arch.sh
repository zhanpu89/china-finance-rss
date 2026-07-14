#!/usr/bin/env bash
# 检查架构设计产出物
# 返回: 0=通过, 1=失败

ARCH_DIR="doc/arch"
ERRORS=0

if [ ! -d "$ARCH_DIR" ]; then
  echo "❌ 架构目录不存在: $ARCH_DIR"
  exit 1
fi

# 检查 SAD Markdown 文档（使用数组处理含空格文件名）
SAD_FILES=()
while IFS= read -r -d '' f; do
  SAD_FILES+=("$f")
done < <(find "$ARCH_DIR" -maxdepth 1 -name "*.md" -print0 2>/dev/null)

if [ ${#SAD_FILES[@]} -eq 0 ]; then
  echo "❌ 架构目录下没有 .md 文件"
  ERRORS=$((ERRORS + 1))
else
  for f in "${SAD_FILES[@]}"; do
    SIZE=$(wc -c < "$f")
    echo "  $(basename "$f") ($SIZE bytes)"
    [ "$SIZE" -lt 200 ] && echo "⚠️  文件过小" && ERRORS=$((ERRORS + 1))
  done
fi

# 检查 tech-stack.json
TS_FILE="$ARCH_DIR/tech-stack.json"
if [ ! -f "$TS_FILE" ]; then
  echo "❌ tech-stack.json 不存在"
  ERRORS=$((ERRORS + 1))
elif python3 -c "
import json, sys
with open('$TS_FILE') as f:
    d = json.load(f)
assert 'project' in d, 'missing project'
assert 'techStack' in d, 'missing techStack'
print('  project=' + d.get('project', '?'))
" 2>/dev/null; then
  echo "✅ tech-stack.json 格式有效"
else
  echo "❌ tech-stack.json 格式无效"
  ERRORS=$((ERRORS + 1))
fi

[ "$ERRORS" -eq 0 ] && echo "✅ 架构检查通过" || echo "⚠️ 架构检查完成，$ERRORS 个问题"
exit $([ "$ERRORS" -eq 0 ] && echo 0 || echo 1)
