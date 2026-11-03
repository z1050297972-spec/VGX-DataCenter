评审结果：深色效果到位，截图逐页看过，表头、按钮、禁用按钮、分页、Alert、日志框、玻璃都清楚。只有一个阻塞问题。

**阻塞：浅色外观变了。**和合并前逐像素对比，浅色下的下拉框（Select）边框和下拉箭头明显变淡。对比图：/home/shawn/.cache/rdp-ui-preview/shots/cmp-filter.png，上面是改前，下面是改后，可以用图片查看能力打开。数据集页、作业列表页也有同类差异，大概率是所有用到 antd 边框色、次要文字色这类派生 token 的地方都变了。

推测原因：加了 `ConfigProvider theme` 后，antd 为这棵树生成了新的 CSS 变量作用域，类名或 key 不再是 `css-var-root`。`shell.css` 里 `.css-var-root.css-var-root { --ant-* }` 那些浅色覆盖匹配不上，antd 就回到了自己的默认值，比如边框 `#d9d9d9`，而不是 `--rdp-border` 的 `#d2d2d7`。请先核实原因，再修。可选的修法：
- 让 ConfigProvider 的 cssVar key 继续是 `css-var-root`（antd 6 的 `theme.cssVar`），原有覆盖继续生效，深色时由算法计算，同时不能被浅色覆盖盖住；
- 或者把浅色覆盖迁成 ConfigProvider 的 token（`colorBorder`、`colorTextSecondary` 等），取值和 `--rdp-*` 一致。

要求：浅色下和合并前视觉一致。执行线会逐像素对比数据集页、作业页和表单页。深色效果保持现在这样。

另外顺手处理：`mountWeb.tsx` 里写死了十六进制色值（`#0068d1`、`#1c1c1e` 等），而 10.7 要求颜色只来自变量。如果 antd token 不能直接用 CSS 变量，就把这组值集中成一个带注释的常量对象，注释写明"与 shell.css 的 --rdp-* 保持一致，改一处要同步改另一处"。

做完跑 `make check`，要全绿。最终回复第一行写状态，写清楚核实到的原因和修法，最后贴出 `make check` 的命令和末尾输出原文。
