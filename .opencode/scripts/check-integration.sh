#!/usr/bin/env bash
# P6d 集成验证门禁 — 启动服务 + curl 端点验证
# 退出码: 0=通过, 1=警告, 2=阻断/跳过
#
# 使用方式（由编排器在 P6d 阶段调用）：
#   bash .opencode/scripts/check-integration.sh
#
# 行为：
# 1. 从 _MEMORY_CACHE.md 读取 scope endpoints（如无则健康检查兜底）
# 2. 检测项目类型，启动服务
# 3. curl 每个端点验证 HTTP 状态码
# 4. 生成集成验证报告到 doc/tester/integration-report.md

PROJECT_DIR="$(cd "$(dirname "$0")/../.." && pwd)"
cd "$PROJECT_DIR" || exit 1

ERRORS=0
PASS_COUNT=0
FAIL_COUNT=0
SKIP_COUNT=0
REPORT_FILE="doc/tester/integration-report.md"

# ---- 解析 scope（从 _MEMORY_CACHE.md 或环境变量）----
ENDPOINTS=()
SCOPE_SOURCE="默认（健康检查）"

if [ -f "_MEMORY_CACHE.md" ]; then
   # 格式兼容: ">>SCOPE: endpoints=X" (code-developer 标记) / "modules: X | endpoints: Y" (缓存模板) / "endpoints=X"
   SCOPE_LINE=$(grep -oE '(endpoints[=:][^|#]+)' _MEMORY_CACHE.md 2>/dev/null | head -1)
   if [ -n "$SCOPE_LINE" ]; then
     SCOPE_DATA=$(echo "$SCOPE_LINE" | sed -E 's/.*endpoints[=:]//' | tr ',' '\n')
     if [ -n "$SCOPE_DATA" ]; then
       while IFS= read -r ep; do
         ep=$(echo "$ep" | xargs)
         [ -n "$ep" ] && ENDPOINTS+=("$ep")
       done <<< "$SCOPE_DATA"
       SCOPE_SOURCE="_MEMORY_CACHE.md"
     fi
   fi
   # Also read modules scope (for pure internal change detection) — 兼容 ">>SCOPE: modules=X" 和 "modules: X |"
   SCOPE_MODULES=$(grep -oE '(modules[=:][^|#]+)' _MEMORY_CACHE.md 2>/dev/null | head -1 | sed -E 's/.*modules[=:]//' | tr ',' ' ')
 fi

# scope 环境变量覆盖文件
if [ -n "$SCOPE_ENDPOINTS" ]; then
  IFS=',' read -ra SCOPED_EP <<< "$SCOPE_ENDPOINTS"
  ENDPOINTS=()
  for ep in "${SCOPED_EP[@]}"; do
    ep=$(echo "$ep" | xargs)
    [ -n "$ep" ] && ENDPOINTS+=("$ep")
  done
  SCOPE_SOURCE="环境变量 SCOPE_ENDPOINTS"
fi

