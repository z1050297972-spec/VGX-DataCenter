# 伪终端运行与逐帧进度

Status: in-progress

分级：直做（负责人 2026-11-08 授权按顺序完成 M4；骨架和合并由执行线按建议过）。按"只做关键测试"。不写导航层。

Blocked by: 无（和第 01 张并行，文件不重叠）

## 依据

- `../decisions.md` 决定 3（伪终端取逐帧进度）、决定 4（bwrap 只读运行）。
- ADR 0004（工具和平台同一套诊断；原始输出进作业日志；工具没上报就退出时补"外部失败"诊断）。
- 真实样本：`tests/fixtures/mcap2lerobot/`（执行线 2026-11-08 在 bwrap + 伪终端里真跑录下，来源见同目录 `meta.json`）。
- 执行线已实测（2026-11-08）：
  - `bwrap --ro-bind / / --dev-bind /dev /dev --proc /proc --tmpfs /tmp --bind <暂存> <暂存> --die-with-parent -- …` 无特权可用；里面 `nvidia-smi`、`ffmpeg -c:v hevc_nvenc` 正常。
  - 经只读绑定读文件不更新 atime，直接读会更新。
  - 200 列伪终端里，indicatif 每行用空格补满整行宽度，行与行之间**没有换行**，靠 `\r`、`ESC[2K`、`ESC[nA/B` 重画；所以不能按行切，要在去掉控制序列后的文本流里匹配。

## 契约

### 1. 作业进度加"分项"

- `JobProgress` 加可选字段 `parts: tuple[ProgressPart, ...] = ()`，最多 16 项。`ProgressPart`：`name`（1–40 码点，非空白）、`done`（≥0）、`total`（≥done，未知为 None）、`unit`（非空）。
- 旧记录没有这个字段时按空元组读出；接口和生成类型跟着加；原有校验和语义不变。
- 前端作业详情（所有作业类型共用的进度区）：`parts` 非空时，在总进度下面逐项显示一条进度条和"done/total unit"；为空时和现在完全一样。

### 2. 伪终端运行外部命令

- `rdp.jobs.processes` 新增 `run_terminal_process(command, reporter, log, clock, *, gpu_index, parser) -> int`。取消、停止、超时、进程组回收、退出码保存、GPU 环境变量，全部和 `run_external_process` 一致（能复用就复用，不复制一份）。
- 区别只在输出：stdin 接 `/dev/null`；stdout 走管道，原样逐行进日志；stderr 接伪终端（标准库 `pty`，窗口 200 列 × 50 行，`TIOCSWINSZ`），读到的字节交给 `parser.feed(chunk)`。
- `parser` 是一个协议：`feed(bytes) -> TerminalUpdate`，`finish() -> TerminalUpdate`。`TerminalUpdate` 带两样：最新进度（可为空）、新出现的文本行（进度条以外的文字）。运行函数把文本行写进作业日志（带工具名前缀），把进度交给 reporter（每秒最多 2 次，结束时强制最后一次）。伪终端的原始重画字节**不进日志**（48 秒的转换就有 1.5 MB）；日志里另外每 30 秒记一行当前进度快照。

### 3. bwrap 沙箱

- `SandboxSpec(writable: tuple[Path, ...])` → 生成 argv：`/usr/bin/bwrap --ro-bind / / --dev-bind /dev /dev --proc /proc --tmpfs /tmp`，每个可写目录 `--bind P P`，再加 `--unshare-net --die-with-parent --`，后接工具 argv。可写目录必须是已存在的绝对路径，且不能是 `/`、不能在任何登记为只读的存储根之下（调用方传入只读根列表）。
- bwrap 不在或起不来时，作业以"外部失败"诊断结束，写明 bwrap 的 stderr；不退回不加沙箱运行。

### 4. mcap2lerobot 进度解析器（`runtime.progress = "mcap2lerobot-pty"`）

