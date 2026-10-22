已完成 A/B/C 三个原型，改动留在 `prototype/dataset-browser` 工作区。可在 `src/web/` 运行 `pnpm dev`，访问 `/?variant=A`、`/?variant=B`、`/?variant=C`。

改动清单如下。除入口文件外，路径均相对于 `src/web/src/prototype/dataset-browser/`：

| 文件 | 说明 |
|---|---|
| `src/web/src/main.tsx` | 挂载原型，配置中文 locale 和 antd App。 |
| `DatasetBrowser.prototype.tsx` | 索引加载、共享状态和变体选择。 |
| `data.prototype.ts` | 四种 JSON 类型、内存缓存、筛选、导航和状态计算。 |
| `VariantA.prototype.tsx` | 树导航、列表与完整详情页，顶栏切换一致性面板。 |
| `VariantB.prototype.tsx` | 树形大表、约 60% 宽的详情抽屉、表格上方折叠一致性面板。 |
| `VariantC.prototype.tsx` | 路径栏、目录分栏、文件预览和右侧一致性面板。 |
| `PrototypeSwitcher.prototype.tsx` | 开发模式浮动切换条、URL 参数和键盘切换。 |
| `DemoToggles.prototype.tsx` | 两个演示开关及当前状态展示。 |
| `widgets/Common.prototype.tsx` | 筛选栏、大小、路径复制、目录标签和问题徽标。 |
| `widgets/Details.prototype.tsx` | 大小、链接、14 项、数据块、其他字段、子任务及跨视图跳转。 |
| `widgets/Consistency.prototype.tsx` | 四组两级诊断、样例跳转和离线状态。 |
| `widgets/JsonViewer.prototype.tsx` | 按需展开的 JSON 查看器，大数组按 100 项分段。 |
| `json.prototype.worker.ts` | 点击加载后，在工作线程读取和解析子任务。 |
| `prototype-jsx.d.ts` | 补充无 React 类型包环境下的 JSX `key` 声明。 |
| `prototype.css` | 三种布局、共用内容及浮动控件样式。 |

三个变体均接入全部共用内容：A 连续展示详情；B 按概览、14 项、数据块、子任务、其他字段分页签；C 按选中的 JSON 文件展示对应内容。筛选和演示开关在切换变体时保留。

`pnpm build` **通过，退出码 0**，TypeScript 与 Vite 均成功。末尾输出：

```text
vite v8.3.5 building client environment for production...
transforming...
✓ 1499 modules transformed.
rendering chunks...
computing gzip size...
dist/assets/json.prototype.worker-BCPiVhRG.js      0.26 kB
dist/index.html                                    0.41 kB │ gzip:   0.31 kB
dist/assets/index-Ds9OG_bE.css                    11.33 kB │ gzip:   3.41 kB
dist/assets/index-BNLDNuzH.js                  1,037.93 kB │ gzip: 328.51 kB

[plugin builtin:vite-reporter]
(!) Some chunks are larger than 500 kB after minification. Consider:
- Using dynamic import() to code-split the application
- Use build.rolldownOptions.output.codeSplitting to improve chunking: https://rolldown.rs/reference/OutputOptions.codeSplitting
- Adjust chunk size limit for this warning via build.chunkSizeWarningLimit.
✓ built in 289ms
```

尚未完成浏览器实测：临时静态服务因沙箱禁止监听套接字而无法启动，未留下服务进程。构建另有上述主包体积警告；没有新增依赖，也未修改受保护配置或导出数据。