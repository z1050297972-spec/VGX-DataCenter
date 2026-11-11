# 给工具开伪终端时设 TERM（修 M4 进度条缺陷）

Status: open（2026-11-10 负责人："请帮忙维修"）

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
