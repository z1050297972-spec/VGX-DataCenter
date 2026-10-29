你在 M1 第 01 张工单「导航层读取、数据集索引与重新扫描」的工作目录 /home/shawn/桌面/robot-data-platform.wt/m1-01-nav-read-index-rescan（git worktree，分支 t/m1-01-nav-read-index-rescan）里写契约骨架。M0 已经全部合并，这个分支从 main 开出，多了一个提交 `依赖：pytest-xdist`。

先读下面这些。规划文件一律读主仓库目录 /home/shawn/桌面/robot-data-platform 里的版本：
- AGENTS.md、docs/standards/CODING_STANDARDS.md
- docs/agents/codex-workflow.md：第 3.0 节（提速规则），以及第 7.1 节「历次评审打回过的写法」，那里列的写法以前都被打回过，一开始就避开
- 工单 /home/shawn/桌面/robot-data-platform/.scratch/m1-datasets/issues/01-nav-read-index-rescan.md 全文
- 它引用的：
  - `.scratch/m1-datasets/spec.md`
  - `.scratch/platform-v1/issues/11-dataset-contract.md` 的 Answer（Q2、Q3、Q6、Q8、Q9、Q11、Q14）
  - `.scratch/platform-v1/issues/12-link-rules.md` 的 Answer（重点 L7、L12）
  - `docs/adr/` 里的 0005、0006、0008
  - `docs/manual/导航层手册.md`、`GLOSSARY.md`
- 现有代码里要复用的：
  - 作业框架（`src/rdp/jobs/`），包括写锁、作业类型登记、定时调度的写法；
  - 存储根（M0 第 10 张）；
  - 假导航层（`tests/` 里的 fake nav）；
  - 迁移（`src/rdp/infra/db/` 和 alembic 目录）；
  - 诊断和报错（五段诊断）。
- 只读参照：执行线采集的真实导航层基线，在 `/home/shawn/桌面/robot-data-platform/.scratch/m1-datasets/assets/01-nav-read-index-rescan/baseline-*.txt`

用 $enterprise-coding。这一步只交契约骨架：
1. 签名、类型和六项 docstring 写全（AGENTS.md 规则 4、CODING_STANDARDS 第 3 条），函数体只写 `raise NotImplementedError`。
2. 新表的迁移照 M0 第 8、9 张的做法，骨架阶段放进 `pending/`，派工 B 再激活。
3. 测试清单写成跳过的测试（`pytest.skip`），每个测试的 docstring 写明它验证哪条契约行为。清单覆盖工单验收第 2–8 条。第 1 条（真实导航层扫描）由执行线在沙箱外做，你不用写。
4. `make check` 全绿。pytest 那一步先照工单改成 `-n auto`（Makefile 只改这一处）；如果骨架阶段在多进程下暴露出现有测试的共享状态问题，在第 4 块列出，不要用 `-p no:xdist` 绕开。

骨架关卡要看的三样东西，在最终回复第 4 块里单独列出：
- 数据集索引的表结构：表、列、约束、索引；第 02 张要填的列也要包括。
- 指纹函数的签名和返回类型（L12）。
- 两张登记表放在代码常量里还是配置里，以及理由。

**执行线给的设计方向**（可以改，改了在第 4 块写理由）
- 模块建议放在 `src/rdp/datasets/`（名字你定，要符合 import-linter 的分层规则），读取契约、登记表、指纹、扫描作业、面板检查各自成模块。
- 读取导航层只用标准库：`os.scandir`、`os.readlink`、`json`、`hashlib`。不跟随软链接去读存储根，那是第 02 张的事。不对 `nav_root` 做任何写操作。
- 指纹返回一个不可变的值对象，可以比较是否相等，可以序列化存进索引。
- 重新扫描作业登记成新的作业类型，写锁、恢复、取消照 ADR 0005 和现有作业框架。第二段只留接口，函数体是空实现，返回"未执行"一类的明确结果。
- 面板发现复用现有的五段诊断结构，分"需要处理"和"提示"两级。
- 索引一次重建的语义：一个事务里替换，失败就保留旧索引。

边界：
- 只改 `src/`、`tests/`，以及 `Makefile` 里 pytest 那一行。
- 改动留在工作区，不 `git add`、不提交。
- 不读 `~/桌面/data_check` 和 `~/桌面/Data_Collection_System-main`。
- **不读也不写 `/mnt`**。真实导航层的事实看执行线给的基线文件。
- 不安装任何东西，不联网，不新增依赖：需要新依赖就停下，写进最终回复的依赖申请。
- 不碰 `~/.config/rdp`、`~/.local/share/rdp`、`~/.local/opt/rdp`，那是正在运行的真实部署。不起占用 8600 端口的服务。
- 自己建的试验文件，交付前删掉。

只有三种情况停下：要加新依赖；要改允许范围以外的受保护文件；要改 M0 已获批契约的含义（只加参数或字段的，可以先做，再在第 3 块申请）。

60 分钟内交付。最终回复分四块：
1. 改动清单：每个文件一行，写做了什么。
2. `make check`：最后一次运行的命令和末尾输出，原样贴出。
3. 契约变更申请、依赖申请：没有就写"无"。
4. 骨架关卡要看的三样东西，以及拿不准的地方。