# 无 scope 时默认健康检查
if [ ${#ENDPOINTS[@]} -eq 0 ]; then
  ENDPOINTS=("GET /health" "GET /api/health")
  SCOPE_SOURCE="默认（健康检查兜底）"
fi

# 优化跳过：纯内部变更无需启动服务
# 当 endpoints 只有健康检查 + 影响模块不含 main/路由层 → 纯内部重构，跳过集成验证
if [ ${#ENDPOINTS[@]} -eq 2 ] && [ "$SCOPE_SOURCE" = "默认（健康检查兜底）" ] && [ -n "$SCOPE_MODULES" ]; then
  if ! echo "$SCOPE_MODULES" | grep -qiE "main|route|api|endpoint|controller"; then
    echo "=== P6d 集成验证 ==="
    echo "端点: 仅健康检查"
    echo "影响模块: $SCOPE_MODULES"
    echo "ℹ️  纯内部变更（无 API/端点影响），跳过集成验证"
    exit 2
  fi
fi

echo "=== P6d 集成验证 ==="
echo "端点来源: $SCOPE_SOURCE"
echo "待验端点: ${#ENDPOINTS[@]} 个"
for ep in "${ENDPOINTS[@]}"; do
  echo "  - $ep"
done
echo ""

# ---- 项目类型检测 ----
PROJECT_TYPE="unknown"
[ -f "pom.xml" ] || [ -f "build.gradle" ] || [ -f "build.gradle.kts" ] && [ "$PROJECT_TYPE" = "unknown" ] && PROJECT_TYPE="java"
[ -f "go.mod" ] && [ "$PROJECT_TYPE" = "unknown" ] && PROJECT_TYPE="go"
[ -f "Cargo.toml" ] && [ "$PROJECT_TYPE" = "unknown" ] && PROJECT_TYPE="rust"
[ -f "package.json" ] && [ "$PROJECT_TYPE" = "unknown" ] && PROJECT_TYPE="node"
[ -f "requirements.txt" ] || [ -f "setup.py" ] || [ -f "pyproject.toml" ] && [ "$PROJECT_TYPE" = "unknown" ] && PROJECT_TYPE="python"
[ -f "package.json" ] && ( [ -f "pyproject.toml" ] || [ -f "requirements.txt" ] || [ -f "setup.py" ] ) && PROJECT_TYPE="polyglot"
[ -f "pom.xml" ] && [ -f "package.json" ] && PROJECT_TYPE="polyglot"
echo "项目类型: $PROJECT_TYPE"

# 初始化报告文件（项目类型已知后写入）
mkdir -p "$(dirname "$REPORT_FILE")"
{
  echo "# 集成验证报告"
  echo ""
  echo "**时间:** $(date -u '+%Y-%m-%dT%H:%M:%SZ')"
  echo "**项目:** $PROJECT_TYPE"
  echo "**端点来源:** $SCOPE_SOURCE"
  echo "**待验端点:** ${#ENDPOINTS[@]} 个"
  for ep in "${ENDPOINTS[@]}"; do
    echo "- $ep"
  done
  echo ""
  echo "## 逐端点结果"
  echo ""
} > "$REPORT_FILE"

# ---- 端口配置 ----
# 可被环境变量覆盖，否则按项目类型推断默认端口
DEFAULT_PORT=""
case "$PROJECT_TYPE" in
  java)   DEFAULT_PORT="8080" ;;
  go)     DEFAULT_PORT="8080" ;;
  rust)   DEFAULT_PORT="8080" ;;
  node)   DEFAULT_PORT="3000" ;;
  python) DEFAULT_PORT="8000" ;;
  polyglot) DEFAULT_PORT="8080" ;;
  *)      DEFAULT_PORT="8080" ;;
esac
PORT="${PORT:-$DEFAULT_PORT}"
# 尝试从配置文件读端口
if [ -f ".env" ]; then
  ENV_PORT=$(grep -E "^PORT=" .env | cut -d= -f2 | xargs)
  [ -n "$ENV_PORT" ] && PORT="$ENV_PORT"
fi
echo "服务端口: $PORT"

# ---- 端口冲突检测 ----
if command -v ss &>/dev/null; then
  PORT_IN_USE=$(ss -tlnp "sport = :$PORT" 2>/dev/null | tail -n +2 | head -1)
elif command -v lsof &>/dev/null; then
  PORT_IN_USE=$(lsof -i TCP:$PORT 2>/dev/null | tail -n +2 | head -1)
else
  PORT_IN_USE=""
fi
if [ -n "$PORT_IN_USE" ]; then
  echo "⚠️  端口 $PORT 已被占用，尝试备用端口..."
  # 找下一个可用端口
  for alt_port in $(seq $((PORT + 1)) $((PORT + 100))); do
    if command -v ss &>/dev/null; then
      ss -tlnp "sport = :$alt_port" 2>/dev/null | tail -n +2 | head -1 | grep -q . || { PORT=$alt_port; break; }
    elif command -v lsof &>/dev/null; then
      lsof -i TCP:$alt_port 2>/dev/null | tail -n +2 | head -1 | grep -q . || { PORT=$alt_port; break; }
    else
      PORT=$((PORT + 1))
      break
    fi
  done
  echo "  备用端口: $PORT"
fi

# ---- 启动服务 ----
SERVER_PID=""
START_CMD=""

