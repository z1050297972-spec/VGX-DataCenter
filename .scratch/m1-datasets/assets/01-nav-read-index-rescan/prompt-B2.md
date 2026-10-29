B1 已通过评审：变异抽查 5 处全部被测试发现。执行线也在沙箱外对真实导航层做了只读扫描（`/home/shawn/桌面/robot-data-platform/.scratch/m1-datasets/assets/01-nav-read-index-rescan/realscan-run.log`），结果如下：
- 35 个数据集；按任务、按格式入口各 35 个；84 条链接；3697 个数据块；210 份 JSON。
- 第一段持锁 0.497 秒，第二段 not_run。
- 目前只报出 1 条发现：TOP_LEVEL_UNREGISTERED（`VGX_video/`），这条符合预期。
- 扫描前后 `/mnt/datasets` 的文件清单逐字节相同。

真实扫描的全部发现在 `realscan-findings.txt`，数据集清单在 `realscan-datasets.txt`。

现在做 **B2**。用 $tdd 和 $enterprise-coding，逐个去掉剩下 28 项的跳过：先单独运行，看到红，再实现。B1 有 35 项第一次运行就是绿的；这次请尽量让每一项先红，做不到的逐项说明原因。

**B2 范围**
1. 一致性面板第 ①② 组的全部检查（工单「一致性面板第 ①② 组」和验收第 7 条）。
   - 每条检查至少一个测试：在展开后的假导航层上改一处，断言报出的诊断（对象、规则、级别）。
   - 同类发现要合并，并列出样例。
   - `已移除/` 不能被报成"顶层有没登记的目录"。
2. 三种触发（验收第 3 条）：
   - worker 启动时提交一次；
   - 每 600 秒定时提交一次全量扫描，时钟要可控；
   - 手动提交 B1 已经做了。
   - 定时触发的提交人是"系统"。接入 `JobService.submit_system` 和 `ExecutorDependencies.poll_submissions`。
   - 生产装配要接通：worker 起来以后，真的会提交启动扫描和定时扫描。
3. 用导航层手册第 8 节对照真实数据：读 `/home/shawn/桌面/robot-data-platform/docs/manual/导航层手册.md` 第 8 节，以及 `.scratch/platform-v1/issues/01-nav-json-inventory.md` 的已知不一致，例如 alpha 那 3 个早已不存在的数据块。
   - 你的 ①② 组检查跑在真实数据上，**预计**会报出哪些发现，写进最终回复第 4 块。
   - 执行线会再跑一次真实扫描，逐条核对你的预计。
   - 你不能读 `/mnt`。手册、盘点票和执行线给的基线文件（`assets/01-nav-read-index-rescan/baseline-*.txt`）就是你的依据。

**交付要求**
- 最后 `make check` 全绿，0 skipped；连跑 3 次，贴出三次 pytest 的汇总行。
- 不留骨架期的说法。
- 边界同前：
  - 只改 `src/`、`tests/`；
  - 不 `git add`、不提交；
  - 不读不写 `/mnt`；
  - 不联网、不安装；
  - 不碰真实部署，不占用 8600 端口。

75 分钟内交付；到时间还没做完，就停在全绿的位置交检查点。最终回复五块：
1. 改动清单；
2. 三次 pytest 汇总行，以及最后一次的末尾输出；
3. 契约变更申请、依赖申请；
4. 真实数据上预计会报出的发现清单，以及拿不准的地方；
5. 先红后绿，每个测试一行。
