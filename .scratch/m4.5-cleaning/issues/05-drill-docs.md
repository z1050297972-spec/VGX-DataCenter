# 真实对照、端到端演练与文档

Status: done（2026-11-09 10:4x 对照、演练、文档完成；集成分支 t/m4.5-cleaning 留待负责人看）

分级：执行线（演练）+ Codex（文档）。依赖：第 01–04 张。决定见 `../decisions.md`「验收与演练」。

## 要做的

### 1. 真实对照（执行线）

负责人同意"挑最小的一个文件"只读对照。用 M5 已有的真实样本副本 `~/.cache/rdp-m5-offline/sample/r1lite_20261011_52s.mcap`（系统盘，O_NOATIME 拷自 dataset-35，不再读数据盘）：

- 工具：`mcap2lerobot verify -v -c tools/mcap2lerobot/configs/r1lite.toml <样本>`，在 bwrap 里只读运行。
- 平台：同一文件的清洗报告。
- 逐项核对：基准帧数；每个话题的容差、坏帧数、复用次数、|Δt| 平均和最大（差在 0.001 ms 以内）；坏帧总数、断点数、过短丢弃；每个 episode 的起止帧和帧数。全部一致才算过；不一致先查原因，属于重写的缺陷就开修缺陷票。
- 记录：耗时、两块数据盘写入扇区前后。

### 2. 端到端演练（执行线）

照 M4 第 05 张的副本环境（测试配置、临时状态目录、回环镜像作测试可写根，`~/.cache/rdp-drill/m4/` 的做法），输入是登记成只读根的样本副本目录：

1. 网页提交清洗预览 → 报告；
2. 在报告里手动剔除一个 episode → 进行转换；
3. 工具转换（GPU）→ 核对一致 → LeRobot 删除 → 入库检查 → 自动入库；
4. 核对：入库数据集的 episode 数 = 保留数；`来源.json` 转换记录带清洗参数；`转换回执.json` 有 `cleaning` 段；
5. 另做一次不剔除的转换，确认「剔除」阶段跳过；
6. 两块数据盘写入扇区前后不变，worker 日志没有 ERROR。

### 3. 文档（Codex 写，执行线审）

- 使用手册：新增"数据清洗与转换"一节（替换现在的"转换"操作说明）：先预览、报告怎么看（对齐规则、每类问题的含义和默认处理）、怎么改剔除选择、进行转换后的阶段、H.264 画面不检查、只有 episode 级剔除。
- 运维手册：`[tools] lerobot_python` 配置、LeRobot 环境指纹和重新登记的做法（改了 `~/桌面/lerobot` 或环境后怎么办）、迁移 0022、预览作业是整盘读（耗时估算）。
- 术语表（GLOSSARY.md）：清洗预览、清洗报告、坏帧、基准断点、致命问题、剔除。
- ADR 0008 修订节："M4.5：转换前清洗"（只能从预览发起、文件级和 episode 级剔除、LeRobot 环境只读+指纹）。
- 不改 README（合并 main 时再改）。

## 不做

- 不在真实部署上转换；不读数据盘做对照（用已有副本）。

## 验收

1. 对照全部一致，记录进 Comments；演练六项都过；文档评审通过。
2. 集成分支 `t/m4.5-cleaning` 上最后一次 `make check` 全绿、0 skipped。

## Comments

- 2026-11-09 执行线做演练和文档（证据在 `assets/05-drill/`：`drill.sh`、`compare.py`、`shot.mjs`、`drill-run.log`、`tool-verify.txt`、`preview-report.json`、`compare.txt`、`convert-receipt.json`、三张截图）。
- **真实对照**：工具 `verify -v`（bwrap 只读运行，输入 M5 的 52 秒 R1 Lite 样本副本）与平台演练里预览作业 #9 的报告逐项比对，共 62 项（基准帧、10 个非基准话题各 5 项、坏帧/断点/过短丢弃、保留帧、episode 数、5 个 episode 的起止和帧数），**0 处不一致**（`compare.txt`）。
- **端到端演练**（`drill.sh`，导航层副本 + 两个回环挂载的 ext4 测试根：样本输入登记为只读根、平台区可写；`[tools] lerobot_python` 指向 conda 环境 `lerobot`）：
  1. 工具库：mcap2lerobot 可用，清洗型号 Galaxea R1 Lite；LeRobot 环境 available、0.6.2、指纹 9e5c3242…5831。
  2. 用建链接口给 dataset-35 加指向样本的数据块，提交清洗预览（作业 9）→ 报告：1 个文件、1651 基准帧、保留 1647、5 个 episode（451/397/357/300/142），默认都保留。
  3. 手动剔除 (0, 2) → 进行转换（作业 12）：六阶段走完，「剔除」用 LeRobot 删掉产物 episode 2，`cleaned` 4 个 episode、1290 帧；回执 `cleaning` 段齐全。
  4. 自动入库检查（13）和自动入库（14）完成，新数据集 `R1_lite_table_withdrawing_lerobot_12`：4 个 episode、1290 帧；`来源.json` 转换记录 `parameters` 带 `cleaning_preview_job_id=9`、`cleaning_excluded_episodes="2"`、LeRobot 版本和指纹。
  5. 同一预览不剔除再转一次（作业 18）：「剔除」阶段跳过，回执 `excluded_episodes=[]`、`command=null`；入库 `_18`：5 个 episode、1647 帧。
  6. 只读核对：`/mnt/datasets` 清单逐字节相同；两块数据盘写入扇区前后 5304 / 33280 不变；工具程序 atime 不变；worker.log 0 个 ERROR。
- **演练暴露的问题**：
  - 报告页三处界面问题（1440 宽横向溢出、时长显示长尾小数、文件警告整张卡片太占地方）→ 第 04 张 resume 修正（f67f73f），重新截图核对通过（`report.png`）。
  - 转换时出现"连续30秒未解析出进度"：工具没有 `TERM` 时不画进度条，真实部署的 worker 也没有 `TERM`——M4 留下的缺陷，记 followups 第 5 条，按负责人要求没有开票。
- **执行线失误**：演练结束后核对导航层副本时，执行线的检查脚本顺着一个入口的软链接打开了数据盘上的 `meta/info.json`，sdb 写入扇区 33280 → 33312（+32，访问时间元数据），之后不再增长（followups 第 8 条，已记进经验）。
- **文档**：使用手册 11.1（清洗型号、LeRobot 环境状态）、11.2 重写为"清洗预览与转换"、11.3 补清洗血缘；运维手册（迁移 0022、清洗规则、预览耗时、LeRobot 环境配置与重新登记、重新编码）；术语表 7 个词（清洗预览、清洗报告、坏帧、基准断点、致命问题、剔除、LeRobot 环境）；ADR 0008 修订节"M4.5：转换前清洗"。README 不改（合并 main 时再改）。
- 演练用的回环镜像已卸载，镜像文件留在 `~/.cache/rdp-drill/m4.5/`。

