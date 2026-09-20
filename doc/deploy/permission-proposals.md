# 权限变更提案（Permission Proposals）

> 本文件是 `pipeline-orchestrator` 按 SKILL「角色边界 → 权限面变更通道」提交的**待用户应用**的
> `opencode.json` 变更提案。编排层**无权**修改 `opencode.json`（`profile.md:50`：治理档，仅用户可改），
> 故只能以提案形式落盘。用户应用后请在对应条目标注 `状态: applied`。

---

## ★ 铁律：只放宽「文件作用域」，禁止放宽「通用执行权」

> 由用户于 2026-09-20 裁定，适用于**一切** agent 权限提案。

1. **允许**的放宽形态：针对**具体产出文件/目录**的 `edit` / `write` pattern（例：`doc/deploy/**`、`Dockerfile`）。
2. **禁止**的放宽形态：**通用执行 / 解释器权限**，包括但不限于
   `python *`、`python3 *`、`python3 -c *`、`sh -c *`、`bash -c *`、`*`（全放）。
3. **理由**：编排层对若干目录**同时拥有写权限**（如 `.opencode/scripts/**`）。一旦再获得通用执行权，
   即可「写入任意脚本 → 执行它」⇒ 等价于任意代码执行 ⇒ **"产出物必须 dispatch"的纪律被彻底架空**，
   编排层退化为"自己把活全干完"（本会话已在用户纠正过一次）。
4. **提案自检要求**：每条提案必须逐条列出 pattern 与理由，并显式回答
   **「该 pattern 是否可被用于执行任意代码？」**——若答案是"是"，**不得提出**。

---

## PROPOSAL-01 — ~~编排层 bash 权限补全~~ 【已撤回】

- **状态**：`withdrawn`（2026-09-20，用户裁定）
- **原内容**：为编排层追加 `python3 -c *`、`python3 .opencode/scripts/*.py *`、`python3 tests/*.py *`、`sh -c *`。
- **撤回理由**（用户裁定）：这些均属**通用执行权**，触犯上述铁律第 2 条。
  尤其 `python3 .opencode/scripts/*.py *`——该目录编排层**可写**，等于「写脚本 + 执行」的完整逃逸链。
- **代价（知情接受）**：编排层无法直接跑 `.py` 脚本；验证环节改由
  ① `.sh` 包装（`bash .opencode/scripts/*.sh *`，既有）、或
  ② 派 `tester`/`code-developer` subagent 代跑（既有权限，且**更符合 dispatch 纪律**）。

---

## PROPOSAL-02 — 收窄既有 `.opencode/scripts/*.sh` 通配（候选，待用户决策）

- **状态**：`draft`（待用户决策；**不是**我方主动要求，而是"铁律"应用到存量配置时暴露的既存缺口）
- **问题（既存事实）**：当前 `pipeline-orchestrator.permission.bash` 含
  `"bash .opencode/scripts/*.sh *": "allow"` 与 `".opencode/scripts/*.sh *": "allow"`，
  **且** `edit/write` 允许 `.opencode/scripts/**` ⇒ 现配置下**已存在**等价逃逸面
  （写入 `新脚本.sh` → 通配匹配 → 执行）。
- **候选修法**：把通配替换为**逐文件白名单**，例如
  `bash .opencode/scripts/check-*.sh *`、`bash .opencode/scripts/log-*.sh *`、
  `bash .opencode/scripts/mirror-log.sh *`、`bash .opencode/scripts/stress-tiers.sh *`、
  `bash .opencode/scripts/run-stress.sh *`、`bash .opencode/scripts/inspect-logs.sh *`、
  `bash .opencode/scripts/record-stress-observations.sh *`、`bash .opencode/scripts/project-init.sh *`
  ⇒ **新脚本不会被自动授予执行权**（新增需你补一条 pattern），形成人工卡点。
- **代价**：编排层/self-evolve 新增门禁脚本后不能立即运行，需你补 pattern（摩擦 ↑）；
  `edit/write` 仍可写 `.opencode/scripts/**`（写不等于可执行，这是该修法的关键）。
- **备选**：维持现状（承认该逃逸面存在，靠 SKILL 纪律 + 人工监督约束）。

---

## PROPOSAL-03 — （模板，未提出）

- **目标**：`opencode.json` → `agent["<agent>"].permission.<edit|write|bash>`
- **理由**：
- **风险**：
- **pattern 明细**（逐条）+ **是否可执行任意代码**：是 / 否
- **精确 patch**：
- **应用后自检**：

> **重要**：任何 agent（含编排层）**不得**自行修改 `opencode.json`——该档是治理档，
> 禁止 agent 自我扩权（`profile.md:50`）。未列入本文件的权限调整，一律视为未授权。
