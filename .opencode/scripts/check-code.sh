#!/usr/bin/env bash
# 检查代码产出物（含编译/类型检查）
# 退出码: 0=通过, 1=失败

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

# ---- 项目类型检测 ----
PROJECT_DIR="$(dirname "$0")/../.."
cd "$PROJECT_DIR" || exit 1

PROJECT_TYPE="unknown"
# 单类型检测（均带 unknown 守卫，防止互相覆盖）
[ -f "pom.xml" ] || [ -f "build.gradle" ] || [ -f "build.gradle.kts" ] && [ "$PROJECT_TYPE" = "unknown" ] && PROJECT_TYPE="java"
[ -f "go.mod" ] && [ "$PROJECT_TYPE" = "unknown" ] && PROJECT_TYPE="go"
[ -f "Cargo.toml" ] && [ "$PROJECT_TYPE" = "unknown" ] && PROJECT_TYPE="rust"
[ -f "package.json" ] && [ "$PROJECT_TYPE" = "unknown" ] && PROJECT_TYPE="node"
[ -f "requirements.txt" ] || [ -f "setup.py" ] || [ -f "pyproject.toml" ] && [ "$PROJECT_TYPE" = "unknown" ] && PROJECT_TYPE="python"
# polyglot 检测（优先覆盖单类型）
[ -f "package.json" ] && ( [ -f "pyproject.toml" ] || [ -f "requirements.txt" ] || [ -f "setup.py" ] ) && PROJECT_TYPE="polyglot"
[ -f "pom.xml" ] && [ -f "package.json" ] && PROJECT_TYPE="polyglot"

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
    # 类型检查（mypy / pyright）
    if command -v mypy &>/dev/null; then
      echo "  📋 mypy 类型检查..."
      mypy "$SRC_DIR" 2>&1 | tail -10 && echo "  ✅ mypy 通过" || { echo "  ❌ mypy 类型检查失败"; ERRORS=$((ERRORS + 1)); }
    elif command -v pyright &>/dev/null; then
      echo "  📋 pyright 类型检查..."
      pyright "$SRC_DIR" 2>&1 | tail -10 && echo "  ✅ pyright 通过" || { echo "  ❌ pyright 类型检查失败"; ERRORS=$((ERRORS + 1)); }
    else
      echo "  ℹ️  mypy/pyright 不可用，跳过类型检查"
    fi
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

# ---- Lint 检查（基于项目类型）----
echo ""
echo "Lint 检查:"

case "$PROJECT_TYPE" in
  node|polyglot)
    # ESLint for JS/TS
    ESLINT_CFG=""
    for cfg in .eslintrc .eslintrc.json .eslintrc.js .eslintrc.yaml eslint.config.js .eslintrc.mjs; do
      [ -f "$cfg" ] && ESLINT_CFG="$cfg" && break
    done
    if [ -n "$ESLINT_CFG" ] && command -v npx &>/dev/null; then
      echo "  📋 检测到 ESLint 配置: $ESLINT_CFG"
      npx eslint "$SRC_DIR" --max-warnings=10 2>&1 | tail -5 && echo "  ✅ ESLint 通过" || { echo "  ❌ ESLint 警告数超过 10"; ERRORS=$((ERRORS + 1)); }
    else
      echo "  ℹ️  未配置 ESLint，跳过 JS/TS lint"
    fi
    ;;&
  python|polyglot)
    # Ruff for Python
    if command -v ruff &>/dev/null; then
      echo "  📋 检测到 Ruff (Python)"
      ruff check "$SRC_DIR" --quiet 2>&1 | tail -5 && echo "  ✅ Ruff 检查通过" || echo "  ⚠️ Ruff 发现问题（不影响门禁）"
    elif command -v pylint &>/dev/null; then
      echo "  📋 检测到 Pylint (Python)"
      pylint "$SRC_DIR" --disable=C,R 2>&1 | tail -5 && echo "  ✅ Pylint 通过" || echo "  ⚠️ Pylint 发现问题（不影响门禁）"
    else
      echo "  ℹ️  ruff/pylint 不可用，跳过 Python lint"
    fi
    ;;&
  java|go|rust|unknown)
    echo "  ℹ️  $PROJECT_TYPE 项目无内置 lint 配置，跳过"
    ;;
esac

