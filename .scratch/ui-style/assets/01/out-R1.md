状态：全部完成

1. **仅保留浅色模式**：删除深色媒体查询及专为深色模式设置的 Alert 覆盖和变量；在 `:root` 设置 `color-scheme: light`，并注明深色模式需使用 antd 暗色算法、另开票处理。
2. **顶栏和横幅对齐内容区**：新增 `--rdp-content-width: 1280px`，顶栏、状态横幅、`main` 和版本 footer 共用该最大宽度并水平居中；横幅之间使用统一间距。
3. **普通链接颜色**：全局链接及悬停态使用主题色；停靠菜单链接保留自身样式。
4. **停靠菜单滚动条**：使用细滚动条和透明轨道，并为 WebKit 设置 4px 高度；保留横向滚动。

本轮只修改了 `shell.css`；工作区中上轮的其他 CSS 改动仍保留，未暂存或提交。未做截图复验。

### `make check`

最后一次命令：

```bash
set -o pipefail; make check 2>&1 | tail -28
```

末尾输出：

```text
  /home/shawn/桌面/robot-data-platform.wt/ui-style/.venv/lib/python3.12/site-packages/fastapi/testclient.py:1: StarletteDeprecationWarning: Using `httpx` with `starlette.testclient` is deprecated; install `httpx2` instead.
    from starlette.testclient import TestClient as TestClient  # noqa

-- Docs: https://docs.pytest.org/en/stable/how-to/capture-warnings.html
================= 2627 passed, 8 warnings in 98.71s (0:01:38) ==================
[7/11] OpenAPI 过期检查
✨ openapi-typescript 7.13.0
🚀 /tmp/tmp.mfpEtxbqqN/openapi.json → /tmp/tmp.mfpEtxbqqN/schema.d.ts [127.5ms]
OpenAPI 与生成类型均未过期
[8/11] tsc
src/web/node_modules/.bin/tsc --project src/web/tsconfig.json --noEmit
[9/11] ESLint
cd src/web && node_modules/.bin/eslint . --max-warnings 0
[10/11] Prettier
cd src/web && node_modules/.bin/prettier --check .
Checking formatting...
All matched files use Prettier code style!
[11/11] Vitest
cd src/web && node_modules/.bin/vitest run

 RUN  v5.0.5 /home/shawn/桌面/robot-data-platform.wt/ui-style/src/web


 Test Files  39 passed (39)
      Tests  373 passed (373)
   Start at  01:58:13
   Duration  10.70s (tests 56%, import 22%, environment 20%, transform 1%)
```

### Build

最后一次命令：

```bash
set -o pipefail; pnpm --dir src/web build 2>&1 | tail -12
```

末尾输出：

```text
dist/assets/index-DoBORzml.js              55.85 kB │ gzip:  18.71 kB
dist/assets/link-DTfZODAI.js               59.49 kB │ gzip:  21.41 kB
dist/assets/react-runtime-CvdC6zOt.js     218.75 kB │ gzip:  68.26 kB
dist/assets/time-8LP5GLf6.js              325.63 kB │ gzip:  68.97 kB
dist/assets/ui-D0Z2k7ns.js                811.12 kB │ gzip: 259.86 kB

[plugin builtin:vite-reporter] 
(!) Some chunks are larger than 500 kB after minification. Consider:
- Using dynamic import() to code-split the application
- Use build.rolldownOptions.output.codeSplitting to improve chunking: https://rolldown.rs/reference/OutputOptions.codeSplitting
- Adjust chunk size limit for this warning via build.chunkSizeWarningLimit.
✓ built in 300ms
```