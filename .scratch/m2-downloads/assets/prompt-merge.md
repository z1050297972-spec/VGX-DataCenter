你在工作目录 /home/shawn/桌面/robot-data-platform.wt/m2-downloads（分支 t/m2-downloads）里。执行线刚运行了 `git merge --no-ff --no-commit main`，有 13 个文件冲突（`git diff --name-only --diff-filter=U`）。你的任务是解决冲突并统一迁移编号，**不要提交、不要 git add**（执行线来提交）。

1. **解决冲突**：两边的改动都要保留。M2 分支加了下载、预览、调参、暂存、token、入库、网络与资源监控相关的接口和作业类型；main 加了 M0 第 13 张遗留整理（含 `0013_login_wait_attempts` 迁移、登录等待相关改动）和其他 M1.5 改动。逐个冲突块读懂两边的意图后合并，不丢任何一边的功能。生成的 `src/web/src/api/openapi.json`、`schema.d.ts` 如果冲突或过期，用 `make api-types` 重新生成，不要手合。
2. **迁移改号**（和 M1 线约定好的，main 的 0013 已经占用）：
   - `src/rdp/infra/db/migrations/versions/v0013_download_adjustments.py` 改名为 `v0014_download_adjustments.py`，`revision = "0014_download_adjustments"`，`down_revision = "0013_login_wait_attempts"`。
   - `v0015_download_staging.py`：`down_revision` 改为 `"0014_download_adjustments"`。
   - `v0016_monitoring.py` 不变（head 仍是 `0016_monitoring`）。
   - 全仓搜索 `0013_download_adjustments`，测试和代码里的引用一起改；各测试里"当前 head""迁移链"之类的期望值按新链 `… → 0012_scene_task_index → 0013_login_wait_attempts → 0014_download_adjustments → 0015_download_staging → 0016_monitoring` 更新。
3. 跑 `make check` 一次（只跑一份）直到全绿。如果有和本次合并无关的页面测试偶发超时（例如 JsonViewer、FileViewer、Repoint），单独重跑确认能过即可，在回复里说明。

边界：只改冲突文件、迁移文件和因改号必须改的测试/代码；不碰 `/mnt` 和两个旧项目；不安装、不访问网络。最终回复第一行写 `状态：全部完成` 或 `状态：未完成`，后面列出每个冲突文件怎么合的（一行一个），以及 `make check` 末尾输出原样。
