评审第 1 轮（一键脚本这一段），两项阻塞，都是真实环境才暴露的。快照 `refs/rdp/m0-11/C-B-out`。

**1. 重复运行会失败（setup.sh）**
`report_existing_installation` 调用了不带参数的 `"$deploy_dir/.venv/bin/rdp" status`。真实 CLI 要求必须且只能选一个参数：
```
$ ~/.local/opt/rdp/.venv/bin/rdp status
rdp status: error: one of the arguments --active-jobs --check-port --worker-stopped is required   (退出码 2)
```
在 `set -e` 下，已安装的机器再运行 setup.sh，会以 2 退出，而不是报告状态。测试没发现，是因为 `tests/setup_support.py:298` 的假 `rdp` 接受了 `["status"]`。
- 修法：
  - 报告状态时用真实存在的子命令。例如 `rdp --version`、`rdp status --worker-stopped`、`rdp status --active-jobs`（退出码 3 表示"在运行/有作业"，要当作正常的状态信息，不能当失败）。
  - 默认模式再报告 `systemctl --user is-active rdp-web.service rdp-worker.service`，`--no-systemd` 时不调用。
- 根本修法：假 `rdp` 的参数规则要和真实 CLI 一致。至少让测试断言 setup.sh 发给 `rdp` 的每一组参数，都能被真实的 `rdp.ops.cli` 参数解析器接受（在测试里直接调用解析器，不起服务）。你也可以给出同等效果的做法。顺手检查 setup.sh 里其余对 `rdp`、`install.sh`、`upgrade.sh`、`setup_queries` 的调用，参数是否都合法。

**2. 真实安装时 systemd 拒绝启动两个服务（install.sh，第 11 张前半段的缺陷）**
负责人做真实安装（验收 6）时，`install.sh` 生成的单元里写的是 `WorkingDirectory="/home/shawn/.local/opt/rdp"`。systemd 259 报错：
```
rdp-web.service:9: WorkingDirectory= path is not absolute: "/home/shawn/.local/opt/rdp"
Unit rdp-web.service has a bad unit file setting.
```
`WorkingDirectory=` 不支持引号，值按整行原样取，空格不用转义，`%` 要写成 `%%`。`ExecStart=` 带引号是合法的。`Environment=` 带引号也合法，要确认它现在的写法对不对。`tests/test_ops_deploy_scripts.py:516` 断言的正是错误的带引号写法。
- 修法：
  - 改 `scripts/install.sh` 的替换逻辑。如果 `upgrade.sh` 也写单元，一并检查。
  - `WorkingDirectory` 不加引号；部署目录里有 `%` 时写成 `%%`；其余指令要符合 systemd 的引号和 `%` 规则。
  - 测试改成断言正确的写法。
  - 再加一项测试：用本机的 `systemd-analyze verify`（只解析单元文件，不连接用户总线、不调用 systemctl）检查渲染出来的两个单元，部署目录取三种：普通路径、含空格和中文、含 `%`。
    - 单元里的 `ExecStart` 指向的可执行文件要真实存在，在临时目录里放一个假的。
    - 本机没有 `systemd-analyze` 时测试失败并说明原因，不要跳过，`make check` 要求 0 skipped。
    - 先确认 `systemd-analyze --version` 能在你的沙箱里运行；不能运行就停下，在最终回复里说明，不要绕开。
- 本票允许改 `scripts/install.sh`、`scripts/upgrade.sh`、`scripts/systemd/`、`tests/test_ops_deploy_scripts.py`。

**要求**
- 每项先写能复现的失败测试，看到它红，再修。
- 只改上面点到的文件，以及 `scripts/setup.sh`、`src/rdp/ops/setup_queries.py`、`tests/`。
- 最后跑一次 `make check`，pytest、Vitest 都要 0 skipped。
- 边界同上一轮：不 `git add`、不提交、不联网、不安装，不调用真实 `systemctl`、`loginctl`，不碰真实 `~/.config`、`~/.local`，不碰 `/mnt`。

40 分钟内交付。最终回复五块，格式同上一轮，第 1、5 块只写本轮。
