R1 的 7 条都看过，1280 和 1440 两种宽度都没问题。还剩一个问题：手机宽度（390px）下有三页横向溢出，页面被撑宽。脚本测出来的结果：

```
390 /accounts   scrollWidth 1144 > 390  超宽元素：header.app-page-header、nav.ant-breadcrumb、div.ant-flex
390 /scheduling scrollWidth 573 > 390   超宽元素：header.app-page-header、nav.ant-breadcrumb、h2.app-page-title
390 /jobs       scrollWidth 477 > 390   超宽元素：header.jobs-header、nav.ant-breadcrumb、div.ant-flex
```

页头被撑到和里面的宽表格一样宽，多半是某层容器（卡片、Flex、栅格列）缺了 `min-width: 0`，或者表格没有在自己的横向滚动容器里滚动。要求：
- 窄屏下页面本身不能横向滚动；
- 宽表格在自己卡片内部横向滚动；
- 页头的标题和操作按钮换行排列。

`/jobs` 是第 04 张的页面，也一并修。

修完后自己用浏览器开发者工具无法验证也没关系，执行线会用脚本复测。跑 `make check` 要全绿。最终回复第一行写状态，然后写清楚原因和改法，最后贴出 `make check` 的命令和末尾输出原文。
