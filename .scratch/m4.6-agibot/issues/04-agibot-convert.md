# AgiBot 转换接入：从预览发起，工具在沙箱里只转保留的集

Status: blocked（依赖第 01、02 张）

分级：直做。与第 03、05 张并行（本票只动 `src/rdp/jobs/conversion/` 和 `src/rdp/api/cleaning_previews.py`；第 03 张只动 `src/rdp/jobs/cleaning/`）。决定见 `../decisions.md` 第 1、5、6 条。报告的 AgiBot 形状见第 01 张第 4 节，本票的测试自己构造这种报告，不依赖第 03 张。

## 要做的

预览报告 `source_format == "agibot_native"` 时转换走下面的规则；MCAP 的行为完全不变。六个阶段名不变。

1. **接口与选择**（`convert_from_cleaning_preview`、`_cleaning_selection.select`）：`agibot_native` 报告不接受 `excluded_episodes`（非空 → 422，文案"AgiBot 数据按集剔除，请使用 excluded_files"）；其余校验沿用（致命文件必须剔除、至少保留一个）。这样 `Selection.excluded_indices` 恒为空，不会走 LeRobot 删除。
2. **预览核对**（`preview_selection`）：工具指纹用 `tool.fingerprint`（第 01 张已改）；`agibot_native` 不要求 LeRobot 环境。
3. **输入核对**（`check_files`）：`agibot_native` 的文件是目录，只比 `st_mtime_ns` 与报告的 `mtime_ns`（并确认是目录）；MCAP 仍比大小和 mtime。
4. **路径**：`_prepare_paths` 里"文件路径在所选数据块之下"的核对对目录同样成立；`selected_inputs` 传 `input_format=manifest.io.input_format`。
5. **命令**：`{inputs}` = 未剔除文件的 `path`（观测目录），按 `file_index` 顺序；模板里有 `{cache}` 时代入 `tool_cache_dir(...)`，并把它加进沙箱可写目录；清单 `runtime.progress == "agibot2lerobot-events"` 的工具，verify 和 convert 命令前都包 `offline_tool_argv(stage, …)`。verify 仍用 `context.run_process`，convert 仍用 `run_terminal_process` + `create_terminal_parser(manifest.runtime.progress, stage_count=6, first_stage=3)`。
6. **产物核对**：照旧用 `check_output` 比每集帧数（期望值 = 保留集的 `frame_count`，顺序与工具产物一致：都按 episode ID 升序）。
7. **剔除阶段**：`excluded_indices` 为空时直接跳过（现有逻辑）；确认此时不会去读 MCAP 专用的工具配置（现在第 5 阶段无条件调用 `load_configs(...)` 解析 mcap2lerobot 格式的配置，对 AgiBot 配置会失败——改成只在需要剔除时才读）。
8. **回执**：`tool.binary_sha256` 用 `tool.fingerprint`，另加 `source_tree_sha256`（没有为 null）；`cleaning` 段沿用。入库写血缘的参数不变。
9. **空间预检**：默认百分比来自清单（第 01 张已做）；确认 AgiBot 报告的 `size_bytes` 合计被用作输入字节。
10. 不占 GPU 的工具（`needs_gpu = false`）转换作业不申请 GPU（登记处已按清单传 `requires_gpu`，确认执行时 `gpu_index` 为 None 不出错）。

## 不做

预览（第 03 张）；页面（第 05 张）；入库检查与入库流程（不变）；改工具。

## 测试范围（只做关键测试；工具用假程序，按参数写出最小的 LeRobot v3.0 目录）

1. 从 `agibot_native` 预览转换：假工具的 verify 和 convert 都只收到未剔除集的目录、顺序正确，`{cache}` 被代入且缓存目录在沙箱可写列表里；产物帧数一致时成功；回执里有两个指纹。
2. `excluded_episodes` 非空 → 422（接口）且执行器也拒绝。
3. 预览后某个保留集的目录 mtime 变了 → 输入问题，没有暂存目录，工具没被调用；被剔除的集变了不影响。
4. 产物某集帧数与预览不一致 → `cleaning.output_mismatch`。
5. 没配置 LeRobot 环境时 `agibot_native` 转换照常成功。
6. 现有 MCAP 转换测试照常通过。

## 验收

测试通过；`PYTHONPATH=$PWD/src make check` 全绿（OpenAPI 快照除外）。

## Comments
