#!/usr/bin/env bash
# 项目镜像约定回写 — 把 agent 学到的项目事实追加到 conventions.md 指定节
# 用法: mirror-log.sh "<节>" "<事实>"
#   节: 命名规范|分层与职责|异常与错误处理|事务与并发|配置管理|测试约定
#   fact 示例: "Go 结构体字段用驼峰命名，包名全小写"
# 幂等：同节同句不重复追加；色码输出。
set -euo pipefail

[ "$#" -lt 2 ] && { echo "用法: mirror-log.sh \"<节>\" \"<事实>\"" >&2; exit 1; }
SECTION="$1"; FACT="$2"

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(cd "$SCRIPT_DIR/../.." && pwd)"
MIRROR_DIR="$PROJECT_DIR/.opencode/project"
CONV="$MIRROR_DIR/conventions.md"

# 无镜像（未 init）→ 引导生成
if [ ! -f "$CONV" ]; then
  echo "  镜像不存在，先运行 project-init.sh" >&2
  exit 1
fi

# 幂等：同节同句已存在 → 跳过
if grep -qF -- "$FACT" "$CONV"; then
  echo "  · 已存在，跳过: [$SECTION] $FACT"
  exit 0
fi

# 章节归一化（映射到文件中的实际 ## 标题）
case "$SECTION" in
  命名*|naming)   HEAD="## 命名规范（提取中）";  PLAIN="## 命名规范";;
  分层*|layer*)   HEAD="## 分层与职责（提取中）"; PLAIN="## 分层与职责";;
  异常*|error*)   HEAD="## 异常与错误处理（提取中）"; PLAIN="## 异常与错误处理";;
  事务*|txn*)     HEAD="## 事务与并发（提取中）"; PLAIN="## 事务与并发";;
  配置*|config*)  HEAD="## 配置管理（提取中）"; PLAIN="## 配置管理";;
  测试*|test*|TC) HEAD="## 测试约定（提取中）"; PLAIN="## 测试约定";;
  *) HEAD="## 通用约定（提取中）"; PLAIN="## 通用约定";;
esac

# 在指定节头下追加一行 "- {fact}"
# 用 python3 执行（sed 的 & / | / \ 替换串会对含这些字符的事实注入破坏）
if grep -qF -- "$HEAD" "$CONV" || grep -qF -- "$PLAIN" "$CONV"; then
  python3 - "$CONV" "$HEAD" "$PLAIN" "$FACT" <<'PYEOF'
import sys
conv, head, plain, fact = sys.argv[1], sys.argv[2], sys.argv[3], sys.argv[4]
target = head if head in open(conv, encoding='utf-8').read() else plain
lines = open(conv, encoding='utf-8').read().splitlines(keepends=True)
out = []
inserted = False
for ln in lines:
    out.append(ln)
    if not inserted and ln.strip().rstrip('\n') == target:
        out.append(f"- {fact}\n")
        inserted = True
open(conv, 'w', encoding='utf-8').write(''.join(out))
if not inserted:
    sys.exit(2)
PYEOF
  echo "  ✅ [$SECTION] 已追加 → $CONV"
else
  # 无该节 → 追加到文件末尾（用 ## 统一层级，避免 ### ## 叠加）
  printf '\n## %s\n- %s\n' "${PLAIN#\#\# }" "$FACT" >> "$CONV"
  echo "  ✅ [$SECTION] 新增节 → $CONV"
fi