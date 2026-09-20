# 权限变更提案（Permission Proposals）

> 本文件是 `pipeline-orchestrator` 按 SKILL「角色边界 → 权限面变更通道」提交的**待用户应用**的
> `opencode.json` 变更提案。编排层**无权**修改 `opencode.json`（`profile.md:50`：治理档，仅用户可改），
> 故只能以提案形式落盘。用户应用后请在对应条目标注 `状态: applied`。

---

## PROPOSAL-01 — 编排层 bash 权限补全（运行 `.py` 脚本 / `sh -c`）

- **状态**：`open`（待用户应用）
- **目标**：`opencode.json` → `agent["pipeline-orchestrator"].permission.bash`
- **提交日期**：2026-09-20
- **提出理由（本会话摩擦实证）**：编排层当前只能用 `python -m py_compile` / `python -m unittest`，
  **无法直接运行仓库内的 `.py` 脚本**，也无法执行 `sh -c` 复合只读命令。实际后果：
  - `.opencode/scripts/stress-tiers.py`、`tests/ac_e4_verify.py`、`tests/loadtest.py` 等**无法由编排层直接跑**，
    只能绕 `.sh` 包装（如 `stress-tiers.sh`）或派 `tester` subagent 代跑，增加了往返与上下文开销；
  - 复合只读命令（如 `docker exec … sh -c "grep … | wc -l"` 之外的本地组合）被拒，只能拆成多次工具调用。
- **风险评估**：**低**。`docker exec *` 与 `bash .opencode/scripts/*.sh *` **本已 allow**，
  「容器内任意命令」与「脚本内任意命令」这两种等价能力已经存在；本提案**不实质新增能力**，
  只是让编排层在验证环节少绕路。

### 精确 patch

在 `opencode.json` 的 `agent["pipeline-orchestrator"].permission.bash` 内，
第 223 行 `"python -m unittest *": "allow",` 之后插入 4 行：

```diff
           "python -m py_compile *": "allow",
           "python -m unittest *": "allow",
+          "python3 -c *": "allow",
+          "python3 .opencode/scripts/*.py *": "allow",
+          "python3 tests/*.py *": "allow",
+          "sh -c *": "allow",
           "docker compose *": "allow",
```

### 应用后自检

```bash
bash .opencode/scripts/check-opencode.sh      # 应仍为 0 阻断 / 0 警告
```

### 备选（如不希望放宽）

若认为 `sh -c *` 过宽，可只应用前 3 条（`python3` 相关）；`sh -c` 缺口可用 `docker exec` 路径替代，
但本机复合只读命令仍会被拆分为多次调用。

---

## PROPOSAL-02 — （模板，未提出）

- **目标**：`opencode.json` → `agent["<agent>"].permission.<edit|write|bash>`
- **理由**：
- **风险**：
- **精确 patch**：
- **应用后自检**：

> **重要**：任何 agent（含编排层）**不得**自行修改 `opencode.json`——该档是治理档，
> 禁止 agent 自我扩权（`profile.md:50`）。未列入本文件的权限调整，一律视为未授权。
