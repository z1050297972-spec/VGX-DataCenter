评审发现下面的问题，逐条修复，别处不动（修的时候对照 /home/shawn/桌面/robot-data-platform/docs/agents/codex-workflow.md 第 7.1 节，不要引入同类问题）：
1. 问题：变异抽查里，把 `filter_files` 中包含模式"以 `/` 结尾补 `*`"那一行去掉，测试仍全部通过；位置：src/rdp/jobs/downloads/plan.py 约 802 行，tests/jobs/downloads/test_plan.py；期望：补一个测试，`include=("meta/",)` 只留下 `meta/` 下的文件（去掉补星后，`meta/` 什么也匹配不到，测试应失败）。排除模式那一行如果同样没测到，一并补。
2. 问题：变异抽查里，把容量判断 `available < remaining + reserve` 改成 `available < remaining`，测试仍全部通过；位置：plan.py 约 1147 行；期望：补一个测试，可用空间在 `remaining` 和 `remaining + SPACE_RESERVE_BYTES` 之间时计划失败，诊断里有余量；可用空间恰好等于 `remaining + SPACE_RESERVE_BYTES` 时通过。
3. 契约变更申请已批准（只是补充说明，不改含义）：在 `UrllibTransport.request` 的 `Side Effects:` 里补上"启动并回收单次请求隔离子进程；超过总时长时终止子进程"。

修完后 `make check` 全绿。

边界：
- 只改 `src/`、`tests/`。本票允许改的受保护文件：无。
- 改动留在工作区，不要 `git add`，也不要提交。
- 不读取 `~/桌面/data_check` 和 `~/桌面/Data_Collection_System-main`，不碰 `/mnt`。
- 不安装任何东西，不访问网络。
- 自己在 `/tmp` 或别处建的试验文件，交付前删掉。

最终回复：逐条写处理结果；`make check` 最后一次运行的命令和末尾输出，原样贴出。
