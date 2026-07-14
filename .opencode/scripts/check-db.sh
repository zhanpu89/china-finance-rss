#!/usr/bin/env bash
# 检查数据库 DDL 产出物
# 返回: 0=通过, 1=失败

DB_DIR="doc/db"
ERRORS=0

if [ ! -d "$DB_DIR" ]; then
  echo "❌ DB 目录不存在: $DB_DIR"
  exit 1
fi

# 收集 SQL 文件（使用数组处理含空格文件名）
SQL_FILES=()
while IFS= read -r -d '' f; do
  SQL_FILES+=("$f")
done < <(find "$DB_DIR" -name "*.sql" -print0 2>/dev/null)

if [ ${#SQL_FILES[@]} -eq 0 ]; then
  echo "❌ 没有 .sql 文件"
  ERRORS=$((ERRORS + 1))
else
  for f in "${SQL_FILES[@]}"; do
    SIZE=$(wc -c < "$f")
    echo "  $(basename "$f") ($SIZE bytes)"
    [ "$SIZE" -lt 50 ] && echo "⚠️  文件过小" && ERRORS=$((ERRORS + 1))

    if ! grep -qi "CREATE TABLE\|ALTER TABLE\|CREATE INDEX" "$f" 2>/dev/null; then
      echo "⚠️  没有 CREATE TABLE/INDEX 语句"
      ERRORS=$((ERRORS + 1))
    fi

    # SQL 语法校验
    if command -v sqlite3 &>/dev/null; then
      if sqlite3 :memory: ".read '$f'" 2>/dev/null; then
        echo "  ✅ SQL 语法通过"
      else
        echo "  ❌ SQL 语法错误: $f"
        sqlite3 :memory: ".read '$f'" 2>&1 | head -5
        ERRORS=$((ERRORS + 1))
      fi
    elif command -v sqlfluff &>/dev/null; then
      if sqlfluff lint --dialect mysql "$f" 2>&1 | grep -q "PASS"; then
        echo "  ✅ SQL 语法通过 (sqlfluff)"
      else
        echo "  ⚠️  sqlfluff 发现问题: $f"
        sqlfluff lint --dialect mysql "$f" 2>&1 | tail -10
      fi
    else
      echo "  ℹ️  未安装 sqlite3/sqlfluff，跳过 SQL 语法校验"
    fi
  done
fi

# 检查 DDL 设计说明文档
DOC_COUNT=0
while IFS= read -r -d '' f; do
  DOC_COUNT=$((DOC_COUNT + 1))
done < <(find "$DB_DIR" -name "*.md" -print0 2>/dev/null)

if [ "$DOC_COUNT" -eq 0 ]; then
  echo "⚠️ 没有数据库设计说明文档"
  ERRORS=$((ERRORS + 1))
fi

[ "$ERRORS" -eq 0 ] && echo "✅ DB 检查通过" || echo "⚠️ DB 检查完成，$ERRORS 个问题"
exit $([ "$ERRORS" -eq 0 ] && echo 0 || echo 1)
