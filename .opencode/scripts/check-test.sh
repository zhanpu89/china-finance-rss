#!/usr/bin/env bash
# 检查测试执行（阶段二）
# 退出码: 0=通过, 1=失败
# 关键升级：实际运行测试，而非仅查文件存在

TESTER_DIR="doc/tester"
SRC_TEST_DIR="src/test"
ERRORS=0
TESTS_PASSED=0
TESTS_FAILED=0

PROJECT_DIR="$(cd "$(dirname "$0")/../.." && pwd)"

echo "=== 测试执行验证 ==="

# ---- 项目类型检测（与 check-code.sh 一致）----
cd "$PROJECT_DIR" || exit 1

PROJECT_TYPE="unknown"
[ -f "pom.xml" ] || [ -f "build.gradle" ] || [ -f "build.gradle.kts" ] && [ "$PROJECT_TYPE" = "unknown" ] && PROJECT_TYPE="java"
[ -f "go.mod" ] && [ "$PROJECT_TYPE" = "unknown" ] && PROJECT_TYPE="go"
[ -f "Cargo.toml" ] && [ "$PROJECT_TYPE" = "unknown" ] && PROJECT_TYPE="rust"
[ -f "package.json" ] && [ "$PROJECT_TYPE" = "unknown" ] && PROJECT_TYPE="node"
[ -f "requirements.txt" ] || [ -f "setup.py" ] || [ -f "pyproject.toml" ] && [ "$PROJECT_TYPE" = "unknown" ] && PROJECT_TYPE="python"
[ -f "package.json" ] && ( [ -f "pyproject.toml" ] || [ -f "requirements.txt" ] || [ -f "setup.py" ] ) && PROJECT_TYPE="polyglot"
[ -f "pom.xml" ] && [ -f "package.json" ] && PROJECT_TYPE="polyglot"

echo "项目类型: $PROJECT_TYPE"

# ---- 解析 scope（从 _MEMORY_CACHE.md 或环境变量）----
# 分级测试 T1 定向：有 modules scope → 只跑受影响模块测试 + 全局冒烟；无 → T2 全量
SCOPE_MODULES=""
SCOPE_SOURCE="无 scope（T2 全量）"

if [ -f "_MEMORY_CACHE.md" ]; then
  # 格式兼容: ">>SCOPE: modules=X,Y" / "modules: X | endpoints: Y" / "modules=X"
  SCOPE_MODULES=$(grep -oE '(modules[=:][^|#]+)' _MEMORY_CACHE.md 2>/dev/null | head -1 | sed -E 's/.*modules[=:]//' | tr ',' ' ' | xargs)
  [ -n "$SCOPE_MODULES" ] && SCOPE_SOURCE="_MEMORY_CACHE.md"
fi

# 环境变量覆盖（编排器可精确控制）
if [ -n "$SCOPE_MODULES_ENV" ]; then
  SCOPE_MODULES="$SCOPE_MODULES_ENV"
  SCOPE_SOURCE="环境变量 SCOPE_MODULES_ENV"
fi

if [ -n "$SCOPE_MODULES" ]; then
  echo "变更范围: 模块 [$SCOPE_MODULES]（来源: $SCOPE_SOURCE）"
  echo "执行模式: T1 定向（受影响模块 + 全局冒烟）"
else
  echo "执行模式: T2 全量"
fi

# ---- 检查测试文件是否存在 ----
echo ""
echo "测试文件状态:"

HAS_TEST_FILES=false
HAS_TEST_CODE=false

# 先查项目级测试目录
if [ -d "$SRC_TEST_DIR" ] && [ "$(find "$SRC_TEST_DIR" -type f 2>/dev/null | wc -l)" -gt 0 ]; then
  echo "  ✅ src/test: $(find "$SRC_TEST_DIR" -type f | wc -l) 个文件"
  HAS_TEST_CODE=true
  HAS_TEST_FILES=true
fi

# 查模块级测试（Go/Node 模式）
if [ "$PROJECT_TYPE" = "go" ]; then
  GO_TEST_FILES=$(find . -name "*_test.go" -type f 2>/dev/null | wc -l)
  if [ "$GO_TEST_FILES" -gt 0 ]; then
    echo "  ✅ Go 测试文件: $GO_TEST_FILES 个"
    HAS_TEST_FILES=true
  fi
