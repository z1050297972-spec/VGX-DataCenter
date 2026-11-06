评审发现下面的问题，逐条修复，别处不动（修的时候对照 /home/shawn/桌面/robot-data-platform/docs/agents/codex-workflow.md 第 7.1 节，不要引入同类问题）：

1. 问题：顶栏字标 `VGX / DATA` 看不见。它被顶栏的玻璃层 `.app-shell > .accounts-menu-row::before`（backdrop-filter 半透明底）盖住了：浏览器截图里只剩一块模糊的影子；注入 `.accounts-menu-row::before{display:none}` 后字标清晰出现。位置：src/web/src/shell.css 约 247 行（::before）和 363–376 行（::after）。期望：字标画在玻璃层之上，浅色、深色都清晰可读；玻璃层仍在所有顶栏内容之下；不影响登出按钮、用户名和底部停靠菜单（停靠菜单 position: fixed，在这个顶栏里面）。
2. 问题：1440 宽度下 11 个页面出现横向滚动，文档宽 1433px，可视宽 1425px。原因是 shell.css 约 250 行顶栏通栏用了 `100vw`，而 100vw 包含竖向滚动条的宽度。期望：顶栏底线仍然通栏，但页面在任何有竖向滚动条的宽度下都不产生横向溢出（document.documentElement.scrollWidth <= clientWidth）。不要用会让 sticky 顶栏失效的办法（例如给祖先加 overflow: hidden/auto）；`overflow-x: clip` 不产生滚动容器，可以考虑，或者换一种不依赖 100vw 的写法。

修完后在 src/web 下 pnpm build，再在仓库根目录 PYTHONPATH=$PWD/src make check 全绿。

边界：
- 只改 `src/`。本票允许改的受保护文件：无。除 mountWeb.tsx 外不改任何 .ts/.tsx，不改测试文件。
- 改动留在工作区，不要 `git add`，也不要提交。
- 不读取 `~/桌面/data_check` 和 `~/桌面/Data_Collection_System-main`，不碰 `/mnt`。
- 不安装任何东西，不访问网络。
- 自己在 `/tmp` 或别处建的试验文件，交付前删掉。

最终回复：逐条写处理结果；`make check` 最后一次运行的命令和末尾输出，原样贴出。
