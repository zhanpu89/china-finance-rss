#!/usr/bin/env bash
# 检查详细设计产出物
# 退出码: 0=通过, 1=失败
#
# 项目适配（v1.1）：必需/可选章节、接口与数据围栏、规则文档路径均可由
#   .opencode/project/manifest.json 的 doc_profile.detailed 声明。
#   空数组 / 空串 = 项目声明为 N/A —— 脚本会打印**显式提示**（不静默跳过）。
# ★ v1.1 修复：原循环把 ERE 交替写成 BRE 转义 `OpenAPI\|接口` / `DDL\|数据`，
#   在 `grep -E` 下匹配的是**字面量竖线** ⇒ 两条「缺少章节」检查**永不命中**、
#   恒为假警告（本仓每份详设都有「## 2. 接口契约」「## 3. 数据结构」）。

DETAILED_DIR="doc/detailed"
ERRORS=0

doc_profile() {  # 用法: doc_profile <kind> <key> [默认值...]
  python3 - "$@" <<'PY' 2>/dev/null || printf '%s\n' "${@:3}"
import json, sys
kind, key, *defaults = sys.argv[1:]
try:
    vals = json.load(open('.opencode/project/manifest.json')) \
        .get('doc_profile', {}).get(kind, {}).get(key)
except Exception:
    vals = None
if vals is None:
    vals = list(defaults)
elif isinstance(vals, str):          # 标量必须整体输出，否则会被逐字符拆开
    vals = [vals]
elif not isinstance(vals, (list, tuple)):
    vals = [str(vals)]
print('\n'.join(str(v) for v in vals))
PY
}

if [ ! -d "$DETAILED_DIR" ]; then
  echo "❌ 详设目录不存在: $DETAILED_DIR"
  exit 1
fi

# 收集详设文档（使用数组处理含空格文件名）
DESIGN_FILES=()
while IFS= read -r -d '' f; do
  DESIGN_FILES+=("$f")
done < <(find "$DETAILED_DIR" -maxdepth 1 -name "*.md" ! -name "编码规范.md" ! -name "项目规则.md" ! -name "_PROGRESS.md" ! -name "_MEMORY_CACHE.md" -print0 2>/dev/null)

IFACE=$(doc_profile detailed interface_section "OpenAPI|接口")
DATA=$(doc_profile detailed data_section "DDL|数据")
IFACE_FENCE=$(doc_profile detailed interface_fence "yaml|json")
DATA_FENCE=$(doc_profile detailed data_fence "sql")

readarray -t DETAILED_SECTIONS < <(doc_profile detailed required_sections \
  "职责|功能描述" "业务规则|BR-" "接口|契约" "测试")
readarray -t OPTIONAL_SECTIONS < <(doc_profile detailed optional_sections "")
echo "必需章节: ${DETAILED_SECTIONS[*]} · 接口围栏: ${IFACE_FENCE:-N/A} · 数据围栏: ${DATA_FENCE:-N/A}"

if [ ${#DESIGN_FILES[@]} -eq 0 ]; then
  echo "❌ 没有详设文档"
  ERRORS=$((ERRORS + 1))
else
  for f in "${DESIGN_FILES[@]}"; do
    SIZE=$(wc -c < "$f")
    echo "  $(basename "$f") ($SIZE bytes)"
    [ "$SIZE" -lt 2000 ] && echo "⚠️  文件过小(＜2KB)" && ERRORS=$((ERRORS + 1))

    # 检查必含章节（仅匹配 Markdown 标题行，避免误匹配代码块/表格）
    for section in "${DETAILED_SECTIONS[@]}"; do
      [ -z "$section" ] && continue
      if ! grep -Eq "^## .*($section)" "$f" 2>/dev/null; then
        echo "⚠️  缺少 $section 章节"
        ERRORS=$((ERRORS + 1))
      fi
    done

    # 可选章节：缺失时只提示「项目声明为 N/A」，不计问题
    for section in "${OPTIONAL_SECTIONS[@]}"; do
      [ -z "$section" ] && continue
      grep -Eq "^## .*($section)" "$f" 2>/dev/null \
        || echo "    ℹ️  无 $section 章节（项目声明为 N/A）"
    done

    # 接口章节内的机器可读围栏
    if grep -Eq "^## .*($IFACE)" "$f" 2>/dev/null; then
      if [ -z "$IFACE_FENCE" ]; then
        echo "    ℹ️  接口围栏检查：项目声明为 N/A（接口以签名表/伪代码承接）"
      else
        SECTION_CONTENT=$(awk -v pat="$IFACE" '/^## /{if(f) exit; if($0 ~ pat) f=1; next} f' "$f")
        if echo "$SECTION_CONTENT" | grep -Eq "\`\`\`($IFACE_FENCE)" 2>/dev/null; then
          echo "    → 接口含 \`\`\`($IFACE_FENCE) 代码块 ✅"
        else
          echo "    ⚠️  接口章节缺少 \`\`\`($IFACE_FENCE) 代码块"
          ERRORS=$((ERRORS + 1))
        fi
      fi
    fi

    # 数据章节内的 SQL 围栏（无持久层的项目在 profile 里置空）
    if grep -Eq "^## .*($DATA)" "$f" 2>/dev/null; then
      if [ -z "$DATA_FENCE" ]; then
        echo "    ℹ️  数据围栏检查：项目声明为 N/A（本项目无 SQL 持久层，数据结构为 yaml/dict）"
      else
        SECTION_CONTENT=$(awk -v pat="$DATA" '/^## /{if(f) exit; if($0 ~ pat) f=1; next} f' "$f")
        if echo "$SECTION_CONTENT" | grep -q "\`\`\`$DATA_FENCE" 2>/dev/null; then
          echo "    → 数据含 \`\`\`$DATA_FENCE 代码块 ✅"
        else
          echo "    ⚠️  数据章节缺少 \`\`\`$DATA_FENCE 代码块"
          ERRORS=$((ERRORS + 1))
        fi
      fi
    fi
  done
fi

# 检查项目规则（路径可由 profile 声明；空 = N/A）
readarray -t RULE_DOCS < <(doc_profile detailed rule_docs "项目规则.md" "编码规范.md")
if [ ${#RULE_DOCS[@]} -eq 0 ] || [ -z "${RULE_DOCS[0]}" ]; then
  echo "  ℹ️  项目规则/编码规范：项目声明为 N/A（规则位于 .opencode/rules/ + AGENTS.md，不在 doc/detailed/）"
else
  for req in "${RULE_DOCS[@]}"; do
    [ -z "$req" ] && continue
    if [ ! -f "$DETAILED_DIR/$req" ]; then
      echo "⚠️  $req 不存在"
      ERRORS=$((ERRORS + 1))
    else
      RULES_SIZE=$(wc -c < "$DETAILED_DIR/$req")
      echo "✅ $req ($RULES_SIZE bytes)"
      [ "$RULES_SIZE" -lt 100 ] && echo "⚠️  $req 文件过小" && ERRORS=$((ERRORS + 1))
    fi
  done
fi

[ "$ERRORS" -eq 0 ] && echo "✅ 详设检查通过" || echo "⚠️ 详设检查完成，$ERRORS 个问题"
exit $([ "$ERRORS" -eq 0 ] && echo 0 || echo 1)
