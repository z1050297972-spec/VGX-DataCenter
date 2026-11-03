# 作业日志框的内联 style 挪进 CSS 类

Status: done

分级：直做。理由：不改行为，只换写法，外加改写一条测试的断言方式。

## 依据

- 负责人 2026-11-03："可以推送，再开一张票"。指的是 followups 第 7 条，也就是这一轮唯一没做的遗留。
- 规范 10.9：静态样式写成 CSS 类，不写 `style={{…}}`。

## 现状

`src/web/src/jobs/Pages.tsx` 的 `JobLogPanel` 里，日志 `<pre>` 带着内联 style `{ whiteSpace: "pre-wrap", overflowWrap: "anywhere", maxWidth: "100%", minWidth: 0 }`，并用 `eslint-disable-next-line no-restricted-syntax` 单条豁免。豁免的原因是测试 `src/web/src/jobs/Pages.test.tsx` 里"评审3：作业日志长行在有界日志框内换行"直接断言了 `log.style.whiteSpace` 等内联值。Vitest 默认不加载 CSS，所以挪进 CSS 类以后，这几条断言会失败。

## 范围

1. 把这四个声明挪进 `jobs/jobs.css` 里已有的 `.jobs-log` 规则，删掉内联 style 和那行 eslint 豁免。外观保持不变。
2. **本票允许改且只允许改**这一条测试的断言方式。测试要守的行为是"超长单行在有界日志框内换行，不撑宽页面"，改写后要继续守住这个行为。例如：
   - 断言日志元素带 `jobs-log` 类；
   - 再读取 `jobs/jobs.css` 的文本，断言 `.jobs-log` 规则里有 `white-space: pre-wrap`、`overflow-wrap: anywhere`、`max-width: 100%`、`min-width: 0`。

   用其他能守住这个行为的写法也可以，在回复里说明理由。不能只删断言。
3. 其他测试一个都不改。

## 不做

- 不改作业页其他地方，也不改 Vitest 配置（`vite.config.ts` 是受保护文件）。

## 验收

1. `git status --porcelain` 只出现 `jobs/Pages.tsx`、`jobs/jobs.css`、`jobs/Pages.test.tsx`。
2. `make check` 全绿。
3. 变异抽查：把 `.jobs-log` 里的 `white-space: pre-wrap` 临时删掉，改写后的测试要变红；验证完撤回。
4. 执行线截图：作业详情的日志框，外观和改前一致。

## Comments

### 2026-11-03 开票与派工（执行线）

- 工作目录 `~/桌面/robot-data-platform.wt/ui-style`，分支 `t/ui-07-log`，从 main@eb67bd4 开。派工 A：Codex gpt-6.1-terra high，单元 `rdp-codex-ui-07`。
- 负责人 2026-11-03："我需要休息一下，接下来我把权限交给你，可以调用gpt 6 astra high执行"。本票后续的返修改用 `gpt-6-astra` high；收尾时照前几张，合并、升级真实部署、推送 GitHub 一并做完再汇报。

### 2026-11-03 评审与合并（执行线）

- Codex 自报"未完成"，原因只是自己截不了图，截图本来就是执行线的活。diff 只动了三个允许的文件：内联 style 删了，四个声明进了 `.jobs-log`，eslint 豁免也删了。改写后的测试断言日志元素带 `jobs-log` 类，并读取 `jobs.css` 检查四个声明。变异抽查（删掉 `white-space: pre-wrap`）时测试变红，原文见 `assets/07/out-A.md`。
- 截图对比：作业详情的日志框和改前一致。整页错开 64px 是因为预览 worker 停了，多出一条"worker 没在运行"横幅，和本票无关。
- 实现提交 `eb67bd4`，合并提交 `eb67bd4`，钩子跑的 `make check` 全绿。工作目录和分支已删除。
