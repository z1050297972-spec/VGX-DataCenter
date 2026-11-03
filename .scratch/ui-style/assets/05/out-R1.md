状态：全部完成

1. **审计筛选溢出**：操作日志和登录日志的筛选栅格调整为 `lg` 及以上每行 4 项、`md` 每行 2 项、窄屏每行 1 项；同时限制页面网格、卡片、列和输入控件宽度，避免宽表格撑开筛选卡。
2. **页头统一**：在 `shell.css` 增加共用页头和标题类，本票页面使用同一套紧凑间距；面包屑按评审指定的大类和页面名称调整。建链页也接入共用页头。
3. **卡片标题**：保留原有标题级别，将 Hugging Face token、下载暂存区和两个资源示例标题的外观统一为卡片标题样式。
4. **下载按钮**：“高级参数”独占一行；“预览”和“确认下载”使用 `Flex gap`；暂存列表刷新按钮与后续状态文字增加间距。
5. **存储根路径**：移除路径列截断，改用等宽小字号完整显示。
6. **首页**：状态卡宽度调整为约 360px，窄屏时不超过容器宽度。
7. **错误态卡片嵌套**：已将审计日志、保留期、账号、口令、下载表单、存储根、导航层恢复及示例作业表单中可直接分离的诊断移到内容卡外。以下位置暂时保留，供评审决定：
   - **下载暂存区**：刷新、快照查询和删除操作的诊断由各自子组件持有，仍可能出现在暂存区卡片内。
   - **网络与资源**：镜像检查按钮组件持有提交失败诊断，仍可能出现在镜像状态卡内。
   - **调度**：GPU 被移出名额池时，诊断条目仍在 GPU 信息卡内，以保持诊断与对应 GPU 的关联。

以上保留项若要完全拆开，需要进一步调整组件边界或信息分组；本轮未改动相关状态和查询逻辑。未修改测试、未安装依赖、未联网，也未暂存或提交。按要求未制作新截图，视觉效果留给执行线验收。

### `make check`

最后一次运行的命令：

```bash
make check > /tmp/rdp-t05-final.log 2>&1; result=$?; tail -n 35 /tmp/rdp-t05-final.log; exit "$result"
```

末尾输出原文：

```text
.venv/lib/python3.12/site-packages/fastapi/testclient.py:1
.venv/lib/python3.12/site-packages/fastapi/testclient.py:1
.venv/lib/python3.12/site-packages/fastapi/testclient.py:1
.venv/lib/python3.12/site-packages/fastapi/testclient.py:1
.venv/lib/python3.12/site-packages/fastapi/testclient.py:1
  /home/shawn/桌面/robot-data-platform.wt/ui-style/.venv/lib/python3.12/site-packages/fastapi/testclient.py:1: StarletteDeprecationWarning: Using `httpx` with `starlette.testclient` is deprecated; install `httpx2` instead.
    from starlette.testclient import TestClient as TestClient  # noqa

-- Docs: https://docs.pytest.org/en/stable/how-to/capture-warnings.html
================= 2757 passed, 8 warnings in 136.01s (0:02:16) =================
[7/12] OpenAPI 过期检查
✨ openapi-typescript 7.13.0
🚀 /tmp/tmp.rAKrDAn233/openapi.json → /tmp/tmp.rAKrDAn233/schema.d.ts [223.1ms]
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
   Start at  21:07:50
   Duration  12.34s (tests 61%, import 19%, environment 17%, setup 2%, transform 1%)
```