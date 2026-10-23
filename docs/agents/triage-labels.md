# Triage 标签

各 skill 使用五个标准 triage 角色。本表把每个角色对应到本仓库实际使用的字符串。本仓库用本地 tracker，这些字符串写在工单的 `Status:` 行。

| mattpocock/skills 中的角色 | 本仓库使用的字符串 | 含义 |
| --- | --- | --- |
| `needs-triage` | `needs-triage` | 等负责人评估 |
| `needs-info` | `needs-info` | 等提出人补充信息 |
| `ready-for-agent` | `ready-for-agent` | 已完整说明，可交给 AFK agent |
| `ready-for-human` | `ready-for-human` | 需要人来实现 |
| `wontfix` | `wontfix` | 不处理 |

skill 提到某个角色时（例如 "apply the AFK-ready triage label"），使用表中对应的字符串。

## 派工之后的状态

实现工单进入派工以后，`Status:` 行改用下面四个字符串，流转规则见 `docs/agents/codex-workflow.md` 6.4。

| 字符串 | 含义 |
| --- | --- |
| `in-progress` | 执行线在做：派工、等 Codex、评审 |
| `in-review` | 等负责人：骨架关卡的"通过"，或者最后的"合并" |
| `changes-requested` | 评审没通过，修复清单已写好，准备发修复轮 |
| `done` | 已合并到 main |

走图的决策票不用这些，照旧用 `open`、`claimed`、`resolved`（`docs/agents/issue-tracker.md`）。
