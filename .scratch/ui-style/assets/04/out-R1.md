状态：未完成（概要字段的灰色标签样式和标题栏操作位置未按评审要求完成）

1. **作业详情页头**：面包屑与标题间距改为 4px；状态使用默认 `Tag`，紧跟标题同一行。
2. **概要卡**：提交人、GPU、阶段使用 `Row`/`Col` 横排；进度条占整行，条目统计与已用时间位于下方同一行。**未完成两点**：
   - 现有测试按完整文本查找提交人、GPU 和阶段，拆分标签后测试失败；因此保留完整文本节点，未将字段名单独设为灰色。
   - “重新提交”仍在卡片底部。现有操作组件也渲染请求失败诊断，直接整体移入 `extra` 会把错误内容挤进标题栏；尚未在不改变交互逻辑的约束下拆开。
3. **日志卡**：标题改为卡片标题；日志框使用浅灰底、圆角、等宽小字号和 480px 最大高度，超出后内部滚动。按批准保留静态内联样式及单条豁免。
4. **诊断卡**：作业页内普通诊断卡片改为浅灰底、无边框、小圆角；保留告警卡片的醒目程度。分组标题加粗，组间距为 16px。样式限定在作业诊断容器内，不影响其他页面；诊断保持默认可见。
5. **作业列表**：增加面包屑，两个提交链接移至标题行右侧；筛选器与按钮间隔 8px，筛选行和表格放入同一张卡片。
6. **新增数据集**：标题下增加 16px 间距，未改变后续卡片间距。
7. **下载详情**：沿用作业详情的页头、概要和卡片间距；下载详情作为独立分节卡。未截图，留待执行线视觉验收。

未改测试、安装依赖、联网、暂存或提交。完整检查重跑后通过；此前一次运行中的后端进程测试曾因读取空 JSON 失败。

最后一次命令：

```bash
make check > /tmp/rdp-ui04-r1-last.log 2>&1
```

末尾输出原文：

```text
================= 2757 passed, 8 warnings in 103.76s (0:01:43) =================
[7/12] OpenAPI 过期检查
✨ openapi-typescript 7.13.0
🚀 /tmp/tmp.U0Syg36XXh/openapi.json → /tmp/tmp.U0Syg36XXh/schema.d.ts [145.5ms]
OpenAPI 与生成类型均未过期
[8/12] tsc
src/web/node_modules/.bin/tsc --project src/web/tsconfig.json --noEmit
[9/12] ESLint
cd src/web && node_modules/.bin/eslint . --max-warnings 0
[10/12] Prettier
cd src/web && node_modules/.bin/prettier --check .
Checking formatting...
All matched files use Prettier code style!
[11/12] stylelint
cd src/web && node_modules/.bin/stylelint "src/**/*.css"
[12/12] Vitest
cd src/web && node_modules/.bin/vitest run

 RUN  v5.0.5 /home/shawn/桌面/robot-data-platform.wt/ui-style/src/web


 Test Files  41 passed (41)
      Tests  380 passed (380)
   Start at  19:58:42
   Duration  11.70s (tests 61%, import 19%, environment 17%, setup 2%, transform 1%)
```