# 作业日志框的内联 style 挪进 CSS 类

Status: in-progress

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
