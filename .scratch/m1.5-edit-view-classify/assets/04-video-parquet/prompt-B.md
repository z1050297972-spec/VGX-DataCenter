你在 M1.5 第 04 张「查看器：AV1 视频转码播放、parquet 表格预览」的工作目录 /home/shawn/桌面/robot-data-platform.wt/m15-04-video-parquet（git worktree，分支 t/m15-04-video-parquet，从 main 开出，多一个提交"依赖：pyarrow"）里工作。

这张票是**直做**：按 TDD 先写测试、看到红，再实现，用 $tdd 和 $enterprise-coding。

先用绝对路径读这些（规划文件读主仓库 /home/shawn/桌面/robot-data-platform 里的版本）：
- 工单 .scratch/m1.5-edit-view-classify/issues/04-video-parquet-preview.md 全文：问题怎么来的、本机 ffmpeg 有什么能力、范围、验收，都在里面。
- AGENTS.md、docs/standards/CODING_STANDARDS.md、docs/agents/codex-workflow.md 第 3.0 节和第 7.1 节（7.1 列的是以前被打回过的写法）
- docs/adr/0006 末尾的修订段：Web 只读存储根的例外只给查看器。
- 已合并的查看器：src/rdp/jobs/file_viewer/（或者实际的模块名）、src/rdp/api/ 里的查看器路由、src/rdp/jobs/datasets/_readonly.py（O_NOATIME 打开）、src/web/src/datasets/FileViewer.tsx。新功能就加在这套上面，路径校验、超时和访问槽沿用。

关键要求：
- **ffmpeg 和 ffprobe 的输入必须是 O_NOATIME 打开的文件描述符，以 `fd:` 协议传入**（用 subprocess 的 pass_fds）。命令行参数里不能出现原文件路径，测试里要断言这一点。
- parquet 用 pyarrow 读，传给它的文件对象来自 O_NOATIME 描述符。
- 测试用的视频和 parquet 文件，在临时目录里用 ffmpeg（例如 `testsrc` 生成几秒 AV1 或任意编码的视频）和 pyarrow 现做，不读 /mnt。测试里调用本机的 ffmpeg 可以；如果 ffmpeg 不可用，测试要明确失败并说明原因，不能跳过。
- 前端控件统一用 antd；1280×900 下不能出现横向滚动条；时间用 time.ts 的 formatDateTime；关键控件加稳定的 aria-label。
- OpenAPI 用 `make api-types` 生成。
- 最后 `make check` 全绿、0 skipped；`cd src/web && node_modules/.bin/vite build`，主入口低于 500 kB，跑完删掉 dist。

边界：
- 只改 `src/`、`tests/`；`pyproject.toml` 只在 import-linter 确实需要时改，写明理由；不再加别的依赖。
- 不 `git add`、不提交；**不读不写 `/mnt`**；不联网、不安装。
- 不碰真实部署（`~/.config/rdp`、`~/.local/share/rdp`、`~/.local/opt/rdp`），不调用 systemctl，不占用 8600 端口；不碰别的 worktree。
- 测试用 `make check`，不要另开更多并行。

75 分钟内交付；做不完就停在全绿的位置交检查点。最终回复五块：
1. 改动清单；
2. make check 汇总行；
3. 契约变更；
4. 演练要用的请求例子和 aria-label，以及拿不准的地方；
5. 先红后绿。