case "$PROJECT_TYPE" in
  java)
    if [ -f "pom.xml" ] && command -v mvn &>/dev/null; then
      START_CMD="mvn spring-boot:run -q"
    elif [ -f "build.gradle" ] || [ -f "build.gradle.kts" ]; then
      [ -f "gradlew" ] && START_CMD="./gradlew bootRun -q"
    fi
    ;;
  go)
    if command -v go &>/dev/null && [ -f "go.mod" ]; then
      MAIN_FILE=$(find . -name "main.go" -type f 2>/dev/null | head -1)
      [ -n "$MAIN_FILE" ] && START_CMD="go run $MAIN_FILE"
    fi
    ;;
  rust)
    if command -v cargo &>/dev/null; then
      START_CMD="cargo run"
    fi
    ;;
  node|polyglot)
    # 尝试常用启动脚本
    for script in "start" "dev" "serve"; do
      if grep -q "\"$script\"" package.json 2>/dev/null; then
        START_CMD="npm run $script"
        break
      fi
    done
    [ -z "$START_CMD" ] && [ -f "server.js" ] && START_CMD="node server.js"
    [ -z "$START_CMD" ] && [ -f "app.js" ] && START_CMD="node app.js"
    [ -z "$START_CMD" ] && [ -f "index.js" ] && START_CMD="node index.js"
    ;;
  python|polyglot)
    for script in "manage.py" "app.py" "main.py" "run.py" "server.py" "application.py"; do
      if [ -f "$script" ]; then
        START_CMD="python3 $script"
        break
      fi
    done
    # 尝试 uvicorn/fastapi
    if [ -z "$START_CMD" ] && [ -f "pyproject.toml" ]; then
      MAIN_MODULE=$(grep -E "^app|^main|^server" pyproject.toml 2>/dev/null | head -1 | cut -d: -f1)
      [ -n "$MAIN_MODULE" ] && START_CMD="uvicorn ${MAIN_MODULE}:app --port $PORT"
    fi
    # FastAPI app 检测
    if [ -z "$START_CMD" ]; then
      APP_FILE=$(find . -maxdepth 2 \( -name "app.py" -o -name "main.py" \) -type f 2>/dev/null | head -1)
      if [ -n "$APP_FILE" ] && grep -q "FastAPI\|flask\|django" "$APP_FILE" 2>/dev/null; then
        START_CMD="python3 $APP_FILE"
      fi
    fi
    ;;
esac

# 全类型兜底：docker-compose / Procfile
if [ -z "$START_CMD" ]; then
  if [ -f "docker-compose.yml" ] || [ -f "docker-compose.yaml" ]; then
    START_CMD="docker-compose up -d"
  elif [ -f "Procfile" ]; then
    START_CMD="cat Procfile | grep '^web:' | head -1 | cut -d: -f2- | xargs"
  fi
fi

if [ -n "$START_CMD" ]; then
  echo ""
  echo "启动服务: $START_CMD"
  # 在后台启动服务，stdout/stderr 导入日志文件
  mkdir -p /tmp/opencode
  LOGFILE="/tmp/opencode/p6d-server-$$.log"
  echo "服务日志: $LOGFILE"

  # 通过 setsid 启动独立进程组，方便后续 kill
  if command -v setsid &>/dev/null; then
    setsid bash -c "$START_CMD" > "$LOGFILE" 2>&1 &
    SERVER_PID=$!
  else
    eval "$START_CMD" > "$LOGFILE" 2>&1 &
    SERVER_PID=$!
  fi
  echo "服务 PID: $SERVER_PID"

  # 等待服务就绪（最多 60 秒）
  echo "等待服务就绪..."
  READY=false
  for i in $(seq 1 60); do
    if command -v curl &>/dev/null && curl -s -o /dev/null -w "%{http_code}" "http://localhost:$PORT/health" 2>/dev/null | grep -q "200"; then
      READY=true
      echo "  ✅ 服务就绪（${i}s）"
      break
    fi
    # 也检查 /api/health
    if command -v curl &>/dev/null && curl -s -o /dev/null -w "%{http_code}" "http://localhost:$PORT/api/health" 2>/dev/null | grep -q "200"; then
      READY=true
      echo "  ✅ 服务就绪（${i}s）"
      break
    fi
    sleep 1
  done

  if [ "$READY" = false ]; then
    echo "  ⚠️  服务未在 60 秒内就绪，继续尝试端点..."
    # 不阻断，继续尝试 curl 各个端点
  fi
else
  echo ""
  echo "⚠️  无法自动启动服务（未识别启动命令）"
  echo "   请确认服务已在运行，或设置 PORT 环境变量"
  echo "   继续执行端点检测..."
fi

# ---- 清理函数 ----
cleanup() {
  if [ -n "$SERVER_PID" ]; then
    echo ""
    echo "清理服务进程..."
    # 杀死整个进程组
    kill -- -$(ps -o pgid= -p "$SERVER_PID" 2>/dev/null | xargs) 2>/dev/null || true
    kill "$SERVER_PID" 2>/dev/null || true
    # 确保所有子进程被清理
    pkill -P "$SERVER_PID" 2>/dev/null || true
    echo "  ✅ 服务已停止"
  fi
}
trap cleanup EXIT INT TERM

# ---- 执行端点验证 ----
echo ""
echo "端点验证:"

BASE_URL="http://localhost:$PORT"

