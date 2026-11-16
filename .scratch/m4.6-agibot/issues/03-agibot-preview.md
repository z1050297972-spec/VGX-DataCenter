# AgiBot 清洗预览：在沙箱里跑工具，生成报告

Status: done（实现及验收完成；负责人已授权合并、升级、推送）

分级：直做。与第 04、05 张并行。决定见 `../decisions.md` 第 1、4、5、7 条和「工具的事实」（预览结果文件的格式在那里）。

## 要做的（`src/rdp/jobs/cleaning/`）

清单有 `command.preview` 的工具，清洗预览作业走新分支；没有的（mcap2lerobot）完全不变。四个阶段名不变（「核对工具」「核对输入」「读取文件」「生成报告」）。

1. **核对输入**：`selected_inputs(..., input_format=manifest.io.input_format)`；必须恰好一个数据块，路径形如 `<…>/observations/<数字>` 且落在已登记存储根内，否则输入问题（文案："请选择一个已解压的任务观测目录"）。在线检查照现有写法。
2. **读取文件**：用清单 `command.preview` 模板生成命令（`{config}` = 登记包里该型号的配置，`{rules}` = 该型号的清洗规则，`{cache}` = `tool_cache_dir(...)`，`{result}` = `result_file(cache, job_id)`，`{inputs}` = 数据块路径），前面包 `offline_tool_argv(cache, …)`，再包 bwrap（只读根 = 全部非可写存储根，可写目录只有工具缓存目录），用 `run_terminal_process` 运行，解析器 `create_terminal_parser(manifest.runtime.progress, stage_count=4, first_stage=3)`（第 4 阶段留给"生成报告"；预览只会用到 `first_stage`）。超时 12 小时。清洗作业的依赖里要加沙箱注入点（照 `ConversionDependencies.sandbox` 的做法，测试可注入不隔离的假工具）。
3. **生成报告**：读结果文件（上限 256 MiB，读完删除；工具失败或作业取消时也要删），用 Pydantic 模型严格校验（未知字段拒绝；`schema_version` 必须是 1；episode 目录必须在数据块路径之下），不合格按外部问题失败（规则 `cleaning.tool_preview_invalid`）。然后按决定第 1 条映射成 `CleaningReport(source_format="agibot_native")`：
   - 每集一个 `FileReport`（`episode_id`、`path` = `observation_dir`、`size_bytes`、`mtime_ns` = `observation_mtime_ns`、`fatal_issues` = 每条 `problems` 一个五段诊断（规则 `cleaning.agibot_episode_unusable`）、`default_excluded` = 有体检问题）。
   - 没有体检问题的集各一个 `EpisodeReport`；`issues` 由工具的 `issues` 映射：`check` 原样，严重程度和文案沿用 `_checks.py` 的 `SEVERE_CHECKS` 与现有描述（`joint_limit`、`action_jump`、`non_finite`、`entire_static`、`long_static`），`details` 填 `count`、`first_time_s`、`ranges`、`feature`；有严重问题的 `default_action = "exclude"`。工具给了未知的 `check` → 按结果不合格处理。
   - `fps` 取结果的 `fps`；`tool_config_sha256` = 登记包配置文件的 sha256（并核对结果里 `robot_config.sha256` 与之相等，不等按不合格处理）；`rules_sha256` = 规则文件原始字节的 sha256；`rules.sync = None`，`rules.checks` 从规则文件填（`static_feature`、`long_static_s`、`jump_feature`、`sources`（`topic` 字段放规则里的 `field`）、`severe_checks`；图像字段为 None）。规则文件格式见工具 README（`schema_version`、`[static]`、`[jump]`、`[[source]]` 的 `field`/`static_threshold`/`jump_threshold`/`limits`）；平台这边只为填快照而读它，读不懂按输入问题失败。
   - `summary`：`files` = 集数，`excluded_files` = 有体检问题的集数，`episodes` = 可转集数，`excluded_episodes` = 默认剔除的 episode 数，`reference_frames = kept_frames` = 可转集的帧数合计。
4. 保存预览记录：`binary_sha256` 用 `tool.fingerprint`，其余同现有。

## 不做

转换（第 04 张）；页面（第 05 张）；改工具。

## 测试范围（只做关键测试；工具用假程序：测试里的可执行脚本，按参数把预设的结果 JSON 写到 `--result`）

1. 正常：假工具收到的参数（配置、规则、缓存目录、结果文件、任务目录）正确；报告的文件/段映射、默认剔除、汇总数正确；结果文件读完已删除；预览记录的指纹是 `tool.fingerprint`。
2. 体检有问题的集 → 文件致命、默认剔除、没有对应的 episode；`non_finite` → 该集默认剔除；`long_static` → 默认保留。
3. 选了两个数据块 / 数据块不是任务观测目录 → 输入问题，工具没被调用。
4. 结果文件不合格（未知字段、episode 目录越出数据块、未知 check、配置 sha256 不符）→ `cleaning.tool_preview_invalid`，不保存预览，结果文件已删除。
5. 工具非零退出 → 作业失败，结果文件（若有）已删除。
6. mcap2lerobot 的预览测试照常通过。

## 验收

测试通过；`PYTHONPATH=$PWD/src make check` 全绿（OpenAPI 快照除外）。执行线另用真实工具在样本上跑一次（第 06 张）。

## Comments

- 执行线收尾：最终后端3120、前端441全绿；Alpha真实本地样本全链路3 passed、G2合成归档真实bwrap全链路1 passed、G2真实task_3405归档13集30681帧四层检查通过。详见 `../assets/verification-results.md`。没有生产部署或推送。