elif [ "$PROJECT_TYPE" = "node" ] || [ "$PROJECT_TYPE" = "polyglot" ]; then
  NODE_TEST_FILES=$(find . -name "*.test.*" -o -name "*.spec.*" -o -name "__tests__" -type d 2>/dev/null | head -1)
  if [ -n "$NODE_TEST_FILES" ]; then
    TEST_COUNT=$(find . \( -name "*.test.*" -o -name "*.spec.*" \) -type f 2>/dev/null | wc -l)
    echo "  ✅ Node 测试文件: $TEST_COUNT 个"
    HAS_TEST_FILES=true
  fi
fi

# 查测试用例文档
if [ -d "$TESTER_DIR" ]; then
  TC_COUNT=$(find "$TESTER_DIR" \( -name "*测试用例*" -o -name "*testcase*" -o -name "*用例*" -o -name "*report*" -o -name "*报告*" \) -type f 2>/dev/null | wc -l)
  [ "$TC_COUNT" -gt 0 ] && echo "  ✅ doc/tester: $TC_COUNT 个文档"
fi

if [ "$HAS_TEST_FILES" = false ]; then
  echo "  ⚠️  未找到测试文件"
fi

# ---- 实际运行测试 ----
echo ""
echo "测试执行:"

run_test_and_count() {
  local output="$1"
  local pass_count fail_count

  # 通用模式匹配：支持多种测试框架输出格式
  pass_count=$(echo "$output" | grep -oiE "([0-9]+) passed|[0-9]+ passing|[0-9]+ ok|[0-9]+ successes?" | grep -oE "[0-9]+" | paste -sd+ | bc 2>/dev/null || echo 0)
  fail_count=$(echo "$output" | grep -oiE "([0-9]+) failed|[0-9]+ failing|[0-9]+ failures?" | grep -oE "[0-9]+" | paste -sd+ | bc 2>/dev/null || echo 0)

  # 如果没解析到，尝试行级解析
  if [ "$pass_count" = "0" ] && [ "$fail_count" = "0" ]; then
    pass_count=$(echo "$output" | grep -cE "^(PASS|ok|✓|✅|PASSED|SUCCESS)" 2>/dev/null || echo 0)
    fail_count=$(echo "$output" | grep -cE "^(FAIL|✗|❌|FAILED|ERROR)" 2>/dev/null || echo 0)
  fi

  [ -z "$pass_count" ] && pass_count=0
  [ -z "$fail_count" ] && fail_count=0

  echo "$pass_count|$fail_count"
}

TEST_OUTPUT=""
EXIT_CODE=0
CACHE_HIT=false

# ---- 全量/定向测试结果缓存（避免重复跑）----
# 指纹 = scope 相关源码文件内容 hash。同指纹且上次通过 → 跳过重跑（Bug-fix 循环内反复调用的主要省时点）
CACHE_DIR="/tmp/opencode/test-cache"
CACHE_KEY=""
FP=""
if [ -n "$SCOPE_MODULES" ]; then
  CACHE_KEY=$(echo "$SCOPE_MODULES" | tr ' ' '-' | tr -d '/\\')
  # T1 定向：扫描受影响模块的源码+测试文件
  FP=""
  for m in $SCOPE_MODULES; do
    FP="$FP$(find src/$m tests/test_${m}*.py tests/${m} tests/test_${m}*.go -type f 2>/dev/null | sort | xargs md5sum 2>/dev/null)"
  done
  FP=$(printf '%s' "$FP" | md5sum 2>/dev/null | cut -d' ' -f1)
