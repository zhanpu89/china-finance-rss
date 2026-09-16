#!/usr/bin/env bash
# 检查测试用例设计产出物（阶段一）
# 退出码: 0=通过, 1=失败

TESTER_DIR="doc/tester"
ERRORS=0

if [ ! -d "$TESTER_DIR" ]; then
  echo "❌ doc/tester 目录不存在"
  exit 1
fi

TC_FILES=()
while IFS= read -r -d '' f; do
  TC_FILES+=("$f")
done < <(find "$TESTER_DIR" \( -name "*测试用例*" -o -name "*testcase*" -o -name "*用例*" \) -print0 2>/dev/null)

if [ ${#TC_FILES[@]} -eq 0 ]; then
  echo "❌ 没有测试用例文档"
  exit 1
fi

for f in "${TC_FILES[@]}"; do
  SIZE=$(wc -c < "$f")
  echo "  $(basename "$f") ($SIZE bytes)"
  [ "$SIZE" -lt 500 ] && echo "⚠️  文件过小(＜500B)" && ERRORS=$((ERRORS + 1))

  # 验证用例文档包含标准 TC-ID 格式（模块缩写 2-4 字，支持中文/拉丁字母）
  # 注意：grep -c 恒输出数字（无匹配时输出 0 但退出码 1），禁止追加 || echo 0 导致 "0\n0"
  # ERE 语法：区间/分组不加反斜杠（\{ 是 BRE 写法，会匹配字面 { ）
  TC_PAT='TC-[^[:space:]-]{2,4}-(UNIT|INTG|SEC|PERF|FE)-[0-9]+'
  TC_COUNT=$(grep -cE "$TC_PAT" "$f" 2>/dev/null || true)
  if [ "${TC_COUNT:-0}" -gt 0 ] 2>/dev/null; then
    echo "    → 含 $TC_COUNT 个标准格式用例 ID"

    # 统计各种类型分布
    for ttype in UNIT INTG SEC PERF FE; do
      tcount=$(grep -cE "TC-[^[:space:]-]{2,4}-${ttype}-[0-9]+" "$f" 2>/dev/null || true)
      [ "${tcount:-0}" -gt 0 ] 2>/dev/null && echo "      ${ttype}: $tcount"
    done
  else
    echo "    ⚠️  未检测到标准格式用例 ID（期望格式: TC-{模块}-{类型}-{序号}）"
  fi
done

[ "$ERRORS" -eq 0 ] && echo "✅ 测试用例检查通过" || echo "⚠️ 测试用例检查完成，$ERRORS 个问题"
exit $([ "$ERRORS" -eq 0 ] && echo 0 || echo 1)
