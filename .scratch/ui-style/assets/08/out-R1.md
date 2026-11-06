1. **字标遮挡**：玻璃伪元素置于 sticky 顶栏自身层叠上下文的底层。离线浏览器验证浅深色字标均清晰，登出按钮、用户名和 fixed 停靠菜单正常。
2. **横向溢出**：顶栏改用父容器宽度和负外边距通栏，不再依赖 `100vw`，未添加祖先 overflow。浅深色 × 1440/1280/390 验证通过；1440 下 `scrollWidth = clientWidth = 1425px`，sticky 正常。

本轮仅修改 `shell.css`。`pnpm build` 成功；测试未改，临时文件已清理，未暂存或提交。首次检查遇到后端测试读取空 JSON 的竞争问题，原样重跑后全绿。

最后一次检查命令：

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
   Start at  22:26:47
   Duration  12.87s (tests 61%, environment 18%, import 17%, setup 3%, transform 1%)
```