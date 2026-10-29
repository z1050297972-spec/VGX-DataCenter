一键部署脚本的骨架已获批（负责人预批，执行线复查通过），契约提交 `51288e7`（`契约：一键部署脚本`），内容就是你交的骨架；你第 4 块的设计选择全部采纳（见工单最后一条 Comment）。工作目录现在是干净的。

动手前用绝对路径重读：工单 /home/shawn/桌面/robot-data-platform/.scratch/m0-foundation/issues/11-ops-entry-systemd.md 的「一键部署脚本」、验收 9 和最后两条 Comment；/home/shawn/桌面/robot-data-platform/docs/agents/codex-workflow.md 第 7.1 节。

现在按测试清单逐个实现，用 $tdd 和 $enterprise-coding：
1. 每次去掉一个测试的跳过，先单独运行它（`.venv/bin/pytest tests/<文件>::<测试名>`），看到它失败，再写实现让它通过。去掉跳过就直接通过的，在最终回复里逐个列出并说明原因。评审会做变异抽查。
2. 已获批的函数划分、参数、`--help` 契约和 docstring 不改含义；措辞补充照改并在第 3 块列出；要改含义就停下写契约变更申请。
3. 最后 `make check` 全绿，pytest、Vitest 都 0 skipped。

要求：
- `usage` 输出骨架注释里的完整帮助文本（这是手册依据），注释里的帮助副本可以删掉，只留一份；版本号从顶部版本表取。
- 脚本测试照 `tests/test_ops_deploy_scripts.py` 的做法：临时目录里的假 `git`、`uv`、`pnpm`、`node`、`curl`、`sha256sum`（可用真的）、`systemctl`、`loginctl`、`nvidia-smi`、`findmnt`、`ip`、`install.sh`/`rdp` 放在 PATH 前面并记录调用；测试进程和脚本的 `HOME` 必须是临时目录；"下载"由假 `curl` 从临时目录返回构造好的归档和校验文件（包括摘要不符、超限、路径逃逸的情况）。交互用 pty 或可控 stdin 驱动，所有子进程有超时并清理。
- 假 `install.sh` 的方式由你定（例如让 setup 通过一个仅测试可设的环境变量找安装脚本，或在临时仓库副本里放假脚本）；不允许改变真实 install.sh 的行为。
- 删掉骨架期的说法（"骨架""桩""实现阶段""待实现""号票"等），只写现在的行为；`第 N 张` 可保留。交付前在本轮改过的文件里搜这些词。

为了不超时：每个测试单独先红后绿，改完一个文件只跑相关测试文件，最后只跑一次 `make check`。到 75 分钟还没做完，停在 `make check` 全绿的位置交检查点（做完的去掉跳过，没做的保留跳过），第 4 块写清还剩什么。

边界：
- 只改 `scripts/setup.sh`、`src/rdp/ops/setup_queries.py`、`tests/`；`Makefile` 不再改。其余已验完的文件不动，除非测试确实需要（写进第 1 块并说明）。
- 改动留在工作区，不 `git add`、不提交。
- 不读 `~/桌面/data_check`、`~/桌面/Data_Collection_System-main`，不碰 `/mnt`。
- 不安装任何东西，不访问网络（真实下载由执行线在验收 9 做；评审查运行日志，出现安装或联网命令整轮打回）。
- 不运行真实 `systemctl`、`loginctl`、`nvidia-smi`、`findmnt`；不碰真实 `~/.config/`、`~/.local/`；不运行真实的 setup.sh/install.sh 去改真实目录。
- 自己在 `/tmp` 或别处建的试验文件交付前删掉。

只有三种情况停下：要加新依赖；要改允许范围以外的文件；要改已获批契约的含义。

最终回复分五块：1 改动清单；2 `make check` 命令和末尾输出原样，加跑之前和之后的 `git status --porcelain --untracked-files=all`；3 契约变更申请、依赖申请（没有写"无"），列出改了哪些 docstring/帮助的哪几句；4 拿不准的地方，交检查点时写清还剩什么；5 先红后绿，每个测试一行。
