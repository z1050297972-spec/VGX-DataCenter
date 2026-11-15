# 事件进度解析与工具缓存目录

Status: done（2026-11-15 合进集成分支）

分级：直做。与第 01 张并行，文件不重叠（本票不动 `src/rdp/tools/`、`src/rdp/jobs/conversion/parameters.py`、`src/rdp/jobs/cleaning/models.py`、`src/rdp/api/tools.py`）。决定见 `../decisions.md` 第 3、5、6 条和「工具的事实」。

## 背景

AgiBot 工具把进度写成 stderr 上的 JSON 行，并需要一个可写的缓存目录（共用归档索引、预览结果文件）。本票提供三样后续执行器要用的能力，自身不改执行器流程。

## 要做的

### 1. 进度解析器 `agibot2lerobot-events`（`src/rdp/jobs/terminal/`）

- 新模块实现 `TerminalParser`：输入是伪终端字节流（任意分块，行尾可能是 `\r\n`），按行处理。
- 行首是 `{"event"` 且能解析成 JSON 对象的是事件行：
  - `progress`：`stage` ∈ `preview`、`probe`、`stage`、`data`、`videos`，`done`、`total` 为非负整数且 `done <= total`。不合法的事件行丢弃（不当文本、不报错）。
  - 其他事件（`log`、`result`、`task_done` 等）丢弃：`log` 的内容工具已经另外打印成普通文本行。
- 其他行原样作为文本行返回（去掉行尾空白）。单行超过 64 KiB 时截断丢弃到下一个换行，不让内存无界。
- 进度映射（`create_terminal_parser(name, stage_count=, first_stage=)` 的现有约定：`first_stage` 是"扫描"阶段序号，下一阶段紧随其后）：
  - `preview`、`probe` → 阶段 `first_stage`，单位"集"，`done`/`total` 取事件值。
  - `stage`、`data`、`videos` → 阶段 `first_stage + 1`；用三个分项（`ProgressPart`，名称依次"逐集处理"、"数据分片"、"视频分片"，单位依次"集"、"个"、"个"）分别显示各自的 `done/total`；顶层 `done/total` 取"逐集处理"的值（它占绝大部分时间）。
  - 阶段只进不退：出现过后一阶段的事件后，前一阶段的事件忽略。
  - 阶段名沿用调用方的展示约定：解析器不知道阶段名表，照现有 `Mcap2LerobotParser` 的做法处理（读它的实现，保持 `JobProgress` 其他字段的填法一致）。
- `create_terminal_parser` 按名字分发；未知名字仍是 `DefectError`。

### 2. 工具缓存目录

- `ToolsConfig` 加 `cache_root: Path`：默认 `<state_dir>/tool-cache`（在配置加载处由 `state_dir` 推出；读实现找到合适的位置，保持 `ToolsConfig()` 无参构造在测试里可用），绝对路径、不含 `..`。
- 新函数（放 `src/rdp/jobs/` 下合适的模块）`tool_cache_dir(settings: ToolsConfig, tool_name: str) -> Path`：返回 `<cache_root>/<tool_name>`，不存在就逐层创建（权限 0700）；任何一层是符号链接、或已存在但不是目录时抛 `ExternalError`（五段诊断）。`tool_name` 只接受清单命名规则允许的字符，其他抛 `DefectError`。
- 新函数 `result_file(cache: Path, job_id: int) -> Path`：返回 `<cache>/preview-<job_id>.json`；若已存在（上次中断留下的）先删除；是符号链接或目录时抛 `ExternalError`。

### 3. 离线环境包装

- 新函数 `offline_tool_argv(scratch: Path, argv: tuple[str, ...]) -> tuple[str, ...]`：在命令前加 `/usr/bin/env HF_HUB_OFFLINE=1 PYTHONDONTWRITEBYTECODE=1 HF_HOME=<scratch>/hf-home`。`src/rdp/jobs/conversion/lerobot.py` 的 `environment_argv` 里相同的环境设置改为复用它（行为不变）。

## 不做

- 清单字段（第 01 张）；执行器接线（第 03、04 张）。

## 允许改的受保护文件

无。

## 测试范围（只做关键测试）

1. 解析器：把一段真实样本（见下）按 1 字节、7 字节、整块三种分块送入，得到的最后进度和文本行相同；`probe 2/2` 后是阶段 `first_stage`；出现 `stage` 事件后进入下一阶段，三个分项的值正确；之后再来 `probe` 事件不回退。
2. 非法事件行（`done > total`、缺字段、JSON 不完整）不产生进度也不产生文本；普通日志行原样返回；超长行不撑爆内存且后续行照常解析。
3. `tool_cache_dir`：新建成功且权限 0700；路径上有符号链接 → `ExternalError`。`result_file`：已有旧文件被删除；是符号链接 → `ExternalError`。
4. `offline_tool_argv` 的输出；`environment_argv` 现有测试照常通过。

真实样本（工具在 bwrap + 伪终端里跑两集的 stderr，节选；测试里内联即可）：

```
任务 327：检查 2 集 ...\r\n
{"event": "log", "time": 1794749000.1, "message": "任务 327：检查 2 集 ..."}\r\n
{"event": "progress", "time": 1794749001.2, "stage": "probe", "done": 1, "total": 2, "task_id": "327"}\r\n
  [probe] 1/2\r\n
{"event": "progress", "time": 1794749001.3, "stage": "probe", "done": 2, "total": 2, "task_id": "327"}\r\n
{"event": "progress", "time": 1794749020.0, "stage": "stage", "done": 1, "total": 2, "task_id": "327"}\r\n
{"event": "progress", "time": 1794749025.0, "stage": "stage", "done": 2, "total": 2, "task_id": "327"}\r\n
{"event": "progress", "time": 1794749026.0, "stage": "data", "done": 1, "total": 1, "task_id": "327"}\r\n
{"event": "progress", "time": 1794749030.0, "stage": "videos", "done": 8, "total": 8, "task_id": "327"}\r\n
任务 327 转换完成：/x/out（392.9 MB，info 57372a1bfc66）\r\n
{"event": "result", "time": 1794749031.0, "command": "convert-episodes", "ok": true, "result": {"task_id": "327"}}\r\n
```

## 验收

测试通过；`PYTHONPATH=$PWD/src make check` 全绿。

## Comments

- 2026-11-15 Codex（rdp-m46-02）交付；执行线在沙箱外跑全量 make check 通过（后端 3019、前端 436），变异抽查（去掉阶段只进不退、去掉 O_NOFOLLOW）都被测试抓到。合进集成分支。
