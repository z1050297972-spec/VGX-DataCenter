你在工单「下载作业」的工作目录 /home/shawn/桌面/robot-data-platform.wt/m2-downloads（git worktree，分支 t/m2-downloads）里写契约骨架。分支上已经有第 01 张「下载计划」的实现（`src/rdp/jobs/downloads/plan.py`、`_http_child.py`），本票建在它上面，不改它已获批的契约。

先读下面这些。规划文件一律读主仓库目录 /home/shawn/桌面/robot-data-platform 里的版本：
- /home/shawn/桌面/robot-data-platform/AGENTS.md
- /home/shawn/桌面/robot-data-platform/docs/standards/CODING_STANDARDS.md
- /home/shawn/桌面/robot-data-platform/docs/agents/codex-workflow.md 第 7.1 节「历次评审打回过的写法」
- 工单 /home/shawn/桌面/robot-data-platform/.scratch/m2-downloads/issues/02-download-job.md
- M2 spec /home/shawn/桌面/robot-data-platform/.scratch/m2-downloads/spec.md（「负责人决定」全部，尤其第 6 条 aria2 参数表）
- 调研 /home/shawn/桌面/robot-data-platform/docs/research/hf-mirror下载机制.md（§2 的 D 列、§5.2 第 4–5 步、§5.3、§5.5、末尾「负责人决定」）
- ADR：/home/shawn/桌面/robot-data-platform/docs/adr/ 下的 0004、0005、0006（含 2026-10 的修订）
- /home/shawn/桌面/robot-data-platform/GLOSSARY.md
- 现有代码（复用，不重复实现）：`src/rdp/jobs/registry.py`、`execution.py`、`processes.py`、`progress.py`、`outcome.py`、`records.py`、`example.py`（作业类型的写法样例）、`src/rdp/infra/config.py`（StorageRootConfig、JobsConfig）、数据库迁移目录 `src/rdp/infra/db/migrations/versions/`（看现在的 head）

用 $enterprise-coding。这一步只交契约骨架：
1. 签名、类型和六项 docstring 写全（AGENTS.md 规则 4，CODING_STANDARDS 第 3 条）。函数体只写 `raise NotImplementedError`。
2. 外部边界做成可注入接口：aria2 RPC 客户端、aria2 进程启动、curl 兜底、校验（哈希）都能在测试里换成替身。
3. 测试清单写成跳过的测试（`pytest.skip`），每个测试的 docstring 写明它验证哪条契约行为。工单「验收」里每一条都要有对应测试，包括那个用本机 aria2c 和本地 `http.server`（只监听 127.0.0.1）的集成测试（骨架阶段同样跳过）。
4. 作业参数模型（Pydantic）写全：spec 第 6 条的每个 aria2 参数含默认值和范围；`DownloadRequest` 的字段；不得有 token 字段。
5. 如果"运行中调参"需要数据库表扩展，骨架里写出迁移文件（结构完整，迁移函数可以先写实）：迁移编号用 `0013`，`down_revision` 指向现在 main 上的 head。表结构变化在最终回复第 4 块写清楚。
6. 新作业类型如果要进生产登记表，在登记表里登记（这会改作业类型计数相关的测试，按需更新）。
7. `make check` 跑到全绿。

工单里写着"骨架里定"的几项（拦截跳往 huggingface.co 的重定向、curl 的跳转处理、校验结果缓存格式、429 降速规则、接口放 02 还是 03），在骨架里给出方案，并在最终回复第 4 块逐条列出理由。负责人已预授权骨架按建议过，所以方案要具体到能直接实现。

边界：
- 只改 `src/`、`tests/`。本票允许改的受保护文件：`pyproject.toml` 里 import-linter 的合约段（只加不改）；新增一个数据库迁移（0013）。
- 改动留在工作区，不要 `git add`，也不要提交。
- 不读取 `~/桌面/data_check` 和 `~/桌面/Data_Collection_System-main`，不碰 `/mnt`。
- 不安装任何东西，不访问网络（沙箱为了跑测试开了网络权限，但这张票用不到外网；集成测试只连 127.0.0.1；评审会查运行日志，出现安装或联网的命令整轮打回）。需要新依赖时停下，在最终回复里写依赖申请。
- 自己在 `/tmp` 或别处建的试验文件，交付前删掉。
- 只在三种情况停下：要加新依赖；要改允许范围以外的受保护文件；要改已有的对外行为（已有 HTTP 接口、已有表结构）。其余拿不准的写进最终回复。
- 只有实际运行到 80 分钟左右还没做完，才停在 `make check` 全绿的位置交检查点；不要开工前预判做不完。

最终回复分四块：
1. 改动清单：每个文件一行，写做了什么。
2. `make check`：最后一次运行的命令和末尾输出，原样贴出。
3. 契约变更申请、依赖申请：没有就写"无"。
4. 拿不准、需要评审决定的地方（含上面"骨架里定"的各项方案）。
