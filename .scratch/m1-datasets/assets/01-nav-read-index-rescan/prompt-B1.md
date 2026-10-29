骨架已获批（执行线按负责人授权过关卡），契约提交是 `2cc5082`，内容就是你交的骨架。你第 3 块的两处只加不改的扩展（`ExecutorDependencies.poll_submissions`、`JobService.submit_system`）都已批准，第 4 块的设计选择全部采纳（见工单最后两条 Comment）。工作目录干净。

动手前用绝对路径重读工单 /home/shawn/桌面/robot-data-platform/.scratch/m1-datasets/issues/01-nav-read-index-rescan.md（含 Comments），以及 docs/agents/codex-workflow.md 第 7.1 节。

本票的派工 B 分两段交，这是 **B1**。用 $tdd 和 $enterprise-coding，逐个去掉跳过：先单独运行，看到红，再实现到绿。

**B1 范围**
1. 读取契约（`reading.py`）及其测试：缺 `schema_version`、省略 `version`、不认识的字段、JSON 解析失败、缺依赖字段、10-12 记录值。
2. 两张登记表（`catalog.py`）。
3. 指纹（`fingerprint.py`）及其测试：没改动时稳定；改 JSON、增删条目、改链接指向时都会变。
4. 激活迁移 0007：照 M0 第 8、9 张的做法，从 `pending/` 移到活动目录、删掉 `pending/`，同步更新迁移测试。
5. 索引的原子替换（`index.py`）。
6. 重新扫描作业的第一段：持写锁、只读导航层、同时算指纹。第二段的空实现照契约返回 `NOT_RUN`。提交时按数据集重新算一次指纹，对不上的跳过并记提示。手动触发（全量、单个数据集）要能跑通。
   - 对应验收第 2、4、5、6 条的测试。

**B1 先不做，留给 B2**：面板第 ①② 组的检查、定时触发和 worker 启动时触发。这几项的测试保留跳过。

**还有一项必须修：多进程下有不稳定的失败**
执行线提交契约时，第一次钩子失败：
```
FAILED tests/test_ops_setup_script.py::test_yes_skips_confirmations - TimeoutError: 部署测试超过十秒
FAILED tests/test_ops_setup_script.py::test_foreground_interrupt_preserves_unrelated_process
FAILED tests/test_ops_setup_script.py::test_questionnaire_platform_validation
```
重试一次就通过了。原因是 32 个 worker 同时跑，CPU 争用，`tests/setup_support.py` 里写死的 10 秒子进程预算不够用。
- 修法由你定，要求：
  - 不关掉 xdist；
  - 不靠加大并发掩盖问题；
  - 不把断言放宽到失去意义。
  - 例如：把预算改成具名常量，并说明为什么取这个值；或者把这批真实子进程测试分到同一个 xdist 组（`--dist loadgroup`）；或者限制 worker 数。
- 验收第 8 条要求 `make check` 连跑 3 次结果一致。你最后要实际连跑 3 次，把三次 pytest 的汇总行都贴出来。

**交付要求**
- 最后 `make check` 全绿，B2 的测试保留跳过。
- 不留骨架期的说法（"骨架""桩""待实现"等）。
- 边界同派工 A：
  - 只改 `src/`、`tests/`，`Makefile` 只改 pytest 那一行；
  - 不 `git add`、不提交；
  - **不读不写 `/mnt`**；
  - 不联网、不安装；
  - 不碰真实部署（`~/.config/rdp`、`~/.local/share/rdp`、`~/.local/opt/rdp`），不起占用 8600 端口的服务。
- 真实导航层扫描由执行线在 B1 交回后，在沙箱外做。

60 分钟内交付。最终回复五块：
1. 改动清单；
2. `make check` 三次的 pytest 汇总行和最后一次的末尾输出，加跑前、跑后的 `git status --porcelain --untracked-files=all`；
3. 契约变更申请、依赖申请；
4. 拿不准的地方，以及 B2 还剩哪些；
5. 先红后绿，每个测试一行。
