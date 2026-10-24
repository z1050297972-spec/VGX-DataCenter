r1 复评发现下面的问题，逐条修复，别处不动。修复清单原文也在工单 /home/shawn/桌面/robot-data-platform/.scratch/m0-foundation/issues/03-config-state-dir-runtime-log.md 的 Comments 最后一条（用绝对路径读主仓库目录的版本）。

1. 问题：过期归档清理时列目录失败，之后的日志全丢，和 r1 第 1 条同一形态。`_delete_expired` 只兜住了单个文件的 `unlink`，`getFilesToDelete` 里的 `iterdir()`（以及 `is_file`、`is_symlink`）报 `OSError` 时异常照样冒出去：启动阶段异常在 `self._startup_cleanup = False` 之前抛出，于是每条记录都重试清理、都经 `handleError` 被丢掉（复评实测跨零点 6 条全丢，`web.log` 是空的）；切分阶段异常在 `rotate` 之后、`rolloverAt` 前进和重开活动文件之前抛出（零点后 3 条全丢）。位置：`src/rdp/infra/logging.py` 的 `_DailyFileHandler._delete_expired`、`shouldRollover`、`doRollover`。期望：清理过程中任何一步的 `OSError`（列目录也算）都只让这次清理跳过或部分完成，当条和之后的记录照常写进活动文件；启动清理只试一次，失败也把 `_startup_cleanup` 清掉，留给下一次切分再试；切分时 `rolloverAt` 照常前进、活动文件照常重开。`getFilesToDelete` 自己的契约（返回过期归档列表、查询本身不删除）不变，兜底放在调用它的地方。先写测试、单独跑看到它失败，再改实现：启动阶段、切分阶段各一种（例如用 `patch.object(Path, "iterdir", …)` 对日志目录抛 `PermissionError`），断言跨零点前后的记录都在。
2. 问题：两个默认路径常量是公开名，多开了 `rdp.infra.config` 的对外接口（CODING_STANDARDS 2.9）。位置：`src/rdp/infra/config.py` 的 `DEFAULT_STATE_DIR_RELATIVE`、`DEFAULT_CONFIG_FILE_RELATIVE`。期望：改成 `_` 开头的私有名（例如 `_DEFAULT_STATE_DIR_RELATIVE`），注释不变；没有别处引用它们。

已获批的签名、类型和 docstring 不改。确实要改契约时停下，在最终回复里写契约变更申请。

修完后 `make check` 全绿。

边界：
- 只改 `src/`、`tests/`。本票允许改的受保护文件：`pyproject.toml`（只在 ruff、basedpyright 需要时调整配置，每条写理由；依赖表不动）。
- 改动留在工作区，不要 `git add`，也不要提交。
- 不读取 `~/桌面/data_check` 和 `~/桌面/Data_Collection_System-main`，不碰 `/mnt`。
- 不安装任何东西，不访问网络（沙箱为了跑测试开了网络权限，但这张票用不到网络；评审会查运行日志，出现安装或联网的命令整轮打回）。需要新依赖时停下，在最终回复里写依赖申请（AGENTS.md 规则 7）。
- 自己在 `/tmp` 或别处建的试验文件，交付前删掉。测试不碰真实的 `~/.config/rdp`、`~/.local/share/rdp`，不写 `.git/info/exclude`。

最终回复：逐条写处理结果（第 1 条新测试第一次运行的失败输出原样贴出）；`make check` 最后一次运行的命令和末尾输出，原样贴出；再原样贴出跑之前和跑之后的 `git status --porcelain --untracked-files=all`。