- 流式：去掉 CSI 控制序列，`\r` 当分隔；能处理切在 UTF-8 多字节字符或控制序列中间的块（不完整的尾巴留到下一块）。
- 识别三种进度（格式见样本，模板出自工具的 `src/progress.rs`）：
  - 分项：`<短名> [条] <done>/<total> 帧 …`，短名如 `head_left`、`wrist_left`、`state`、`action`；`0/0` 视为总数未知。
  - 总进度：`总进度 [条] <N>%  剩余 …`。
  - 消息计数：`扫描|转换 [条] <done>/<total> 条消息 …`，数字带千分位逗号。
- 换成 `JobProgress`：阶段按 `扫描 → 转换` 推进（阶段名就用这两个词，stage_count 由调用方给定）；`done/total` 用帧数（各分项 total 之和、done 之和），单位"帧"；`parts` 是每个分项的帧数。扫描阶段 done/total 用消息数、单位"条消息"。
- 进度条以外的文字（例如 `完成：5 个 episode，1647 帧 -> …`、`Error: …`、`Caused by:` 链）作为文本行返回，去掉补位空格，同一行不重复返回。
- 工具还在运行、却连续 30 秒没解析出任何进度时：报一条警告诊断（"进度解析不出来，只显示阶段"），之后只报阶段级进度；不让作业失败。成败只看退出码，不看解析结果。

## 范围

`rdp.jobs`（进度类型、processes、沙箱、解析器；解析器放 `src/rdp/jobs/terminal/` 之类的新子包，按解析器名登记，第 03 张按清单的 `runtime.progress` 取用）、作业详情前端的分项进度条、生成的接口类型。不碰 `src/rdp/tools/`（第 01 张同时在建）。

## 不做

- 转换作业本身、提交页面（第 03 张）。
- ADR 0004 的上报管道协议（现在没有工具支持；解析器只为这个工具写）。

## 允许改的受保护文件

- 生成的 `openapi.json`、`schema.d.ts`（只能 `make api-types`）。
- 如果 `JobProgress` 的持久化需要迁移，迁移编号用 main 上下一个空号（合并时执行线核对）。

## 依赖申请

无（`pty`、`fcntl`、`termios`、`select` 都是标准库）。

## 验收（关键测试）

1. 解析器回放 `convert-v3.ptylog.jsonl`：最后的进度 parts 是 5 项、每项 1647/1647 帧；全程 done 不减；能取到 `完成：5 个 episode，1647 帧` 这行文字。
2. 把同一段字节在每个位置切开再喂（至少覆盖一个汉字中间、一个控制序列中间），结果和不切一样。
3. `error-truncated-input.ptylog.jsonl`：文本行里有 `Error: 转换 … 失败`、`Caused by:`、`Bad magic number`。
4. `run_terminal_process` 用测试里的假程序（Python 脚本，在 stderr 是终端时才往 stderr 写进度，否则不写）：能拿到进度；取消时进程组被回收；超时按现有语义失败；stdout 原样进日志、伪终端重画字节不进日志。
5. 沙箱 argv：可写目录、`--unshare-net`、`--die-with-parent` 在内；可写目录是 `/` 或位于只读根之下时拒绝（纯函数测试，测试不依赖本机能否运行 bwrap）。
6. 前端：作业有 parts 时显示每项进度条和"done/total 帧"；没有 parts 时和原来一样，一个 Vitest 用例。
7. `make check` 全绿、0 skipped。
8. 执行线另做：在探针工作目录里用真实程序和 `~/.cache/rdp-m4-sample` 的 MCAP 副本跑一次 `run_terminal_process` + bwrap，核对进度和日志；两块数据盘写入扇区不变。

## Comments

- 2026-11-08 开票（执行线）。
- 2026-11-08 05:1x 派工（直做，一次交付）：worktree `robot-data-platform.wt/m4-02-terminal-progress`，分支 `t/m4-02-terminal-progress`；systemd 单元 `rdp-m4-02`；模型 `gpt-6-astra` high，90 分钟上限；会话 `01a1bb11-9d41-79c2-9438-f8b18932d54a`；提示和日志在 `~/.cache/rdp-dispatch/m4-02/`。第 01、02 张并行。
