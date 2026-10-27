上一轮在最终 `make check` 全绿后到了 90 分钟时限，最终回复没写出来。执行线已复跑 `make check` 全绿（pytest 1667 passed / 0 skipped，Vitest 205 / 23 skipped），日志审计干净，快照 `refs/rdp/m0-09/B4-timeout`。

本轮只做前端，按 prompt-B 的要求和边界（必要时用绝对路径重读 /home/shawn/桌面/robot-data-platform/.scratch/m0-foundation/assets/09-job-scheduling-resources/prompt-B.md 和 /home/shawn/桌面/robot-data-platform/docs/agents/codex-workflow.md 第 7.1 节），每条先单独运行看到红再实现：
- `src/web/src/api/scheduling.test.ts`、`src/web/src/jobs/Resources.test.tsx`、`src/web/src/scheduling/Pages.test.tsx` 共 23 条；
- 调度页挂进菜单和路由；页面 search 参数经真实 router 测；类型用生成的 OpenAPI 类型，有变化用 `make api-types`，不手改生成文件；
- 已完成的后端不要再改，除非前端测试暴露了真实缺陷（写进第 4 块）。

交付前在本票改过的全部文件里搜"骨架""提案""派工""桩""实现阶段""留待""负责人决定""评审""09/"，不留。最后跑一次 `make check`，pytest 和 Vitest 都不留 skipped。

为了不再超时：前端预计 60 分钟内完成；到 70 分钟还没做完，停在 `make check` 全绿处，先写最终回复。

最终回复五块同前，但第 3、4、5 块要覆盖上一轮（prompt-B4/B4b，回复丢失）和本轮：契约变更/docstring 措辞调整、拿不准的地方（包括上一轮提到的"系统提交人的两处问题"是怎么修的）、每条测试第一次运行的结果（上一轮的可以按文件汇总，直接通过的逐条说明原因）。
