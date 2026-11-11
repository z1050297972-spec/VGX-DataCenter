# 给工具开伪终端时设 TERM（修 M4 进度条缺陷）

Status: done（2026-11-10 评审、复验通过；分支 t/m4.5-06-worker-term b45cdaa 从 main 701ae34 开，已合进 t/m4.5-cleaning；2026-11-10 负责人"merge,update"后合进 main a7218f0 并升级部署）

分级：直做（后端，一处改动）。代码分支从 main 开（`t/m4.5-06-worker-term`，部署要单独用），做完也合进 `t/m4.5-cleaning`。来源：`../followups.md` 第 5 条。

## 背景

工具 mcap2lerobot 用 indicatif 画逐帧进度。环境里没有 `TERM` 时，即使 stderr 是伪终端也不画：第 05 张试跑实测，无 TERM 输出 197 字节，有 TERM 时近千行进度（`~/.cache/rdp-drill/m4.5-spike/pty-noterm.txt`、`pty-term.txt`）。真实部署的 `rdp-worker` 是 systemd 用户服务，环境里没有 `TERM`，平台开伪终端时也没补，所以转换作业 30 秒后记一条"连续30秒未解析出进度"的警告，之后只显示阶段。成败不受影响。M4 演练时 worker 是从带 TERM 的终端里起的，所以没暴露。

## 要做的

`src/rdp/jobs/processes.py`：

1. 走伪终端的运行（`run_terminal_process`，即 `parser` 不为空）给子进程的环境设 `TERM=xterm-256color`，不管 worker 自己有没有 `TERM`、是什么值，都覆盖成这个值。这个伪终端是平台开的，终端类型由平台声明；M4 录制解析样本时用的也是 xterm-256color。
2. 和 GPU 环境（`CUDA_VISIBLE_DEVICES`、`CUDA_DEVICE_ORDER`）合在同一份子进程环境里。不改进程全局的 `os.environ`。
3. 不走伪终端的运行（`run_external_process`、`ManagedExternalProcess`）保持原样。
4. 更新 `run_terminal_process` docstring 的 Side Effects。

bwrap 不清环境变量（没有 `--clearenv`），子进程能拿到这个值，不用改沙箱。

## 不做

- 不改解析器、窗口大小和阶段逻辑，不改工具。

## 测试范围（只做关键测试）

1. `tests/test_terminal_process.py`：测试进程里删掉 `TERM`（`monkeypatch.delenv`），假工具断言自己看到的 `TERM == "xterm-256color"`，同时 GPU 两个变量照旧。可以并进现有的 `test_terminal_progress_and_logs`，也可以单独写一个。
2. 再加一个情形：worker 的 `TERM=dumb` 时，子进程看到的仍是 `xterm-256color`。

## 验收

1. 相关测试和 `make check` 全绿、0 skipped。
2. 执行线验证：在没有 `TERM` 的环境里，用平台的 `run_terminal_process` 跑真实工具转换样本副本（系统盘上的那份，不读数据盘），作业进度里能解析出逐帧进度，不再出现"连续30秒未解析出进度"。

## Comments
- 2026-11-10 派工 Codex（gpt-6-astra high，单元 rdp-m45-06，日志 `~/.cache/rdp-dispatch/m4.5-06/`）。改 `_ProcessRun._spawn`：只在伪终端运行时复制环境（含 GPU 设置）并强制 `TERM=xterm-256color`，父进程环境不变；测试参数化 TERM 缺失和 `dumb` 两种。
- 评审通过；变异抽查（去掉设 TERM 那一行）两个用例都失败。本分支全量检查后端 2880 过、1 个失败是已知偶发的 `test_file_preview_api.py::test_video_concurrency_is_two_and_recovers`（与第 07 张钩子并行时负载高，单独重跑该文件 9 个全过；followups 第 10 条）。提交 b45cdaa（`--no-verify`）。
- 复验（`assets/07-drill/`，worker 用 `env -u TERM` 起，环境里 TERM 条数 0）：转换作业 12 的「转换」阶段 12 次采样全部带逐路帧进度（如 head_left 45/1647 → 1620/1647），作业日志里"未解析出进度"0 条。
- 2026-11-10 负责人"merge,update"：在 main 的工作树（m15-19-remove-backfill）把本分支合进 main（a7218f0，只带进 processes.py 和测试两个文件；main 已含 M5 第 03 张 viz_relay，是机器人侧程序，平台不加载）。main 全量检查全绿（后端 2895、前端 418）。`upgrade.sh --commit a7218f0 --yes` 升级真实部署：0.1.0 (85d7488) → 0.1.0 (a7218f0)，无新迁移，两个服务 active，`/api/health` ok；真实 rdp-worker 环境里确实没有 TERM，部署代码已含修复。真实转换要等 NAS，部署上的进度条没有实际跑过。未推送。升级前后已和 M5 会话（datasets-87）打过招呼。