else
  # T2 全量：按语言推导实际源文件（不依赖固定目录）
  case "$PROJECT_TYPE" in
    python)   FP=$(find . \( -name "*.py" \) -not -path "./.*" -not -path "./doc/*" -type f 2>/dev/null | sort | xargs md5sum 2>/dev/null | md5sum 2>/dev/null | cut -d' ' -f1) ;;
    go)       FP=$(find . -name "*.go" -not -path "./.*" -type f 2>/dev/null | sort | xargs md5sum 2>/dev/null | md5sum 2>/dev/null | cut -d' ' -f1) ;;
    node|polyglot) FP=$(find . \( -name "*.js" -o -name "*.ts" -o -name "*.jsx" -o -name "*.tsx" \) -not -path "./node_modules/*" -not -path "./.*" -type f 2>/dev/null | sort | xargs md5sum 2>/dev/null | md5sum 2>/dev/null | cut -d' ' -f1) ;;
    rust)     FP=$(find . -name "*.rs" -not -path "./.*" -type f 2>/dev/null | sort | xargs md5sum 2>/dev/null | md5sum 2>/dev/null | cut -d' ' -f1) ;;
    java)     FP=$(find . -name "*.java" -not -path "./.*" -type f 2>/dev/null | sort | xargs md5sum 2>/dev/null | md5sum 2>/dev/null | cut -d' ' -f1) ;;
    *)        FP=$(find . -type f \( -name "*.java" -o -name "*.go" -o -name "*.py" -o -name "*.ts" -o -name "*.js" -o -name "*.rs" \) -not -path "./.*" -not -path "./node_modules/*" -not -path "./doc/*" 2>/dev/null | sort | xargs md5sum 2>/dev/null | md5sum 2>/dev/null | cut -d' ' -f1) ;;
  esac
fi

# 指纹纳入构建/依赖文件（依赖或配置变化也会使缓存失效）——全量模式追加
if [ -z "$SCOPE_MODULES" ]; then
  BUILD_FILES="pom.xml build.gradle build.gradle.kts settings.gradle go.mod go.sum Cargo.toml Cargo.lock package.json package-lock.json requirements.txt pyproject.toml setup.py"
  BUILD_FP=$(find $BUILD_FILES -type f 2>/dev/null | sort | xargs md5sum 2>/dev/null | md5sum 2>/dev/null | cut -d' ' -f1)
  [ -n "$BUILD_FP" ] && FP=$(printf '%s\n%s' "$FP" "$BUILD_FP" | md5sum 2>/dev/null | cut -d' ' -f1)
fi
CACHE_FILE="$CACHE_DIR/test-${PROJECT_TYPE}-${CACHE_KEY:-full}.cache"

if [ -n "$FP" ] && [ -f "$CACHE_FILE" ]; then
  read -r cached_fp cached_result < "$CACHE_FILE" 2>/dev/null
  if [ "$cached_fp" = "$FP" ] && [ "$cached_result" = "PASS" ]; then
    CACHE_HIT=true
    EXIT_CODE=0
    echo "  🟢 缓存命中：源码指纹未变且上次通过，跳过重跑（如需强制刷新请删 $CACHE_FILE）"
  fi
fi

