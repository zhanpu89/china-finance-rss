#!/usr/bin/env bash
# 自举门禁 — 验证 pipeline 工具自身的结构完整性
# 适用于修改 .opencode/ 下的脚本/规则/SKILL/配置后的自检
# 退出码: 0=通过, 1=警告, 2=阻断
#
# 使用方式:
#   bash .opencode/scripts/check-opencode.sh

PROJECT_DIR="$(cd "$(dirname "$0")/../.." && pwd)"
ERRORS=0
WARNINGS=0

echo "=== Pipeline 工具自身检查 ==="

# ---- 1. bash 语法检查 ----
echo ""
echo "--- Shell 语法 ---"
SCRIPT_FILES=()
while IFS= read -r -d '' f; do
  SCRIPT_FILES+=("$f")
done < <(find "$PROJECT_DIR/.opencode/scripts" -name "*.sh" -print0 2>/dev/null)

for f in "${SCRIPT_FILES[@]}"; do
  REL="${f#$PROJECT_DIR/}"
  if bash -n "$f" 2>/dev/null; then
    echo "  ✅ $REL"
  else
    echo "  ❌ $REL — bash 语法错误:"
    bash -n "$f" 2>&1 | sed 's/^/      /'
    ERRORS=$((ERRORS + 1))
  fi
done

# ---- 2. opencode.json 验证 ----
echo ""
echo "--- opencode.json 验证 ---"
if [ -f "$PROJECT_DIR/opencode.json" ]; then
  python3 -c "
import json, sys
with open('$PROJECT_DIR/opencode.json') as f:
    d = json.load(f)
assert 'default_agent' in d, '缺少 default_agent'
assert 'agent' in d, '缺少 agent'
assert 'pipeline-orchestrator' in d['agent'], '缺少 pipeline-orchestrator agent'
# 检查所有 agent 有 description
for name, cfg in d['agent'].items():
    assert 'description' in cfg, f'{name} 缺少 description'
    assert 'prompt' in cfg, f'{name} 缺少 prompt'
print('  ✅ JSON 格式有效，agent 配置完整')
" 2>&1 || {
  echo "  ❌ opencode.json 验证失败"
  ERRORS=$((ERRORS + 1))
}
else
  echo "  ❌ opencode.json 不存在"
  ERRORS=$((ERRORS + 1))
fi

# ---- 3. SKILL.md front matter 检查 ----
echo ""
echo "--- SKILL.md 结构检查 ---"
SKILL_FILES=()
while IFS= read -r -d '' f; do
  SKILL_FILES+=("$f")
done < <(find "$PROJECT_DIR/.opencode/skills" -name "SKILL.md" -print0 2>/dev/null)

for f in "${SKILL_FILES[@]}"; do
  REL="${f#$PROJECT_DIR/}"
  # 检查前 3 行是否为 YAML front matter (--- ... ---)
  LINE1=$(head -1 "$f" 2>/dev/null)
  LINE2=$(head -3 "$f" 2>/dev/null | tail -1)
  if [ "$LINE1" = "---" ]; then
    # find closing ---
    CLOSING=$(tail -n +2 "$f" | grep -n "^---" | head -1 | cut -d: -f1)
    if [ -n "$CLOSING" ]; then
      echo "  ✅ $REL (YAML front matter: $CLOSING 行)"
    else
      echo "  ⚠️  $REL — 有开 --- 无闭 ---"
      WARNINGS=$((WARNINGS + 1))
    fi
  else
    echo "  ⚠️  $REL — 无 YAML front matter"
    WARNINGS=$((WARNINGS + 1))
  fi
done

# ---- 4. 引用完整性检查 ----
echo ""
echo "--- 引用完整性 ---"
# 检查 scripts 表中引用的文件是否存在
REF_FILES=(
  ".opencode/scripts/check-arch.sh"
  ".opencode/scripts/check-arch-compliance.sh"
  ".opencode/scripts/check-audit.sh"
  ".opencode/scripts/check-code.sh"
  ".opencode/scripts/check-detailed.sh"
  ".opencode/scripts/check-drift.sh"
  ".opencode/scripts/check-feedback.sh"
  ".opencode/scripts/check-integration.sh"
  ".opencode/scripts/check-prd.sh"
  ".opencode/scripts/check-review.sh"
  ".opencode/scripts/check-test.sh"
  ".opencode/scripts/check-testcase.sh"
  ".opencode/scripts/log-skill.sh"
  ".opencode/scripts/log-feedback.sh"
  ".opencode/scripts/project-init.sh"
  ".opencode/scripts/mirror-log.sh"
  ".opencode/project/manifest.json"
  ".opencode/project/profile.md"
  ".opencode/project/conventions.md"
)
MISSING=0
for f in "${REF_FILES[@]}"; do
  if [ -f "$PROJECT_DIR/$f" ]; then
    echo "  ✅ $f"
  else
    echo "  ❌ $f — 引用文件不存在"
    ERRORS=$((ERRORS + 1))
    MISSING=$((MISSING + 1))
  fi
done
[ "$MISSING" -eq 0 ] && echo "  所有引用文件存在 ✅"

# ---- 5. opencode.json 中 agent 名称与 SKILL.md 一致性 ----
echo ""
echo "--- Agent/SKILL 一致性 ---"
python3 -c "
import json, os, sys
with open('$PROJECT_DIR/opencode.json') as f:
    d = json.load(f)
