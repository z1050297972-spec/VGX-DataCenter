第 11 张前面的部分已经验完（最新实现提交 `b3a1b7b`，工作目录干净）。负责人在合并前加了一段新范围：**一键部署脚本 `scripts/setup.sh`**。这一轮只交它的契约骨架。

先用绝对路径重读工单 /home/shawn/桌面/robot-data-platform/.scratch/m0-foundation/issues/11-ops-entry-systemd.md 的「一键部署脚本」小节、验收 9 和最后一条 Comment；再读 /home/shawn/桌面/robot-data-platform/docs/agents/codex-workflow.md 第 7.1 节。

用 $enterprise-coding。骨架要求：
1. `scripts/setup.sh`（bash，`set -euo pipefail`）写出完整的 `--help`（执行线照它写手册：每个参数、默认值、交互时问什么、非交互怎么用、会联网下载什么、失败后怎么办、重复运行会怎样）和全部函数的结构与注释（每段做什么、读写什么、失败怎么停）；函数体只写 `exit 78`，和前面安装脚本的骨架做法一样。
2. 需要 Python 侧配合的（例如生成配置后用平台自己的配置校验检查、"已有管理员就跳过"要的只读查询、列出可访问地址），写成签名 + 六项 docstring + `raise NotImplementedError`；只能是只读的状态/校验查询，不放业务功能。
3. 测试清单写成跳过的测试，docstring 写明验证哪条行为。至少覆盖：缺 uv/pnpm/Node 时先问再装、拒绝就停下并打印手动安装办法、`--yes` 不问；安装位置在临时 `HOME` 的用户目录、不用 sudo；下载校验失败时停下且不留半装的工具；缺 git 或 systemd 只提示；linger 关着时问过再调用 `loginctl enable-linger`、失败打印管理员命令；已有配置不覆盖；问答生成的配置能通过平台校验，存储根的 UUID 来自挂载信息、只读与否标出；没有 `nvidia-smi` 时 GPU 为空；`install.sh` 参数透传；已有管理员时跳过建管理员；已安装时不重装、打印状态和升级命令；没有终端时缺参数报错退出、不卡住；健康检查失败时退出码非 0 并指出日志位置。
4. `make check` 全绿（新测试是跳过状态）。

**执行线给的设计方向**（可以改，改了在第 4 块写理由）
- 脚本从仓库副本里运行，自己由 `BASH_SOURCE` 定位仓库，不取代码、不 fetch。
- 工具自动安装：装到 `$HOME/.local/`（例如 uv 官方独立安装包、Node 官方 linux-x64 压缩包、pnpm 用 Node 自带的 corepack 或 pnpm 官方独立包，你选一种并说明）；版本固定写在脚本顶部一处，和仓库的 `pyproject.toml`、`uv.lock`、`src/web/package.json` 要求一致（本机现在是 uv 0.13.5、Node 22.23.2、pnpm 11.22.0，可作参考）；下载后校验 sha256（校验值写在脚本里，或从官方同源校验文件取，你定并说明）；遵守 `HTTPS_PROXY` 等环境变量；PATH 只在本次运行里加，另外提示怎么写进 shell 配置。Python 由 uv 按 `requires-python` 自己装，不单独处理。
- 生成配置前平台还没装，配置校验怎么做由你提出（例如先 `uv sync` 再用部署目录里的 `rdp` 校验，或者 `install.sh` 拆出"只构建"一步）；不改已获批的 `install.sh` 行为含义，只加参数可以，写进第 3 块。
- 存储根的挂载信息用 `findmnt`（或读 `/proc/self/mountinfo`）获取，测试里用假命令；不在脚本里写 `/mnt`。
- 监听地址默认 0.0.0.0，问的时候说明"局域网明文 HTTP，可改成 127.0.0.1"。

边界同 prompt-B：只改 `scripts/`、`src/`、`tests/`（`Makefile` 只为把新脚本的 `bash -n` 接进来）；不 `git add`、不提交；不读 `~/桌面/data_check`、`~/桌面/Data_Collection_System-main`，不碰 `/mnt`；不安装、不联网；不运行真实 `systemctl`、`loginctl`、`nvidia-smi`、`findmnt`，不碰真实 `~/.config/`、`~/.local/`；不运行 setup.sh 或 install.sh 本身（只在测试里配假命令）。

45 分钟内交付。最终回复分四块：1 改动清单；2 `make check` 末尾输出原样；3 契约变更申请、依赖申请（没有写"无"）；4 拿不准的地方和你对设计方向的改动（需要负责人决定的单独标出）。