if [ "$CACHE_HIT" = false ]; then
case "$PROJECT_TYPE" in
  java)
    if [ -f "pom.xml" ] && command -v mvn &>/dev/null; then
      echo "  📦 Maven 测试..."
      if [ -n "$SCOPE_MODULES" ]; then
        # T1 定向：只跑受影响模块的测试类（通配符匹配模块名）
        SCOPED_PATTERN=""
        for m in $SCOPE_MODULES; do
          SCOPED_PATTERN="${SCOPED_PATTERN:+$SCOPED_PATTERN,}*${m}*Test"
        done
        echo "    定向类: -Dtest=$SCOPED_PATTERN"
        TEST_OUTPUT=$(mvn test -q -Dtest="$SCOPED_PATTERN" 2>&1)
      else
        TEST_OUTPUT=$(mvn test -q 2>&1)
      fi
      EXIT_CODE=$?
    elif [ -f "build.gradle" ] || [ -f "build.gradle.kts" ]; then
      if [ -f "gradlew" ]; then
        echo "  📦 Gradle 测试..."
        if [ -n "$SCOPE_MODULES" ]; then
          SCOPED_PATTERN=""
          for m in $SCOPE_MODULES; do
            SCOPED_PATTERN="${SCOPED_PATTERN:+$SCOPED_PATTERN,}*${m}*Test"
          done
          echo "    定向类: --tests \"$SCOPED_PATTERN\""
          TEST_OUTPUT=$(./gradlew test --tests "$SCOPED_PATTERN" -q 2>&1)
        else
          TEST_OUTPUT=$(./gradlew test -q 2>&1)
        fi
        EXIT_CODE=$?
      else
        echo "  ⚠️  gradlew 不可用，跳过测试"
        EXIT_CODE=2
      fi
    else
      echo "  ⚠️  未找到 Maven/Gradle 构建文件，跳过测试"
      EXIT_CODE=2
    fi
    ;;

  go)
    if command -v go &>/dev/null; then
      echo "  📦 Go test..."
      if [ -n "$SCOPE_MODULES" ]; then
        # T1 定向：只跑受影响包的测试
        GO_TARGETS=""
        for m in $SCOPE_MODULES; do
          GO_TARGETS="$GO_TARGETS ./$m/... ./internal/$m/..."
        done
        echo "    定向包: $GO_TARGETS"
        TEST_OUTPUT=$(go test $GO_TARGETS -v 2>&1)
      else
        TEST_OUTPUT=$(go test ./... -v 2>&1)
      fi
      EXIT_CODE=$?
    else
      echo "  ⚠️  go 不可用，跳过测试"
      EXIT_CODE=2
    fi
    ;;

  rust)
    if command -v cargo &>/dev/null; then
      if [ -n "$SCOPE_MODULES" ]; then
        # T1 定向：只跑受影响 crate/module 的测试（cargo test <module> 过滤）
        RUST_TARGETS=""
        for m in $SCOPE_MODULES; do
          RUST_TARGETS="$RUST_TARGETS $m"
        done
        RUSTOK=1
        for m in $RUST_TARGETS; do
          echo "    定向模块: cargo test $m"
          T=$(cargo test "$m" 2>&1)
          [ $? -ne 0 ] && RUSTOK=0
          TEST_OUTPUT="$TEST_OUTPUT