agents = d.get('agent', {})
skills_dir = '$PROJECT_DIR/.opencode/skills'
all_good = True
for name in agents:
    skill_path = os.path.join(skills_dir, name, 'SKILL.md')
    if agents[name].get('mode') == 'primary':
        continue  # 主 agent 不走 file 加载
    if not os.path.exists(skill_path):
        print(f'  ❌ agent {name}: 对应的 .opencode/skills/{name}/SKILL.md 不存在')
        all_good = False
    else:
        print(f'  ✅ {name} → skills/{name}/SKILL.md')
if all_good:
    print('  所有 agent 有对应 SKILL.md ✅')
" 2>&1 || ERRORS=$((ERRORS + 1))

# ---- 6. SKILL 资源引用完整性 ----
# 检查每个 SKILL.md 中引用的 resources/*.md 和 templates/*.md 是否真实存在
echo ""
echo "--- SKILL 资源引用完整性 ---"
python3 -c "
import os, re, sys
skills_dir = '$PROJECT_DIR/.opencode/skills'
all_good = True
for name in sorted(os.listdir(skills_dir)):
    skill_dir = os.path.join(skills_dir, name)
    skill_file = os.path.join(skill_dir, 'SKILL.md')
    if not os.path.isfile(skill_file):
        continue
    with open(skill_file) as f:
        content = f.read()
    # 匹配 resources/xxx.md 和 templates/xxx.md 引用
    refs = set(re.findall(r'(?:resources|templates)/[\w.-]+\.md', content))
    for ref in sorted(refs):
        if not os.path.exists(os.path.join(skill_dir, ref)):
            print(f'  ❌ {name}: 引用 {ref} 不存在')
            all_good = False
if all_good:
    print('  所有 SKILL 资源引用存在 ✅')
" 2>&1 || ERRORS=$((ERRORS + 1))

# ---- 7. 权限契约一致性 ----
# SKILL 中"产出/输出/写入"语境下声明的路径必须能被 opencode.json 的 write 权限覆盖
echo ""
echo "--- 权限契约一致性 ---"
PERM_MISMATCH=$(python3 -c "
import json, os, re, fnmatch
with open('$PROJECT_DIR/opencode.json') as f:
    d = json.load(f)
agents = d.get('agent', {})
skills_dir = '$PROJECT_DIR/.opencode/skills'

def covered(path, allow_patterns):
    return any(fnmatch.fnmatch(path, pat) for pat in allow_patterns)

issues = []
for name, cfg in agents.items():
    if cfg.get('mode') == 'primary':
        continue
    wp = cfg.get('permission', {}).get('write', {})
    if wp == 'allow' or not isinstance(wp, dict):
        continue
    allow_pats = [p for p, v in wp.items() if v == 'allow']
    skill_file = os.path.join(skills_dir, name, 'SKILL.md')
    if not os.path.isfile(skill_file):
        continue
    content = open(skill_file).read()
    # 产出语境：行内包含 输出/产出/写入/生成 关键词，且引用具体的 doc/ 或 src/ 文件路径
    # 只匹配"以文件名结尾"的路径（xxx.md / xxx.py 等），目录引用（doc/detailed/）视为只读参考
    for m in re.finditer(r'\`((?:doc|src|tests|frontend)/[^\s\`]+/[^\s\`]+\.[a-z]+)\`', content):
        p = m.group(1)
        if covered(p, allow_pats):
            continue
        line_start = content.rfind('\n', 0, m.start()) + 1
        nxt = content.find('\n', m.start())
        line = content[line_start:nxt if nxt != -1 else len(content)]
        # 产出语境关键词；同时排除"禁止/不修改/只读/不改"等否定语境
        if not re.search(r'输出|产出|写入|生成', line):
            continue
        if re.search(r'禁止|不修改|只读|不改|跳过', line):
            continue
        issues.append(f'  ⚠️  {name}: 产出声明 {p} 不在 write 白名单 {allow_pats}')
for i in issues:
    print(i)
print(f'PERM_ISSUES={len(issues)}')
" 2>&1)
PERM_COUNT=$(echo "$PERM_MISMATCH" | grep -oE "PERM_ISSUES=[0-9]+" | cut -d= -f2)
echo "$PERM_MISMATCH" | grep -vE "PERM_ISSUES=" || true
if [ -z "$PERM_COUNT" ] || [ "$PERM_COUNT" -eq 0 ]; then
  echo "  权限契约一致 ✅"
else
  echo "  ⚠️  检测到 $PERM_COUNT 处权限契约不一致（产出声明超出 write 白名单）"
  WARNINGS=$((WARNINGS + 1))
fi

# ---- 汇总 ----
echo ""
echo "=== 自举检查汇总 ==="
echo "阻断: $ERRORS | 警告: $WARNINGS"
if [ "$ERRORS" -gt 0 ]; then
  echo "❌ 自举检查不通过，$ERRORS 个阻断问题"
  exit 2
elif [ "$WARNINGS" -gt 0 ]; then
  echo "⚠️  自举检查有条件通过，$WARNINGS 个警告"
  exit 1
else
  echo "✅ 自举检查通过"
  exit 0
fi
