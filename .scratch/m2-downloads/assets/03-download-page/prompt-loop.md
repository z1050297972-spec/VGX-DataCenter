继续做这张工单剩下的部分（范围、边界、关键测试清单见 /home/shawn/桌面/robot-data-platform/.scratch/m2-downloads/assets/03-download-page/prompt-A.md 和 prompt-A2.md）。先看 `git status` 了解已经做了什么，然后接着做下一批没做的项。

最终回复的**第一行**必须是下面两种之一：
- `状态：全部完成`：工单里所有项都做完了，`make check` 全绿，后面接五块格式的最终回复。
- `状态：未完成`：还有没做的项，后面列出这一轮做了什么、还剩什么。执行线会自动让你继续。

这一轮结束前跑一次 `make check`（只跑一份），保证工作区处于全绿状态。

**迁移编号更正（2026-11-01）**：main 上即将出现 `0013_login_wait_attempts`。本票如果需要新增迁移，编号用 **0015**，`down_revision` 先接 `0013_download_adjustments`（合并时执行线会统一改号）。不要用 0014。如果你已经建了 0014 的迁移，改名成 0015。