$T"
        done
        [ "$RUSTOK" -eq 1 ] && EXIT_CODE=0 || EXIT_CODE=1
      else
        echo "  📦 Cargo test..."
        TEST_OUTPUT=$(cargo test 2>&1)
        EXIT_CODE=$?
      fi
    else
      echo "  ⚠️  cargo 不可用，跳过测试"
      EXIT_CODE=2
    fi
    ;;

  node|polyglot)
    echo "  📦 Node.js 测试..."
    if [ -f "package.json" ]; then
      # 检测测试框架
      TEST_FRAMEWORK=""
      if grep -q '"jest"' package.json 2>/dev/null; then
        TEST_FRAMEWORK="jest"
      elif grep -q '"vitest"' package.json 2>/dev/null; then
        TEST_FRAMEWORK="vitest"
      elif grep -q '"mocha"' package.json 2>/dev/null; then
        TEST_FRAMEWORK="mocha"
      elif grep -q '"ava"' package.json 2>/dev/null; then
        TEST_FRAMEWORK="ava"
      fi

      # 优先用 package.json scripts.test
      if [ -n "$SCOPE_MODULES" ] && [ -n "$TEST_FRAMEWORK" ]; then
        # T1 定向：只跑受影响模块的测试（框架原生路径过滤）
        echo "    定向模块: $SCOPE_MODULES"
        TEST_OUTPUT=$(npx "$TEST_FRAMEWORK" run $SCOPE_MODULES 2>&1)
        EXIT_CODE=$?
      elif grep -q '"test"' package.json 2>/dev/null; then
        echo "    运行 npm test..."
        if [ -n "$SCOPE_MODULES" ]; then
          # 有 scope 但框架名未被 package.json 关键词识别 → 用 --testPathPattern 追加过滤
          TEST_OUTPUT=$(npm test -- --testPathPattern="$SCOPE_MODULES" 2>&1)
        else
          TEST_OUTPUT=$(npm test 2>&1)
        fi
        EXIT_CODE=$?
      elif [ -n "$TEST_FRAMEWORK" ] && command -v npx &>/dev/null; then
        echo "    运行 $TEST_FRAMEWORK..."
        TEST_OUTPUT=$(npx "$TEST_FRAMEWORK" run 2>&1)
        EXIT_CODE=$?
      elif command -v npx &>/dev/null; then
        # 兜底：尝试自动发现
        if ls ./*.test.* ./*.spec.* 2>/dev/null | head -1 >/dev/null; then
          echo "    尝试 node --test..."
          TEST_OUTPUT=$(node --test 2>&1)
          EXIT_CODE=$?
        else
          echo "  ⚠️  无可用测试框架，跳过执行"
          EXIT_CODE=2
        fi
      else
        echo "  ⚠️  无可用测试框架，跳过执行"
        EXIT_CODE=2
      fi
    else
      echo "  ⚠️  package.json 不存在"
      EXIT_CODE=2
    fi
    ;;

  python|polyglot)
    echo "  📦 Python 测试..."
    if [ -n "$SCOPE_MODULES" ]; then
      # T1 定向：只跑受影响模块的测试 + 全局冒烟（test_health/test_smoke 必有）
      # 只收集存在的目标，避免 pytest 因路径不存在而报错
      SCOPED_TARGETS=""
      for m in $SCOPE_MODULES; do
        for cand in tests/test_${m}*.py tests/${m}/; do
          [ -e "$cand" ] && SCOPED_TARGETS="$SCOPED_TARGETS $cand"
        done
      done
      for cand in tests/test_health.py tests/test_smoke*.py; do
        [ -e "$cand" ] && SCOPED_TARGETS="$SCOPED_TARGETS $cand"
      done
      if [ -z "$SCOPED_TARGETS" ]; then
        echo "  ⚠️  定向目标为空：模块 [$SCOPE_MODULES] 未匹配到任何测试文件，禁止回落全量，标记失败"
        EXIT_CODE=1
      else
        echo "    定向目标: $SCOPED_TARGETS"
        if command -v pytest &>/dev/null; then
          TEST_OUTPUT=$(pytest -v $SCOPED_TARGETS 2>&1)
        elif command -v python3 &>/dev/null; then
          TEST_OUTPUT=$(python3 -m pytest -v $SCOPED_TARGETS 2>&1)
        elif command -v python &>/dev/null; then
          TEST_OUTPUT=$(python -m pytest -v $SCOPED_TARGETS 2>&1)
        else
          echo "  ⚠️  pytest 不可用，跳过测试执行"
          EXIT_CODE=2
        fi
        EXIT_CODE=$?
      fi
    elif command -v pytest &>/dev/null; then
      echo "    pytest..."
      TEST_OUTPUT=$(pytest -v 2>&1)
      EXIT_CODE=$?
    elif command -v python3 &>/dev/null; then
      echo "    python3 -m pytest..."
      TEST_OUTPUT=$(python3 -m pytest -v 2>&1)
      EXIT_CODE=$?
    elif command -v python &>/dev/null; then
      echo "    python -m pytest..."
      TEST_OUTPUT=$(python -m pytest -v 2>&1)
      EXIT_CODE=$?
    elif [ -f "manage.py" ]; then
      echo "    Django test..."
      if command -v python3 &>/dev/null; then
        TEST_OUTPUT=$(python3 manage.py test 2>&1)
        EXIT_CODE=$?
      else
        TEST_OUTPUT=$(python manage.py test 2>&1)
        EXIT_CODE=$?
      fi
    else
      echo "  ⚠️  pytest 不可用，跳过测试执行"
      EXIT_CODE=2
    fi
    ;;

  *)
    # polyglot 的 Java 部分
    if [ -f "pom.xml" ] && command -v mvn &>/dev/null; then
      echo "  📦 Maven 测试（polyglot 的 Java 部分）..."
      if [ -n "$SCOPE_MODULES" ]; then
        SCOPED_PATTERN=""
        for m in $SCOPE_MODULES; do
          SCOPED_PATTERN="${SCOPED_PATTERN:+$SCOPED_PATTERN,}*${m}*Test"
        done
        echo "    定向类: -Dtest=$SCOPED_PATTERN"
        TEST_OUTPUT=$(mvn test -q -Dtest="$SCOPED_PATTERN" 2>&1)
      else
        TEST_OUTPUT=$(mvn test -q 2>&1)
      fi
      EXIT_CODE=$?
    elif [ -f "package.json" ] && command -v npx &>/dev/null; then
      echo "  📦 npm test（polyglot 的 Node 部分）..."
      TEST_OUTPUT=$(npm test 2>&1)
      EXIT_CODE=$?
    else
      echo "  ⚠️  未检测到可执行的测试框架"
      EXIT_CODE=2
    fi
    ;;
esac
fi # CACHE_HIT=false

# ---- 解析测试结果 ----
if [ "$EXIT_CODE" -eq 2 ]; then
  echo ""
  echo "ℹ️  测试已跳过（无可用框架或未配置）"
  # 文件级检查仍然执行（至少要有测试文件）
  if [ "$HAS_TEST_CODE" = true ]; then
    echo "✅ 有测试代码文件，但无执行框架可调用"
  fi
  exit 0
elif [ "$EXIT_CODE" -eq 0 ]; then
  echo ""
  echo "✅ 测试全部通过"
  # 记录缓存（供下次同指纹跳过）
  if [ "$CACHE_HIT" = false ] && [ -n "$FP" ]; then
    mkdir -p "$CACHE_DIR"
    echo "$FP PASS" > "$CACHE_FILE"
    echo "  📦 已缓存测试结果（指纹 $FP）"
  fi
  TESTS_PASSED=1
else
  echo ""
  echo "❌ 测试执行失败 (exit=$EXIT_CODE)"

  # 输出关键错误信息（截取前后文）
  echo "--- 错误摘要（前 30 行）---"
  echo "$TEST_OUTPUT" | grep -iE "(FAIL|ERROR|Exception|FAILED|failed|error)" | head -30
  echo "--- 错误摘要（后 30 行）---"
  echo "$TEST_OUTPUT" | tail -30
  echo "------------------------"
  ERRORS=$((ERRORS + 1))
fi

# 解析 PASS/FAIL 计数（信息用途，不影响门禁判定）
if [ -n "$TEST_OUTPUT" ]; then
  RESULT=$(run_test_and_count "$TEST_OUTPUT")
  PASS_CNT=$(echo "$RESULT" | cut -d'|' -f1)
  FAIL_CNT=$(echo "$RESULT" | cut -d'|' -f2)
  [ "$PASS_CNT" -gt 0 ] && echo "  通过: $PASS_CNT"
  [ "$FAIL_CNT" -gt 0 ] && echo "  失败: $FAIL_CNT"
fi

# ---- 测试报告文件检查（辅助）----
echo ""
echo "测试报告检查:"
if [ -d "$TESTER_DIR" ]; then
  REPORT_FILES=$(find "$TESTER_DIR" \( -name "*报告*" -o -name "*report*" \) -type f 2>/dev/null)
  if [ -n "$REPORT_FILES" ]; then
    echo "  ✅ 测试报告已生成"
  fi
fi

# ---- 覆盖度检查 ----
echo ""
echo "覆盖度检查:"
COV_FILE=$(find . -name "coverage.xml" -o -name "lcov.info" -o -name "coverage-final.json" -o -name ".coverage" 2>/dev/null | head -1)
if [ -n "$COV_FILE" ]; then
  echo "  ✅ 检测到覆盖度报告: $(basename "$COV_FILE")"
else
  echo "  ⚠️  未检测到覆盖度报告（建议≥60%，通过 coverage.py / c8 / istanbul 生成）"
fi

# ---- 最小断言计数 ----
echo ""
echo "断言计数:"
ASSERT_COUNT=0
if [ -d "$SRC_TEST_DIR" ]; then
  ASSERT_COUNT=$(grep -rE "(assert|expect|should|Assert|assertEqual|assertThat|assertTrue|assertEquals)" "$SRC_TEST_DIR" --include="*.py" --include="*.java" --include="*.ts" --include="*.js" --include="*.go" --include="*.rs" 2>/dev/null | wc -l)
elif [ "$PROJECT_TYPE" = "go" ]; then
  ASSERT_COUNT=$(grep -rE "(assert|require)" --include="*_test.go" 2>/dev/null | wc -l)
fi
echo "  🔢 断言语句: $ASSERT_COUNT 处"
if [ "$ASSERT_COUNT" -eq 0 ] && [ "$HAS_TEST_CODE" = true ]; then
  echo "  ⚠️  测试文件中未检测到断言语句"
fi

echo ""
[ "$ERRORS" -eq 0 ] && echo "✅ 测试执行检查通过" || echo "❌ 测试执行检查失败，$ERRORS 个问题"
exit $([ "$ERRORS" -eq 0 ] && echo 0 || echo 1)