# ---- 结构性内聚检查（防止打补丁式散落修改）----
echo ""
echo "结构性内聚检查:"

if git rev-parse --git-dir &>/dev/null; then
  # 有 Git：检查未提交的变更文件数
  CHANGED_FILES=$(git diff --name-only --diff-filter=AM 2>/dev/null | grep -v "^.opencode/" | wc -l)
  CHANGED_LIST=$(git diff --name-only --diff-filter=AM 2>/dev/null | grep -v "^.opencode/" || true)

  # 也包含已 staged 的文件
  STAGED_FILES=$(git diff --cached --name-only --diff-filter=AM 2>/dev/null | grep -v "^.opencode/" | wc -l)
  CHANGED_FILES=$((CHANGED_FILES + STAGED_FILES))
  if [ -n "$CHANGED_LIST" ]; then
    STAGED_LIST=$(git diff --cached --name-only --diff-filter=AM 2>/dev/null | grep -v "^.opencode/" || true)
    CHANGED_LIST=$(echo -e "$CHANGED_LIST\n$STAGED_LIST" | sort -u)
  fi

  echo "  修改文件数: $CHANGED_FILES"

  # 简单修改却改了大量文件 -> 疑似散落（阈值 8）
  if [ "$CHANGED_FILES" -gt 8 ]; then
    echo "  ⚠️  修改文件过多（$CHANGED_FILES > 8），可能是打补丁式散落修改"
    echo "  修改清单:"
    echo "$CHANGED_LIST" | head -20
    [ "$(echo "$CHANGED_LIST" | wc -l)" -gt 20 ] && echo "  ... (共 $CHANGED_FILES 个)"
  else
    echo "  ✅ 修改集中度正常"
  fi

  # 检测同一类/函数名是否在多个文件中出现（重复定义风险）
  for pattern in "class " "def " "function " "interface "; do
    DUP_COUNT=$(echo "$CHANGED_LIST" | grep -v "^.opencode/" | xargs -r grep -l "$pattern" 2>/dev/null | sort -u | wc -l)
    if [ "$DUP_COUNT" -gt 1 ]; then
      # 检查是否有同名定义
      for search_word in $(echo "$CHANGED_LIST" | xargs -r grep -h "$pattern" 2>/dev/null | awk '{print $2}' | sort -u); do
        OCCURRENCES=$(echo "$CHANGED_LIST" | xargs -r grep -l "${pattern}${search_word}" 2>/dev/null | wc -l)
        if [ "$OCCURRENCES" -gt 1 ]; then
          echo "  ⚠️  '${pattern}${search_word}' 在 $OCCURRENCES 个文件中出现，可能是重复定义"
        fi
      done
    fi
  done
else
  # 无 Git：仅统计源文件总数（信息性）
  TOTAL=$(find "$SRC_DIR" -type f 2>/dev/null | wc -l)
  echo "  ℹ️  无 Git 仓库，仅做文件计数: $TOTAL 个源文件（跳过变更检测）"
fi

# ---- 验证 SCOPE 声明文件真实存在 ----
echo ""
echo "SCOPE 文件真实性验证:"
if [ -f "_MEMORY_CACHE.md" ]; then
  SCOPE_FILES=$(grep -oE '(files[=:][^|#]+)' _MEMORY_CACHE.md 2>/dev/null | head -1 | sed -E 's/.*files[=:]//' | tr ',' '\n' | xargs)
  if [ -n "$SCOPE_FILES" ]; then
    MISSING=0
    for sf in $SCOPE_FILES; do
      sf=$(echo "$sf" | xargs)
      if [ -n "$sf" ] && [ ! -f "$sf" ]; then
        echo "  ❌ SCOPE 声明的文件不存在: $sf"
        MISSING=$((MISSING + 1))
        ERRORS=$((ERRORS + 1))
      fi
    done
    [ "$MISSING" -eq 0 ] && echo "  ✅ SCOPE 文件全部存在"
  else
    echo "  ℹ️  未检测到 SCOPE 文件声明"
  fi
else
  echo "  ℹ️  无 _MEMORY_CACHE.md，跳过 SCOPE 验证"
fi

echo ""
[ "$ERRORS" -eq 0 ] && echo "✅ 代码检查通过" || echo "⚠️ 代码检查完成，$ERRORS 个问题"
exit $([ "$ERRORS" -eq 0 ] && echo 0 || echo 1)
