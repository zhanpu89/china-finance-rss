# 权限变更提案（Permission Proposals）

> 本文件是 `pipeline-orchestrator` 按 SKILL「角色边界 → 权限面变更通道」提交的**待用户应用**的
> `opencode.json` 变更提案。编排层**无权**修改 `opencode.json`（`profile.md:50`：治理档，仅用户可改），
> 故只能以提案形式落盘。用户应用后请在对应条目标注 `状态: applied`。

---

## ★ 铁律：只放宽「文件作用域」，禁止放宽「通用执行权」

> 由用户于 2026-09-20 裁定，适用于**一切** agent 权限提案。

1. **允许**：针对**具体产出文件/目录**的 `edit` / `write` pattern（例：`doc/deploy/**`、`Dockerfile`）。
2. **禁止**：**通用执行 / 解释器权限** —— `python *`、`python3 *`、`python3 -c *`、`sh -c *`、`bash -c *`、`*`（全放）。
3. **理由**：编排层对若干目录**同时拥有写权限**（如 `.opencode/scripts/**`）。若再获得通用执行权，即可
   「写入任意脚本 → 执行它」⇒ 等价任意代码执行 ⇒ **"产出物必须 dispatch"的纪律被彻底架空**。
4. **提案自检**：每条提案须逐条列 pattern + 理由，并显式回答 **「该 pattern 能否被用于执行任意代码？」**；
   答案为"是"则**不得提出**。

---

## PROPOSAL-01 — ~~编排层 bash 权限补全~~ 【已撤回】

- **状态**：`withdrawn`（2026-09-20，用户裁定）
- **原内容**：追加 `python3 -c *`、`python3 .opencode/scripts/*.py *`、`python3 tests/*.py *`、`sh -c *`。
- **撤回理由**：均属**通用执行权**（铁律第 2 条）。尤其 `python3 .opencode/scripts/*.py *`——该目录**可写**，
  等于「写脚本 + 执行」的完整逃逸链。
- **代价（知情接受）**：编排层不直接跑 `.py`；验证改由 ① 已授权包装脚本、② 派 `tester`/`code-developer` 代跑。

---

## PROPOSAL-02 — 收窄 `.opencode/scripts/*.sh` 通配为逐文件白名单 【待应用 · 已确认采纳】

- **状态**：`open`（用户 2026-09-20 裁定"收窄为逐文件白名单"）
- **问题（存量同类逃逸面）**：当前 `pipeline-orchestrator.permission.bash` 含两条通配
  （`.opencode/scripts/*.sh *` 与 `bash .opencode/scripts/*.sh *`），而 `edit/write` 允许
  `.opencode/scripts/**` ⇒ **写入任意 `.sh` → 通配即执行** = 任意代码执行，与 PROPOSAL-01 被否掉的风险**同类**。
- **修法**：两条通配**替换为逐文件白名单**；`.opencode/scripts/**` 的**写权保留**（**写 ≠ 可执行**）。
  此后新增门禁脚本**不会自动获得执行权**，需用户补一行 pattern —— 形成人工卡点。
- **pattern 明细**（22 条，均为 `bash <脚本> …` 形式；本会话编排层实际调用方式即此）：

```diff
-          ".opencode/scripts/*.sh *": "allow",
-          "bash .opencode/scripts/*.sh *": "allow",
+          "bash .opencode/scripts/check-arch-compliance.sh *": "allow",
+          "bash .opencode/scripts/check-arch.sh *": "allow",
+          "bash .opencode/scripts/check-audit.sh *": "allow",
+          "bash .opencode/scripts/check-changed.sh *": "allow",
+          "bash .opencode/scripts/check-code.sh *": "allow",
+          "bash .opencode/scripts/check-detailed.sh *": "allow",
+          "bash .opencode/scripts/check-drift.sh *": "allow",
+          "bash .opencode/scripts/check-feedback.sh *": "allow",
+          "bash .opencode/scripts/check-integration.sh *": "allow",
+          "bash .opencode/scripts/check-opencode.sh *": "allow",
+          "bash .opencode/scripts/check-prd.sh *": "allow",
+          "bash .opencode/scripts/check-review.sh *": "allow",
+          "bash .opencode/scripts/check-test.sh *": "allow",
+          "bash .opencode/scripts/check-testcase.sh *": "allow",
+          "bash .opencode/scripts/inspect-logs.sh *": "allow",
+          "bash .opencode/scripts/log-feedback.sh *": "allow",
+          "bash .opencode/scripts/log-skill.sh *": "allow",
+          "bash .opencode/scripts/mirror-log.sh *": "allow",
+          "bash .opencode/scripts/project-init.sh *": "allow",
+          "bash .opencode/scripts/record-stress-observations.sh *": "allow",
+          "bash .opencode/scripts/run-stress.sh *": "allow",
+          "bash .opencode/scripts/stress-tiers.sh *": "allow",
```

- **「是否能执行任意代码」自检**：**否**。每条 pattern 锚定到**具名脚本文件**；虽然这些文件仍可被编辑，
  但**新增文件不会自动获得执行权**，编辑现有文件受 `edit/write` 与 SKILL 留痕纪律约束 ⇒ 逃逸链被打断。
- **同批建议（可选，同一原理）**：`"bash .opencode/project/scripts/*.sh *": "allow"` 亦为通配，
  且 `.opencode/project/**` 可写。该目录**当前不存在**（无 `scripts/` 子目录，pattern 今日为惰性），
  但一旦创建即成为同类逃逸面。建议**一并删除**；将来真正需要时按逐文件方式重新申请。
  另注：`self-evolve` 的白名单中亦有 `.opencode/project/scripts/*.sh *` 通配（同类问题，需另行提案）。
- **代价（知情接受）**：编排层/self-evolve 新增门禁脚本后**不能立即运行**，需你补一行 pattern（摩擦 ↑）。
- **应用后自检**：`bash .opencode/scripts/check-opencode.sh`（应 0 阻断 0 警告）；并验证
  `bash .opencode/scripts/check-changed.sh` 仍可执行、而一个**临时新建**的 `.sh` 被拒绝。

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
