**1. 改动清单**

以下路径均相对 `src/web/src/`：

- `shell.css`：Studio 浅深主题、字体声明、全局部件、装饰字标、动效及降级。
- `mountWeb.tsx`：主题和组件 token；Button 独立反色，全局强调色及反白文字保持正确。
- `datasets/browser.css`：筛选托盘、字段标签、JSON 排版及数字对齐。
- `datasets/fileViewer.css`：文件预览等宽排版。
- `jobs/jobs.css`：日志字号、行高及圆角。
- `fonts/inter-tight-latin-wght-normal.woff2`：原样复制。
- `fonts/inter-tight-latin-ext-wght-normal.woff2`：原样复制。
- `fonts/jetbrains-mono-latin-wght-normal.woff2`：原样复制。
- `fonts/jetbrains-mono-latin-ext-wght-normal.woff2`：原样复制。
- `fonts/LICENSE-InterTight.txt`：原样复制。
- `fonts/LICENSE-JetBrainsMono.txt`：原样复制。

`pnpm build` 成功，4 个字体均进入产物。测试零修改；未安装、未联网、未暂存或提交。临时目录已删除，依赖软链已恢复。

**2. `make check`**

最后一次命令：

```bash
PYTHONPATH=$PWD/src make check
```

末尾输出原样：

```text
[10/12] Prettier
cd src/web && node_modules/.bin/prettier --check .
Checking formatting...
All matched files use Prettier code style!
[11/12] stylelint
cd src/web && node_modules/.bin/stylelint "src/**/*.css"
[12/12] Vitest
cd src/web && node_modules/.bin/vitest run

 RUN  v5.0.5 /home/shawn/桌面/robot-data-platform.wt/ui-08-redesign/src/web


 Test Files  40 passed (40)
      Tests  385 passed (385)
   Start at  21:59:33
   Duration  13.01s (tests 56%, environment 17%, import 16%, transform 10%, setup 2%)
```

后端：2763 passed。

**3. 依赖申请、跳过的设计条目**

无。

**4. 拿不准、需要评审决定的地方**

无待决设计问题。18 页、多尺寸、弹层和无障碍偏好的浏览器截图验收，仍需执行线按工单完成。

工作区原有未跟踪项 `.venv`、`src/web/node_modules` 均保留。