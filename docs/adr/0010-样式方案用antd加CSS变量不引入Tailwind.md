# 样式方案：antd 加 CSS 变量，不引入 Tailwind

Status: accepted（2026-11-01，负责人："可以使用工程框架，比如tailwind，但是我不太懂这个东西，需要你来把控"，委托 Claude 决定）

前端的组件继续用 antd（ADR 0002），外观统一由 `src/web/src/shell.css` 里的 `--rdp-*` 设计变量控制，再由这些变量覆盖 antd 自己的 `--ant-*` CSS 变量。每个模块的样式放在自己目录下的 CSS 文件里。写法规则见 `CODING_STANDARDS.md` 10.1 节，机检以后接 stylelint（依赖待批）。不引入 Tailwind。

## 考虑过的方案

- **Tailwind CSS**：放弃，原因有四条。
  1. Tailwind 的写法是在每个 JSX 元素的 `className` 上堆工具类，用上它就要改遍所有 tsx。负责人要求这次只改样式、不碰功能代码，而且其他线正在改同一批 tsx。
  2. 平台的界面大部分是 antd 组件（表格、表单、弹窗），这些组件内部的 DOM 不归我们写，工具类贴不上去，最后还是要写 CSS 覆盖 antd，等于维护两套样式体系。
  3. Tailwind 的全局重置（preflight）会和 antd 的基础样式互相打架，需要额外配置来隔离。
  4. 需要新的构建依赖和 `vite.config.ts` 插件，两者都是受保护文件。
- **CSS Modules / CSS-in-JS**：同样要改 tsx 的 import 和 className，收益是类名不冲突。现在的类名有模块前缀（10.10），冲突的风险很小，不值得为此改代码。
- **ConfigProvider 主题 token**：这是 antd 官方的换肤方式，派生色由 antd 自动算。缺点是要改 `mountWeb.tsx`。这次先用 CSS 变量覆盖；如果派生色覆盖得不齐，再开票改用 ConfigProvider，`--rdp-*` 变量保留不变。

## 后果

- 换肤、深色模式、降级开关都集中在 `shell.css` 一个文件里，开发者在浏览器开发者工具里改变量就能实时看效果，不需要重新构建。
- antd 升级可能改 `--ant-*` 变量名。升级 antd 时，要检查 `shell.css` 里覆盖的变量是否还存在。
- 内联 style 还有存量 24 处，等其他线合并后由 ui-style 第 02 张清理（`.scratch/ui-style/followups.md`）。
