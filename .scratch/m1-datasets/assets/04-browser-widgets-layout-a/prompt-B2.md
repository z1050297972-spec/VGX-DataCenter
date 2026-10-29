前半段在真实浏览器演练里查出一项阻塞（打回第 1 轮）：**正式构建的前端打开后一片空白**。

执行线用 `vite build` 构建后起 Web，无头 Chrome 打开 `/login`，页面上什么都没有，控制台报：
```
Uncaught TypeError: Cannot destructure property 'ESC' of 'h' as it is undefined.
  source: /assets/ui-Btq1zqpx.js
```
原因：你在 `vite.config.ts` 里加的 rolldown `codeSplitting`，`ui` 分组带了 `maxSize: 700_000`，把 antd、`@rc-component`、`rc-*` 切成了好几个块，块之间出现循环依赖，初始化顺序错了，`rc-util` 的 `KeyCode` 还没定义就被解构。Vitest 不经过打包，所以测不出来。

**修法**
- 不要按大小把 antd 这一族切开。可以用一个 `ui` 分组、不设 `maxSize`，或者干脆去掉手工分组，只靠路由动态导入拆包。选哪种由你定。
- 工单验收 6 要求的是**主入口**低于 500 kB，不要求 vendor 块也低于 500 kB。如果整块 antd 超过 500 kB 会出警告，可以在 `build.chunkSizeWarningLimit` 上只针对这一点调整，并写理由；更好的办法是让 antd 只出现在按需加载的路由块里。
- 必须证明正式构建能在浏览器里加载。你的沙箱里如果能运行 `google-chrome --headless=new --dump-dom http://127.0.0.1:<临时端口>/login`（起 `vite preview`，或者用 `python -m http.server` 托管 dist，只绑 127.0.0.1），就跑一次，贴出 DOM 里登录表单的片段，以及控制台有没有 Uncaught；跑不了就在第 4 块说明，由执行线来验。
- 把构建输出（各块大小）放进最终回复。

然后补齐**后半段**剩下的 8 项跳过，在 `checkpoint.test.ts` 里：离线提示、过期重扫、型号映射、其余筛选与分页、14 项 Markdown、链接与数据块、统计大小、异常与生命周期。先红后绿。

最后 `make check` 全绿、0 skipped，连跑 3 次贴出汇总行。边界不变：只改 `src/`、`tests/`；不 `git add`、不提交；不读不写 `/mnt`；不联网、不安装；不碰真实部署，不占用 8600 端口。60 分钟内交付。最终回复五块，格式同上。
