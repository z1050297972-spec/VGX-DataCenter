# 平台统一的 LeRobot 版本

Type: research
Status: resolved

## Question

平台应该以哪个 LeRobot 数据集格式版本（v2.1 还是 v3.0）为准？配套用哪个版本的 lerobot 库？

现状（0002 的 F8、F9）：

- 现有样本：libero_10、R1_lite_table_withdrawing_lerobot、aloha_mobile_cabinet 是 v3.0，智元的仿真样本是 v2.1。
- mcap2lerobot 两种版本都能输出。
- CB_Autolife_Data_Collector 依赖 lerobot ≥ 0.6，产出版本只是推断为 v3.0，没有确认过。

要回答的问题：

- v2.1 和 v3.0 在目录结构、`meta/` 文件、视频与分块方式上有什么差别。
- 官方工具对两个版本的读写支持如何，有没有 v2.1 → v3.0 的转换脚本。
- lerobot 库的各个版本和数据集格式版本怎么对应；当前最新的稳定版是哪个。
- 训练一侧主流的 policy 训练代码读哪个版本。

**完成标准**：以上每个问题都有结论并附出处，最后给出推荐的版本组合。结果写到 `docs/research/LeRobot版本.md`；本票 Answer 写要点并链接过去。

## Answer

- **推荐**：平台以 **LeRobot v3.0** 为唯一规范格式，配套 **lerobot 0.6.1**（2026-08-03 发布，是当前最新的稳定版；安装 `lerobot[dataset]`，Python 3.12）。v2.1 只作为按需导出的派生格式。
- **格式差别**：v2.1 是一个 episode 一个 parquet/mp4，元数据为 `episodes.jsonl`、`episodes_stats.jsonl`、`tasks.jsonl`。v3.0 把多个 episode 拼进按大小切分的分片（视频路径变为 `videos/<key>/chunk-*/file-*.mp4`），用 `meta/episodes/*.parquet` 里的偏移量定位 episode，任务表是 `tasks.parquet`，全局统计在 `stats.json`。官方文档把 v3.0 的任务表写成 `tasks.jsonl`，这是错的，以代码为准。
- **官方工具**：lerobot ≥ 0.4.0 只读写 v3.0，读 v2.1 直接抛 `BackwardCompatibilityError`（本机已实测）。官方只有单向的 `lerobot.scripts.convert_dataset_v21_to_v30`。这个脚本原地改目录（`/mnt` 上的数据要先拷到可写位置），会丢弃非标准的 `info.json` 字段（智元的 10 个字段全丢），视频不重编码。反向的 v3.0 → v2.1 只有 Isaac-GR00T 仓库里有脚本。
- **训练侧分成两派**：lerobot 自带训练（ACT、Diffusion、pi0/pi0.5、SmolVLA、GR00T N1.7 等）只读 v3.0；openpi、Isaac-GR00T 官方仓库、Galaxea G0.5、智元 GO-1 仍然只读 v2.1。
- **主要代价**：给后一派用时要导出 v2.1；"v3.0" 在 0.4 → 0.6 之间不断加入可选内容（深度视频、语言列），所以必须同时锁定库版本。另外，本机 `lerobot` 环境是 `main` 的 0.6.2 开发快照，不是发布版。
- 详细结论、出处和未能查实的点：[docs/research/LeRobot版本.md](../../../docs/research/LeRobot版本.md)
