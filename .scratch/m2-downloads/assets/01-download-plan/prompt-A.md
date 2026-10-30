你在工单「下载计划」的工作目录 /home/shawn/桌面/robot-data-platform.wt/m2-downloads（git worktree，分支 t/m2-downloads）里写契约骨架。

先读下面这些。规划文件一律读主仓库目录 /home/shawn/桌面/robot-data-platform 里的版本：工作目录里的副本停在开分支的那一刻，可能已经过期，也可能缺少还没提交的文件。
- /home/shawn/桌面/robot-data-platform/AGENTS.md
- /home/shawn/桌面/robot-data-platform/docs/standards/CODING_STANDARDS.md
- /home/shawn/桌面/robot-data-platform/docs/agents/codex-workflow.md 第 7.1 节「历次评审打回过的写法」：这些写法以前被打回过，一开始就避免
- 工单 /home/shawn/桌面/robot-data-platform/.scratch/m2-downloads/issues/01-download-plan.md
- M2 spec /home/shawn/桌面/robot-data-platform/.scratch/m2-downloads/spec.md（尤其「负责人决定」）
- 调研 /home/shawn/桌面/robot-data-platform/docs/research/hf-mirror下载机制.md（§1.2–1.3、§4、§5.2 第 1–3 步、§5.3、§5.4、末尾「负责人决定」）
- ADR：/home/shawn/桌面/robot-data-platform/docs/adr/ 下的 0004、0005、0006、0008
- /home/shawn/桌面/robot-data-platform/GLOSSARY.md 里的术语
- 现有代码里可以复用的：`src/rdp/infra/config.py`（StorageRootConfig、PlatformConfig、state_dir）、`src/rdp/infra/diagnostics.py`（诊断与错误分类）、`src/rdp/infra/timeutil.py`、存储根在线与剩余空间相关的现有函数（用 grep 找，不要重复实现）

用 $enterprise-coding。这一步只交契约骨架：
1. 签名、类型和六项 docstring 写全（AGENTS.md 规则 4，CODING_STANDARDS 第 3 条）。函数体只写 `raise NotImplementedError`。
2. HTTP 传输做成可注入的接口，测试里用替身，测试不访问网络。
3. 测试清单写成跳过的测试（`pytest.skip`），每个测试的 docstring 写明它验证哪条契约行为。工单「验收」里的每一条都要有对应测试。
4. 如果新包需要登记 import-linter 的依赖方向（看 pyproject.toml 里现有合约的写法），按现有约定补上；这算本票允许改的 `pyproject.toml` 配置段，只加不改已有合约。
5. `make check` 跑到全绿。

工单「待负责人确认」里的两条不用你决定；骨架里涉及的地方按工单的建议写，并在最终回复第 4 块指出位置。

边界：
- 只改 `src/`、`tests/`。本票允许改的受保护文件：`pyproject.toml` 里 import-linter 的合约段（只加新包的合约，不改已有的）。
- 改动留在工作区，不要 `git add`，也不要提交。
- 不读取 `~/桌面/data_check` 和 `~/桌面/Data_Collection_System-main`，不碰 `/mnt`。
- 不安装任何东西，不访问网络（沙箱为了跑测试开了网络权限，但这张票用不到网络；评审会查运行日志，出现安装或联网的命令整轮打回）。需要新依赖时停下，在最终回复里写依赖申请（AGENTS.md 规则 7）。
- 自己在 `/tmp` 或别处建的试验文件，交付前删掉。
- 只在三种情况停下：要加新依赖；要改允许范围以外的受保护文件；要改已有的对外行为（HTTP 接口、数据库表结构）。其余拿不准的写进最终回复。
- 预计 80 分钟做不完，就停在 `make check` 全绿的位置交检查点，并在最终回复里写明还差什么。

最终回复分四块：
1. 改动清单：每个文件一行，写做了什么。
2. `make check`：最后一次运行的命令和末尾输出，原样贴出。
3. 契约变更申请、依赖申请：没有就写"无"。
4. 拿不准、需要评审决定的地方。
