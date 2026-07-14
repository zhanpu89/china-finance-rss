#!/usr/bin/env bash
# 检查测试用例设计产出物（阶段一）
# 返回: 0=通过, 1=失败

TESTER_DIR="doc/tester"
ERRORS=0

if [ ! -d "$TESTER_DIR" ]; then
  echo "❌ doc/tester 目录不存在"
  exit 1
fi

TC_FILES=()
while IFS= read -r -d '' f; do
  TC_FILES+=("$f")
done < <(find "$TESTER_DIR" \( -name "*测试用例*" -o -name "*testcase*" \) -print0 2>/dev/null)

if [ ${#TC_FILES[@]} -eq 0 ]; then
  echo "❌ 没有测试用例文档"
  exit 1
fi

for f in "${TC_FILES[@]}"; do
  SIZE=$(wc -c < "$f")
  echo "  $(basename "$f") ($SIZE bytes)"
  [ "$SIZE" -lt 200 ] && echo "⚠️  文件过小" && ERRORS=$((ERRORS + 1))
done

[ "$ERRORS" -eq 0 ] && echo "✅ 测试用例检查通过" || echo "⚠️ 测试用例检查完成，$ERRORS 个问题"
exit $([ "$ERRORS" -eq 0 ] && echo 0 || echo 1)
