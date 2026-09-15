#!/usr/bin/env bash
# 项目镜像引导 — 将通用 pipeline 适配为当前项目的专职开发者
# 用法: bash project-init.sh [--force]
# 行为:
#   通用语言探测（Python/Java/Go/Node/Rust/polyglot + 前端框架 + 小程序）
#   → 生成 .opencode/project/manifest.json（机器可读）
#   → 生成 .opencode/project/profile.md（人+AI 可读画像）
#   → 生成 .opencode/project/conventions.md（从存量代码提取约定骨架）
#   → 确保 .opencode/project/.gitignore
# 幂等：已存在且非 --force 时跳过覆盖，仅补缺
set -euo pipefail

RED='\033[0;31m'; GREEN='\033[0;32m'; CYAN='\033[0;36m'; NC='\033[0m'
ok()   { echo -e "  ${GREEN}✅${NC} $1"; }
info() { echo -e "  ${CYAN}ℹ️${NC}  $1"; }
fail() { echo -e "  ${RED}❌${NC} $1"; exit 1; }

FORCE=false
[ "${1:-}" = "--force" ] && FORCE=true

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(cd "$SCRIPT_DIR/../.." && pwd)"
MIRROR_DIR="$PROJECT_DIR/.opencode/project"
cd "$PROJECT_DIR"

echo ""
echo -e "${CYAN}╔══════════════════════════════════════╗${NC}"
echo -e "${CYAN}║  项目镜像引导 project-init             ${NC}"
echo -e "${CYAN}╚══════════════════════════════════════╝${NC}"
echo "  项目目录: $PROJECT_DIR"

# ── 1. 通用语言探测（与 check-code.sh 保持一致的判定逻辑）──
LANG="unknown"; LANG_PRIMARY=""; LANGS=""
[ -f "pom.xml" ] || [ -f "build.gradle" ] || [ -f "build.gradle.kts" ] && LANGS="$LANGS java"
[ -f "go.mod" ] && LANGS="$LANGS go"
[ -f "Cargo.toml" ] && LANGS="$LANGS rust"
[ -f "package.json" ] && LANGS="$LANGS node"
[ -f "requirements.txt" ] || [ -f "setup.py" ] || [ -f "pyproject.toml" ] && LANGS="$LANGS python"

# 去重 + 定主语言（polyglot 时按出现顺序取第一）
LANGS=$(echo "$LANGS" | tr ' ' '\n' | grep -v '^$' | sort -u | tr '\n' ' ' || true)
LANG_PRIMARY=$(echo "$LANGS" | awk '{print $1}')
[ "$(echo "$LANGS" | wc -w)" -gt 1 ] && LANG="polyglot" || LANG="$LANG_PRIMARY"
[ -z "$LANG" ] && LANG="unknown"

# ── 前端 / 小程序探测 ──
FE="none"; MP="none"
if [ -f "package.json" ]; then
  grep -qi '"vue"' package.json && FE="vue"
  grep -qi '"react"' package.json && FE="react"
  grep -qi '"@angular' package.json && FE="angular"
fi
[ -d "miniprogram" ] || [ -d "weapp" ] || [ -d "uni-app" ] && MP="miniprogram"

# ── 构建/测试命令探测 ──
BUILD_CMD=""; TEST_CMD=""
case "$LANG_PRIMARY" in
  java)  [ -f "pom.xml" ] && BUILD_CMD="mvn compile"; TEST_CMD="mvn test" ;;
  go)    BUILD_CMD="go build ./..."; TEST_CMD="go test ./..." ;;
  rust)  BUILD_CMD="cargo build"; TEST_CMD="cargo test" ;;
  node)  [ -f "package.json" ] && BUILD_CMD="npm run build 2>/dev/null || true"; TEST_CMD="npm test" ;;
  python) BUILD_CMD="python -m compileall -q . 2>/dev/null || true"; TEST_CMD="pytest 2>/dev/null || python -m pytest" ;;
esac

# ── 来源目录探测 ──
SRC_DIRS=""
for d in src app service server api core lib backend; do
  [ -d "$d" ] && SRC_DIRS="$SRC_DIRS $d"
done
TEST_DIRS=""
for d in src/test tests test __tests__ test/; do
  [ -e "$d" ] && TEST_DIRS="$TEST_DIRS $d"
done
[ -z "$SRC_DIRS" ] && info "未发现常见源码目录，可在 profile.md 手工补充（src/app/service 等）"

# ── 2. 生成 manifest.json ──
mkdir -p "$MIRROR_DIR"
MANIFEST="$MIRROR_DIR/manifest.json"

