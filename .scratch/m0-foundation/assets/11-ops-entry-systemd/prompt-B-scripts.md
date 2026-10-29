检查点收到（快照 `refs/rdp/m0-11/B-out`）。执行线在复查已完成部分，有问题会在下一轮一起提。现在只做剩下的安装、升级脚本：

- 实现 `scripts/install.sh`、`scripts/upgrade.sh` 的可执行逻辑和 `--help`，去掉 `exit 78`，按契约提交里脚本注释写的步骤、失败处理和 prompt-B 的要求做。
- 逐个去掉 `tests/test_ops_deploy_scripts.py` 里 22 项的跳过，先单独运行看到红，再实现（$tdd）。
- 假命令（git、uv、pnpm、systemctl、rdp）放在临时目录、PATH 前面，记录调用；测试进程的 `HOME` 是临时目录；不调用真实 systemctl/loginctl，不碰真实 `~/.config/systemd/user/`、`~/.local/opt/`，不运行脚本去改真实仓库（git worktree 用假命令或临时仓库）。
- 其余已完成的文件不要再动，除非脚本测试需要（写进第 1 块）。

边界同 prompt-B。60 分钟内交付；最后跑一次 `make check`（pytest、Vitest 都 0 skipped）。最终回复五块，第 1、5 块只写本轮。
