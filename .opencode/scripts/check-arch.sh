#!/usr/bin/env bash
# 检查架构设计产出物
# 退出码: 0=通过, 1=失败

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
    [ "$SIZE" -lt 1000 ] && echo "⚠️  文件过小(＜1KB)" && ERRORS=$((ERRORS + 1))

    # 检查 NFR 量化（仅在 NFR 章节内匹配数字指标）
    NFR_SECTION=$(awk '/^## .*(NFR|非功能性|性能|安全.*架构|可扩展性)/{found=1} found{print} /^## /{if(found && NR>1) exit}' "$f" 2>/dev/null)
    NFR_Q=$(echo "$NFR_SECTION" | grep -cE "(并发|TPS|QPS|延迟|<[0-9]+ms|>[0-9]+%|[0-9]+核|[0-9]+GB|99[.%])" 2>/dev/null)
    if [ "$NFR_Q" -gt 0 ]; then
      echo "    → NFR 含 $NFR_Q 处量化指标 ✅"
    else
      echo "    ⚠️  NFR 可能未量化，未检测到具体指标数字"
    fi

    # 检查组件决策表（是/为什么/不选其他/权衡）
    DECISION_COUNT=$(grep -ciE "(为什么选|不选|权衡|对比|替代方案)" "$f" 2>/dev/null || echo 0)
    if [ "$DECISION_COUNT" -gt 0 ]; then
      echo "    → 含 $DECISION_COUNT 处技术决策论证 ✅"
    else
      echo "    ⚠️  未检测到技术决策论证（为什么选/不选其他/权衡）"
    fi
  done
fi

# 检查 tech-stack.json
TS_FILE="$ARCH_DIR/tech-stack.json"
if [ ! -f "$TS_FILE" ]; then
  echo "❌ tech-stack.json 不存在"
  ERRORS=$((ERRORS + 1))
elif python3 -c "
import json, sys
with open('${TS_FILE}') as f:
    d = json.load(f)
assert 'project' in d, 'missing project'
assert 'techStack' in d, 'missing techStack'
ts = d['techStack']
assert isinstance(ts, dict), 'techStack must be an object'
# validate architectureRules if present
ar = d.get('architectureRules')
if ar is not None:
    assert isinstance(ar, dict), 'architectureRules must be an object'
    for k in ar:
        assert k in ('layerIsolation','importRestrictions','namingRules','fileStructure'), f'unknown rule key: {k}'
    print('  → 含 architectureRules（', len(ar), '条）')
print('  project=' + d.get('project', '?'))
" 2>/dev/null; then
  echo "✅ tech-stack.json 格式有效"
else
  echo "❌ tech-stack.json 格式无效（需含 project + techStack 字段）"
  ERRORS=$((ERRORS + 1))
fi

[ "$ERRORS" -eq 0 ] && echo "✅ 架构检查通过" || echo "⚠️ 架构检查完成，$ERRORS 个问题"
exit $([ "$ERRORS" -eq 0 ] && echo 0 || echo 1)
