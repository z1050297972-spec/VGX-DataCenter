# 清单与登记扩展：源码目录指纹、预览命令、报告模型的 AgiBot 形状

Status: done（2026-11-15 合进集成分支）

分级：直做（负责人 2026-11-15 "可以使用多个gpt去做"，骨架关卡由执行线预授权略过）。与第 02 张并行，文件不重叠。决定见 `../decisions.md` 第 1、2、4、5、6 条。

## 背景

要把 Python 写的 AgiBot 转换工具登记进工具库。现有清单模型只认"单个程序文件 + 伪终端进度 + MCAP 报告"，本票把后面三张票共用的契约一次改好：清单字段、登记状态、数据块格式参数、清洗报告模型。本票不运行工具，不改执行器的流程。

## 要做的

### 1. 清单模型（`src/rdp/tools/manifest.py`）

- `ToolProgram` 加可选 `tree: RelativePath | None`、`tree_sha256: str | None`（64 位小写十六进制）；两者必须同时给或同时省略。
- `ToolRuntime.progress` 的取值加 `"agibot2lerobot-events"`；加 `space_ratio_percent: int = 25`（严格整数，0–1000）：转换空间估算的默认百分比。
- `ToolCommands`：
  - 加可选 `preview: tuple[str, ...] | None = None`。给了就必须含 `{config}`、`{rules}`、`{cache}`、`{result}`、`{inputs}` 各恰好一次，`{inputs}` 单独成一个参数。
  - `verify`、`convert` 允许出现 `{cache}`（至多一次）；原有约束不变。
- `ToolManifest`：`command.preview` 给了时，`cleaning` 不能为空（预览要用规则文件）。

### 2. 登记状态（`src/rdp/tools/registry.py`）

- 有 `program.tree` 时，在程序指纹通过后再核对源码目录指纹；不符为"指纹不符"，诊断写明是源码目录、期望和实际的前 12 位。目录不存在或读不了为"程序找不到"。
- 指纹算法（要与登记一致）：`tree` 目录下递归找 `.py`（跳过名为 `__pycache__` 的目录，不跟随符号链接；遇到符号链接文件按读取失败处理），取相对 `tree` 的 POSIX 路径，按路径排序；依次把 `路径 UTF-8 + b"\0" + 文件内容 sha256 十六进制 + b"\n"` 送进一个 sha256，取十六进制。
- 读取沿用现有写法：`O_RDONLY | O_NOATIME | O_NOFOLLOW`，目录也用 `O_NOATIME` 打开后列举；总预算沿用现有 10 秒；上限 2000 个文件、合计 64 MiB，超过按读取失败处理。可按"每个文件的 (dev, ino, size, mtime_ns) 组成的元组"缓存结果。
- `RegisteredTool` 加只读属性 `fingerprint`：清单有 `tree_sha256` 时取它，否则取 `program.sha256`；清单无效时为 None。**本票把 `src/rdp/jobs/cleaning/job.py` 和 `src/rdp/jobs/conversion/`（`_cleaning.py` 的预览核对、`job.py` 的回执 `binary_sha256`）里直接用 `manifest.program.sha256` 的地方改成这个属性**（对 mcap2lerobot 值不变）。

### 3. 数据块格式参数（`src/rdp/jobs/conversion/parameters.py`）

- `selected_inputs` 加必填的关键字参数 `input_format: str`，把写死的 `"mcap"` 换成它（诊断文案里的格式名也跟着变）；两个调用方（清洗预览作业、转换作业）传 `manifest.io.input_format`。
- `tool_parameters`（转换）：请求没给 `space_ratio_percent` 时取清单的 `runtime.space_ratio_percent`（现在是模型默认 25；要能区分"没给"和"给了 25"）。

### 4. 清洗报告模型（`src/rdp/jobs/cleaning/models.py`）

- `CleaningReport` 加 `source_format: Literal["mcap", "agibot_native"] = "mcap"`；`reference_topic` 改成 `str | None`。
- `CleaningRuleSnapshot.sync` 改成 `CleaningSyncRules | None`；`CleaningCheckRules` 的 `frozen_s`、`sample_interval_s`、`dark_below`、`bright_above` 改成 `float | None`。
- `FileReport` 加 `episode_id: str | None = None`。
- 校验：`source_format == "mcap"` 时上述可空字段都必须非空、`episode_id` 必须为空（旧报告照常能读）；`"agibot_native"` 时 `reference_topic`、`rules.sync`、四个图像字段必须为空，每个文件的 `episode_id` 非空、`topics` 为空。
- 现有 MCAP 报告的生成和已存报告的读取不受影响（库里的旧 JSON 没有新字段）。

### 5. 工具列表接口（`src/rdp/api/tools.py`）

- 列表项加：`preview_by_tool: bool`（清单有 `command.preview`）、`default_space_ratio_percent: int`、`source_tree_sha256: str | None`。清单无效的工具三项分别为 false、25、null。

## 不做

- 运行工具、进度解析、缓存目录（第 02 张）；预览和转换执行器的 AgiBot 分支（第 03、04 张）；前端（第 05 张）；`tools/agibot2lerobot/` 登记包（执行线在本票合并后加）。

## 允许改的受保护文件

无。OpenAPI 快照过期的失败写在回复里，执行线来更新。

## 测试范围（只做关键测试）

1. 清单：`tree` 与 `tree_sha256` 只给一个 → 无效；`preview` 缺占位符 → 无效；`preview` 给了而 `cleaning` 为空 → 无效；现有 mcap2lerobot 清单照常有效。
2. 登记：临时工具库里造一个带 `tree` 的工具——指纹对上"可用"；改一个 `.py` 的内容 → "指纹不符"；新增一个 `.py` → "指纹不符"；`__pycache__/x.pyc` 的增删不影响；`tree` 目录不存在 → "程序找不到"。用测试里独立写的参考实现算期望指纹。
3. `fingerprint` 属性：有 `tree` 取 `tree_sha256`，没有取程序 sha256。
4. `selected_inputs`：`input_format="agibot_native"` 时接受该格式的数据块、拒绝 mcap 数据块；`"mcap"` 行为不变。
5. 空间百分比：清单 130、请求没给 → 130；请求给 25 → 25。
6. 报告模型：一份合法的 `agibot_native` 报告能往返 JSON；`agibot_native` 带 `reference_topic` → 拒绝；不带 `source_format` 的旧 MCAP 报告 JSON 仍能读。
7. 工具列表接口返回三个新字段。

## 验收

1. 测试通过；`PYTHONPATH=$PWD/src make check` 除 OpenAPI 快照外全绿。
2. 执行线用真实工具目录核对：按本票算法算出的源码目录指纹等于 `dd098862…82f1`。

## Comments

- 2026-11-15 Codex（rdp-m46-01，含负责人线外批准的四处接线扩展）交付。执行线：真实工具源码目录指纹 = dd098862…（验收 2 通过）；后端全量 3004 通过；生成了 OpenAPI 类型；前端 tsc 有 11 处因新字段报错，交第 05 张修。变异：空间百分比默认判断被抓到；`__pycache__` 跳过规则没被测到（测试只放了 .pyc），不阻塞，记 followups。