# 数组字段：转成 JSON 数组的字符串（空输入 → []）
to_json_arr() {
  echo "$1" | tr ' ' '\n' | grep -v '^$' | sed 's/.*/"&"/' | paste -sd, - 2>/dev/null || true
}
SRC_ARR=$(to_json_arr "$SRC_DIRS")
TEST_ARR=$(to_json_arr "$TEST_DIRS")

gen_manifest() {
cat > "$MANIFEST" <<EOF
{
  "schema_version": 1,
  "project": "$(basename "$PROJECT_DIR")",
  "language": "$LANG",
  "languages": [$(echo "$LANGS" | awk '{for(i=1;i<=NF;i++) printf "\"%s\"%s", $i, (i<NF?",":"")}')],
  "primary_language": "$LANG_PRIMARY",
  "frontend": "$FE",
  "miniprogram": "$MP",
  "source_dirs": [$SRC_ARR],
  "test_dirs": [$TEST_ARR],
  "build_command": "$BUILD_CMD",
  "test_command": "$TEST_CMD",
  "init_ts": "$(date -u +%Y-%m-%dT%H:%M:%SZ)"
}
EOF
}
if [ ! -f "$MANIFEST" ] || [ "$FORCE" = true ]; then
  gen_manifest
  ok "manifest.json（$LANG / $LANG_PRIMARY / FE=$FE / MP=$MP）"
else
  info "manifest.json 已存在（--force 覆盖）"
fi

# ── 3. 生成 profile.md ──
PROFILE="$MIRROR_DIR/profile.md"
if [ ! -f "$PROFILE" ] || [ "$FORCE" = true ]; then
cat > "$PROFILE" <<EOF
# 项目画像 Project Profile

> 由 project-init.sh 生成，是编排器与各 subagent 认识本项目的唯一权威画像。
> 技术/目录等自动探测字段由脚本维护；"项目特色/约束/踩坑"由 agent 持续补充。

## 技术与栈
- 主语言: **$LANG_PRIMARY**（检测到: $(echo "$LANGS" | sed 's/^ //;s/ /, /g' || echo 无)）
- 前端框架: ${FE:-none} | 小程序: ${MP:-none}
- 构建命令: \`${BUILD_CMD:-未检测}\`
- 测试命令: \`${TEST_CMD:-未检测}\`

## 目录结构
- 源码目录: $(echo "$SRC_DIRS" | sed 's/^ //;s/ /, /g')
- 测试目录: $(echo "$TEST_DIRS" | sed 's/^ //;s/ /, /g')

## 分层约定（由 agent 从存量代码提取后补充）
- _（首次生成的占位，后续由 code-developer/task-decomposer 填充）_

## 项目特色 / 约束 / 踩坑（agent 持续追加）
- _（例如：本项目的异常处理统一走全局拦截器；封账逻辑不可并发）_

## 需要人工确认的点
- _（探测不准的地方，手工修正后 --force 或直接编辑）_
EOF
  ok "profile.md"
else
  info "profile.md 已存在（--force 覆盖）"
fi

# ── 4. 生成 conventions.md（约定骨架）──
CONV="$MIRROR_DIR/conventions.md"
if [ ! -f "$CONV" ] || [ "$FORCE" = true ]; then
cat > "$CONV" <<EOF
# 项目约定 Project Conventions

> 由 project-init.sh 生成骨架，由 agent 在编码/评审中持续提炼。
> 约定来源：存量代码的实际模式（命名/分层/异常/事务/配置），不是臆想。

## 命名规范（提取中）
- _（如：Go 结构体驼峰、Python 模块下划线、Java 服务接口以 Service 结尾）_

## 分层与职责（提取中）
- _（如：controller→service→repository；Go 按 domain 目录分层）_

## 异常与错误处理（提取中）
- _（如：统一错误码、全局异常拦截、日志规范）_

## 事务与并发（提取中）
- _（如：写操作用事务注解；封账逻辑加锁）_

## 配置管理（提取中）
- _（如：配置走 config 文件；敏感信息走环境变量）_

## 测试约定（提取中）
- _（如：测试数据用 fixture；集成测试独立库）_
EOF
  ok "conventions.md（骨架）"
else
  info "conventions.md 已存在（--force 覆盖）"
fi

# ── 5. 确保 .gitignore ──
GI="$MIRROR_DIR/.gitignore"
if [ ! -f "$GI" ]; then
cat > "$GI" <<EOF
# 项目镜像：经验类产物不纳入 git（可重建），画像/约定纳入版本管理
experience.md
*.cache
EOF
  ok ".gitignore"
fi

echo ""
echo -e "${GREEN}══════════════════════════════════════${NC}"
echo -e "${GREEN}  项目镜像就绪 ✓${NC}"
echo -e "${GREEN}  编排器可从 .opencode/project/ 认识本项目${NC}"
echo -e "${GREEN}══════════════════════════════════════${NC}"
