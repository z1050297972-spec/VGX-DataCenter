# 前端样式线的遗留事项

1. **[已开第 02 张，负责人 2026-11-01 批准] 第 02 张：清理内联 style，规则改成机检。** 把 tsx 里存量的 24 处 `style={{…}}`（10 个文件）改成 CSS 类；`eslint.config.js` 用 `no-restricted-syntax` 禁止静态值的 `style` 属性（不需要新依赖）。要改 tsx，也要动受保护文件 `eslint.config.js`，所以等 m2-03、m0-13 合并后再开，开之前请负责人确认。
2. **依赖申请（负责人 2026-11-01 批准，第 02 张安装）：stylelint。** 包：`stylelint` 和 `stylelint-config-standard`，开发依赖。用途：把 CODING_STANDARDS 10.7、10.10、10.11 里能机检的部分（禁止写死颜色、类名格式、选择器层数、`!important` 要带注释）接进 `make check`。Prettier 只管格式，ESLint 不看 CSS，现有依赖都做不到。要改 `package.json`、`pnpm-lock.yaml`、`Makefile`。
3. **ConfigProvider 主题（可选）。** 第 01 张用纯 CSS 覆盖 antd 变量，派生色要逐个覆盖。改用 ConfigProvider 更彻底，但要改 `mountWeb.tsx`。看第 01 张的效果再决定要不要做。
4. **深色模式。** 第 01 张评审发现：只靠 CSS 变量盖不全 antd 的组件 token，所以第 01 张只做浅色。要做深色，就用 ConfigProvider 的 `theme.darkAlgorithm` 跟随系统切换，这要改 `mountWeb.tsx`，可以和第 3 条合成一张票。
5. **M2 合并时：** 第 02 张没碰 `accounts/Pages.tsx`、`jobs/Pages.tsx`，这两个文件在 `eslint.config.js` 里临时关掉了禁止 style 的规则。M2 合并时要清理这两个文件和 M2 新加的下载页组件里的内联 style，删掉临时关闭，并修作业页两个链接挤在一起的问题。
