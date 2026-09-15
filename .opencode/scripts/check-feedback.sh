#!/usr/bin/env bash
# 反馈闭环健康检查 — 验证编排器的用户反馈采集是否真正运转
# 用法: check-feedback.sh [--since N]   N=最近 N 小时窗口内必须有反馈记录（默认 24）
# 退出码: 0=闭环运转正常, 1=⚠️ 有记录但窗口内无活跃（条件）, 2=❌ 从未采集（阻断 self-evolve 建议）
# 数据源: ~/.opencode/history/user-feedback.jsonl（log-feedback.sh 产出）

HISTORY_DIR="${HOME:-/tmp}/.opencode/history"
FEEDBACK_FILE="$HISTORY_DIR/user-feedback.jsonl"
WINDOW_HOURS="${1:-24}"

echo "=== 反馈闭环健康检查 ==="
echo "反馈文件: $FEEDBACK_FILE"

if [ ! -f "$FEEDBACK_FILE" ]; then
  echo "  ❌ user-feedback.jsonl 不存在 — 反馈采集从未运转"
  echo "  影响: self-evolve 的反馈数据源为空，无法识别用户痛点"
  echo "  建议: 编排器在收到用户纠正/吐槽/改向时调用 .opencode/scripts/log-feedback.sh"
  exit 2
fi

TOTAL=$(wc -l < "$FEEDBACK_FILE" 2>/dev/null || echo 0)
echo "  累计反馈记录: $TOTAL 条"

if [ "$TOTAL" -eq 0 ]; then
  echo "  ❌ 文件存在但为空 — 采集纪律未执行"
  echo "  影响: self-evolve 的反馈数据源为空"
  echo "  建议: 确认编排器是否在收到纠正时真的调用了 log-feedback.sh"
  exit 2
fi

# 窗口内活跃检查：最近 WINDOW_HOURS 小时内是否有反馈记录
# 注意 ts_epoch 为毫秒(13位)，需先 /1000 转秒再与阈值(10位)比较，否则旧记录会被误判为"最近"
THRESHOLD_EPOCH=$(( $(date +%s) - WINDOW_HOURS * 3600 ))
RECENT=$(grep -oE '"ts_epoch":[0-9]+' "$FEEDBACK_FILE" 2>/dev/null | grep -oE '[0-9]+' | awk -v t="$THRESHOLD_EPOCH" '{e=$1/1000; if (e >= t) n++} END{print n+0}')

if [ "$RECENT" -gt 0 ]; then
  echo "  ✅ 最近 ${WINDOW_HOURS}h 内有 $RECENT 条反馈记录 — 闭环运转正常"
  exit 0
else
  echo "  ⚠️  最近 ${WINDOW_HOURS}h 内无新反馈（累计 $TOTAL 条）"
  echo "  可能原因: ① 本会话无用户纠正（正常） ② 采集纪律失效（异常，需排查）"
  exit 1
fi
