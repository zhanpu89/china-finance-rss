#!/usr/bin/env bash
# 检查代码产出物（含编译/类型检查）
# 返回: 0=通过, 1=失败

SRC_DIR="src"
ERRORS=0

if [ ! -d "$SRC_DIR" ]; then
  echo "❌ src 目录不存在"
  exit 1
fi

# 统计各语言文件
echo "文件统计:"
find "$SRC_DIR" -type f \( -name "*.java" -o -name "*.py" -o -name "*.go" -o -name "*.ts" -o -name "*.js" -o -name "*.vue" -o -name "*.rs" \) 2>/dev/null | awk -F. '{counts[$NF]++} END{for(ext in counts) printf "  %s: %d files\n", ext, counts[ext]}'

TOTAL_FILES=$(find "$SRC_DIR" -type f 2>/dev/null | wc -l)
echo "  总文件数: $TOTAL_FILES"

if [ "$TOTAL_FILES" -eq 0 ]; then
  echo "❌ src 目录为空"
  exit 1
fi

# 检查空文件
EMPTY_FILES=$(find "$SRC_DIR" -type f -empty 2>/dev/null | wc -l)
[ "$EMPTY_FILES" -gt 0 ] && echo "⚠️  空文件: $EMPTY_FILES 个" && ERRORS=$((ERRORS + EMPTY_FILES))

# ---- 编译/类型检查 ----
PROJECT_DIR="$(dirname "$0")/../.."
cd "$PROJECT_DIR" || exit 1

echo ""
echo "编译/类型检查:"

if [ -f "pom.xml" ]; then
  echo "  📦 检测到 Maven (Java)"
  if command -v mvn &>/dev/null; then
    mvn compile -q 2>&1 | head -20 && echo "  ✅ Maven 编译通过" || { echo "  ❌ Maven 编译失败"; ERRORS=$((ERRORS + 1)); }
  elif [ -f "mvnw" ]; then
    ./mvnw compile -q 2>&1 | head -20 && echo "  ✅ Maven 编译通过" || { echo "  ❌ Maven 编译失败"; ERRORS=$((ERRORS + 1)); }
  else
    echo "  ⚠️  mvn/mvnw 不可用，跳过编译"
  fi
elif [ -f "build.gradle" ] || [ -f "build.gradle.kts" ]; then
  echo "  📦 检测到 Gradle (Java/Kotlin)"
  if [ -f "gradlew" ]; then
    ./gradlew compileJava -q 2>&1 | tail -5 && echo "  ✅ Gradle 编译通过" || { echo "  ❌ Gradle 编译失败"; ERRORS=$((ERRORS + 1)); }
  else
    echo "  ⚠️  gradlew 不可用，跳过编译"
  fi
elif [ -f "go.mod" ]; then
  echo "  📦 检测到 Go"
  if command -v go &>/dev/null; then
    go build ./... 2>&1 && echo "  ✅ Go 编译通过" || { echo "  ❌ Go 编译失败"; ERRORS=$((ERRORS + 1)); }
  else
    echo "  ⚠️  go 不可用，跳过编译"
  fi
elif [ -f "Cargo.toml" ]; then
  echo "  📦 检测到 Rust/Cargo"
  if command -v cargo &>/dev/null; then
    cargo check 2>&1 | tail -5 && echo "  ✅ Cargo check 通过" || { echo "  ❌ Cargo check 失败"; ERRORS=$((ERRORS + 1)); }
  else
    echo "  ⚠️  cargo 不可用，跳过编译"
  fi
elif [ -f "package.json" ]; then
  echo "  📦 检测到 Node.js"
  if [ -f "tsconfig.json" ]; then
    if command -v npx &>/dev/null; then
      npx tsc --noEmit 2>&1 | head -30 && echo "  ✅ TypeScript 类型检查通过" || { echo "  ❌ TypeScript 类型检查失败"; ERRORS=$((ERRORS + 1)); }
    else
      echo "  ⚠️  npx 不可用，跳过类型检查"
    fi
  else
    # 纯 JS 项目：尝试 node --check 语法验证
    JS_FILES=$(find "$SRC_DIR" -name "*.js" -type f 2>/dev/null)
    if [ -n "$JS_FILES" ] && command -v node &>/dev/null; then
      SYNTAX_OK=true
      for jsf in $JS_FILES; do
        node --check "$jsf" 2>/dev/null || { SYNTAX_OK=false; echo "  ❌ 语法错误: $jsf"; ERRORS=$((ERRORS + 1)); }
      done
      $SYNTAX_OK && echo "  ✅ JavaScript 语法检查通过"
    fi
  fi
elif [ -f "requirements.txt" ] || [ -f "setup.py" ] || [ -f "pyproject.toml" ]; then
  echo "  📦 检测到 Python"
  PY_FILES=$(find "$SRC_DIR" -name "*.py" -type f 2>/dev/null)
  if [ -n "$PY_FILES" ] && command -v python3 &>/dev/null; then
    SYNTAX_OK=true
    for pyf in $PY_FILES; do
      python3 -m py_compile "$pyf" 2>/dev/null || { SYNTAX_OK=false; ERRORS=$((ERRORS + 1)); echo "  ❌ 语法错误: $pyf"; }
    done
    $SYNTAX_OK && echo "  ✅ Python 语法检查通过"
  elif command -v python &>/dev/null; then
    SYNTAX_OK=true
    for pyf in $PY_FILES; do
      python -m py_compile "$pyf" 2>/dev/null || { SYNTAX_OK=false; ERRORS=$((ERRORS + 1)); echo "  ❌ 语法错误: $pyf"; }
    done
    $SYNTAX_OK && echo "  ✅ Python 语法检查通过"
  fi
else
  echo "  ℹ️  未识别项目类型，跳过编译检查"
fi

[ "$ERRORS" -eq 0 ] && echo "✅ 代码检查通过" || echo "⚠️ 代码检查完成，$ERRORS 个问题"
exit $([ "$ERRORS" -eq 0 ] && echo 0 || echo 1)
