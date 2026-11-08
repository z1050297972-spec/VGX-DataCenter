# 工具登记与工具库页面

Status: in-progress

分级：直做（负责人 2026-11-08："可以拜托你按照顺序帮忙完成M4吗"，此前"其他按照推荐来"；骨架和合并由执行线按建议过，记进 Comments）。按"只做关键测试"。不写导航层。

Blocked by: 无（和第 02 张并行，文件不重叠）

## 依据

- `../decisions.md` 决定 1、2：工具原样不动；平台侧登记包 `tools/<工具名>/`；版本靠程序 sha256。
- ADR 0008（工具库、清单是工具的事实来源）；ADR 0003（平台不 import lerobot）；ADR 0006（Web 不碰存储根）。
- 已放好的登记包：`tools/mcap2lerobot/tool.toml`、`tools/mcap2lerobot/configs/r1lite.toml`（执行线维护，本票只读，不改）。

## 契约

### 新领域包 `rdp.tools`

- 在 import-linter 里登记成领域包（和 `rdp.jobs`、`rdp.accounts` 同层的规则照抄现有写法）。
- **清单模型**：按 `tools/mcap2lerobot/tool.toml` 的字段写 Pydantic 模型（`extra="forbid"`，冻结）。校验：
  - `schema_version == 1`。
  - `tool.name` 匹配 `^[a-z0-9]+2[a-z0-9]+(-[a-z0-9]+)?$`，且等于登记包目录名。
  - `tool.directory`、`program.path`、`models` 的值都是相对路径，不含 `..`、不以 `/` 开头；`models` 指向的配置文件必须在登记包里存在。
  - `program.sha256` 是 64 位小写十六进制；`program.size` 正整数。
  - `io.output_versions` 非空、不重复。
  - `command.convert` 必须含 `{config}`、`{output}`、`{format}`、`{inputs}` 各一次，且不含 `--force`；`command.verify` 必须含 `{config}`、`{inputs}`。`{inputs}` 必须单独作为一个参数。
  - `runtime.progress` 是已知解析器名的枚举，本票只有 `"mcap2lerobot-pty"`（解析器本身在第 02 张）。
- **读取登记**：`load_tool_registry(registry_dir, library_root) -> ToolRegistry`。逐个子目录读 `tool.toml`；一个清单坏了只让它自己标"清单无效"并带诊断（五段式），不影响其他工具。
- **工具状态**：每个工具一个状态，四选一：`可用`、`程序找不到`、`指纹不符`、`清单无效`。
  - 程序绝对路径 = `library_root / tool.directory / program.path`。
  - 指纹：`O_RDONLY | O_NOATIME` 打开，分块算 sha256；大小先比，大小不同直接判"指纹不符"不读全文件。
  - 结果按 `(st_dev, st_ino, st_size, st_mtime_ns)` 缓存，同一进程内文件没变就不重算。
  - 诊断写明：对象（工具名、程序路径）、期望和实际（sha256 前 12 位、大小）、后果（不能用于转换）、下一步（"工具程序已变化，需要执行线重新登记"）。
- **配置**：`PlatformConfig` 加 `tools` 一节：`library_root`（默认 `/mnt/datasets/工具`）、`registry_dir`（默认平台安装目录下的 `tools/`，照现有定位前端构建产物的办法找安装目录，不写死路径）。旧配置文件没有这一节照常加载。

### 接口（Web 进程）

- `GET /api/tools`：列表，每项含 name、version、summary、input_format、output_format、output_versions、适用型号列表、needs_gpu、status 和诊断、程序路径、sha256 前 12 位。成员可看。
- `GET /api/tools/{name}`：详情，在列表字段之外加：每个型号的配置文件名、配置全文、配置 sha256；两条命令模板；`source_commit`、`source_note`。不存在 404。
- Web 只读登记包和工具程序文件（stat + 算指纹），不读别的存储根内容（ADR 0006 的例外只限这一处，写进模块注释）。

### 页面

- 左侧导航加"工具库"。表格列：名称、版本、说明、输入 → 输出、适用型号、需要 GPU、状态（`可用` 绿色，其余红色并在悬停或展开里显示诊断）。
- 点一行打开详情抽屉：上面的详情字段；配置全文用等宽只读块显示。
- 只用 antd（前端样式线约定），文案中文。

## 范围

后端 `src/rdp/tools/`、配置、接口路由、生成的 `openapi.json`/`schema.d.ts`；前端工具库页面和路由。

## 不做

- 数据库表（工具只有几个，清单本身就是事实来源，每次读登记包即可）。
- 运行工具（第 02、03 张）。
- 在页面上新增或修改登记包（登记包随平台代码评审）。

## 允许改的受保护文件

- `pyproject.toml` 里 import-linter 的配置段（只为登记 `rdp.tools`）。
- 生成的 `openapi.json`、`schema.d.ts`（只能 `make api-types`）。

## 依赖申请

无（`tomllib`、`hashlib` 是标准库）。

## 验收（关键测试）

1. 用真实的 `tools/` 目录和一个 tmp 下的假工具库（假程序文件内容按测试自己算 sha256 写进临时清单）：`可用`；改一个字节后 `指纹不符`；删掉程序 `程序找不到`。
2. 清单校验：名字和目录名不一致、`command.convert` 带 `--force`、缺 `{output}`，各一个用例，状态"清单无效"且其他工具不受影响。
3. 真实 `tools/mcap2lerobot/tool.toml` 能通过清单校验（不检查真实程序，测试不碰 `/mnt`）。
4. 接口：列表和详情经真实应用测；详情返回配置全文；不存在的名字 404。
5. 前端：列表里一行 `指纹不符` 显示红色状态和诊断，一个 Vitest 用例。
6. `make check` 全绿、0 skipped。

## Comments

- 2026-11-08 开票（执行线）。
- 2026-11-08 05:1x 派工（直做，一次交付）：worktree `robot-data-platform.wt/m4-01-tool-registry`，分支 `t/m4-01-tool-registry`；systemd 单元 `rdp-m4-01`；模型 `gpt-6-astra` high，90 分钟上限；会话 `01a1bb11-9d41-74c0-944b-565981d1ec4b`；提示和日志在 `~/.cache/rdp-dispatch/m4-01/`。第 01、02 张并行。
