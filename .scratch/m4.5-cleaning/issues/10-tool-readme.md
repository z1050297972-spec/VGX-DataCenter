# 工具库页面"说明"按钮：浏览工具目录里的 README

Status: done（评审、截图通过；在分支 t/m4.5-10-tool-readme，未合并 main、未升级。原：2026-11-11 负责人："给mcap2lerobot写一个readme文件，放在其目录下，工具库页面再加一个读说明的摁纽，点击浏览该readme文件"）

分级：直做。分支 `t/m4.5-10-tool-readme`，从 main 开。

## 负责人的决定

- README 放在**工具本体目录**（`<library_root>/<tool.directory>/README.md`，即 `/mnt/datasets/工具/mcap2lerobot/README.md`）。内容由执行线写；工具目录里的其他东西仍然不动。
- 前端新增依赖 `react-markdown`、`remark-gfm`（执行线已加进 package.json 和锁文件）。

## 要做的

1. **后端**：
   - 新接口 `GET /api/tools/{name}/readme`（登录可读，权限照 `get_tool`），operation_id `get_tool_readme`，返回 `{ "name", "content" }`。
   - 文件位置：登记清单里 `tool.directory` 解析出的工具目录下的 `README.md`，复用 registry 已有的目录约束（`_contained_path`），不跟随越出工具目录的软链接。
   - 只读，用 O_NOATIME（照仓库已有的只读打开写法，EPERM 时退回普通只读）。上限 1 MiB；必须是 UTF-8。
   - 没有文件返回 404，诊断说明"该工具目录里没有 README.md"；超过上限或不是 UTF-8 时按输入问题报告。
   - 工具摘要（列表和详情）加 `readme_available: bool`。清单无效时为 false。
2. **前端**：
   - 工具库页面每个工具加一个"说明"按钮；`readme_available` 为 false 时按钮禁用，并提示"工具目录里没有 README.md"。
   - 点击后打开 antd Drawer（宽度照现有抽屉，手机宽度全屏），标题"<工具名> 说明"。
   - 用 `react-markdown` + `remark-gfm` 渲染。不渲染原始 HTML（默认的 skipHtml 行为即可，不要加 rehype-raw）。链接新窗口打开，并带 `rel="noreferrer"`。
   - 标题、表格、代码块的样式跟随 antd 主题，深色模式可读。表格和代码块可以横向滚动，不撑破抽屉。
3. 跑 `make api-types` 由执行线做；Codex 先按上面的契约手写类型或等执行线生成（照第 04 张的做法，交付前执行线换成生成类型）。

## 测试范围（只做关键测试）

1. 后端：有 README 返回内容；没有返回 404；README 是指向工具目录外的软链接时拒绝；超过上限时拒绝；摘要的 `readme_available` 正确。
2. 前端：按钮可用和禁用两种状态；点击后渲染出 Markdown 标题和表格；`<script>` 之类的原始 HTML 不被渲染。

## 验收

1. `make check` 全绿、0 skipped。
2. 执行线在真实 README 上截图抽屉（1440 宽、390 宽）。
- 2026-11-11 执行线写 README：`/mnt/datasets/工具/mcap2lerobot/README.md`（负责人选"放工具本体目录"；对照工具源码 main.rs/convert.rs/verify.rs/config.rs/h264.rs 和 configs/r1lite.toml；工具目录其他文件未动，未在工具目录跑 git）。
- 派工 Codex（rdp-m45-10）：`registry.read_tool_readme`（工具目录约束、不跟随越界软链接、O_NOATIME、1 MiB、UTF-8）、`GET /api/tools/{name}/readme`、摘要 `readme_available`；前端"说明"按钮 + Drawer + react-markdown/remark-gfm（不渲染原始 HTML）。执行线 `make api-types` 后 resume 一轮换成生成类型、删临时契约文件。
- 检查：`make check` 全绿，后端 2971、前端 434，0 skipped。演练状态目录起网页读真实 README（4301 字符），1440/390 宽截图无横向溢出（`assets/10-tool-readme/`）。
