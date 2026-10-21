# 平台运行时不依赖 lerobot

Status: accepted（2026-10-21，决策票「技术栈与工程规范」）

平台虽然以 LeRobot v3.0 为规范格式（见「平台统一的 LeRobot 版本」），但平台本身不 import lerobot。原因是 lerobot 0.6 的核心依赖包含 torch、torchvision、opencv、gymnasium、cmake，光 torch 在本机就占 1.7 GB；而平台需要读的只是 `meta/` 下的 JSON 和 Parquet。

具体做法：
- 读 v3.0 元数据时，直接读 JSON。要读 Parquet 时，按依赖审批流程加 pyarrow。
- 需要 lerobot 本身的工作（格式转换、导出 v2.1）一律做成工具库里的工具，在工具自己的环境里（例如 conda 的 lerobot 环境）以子进程方式运行。
- 代码测试的基准样本从真实数据里截取一小段，放在 `tests/fixtures/`，不用 lerobot 现场生成。

## Consequences

- 平台对 v3.0 元数据的理解，要靠截取自真实数据的样本来校准。lerobot 往 v3.0 里加了新的可选内容（例如深度视频、语言列）时，要补一份对应的新样本。
- 平台的环境里不会出现 torch，所以平台进程永远不能直接调用 `LeRobotDataset`。任何需要它的功能都要走工具。
