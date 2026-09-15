#!/usr/bin/env bash
# 检查详细设计产出物
# 退出码: 0=通过, 1=失败

DETAILED_DIR="doc/detailed"
ERRORS=0

if [ ! -d "$DETAILED_DIR" ]; then
  echo "❌ 详设目录不存在: $DETAILED_DIR"
  exit 1
fi

# 收集详设文档（使用数组处理含空格文件名）
DESIGN_FILES=()
while IFS= read -r -d '' f; do
  DESIGN_FILES+=("$f")
done < <(find "$DETAILED_DIR" -maxdepth 1 -name "*.md" ! -name "编码规范.md" ! -name "项目规则.md" ! -name "_PROGRESS.md" ! -name "_MEMORY_CACHE.md" -print0 2>/dev/null)

if [ ${#DESIGN_FILES[@]} -eq 0 ]; then
  echo "❌ 没有详设文档"
  ERRORS=$((ERRORS + 1))
else
  for f in "${DESIGN_FILES[@]}"; do
    SIZE=$(wc -c < "$f")
    echo "  $(basename "$f") ($SIZE bytes)"
    [ "$SIZE" -lt 2000 ] && echo "⚠️  文件过小(＜2KB)" && ERRORS=$((ERRORS + 1))

    # 检查必含章节（仅匹配Markdown标题行，避免误匹配代码块/表格）
    for section in "功能描述" "业务规则" "OpenAPI\|接口" "DDL\|数据"; do
      if ! grep -Eq "^## .*($section)" "$f" 2>/dev/null; then
        echo "⚠️  缺少 $section 章节"
        ERRORS=$((ERRORS + 1))
      fi
    done

    # 验证 OpenAPI 章节内有 ```yaml 或 ```json 代码块
    if grep -Eq "^## .*(OpenAPI|接口)" "$f" 2>/dev/null; then
      SECTION_CONTENT=$(awk '/^## /{if(f) exit; if(/OpenAPI|接口/) f=1; next} f' "$f")
      if echo "$SECTION_CONTENT" | grep -Eq '```(yaml|json)' 2>/dev/null; then
        echo '    → OpenAPI 含代码块 ✅'
      else
        echo '    ⚠️  接口章节缺少 ```yaml/```json 代码块'
        ERRORS=$((ERRORS + 1))
      fi
    fi

    # 验证 DDL 章节内有 ```sql 代码块
    if grep -Eq "^## .*(DDL|数据)" "$f" 2>/dev/null; then
      SECTION_CONTENT=$(awk '/^## /{if(f) exit; if(/DDL|数据/) f=1; next} f' "$f")
      if echo "$SECTION_CONTENT" | grep -q '```sql' 2>/dev/null; then
        echo '    → DDL 含 SQL 代码块 ✅'
      else
        echo '    ⚠️  数据章节缺少 ```sql 代码块'
        ERRORS=$((ERRORS + 1))
      fi
    fi
  done
fi

# 检查项目规则
for req in "项目规则.md" "编码规范.md"; do
  if [ ! -f "$DETAILED_DIR/$req" ]; then
    echo "⚠️  $req 不存在"
    ERRORS=$((ERRORS + 1))
  else
    RULES_SIZE=$(wc -c < "$DETAILED_DIR/$req")
    echo "✅ $req ($RULES_SIZE bytes)"
    [ "$RULES_SIZE" -lt 100 ] && echo "⚠️  $req 文件过小" && ERRORS=$((ERRORS + 1))
  fi
done

[ "$ERRORS" -eq 0 ] && echo "✅ 详设检查通过" || echo "⚠️ 详设检查完成，$ERRORS 个问题"
exit $([ "$ERRORS" -eq 0 ] && echo 0 || echo 1)
