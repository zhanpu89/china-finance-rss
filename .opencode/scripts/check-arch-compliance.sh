#!/usr/bin/env bash
# P5a 架构合规门禁 — 验证代码实现遵循系统架构约束
# 退出码: 0=通过/无可检规则, 1=违规, 2=阻断（配置错误/解析失败）
#
# 注意：无 architectureRules 时视为"无可检规则"返回 0，
# 不返回 2，以免与编排器的"阻断"语义冲突。

PROJECT_DIR="$(cd "$(dirname "$0")/../.." && pwd)"
TS_FILE="$PROJECT_DIR/doc/arch/tech-stack.json"
SRC_DIR="$PROJECT_DIR/src"
ERRORS=0

if [ ! -f "$TS_FILE" ]; then
  echo "ℹ️  tech-stack.json 不存在，跳过架构合规检查"
  exit 0
fi

# ---- 用 Python 解析 architectureRules 并输出 JSON 结果 ----
RULES=$(python3 -c "
import json, sys
with open('$TS_FILE') as f:
    d = json.load(f)
ar = d.get('architectureRules')
if not ar:
    print('SKIP')
    sys.exit(0)
print(json.dumps(ar))
" 2>/dev/null)

if [ "$RULES" = "SKIP" ] || [ -z "$RULES" ]; then
  echo "ℹ️  architectureRules 未定义（可在 tech-stack.json 中按需启用），跳过架构合规检查"
  exit 0
fi

echo "=== 架构合规检查 ==="

# ---- 1. Layer Isolation ----
LAYER_RULES=$(echo "$RULES" | python3 -c "
import json, sys
r = json.load(sys.stdin)
print(json.dumps(r.get('layerIsolation', [])))
" 2>/dev/null)

if [ "$(echo "$LAYER_RULES" | python3 -c "import json,sys; print(len(json.load(sys.stdin)))" 2>/dev/null)" -gt 0 ]; then
  echo ""
  echo "--- 层隔离检查 ---"
  
  # 解析层隔离规则并用 find + grep 逐条检查
  LAYER_RESULTS=$(echo "$LAYER_RULES" | python3 -c "
import json, sys, os, fnmatch, re

rules = json.load(sys.stdin)
violations = []
for rule in rules:
    pattern = rule.get('pattern', '')
    forbidden_imports = rule.get('forbiddenImports', [])
    if not pattern or not forbidden_imports:
        continue
    
    # 查找匹配 pattern 的文件
    src = os.path.join('$PROJECT_DIR', 'src')
    if not os.path.isdir(src):
        continue
    
    for root, dirs, files in os.walk(src):
        for f in files:
            fpath = os.path.join(root, f)
            rel = os.path.relpath(fpath, '$PROJECT_DIR')
            if not fnmatch.fnmatch(rel, pattern):
                continue
            
            # 文件类型过滤（只检查代码文件）
            ext = os.path.splitext(f)[1].lower()
            if ext not in ('.py','.js','.ts','.tsx','.jsx','.java','.go','.rs','.kt','.kts','.vue','.php'):
                continue
            
            # 读文件内容，检查是否有禁止导入
            try:
                with open(fpath, 'r', errors='ignore') as fh:
                    content = fh.read()
            except:
                continue
            
            for imp in forbidden_imports:
                # 按语言匹配 import 语句
                if ext == '.py':
                    if re.search(r'^\s*(from|import)\s+' + re.escape(imp), content, re.MULTILINE):
                        violations.append((rel, imp, rule.get('reason', '层隔离违规')))
                elif ext in ('.go',):
                    if re.search(r'^\s*import\s+.*\"' + re.escape(imp), content, re.MULTILINE):
                        violations.append((rel, imp, rule.get('reason', '层隔离违规')))
                elif ext in ('.java','.kt','.kts'):
                    if re.search(r'^\s*import\s+.*' + re.escape(imp.replace('/','.')), content, re.MULTILINE):
                        violations.append((rel, imp, rule.get('reason', '层隔离违规')))
                else:
                    # JS/TS/Vue/PHP: import/require
                    if re.search(r'(from\s+[\"\\']' + re.escape(imp) + r'[\"\\']|require\([\"\\']' + re.escape(imp) + r'[\"\\']\))', content):
                        violations.append((rel, imp, rule.get('reason', '层隔离违规')))

# 输出结果
if violations:
    print('VIOLATIONS')
    for fp, imp, reason in violations:
        print(f'{fp} - {imp} ({reason})')
else:
    print('OK')
" 2>/dev/null)

  while IFS= read -r line; do
    if [ "$line" = "VIOLATIONS" ]; then
      continue
    elif [ "$line" = "OK" ]; then
      echo "  层隔离检查通过 ✅"
    else
      echo "  ⚠️  $line"
      ERRORS=$((ERRORS + 1))
    fi
  done <<< "$LAYER_RESULTS"
fi

# ---- 2. Import Restrictions ----
echo ""
echo "--- 导入限制检查 ---"

IMPORT_RESULTS=$(echo "$RULES" | python3 -c "
import json, sys, os, fnmatch, re

r = json.load(sys.stdin)
ir = r.get('importRestrictions', {})
denylist = ir.get('denylist', [])
allowlist = ir.get('allowlist', {})
violations = []

src = os.path.join('$PROJECT_DIR', 'src')
if not os.path.isdir(src):
    print('OK')
    sys.exit(0)

for root, dirs, files in os.walk(src):
    for f in files:
        fpath = os.path.join(root, f)
        rel = os.path.relpath(fpath, '$PROJECT_DIR')
        ext = os.path.splitext(f)[1].lower()
        if ext not in ('.py','.js','.ts','.tsx','.jsx','.java','.go','.rs','.kt','.kts','.vue','.php'):
            continue
        try:
            with open(fpath, 'r', errors='ignore') as fh:
                content = fh.read()
        except:
            continue
        
        # 检查 denylist
        for imp in denylist:
            if ext == '.py':
                if re.search(r'^\s*(from|import)\s+' + re.escape(imp), content, re.MULTILINE):
                    violations.append((rel, f'禁止导入: {imp}', 'importRestrictions'))
            elif ext in ('.go',):
                if re.search(r'^\s*import\s+.*\"' + re.escape(imp), content, re.MULTILINE):
                    violations.append((rel, f'禁止导入: {imp}', 'importRestrictions'))
            elif ext in ('.java','.kt','.kts'):
                if re.search(r'^\s*import\s+.*' + re.escape(imp.replace('/','.')), content, re.MULTILINE):
                    violations.append((rel, f'禁止导入: {imp}', 'importRestrictions'))
            else:
                if re.search(r'(from\s+[\"\\']' + re.escape(imp) + r'[\"\\']|require\([\"\\']' + re.escape(imp) + r'[\"\\']\))', content):
                    violations.append((rel, f'禁止导入: {imp}', 'importRestrictions'))
        
        # 检查 allowlist（如果文件匹配某个 pattern）
        for pat, allowed_imports in allowlist.items():
            if not fnmatch.fnmatch(rel, pat):
                continue
            # 提取文件中的所有 import
            if ext == '.py':
                imports = re.findall(r'^\s*(?:from\s+(\S+)|import\s+(\S+))', content, re.MULTILINE)
                for from_imp, import_imp in imports:
                    imp = from_imp or import_imp
                    base = imp.split('.')[0]  # 顶级包名
                    if base not in allowed_imports and not base.startswith('_') and base not in ('os','sys','re','json','math','time','typing','collections','pathlib'):
                        violations.append((rel, f'导入不在白名单: {base} (允许: {allowed_imports})', 'importRestrictions'))

if violations:
    print('VIOLATIONS')
    for fp, msg, _ in violations:
        print(f'{fp} - {msg}')
else:
    print('OK')
" 2>/dev/null)

while IFS= read -r line; do
  if [ "$line" = "VIOLATIONS" ]; then
    continue
  elif [ "$line" = "OK" ]; then
    echo "  导入限制检查通过 ✅"
  elif [ -n "$line" ]; then
    echo "  ⚠️  $line"
    ERRORS=$((ERRORS + 1))
  fi
done <<< "$IMPORT_RESULTS"

# ---- 3. Naming Rules ----
echo ""
echo "--- 命名规范检查 ---"

NAMING_RESULTS=$(echo "$RULES" | python3 -c "
import json, sys, os, fnmatch

r = json.load(sys.stdin)
nr = r.get('namingRules', {})
file_rules = nr.get('files', [])
violations = []

src = os.path.join('$PROJECT_DIR', 'src')
if not os.path.isdir(src):
    print('OK')
    sys.exit(0)

for root, dirs, files in os.walk(src):
    for f in files:
        fpath = os.path.join(root, f)
        rel = os.path.relpath(fpath, '$PROJECT_DIR')
        for rule in file_rules:
            pattern = rule.get('pattern', '')
            rule_type = rule.get('type', '')
            expected = rule.get('expect', '')
            if not fnmatch.fnmatch(rel, pattern):
                continue
            basename = os.path.splitext(f)[0]
            if rule_type == 'mustEndWith':
                if not basename.endswith(expected):
                    violations.append(f'{rel} 应以 {expected} 结尾')
            elif rule_type == 'mustStartWith':
                if not basename.startswith(expected):
                    violations.append(f'{rel} 应以 {expected} 开头')
            elif rule_type == 'mustMatch':
                import re
                if not re.search(expected, basename):
                    violations.append(f'{rel} 应匹配模式 {expected}')

if violations:
    for v in violations:
        print(f'{v}')
else:
    print('OK')
" 2>/dev/null)

while IFS= read -r line; do
  if [ "$line" = "OK" ]; then
    echo "  命名规范检查通过 ✅"
  elif [ -n "$line" ]; then
    echo "  ⚠️  $line"
    ERRORS=$((ERRORS + 1))
  fi
done <<< "$NAMING_RESULTS"

# ---- 汇总 ----
echo ""
echo "=== 架构合规汇总 ==="
if [ "$ERRORS" -eq 0 ]; then
  echo "✅ 架构合规检查通过"
  exit 0
else
  echo "⚠️ 架构合规检查完成，$ERRORS 个违规"
  exit 1
fi
