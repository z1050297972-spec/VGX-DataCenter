你在工单「作业日志框的内联 style 挪进 CSS 类」的工作目录 /home/shawn/桌面/robot-data-platform.wt/ui-style（git worktree，分支 t/ui-07-log）里工作。

先读：
- /home/shawn/桌面/robot-data-platform/AGENTS.md
- /home/shawn/桌面/robot-data-platform/docs/standards/CODING_STANDARDS.md 第 10 节，尤其 10.9
- 工单 /home/shawn/桌面/robot-data-platform/.scratch/ui-style/issues/07-job-log-inline-style.md：本次唯一的需求来源

分级是直做，一次交付。本票允许改的测试只有 `jobs/Pages.test.tsx` 里"评审3：作业日志长行在有界日志框内换行"这一条，其他测试不动。按工单"验收"第 3 条做一次变异抽查，验证完撤回。

边界：
- 只改 `src/web/src/jobs/Pages.tsx`、`src/web/src/jobs/jobs.css`、`src/web/src/jobs/Pages.test.tsx`。
- 改动留在工作区，不要 `git add`，也不要提交。
- 不安装任何东西，不访问网络，不碰 `/mnt`。

最终回复第一行写"状态：全部完成"或"状态：未完成（原因）"，然后写：
1. 改动清单；
2. 改写后的测试原文；
3. 变异抽查的命令和失败输出原文；
4. `make check` 的最后一次命令和末尾输出原文。
