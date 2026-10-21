# 工具清单与转换血缘

Type: grilling
Status: open
Blocked by: 07, 13

## Question

工具库按什么约定组织（原始需求 (8)）？数据集的血缘，也就是它"是怎么来的"，记录在哪里（原始需求 (7)）？推荐答案见 0003 第六节的 (7)、(8)；格式版本以「[平台统一的 LeRobot 版本](07-lerobot-version.md)」为准，对象以「[核心领域模型与术语](13-domain-model.md)」为准。

要定的：

- **工具目录与清单**：
  - 目录怎么命名；`tool.toml` 清单有哪些字段
  - 工具放在哪里：`/mnt/datasets/工具/`，还是平台仓库里的 `tools/`
  - 现有的 mcap2lerobot 怎么纳入
- **调用方式**：平台用子进程调用工具；运行环境怎么指定（conda 的 lerobot 环境、Rust 二进制）。
- **血缘**：录制时转换、录制后转换、下载，这三种来源记在哪里，导航层 JSON 还是数据库；记录方式要和"导航层是事实来源"一致。
- **导出 v2.1 算不算平台功能**：openpi、GR00T、Galaxea、智元自家的训练代码只读 v2.1，但官方只有 v2.1 → v3.0 的单向脚本，而且它会丢掉非标准的 `info.json` 字段。导出 v2.1 要不要作为一个登记在册的工具，导出产物是否计入血缘（见「[平台统一的 LeRobot 版本](07-lerobot-version.md)」）。

**完成标准**：以上各项都有结论，并用 mcap2lerobot 写一份清单草样来验证；用 R1_lite_table_withdrawing 的 MCAP 和 LeRobot 两个版本，写一条血缘记录草样。结论写成 ADR；术语写进 `GLOSSARY.md`。本票加调 `algorithm-engineering`。
