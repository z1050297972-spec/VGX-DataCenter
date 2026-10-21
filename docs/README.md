# 文档地图

本仓库的所有计划文档都按下面的分类存放。新文档先确定属于哪一类，再放到对应位置。不要另起目录。

## 分类

| 类别 | 位置 | 由谁产生 | 何时写 | 生命周期 |
|---|---|---|---|---|
| 输入 | `docs/brief/NNNN-*.md` | 负责人 + Claude | 需求或环境发生变化时 | 只追加，不改写 |
| 过程 | `.scratch/platform-v1/`（`map.md` + `issues/NN-*.md` 决策票） | `/wayfinder` | 开图、走图时 | 地图走完后冻结 |
| 决策结果·术语 | `GLOSSARY.md`（仓库根目录） | domain-modeling | 某个术语定下来时立即写 | 长期有效 |
| 决策结果·难以逆转的选择 | `docs/adr/NNNN-*.md` | domain-modeling | 同时满足"难以逆转、事后看会意外、经过真实权衡"三条时 | 长期有效；被推翻时新写一份 ADR 取代旧的 |
| 调研 | `docs/research/<主题>.md` | `/research` | research 决策票完成时 | 长期参考；每条结论附出处 |
| 构建计划 | `.scratch/m<N>-<名>/`（`spec.md` + `issues/NN-*.md` 实现工单） | `/to-spec`、`/to-tickets` | 每个里程碑开始时 | 里程碑完成后关闭 |
| 函数级文档 | 代码里的 docstring（不另写 md） | 实现阶段 | 写函数契约骨架时 | 和代码同步修改 |
| 规范 | `docs/standards/`、`AGENTS.md`、自动检查 | 负责人、`/retro` | 每次复盘后 | 持续演进 |
| 协作配置 | `docs/agents/` | `/setup-matt-pocock-skills`、Claude | 一次性写好，按需更新 | 持续演进 |
| 派工与评审记录 | 对应工单文件末尾的 `## Comments` | Claude | 每次派工或评审后 | 跟随工单 |

## 命名

- `brief/` 和 `adr/` 下的文件用四位序号加中文短名，例如 `0004-NAS接入后的存储变化.md`。
- 工单和决策票用两位序号加英文 slug，例如 `03-plan-link.md`，遵循本地 tracker 的约定（`docs/agents/issue-tracker.md`）。
- 一个里程碑对应一个目录：`.scratch/m0-foundation/`、`.scratch/m1-datasets/`……

## 文件归属

- **Codex**：只修改 `src/`、`tests/`。`pyproject.toml` 和 `Makefile` 只有在工单明确允许时才能改。
- **Claude**：负责 `.scratch/`、`docs/`、`GLOSSARY.md`、`AGENTS.md`、`CLAUDE.md`。
- 进度不另存看板，需要时扫描各工单的 `Status:` 行现场生成。

## 现在从哪里读起

1. `brief/0001-初始需求.md`：负责人的原话和已确认的约束
2. `brief/0002-环境事实.md`：F1–F10
3. `brief/0003-初步建议与开图草案.md`：技能路线（第二节）、数据集板块（第四节）、协作分工（第八节）、开图草案（第九节）
4. `standards/engineering-control/`：从 mcap2lerobot 原样复制过来的工程规范，作为种子；`CODING_STANDARDS.md` 将从它派生