for ep in "${ENDPOINTS[@]}"; do
  # 解析 "METHOD /path"
  METHOD=$(echo "$ep" | awk '{print $1}')
  PATH_PART=$(echo "$ep" | awk '{$1=""; print $0}' | xargs)

  # 如果端点不含 METHOD 前缀，默认 GET
  if ! echo "$METHOD" | grep -qiE "^(GET|POST|PUT|DELETE|PATCH|HEAD|OPTIONS)$"; then
    PATH_PART="$ep"
    METHOD="GET"
  fi

  URL="${BASE_URL}${PATH_PART}"

  echo -n "  $METHOD $PATH_PART ... "

  # 执行 curl
  RESPONSE=$(curl -s -w "\n%{http_code}" -X "$METHOD" "$URL" 2>/dev/null || true)
  HTTP_CODE=$(echo "$RESPONSE" | tail -1)
  BODY=$(echo "$RESPONSE" | sed '$d')

  if [ -z "$HTTP_CODE" ]; then
    echo "❌ 连接失败（服务未响应）"
    FAIL_COUNT=$((FAIL_COUNT + 1))
    ERRORS=$((ERRORS + 1))
    continue
  fi

  # HTTP 状态码判定
  if [ "$HTTP_CODE" -ge 200 ] && [ "$HTTP_CODE" -lt 300 ]; then
    echo "✅ $HTTP_CODE"
    PASS_COUNT=$((PASS_COUNT + 1))
  elif [ "$HTTP_CODE" -ge 300 ] && [ "$HTTP_CODE" -lt 400 ]; then
    echo "⚠️  $HTTP_CODE（重定向）"
    PASS_COUNT=$((PASS_COUNT + 1))
  elif [ "$HTTP_CODE" -ge 400 ] && [ "$HTTP_CODE" -lt 500 ]; then
    echo "❌ $HTTP_CODE（客户端错误）"
    FAIL_COUNT=$((FAIL_COUNT + 1))
    ERRORS=$((ERRORS + 1))
  elif [ "$HTTP_CODE" -ge 500 ]; then
    echo "❌ $HTTP_CODE（服务端错误）"
    FAIL_COUNT=$((FAIL_COUNT + 1))
    ERRORS=$((ERRORS + 1))
  else
    echo "❌ $HTTP_CODE（未知）"
    FAIL_COUNT=$((FAIL_COUNT + 1))
    ERRORS=$((ERRORS + 1))
  fi

  # 验证 JSON 响应合法性（如果有 Content-Type）
  CONTENT_TYPE=$(echo "$RESPONSE" | grep -i "Content-Type" 2>/dev/null || echo "")
  if echo "$CONTENT_TYPE" | grep -qi "application/json"; then
    if echo "$BODY" | python3 -c "import json,sys;json.load(sys.stdin)" 2>/dev/null; then
      :  # JSON 合法
    else
      echo "    ⚠️  响应体不是合法 JSON"
    fi
  fi

  # 记录详细信息到报告
  {
    echo "### $METHOD $PATH_PART"
    echo "- **状态码:** $HTTP_CODE"
    echo "- **响应体:**"
    echo '```'
    echo "$BODY" | head -50
    [ "$(echo "$BODY" | wc -l)" -gt 50 ] && echo "... (截断)"
    echo '```'
    echo ""
  } >> "$REPORT_FILE" 2>/dev/null || true
done

# ---- 清理由 trap 完成 ----

# ---- 汇总报告 ----
echo ""
echo "=== 集成验证汇总 ==="
echo "通过: $PASS_COUNT | 失败: $FAIL_COUNT | 跳过: $SKIP_COUNT"

# 追加汇总结果到报告
{
  echo ""
  echo "---"
  echo ""
  echo "## 汇总"
  echo ""
  echo "| 指标 | 值 |"
  echo "|------|-----|"
  echo "| ✅ 通过 | $PASS_COUNT |"
  echo "| ❌ 失败 | $FAIL_COUNT |"
  echo "| ⏭️  跳过 | $SKIP_COUNT |"
  echo ""
  if [ "$ERRORS" -eq 0 ]; then
    echo "**结论:** ✅ 集成验证通过"
  else
    echo "**结论:** ❌ 集成验证不通过，$ERRORS 个端点异常"
  fi
} >> "$REPORT_FILE"

echo ""
echo "报告: $REPORT_FILE"

[ "$ERRORS" -eq 0 ] && echo "✅ 集成验证通过" || echo "❌ 集成验证不通过"
exit $([ "$ERRORS" -eq 0 ] && echo 0 || echo 1)
