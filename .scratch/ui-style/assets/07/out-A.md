状态：未完成（工单要求的作业详情日志框截图尚未取得，无法确认视觉验收；代码、变异抽查和检查链已完成）

### 1. 改动清单

- 将日志框的四项静态样式从 `Pages.tsx` 的内联 `style` 移入 `jobs.css` 的 `.jobs-log`，并删除对应的 ESLint 豁免。
- 只改写了 `Pages.test.tsx` 中指定的一条测试：验证日志元素绑定了 `jobs-log` 类，并检查该 CSS 规则包含四项声明。由于 jsdom 不计算外部样式，此测试**不能代替浏览器截图验收**。
- `git status --porcelain` 只显示工单允许的三个文件；未暂存、未提交。
- 变异抽查时，自动恢复命令因切换了工作目录而失败；随后已手动恢复 CSS，再运行 `make check`。

### 2. 改写后的测试原文

```tsx
it("评审3：作业日志长行在有界日志框内换行", async () => {
  const line = "x".repeat(10000);
  const view = mountPage(
    `/jobs/${job.job_id}`,
    detailFetch(
      () => completedJob,
      () => ({
        tail: { status: "available", lines: [line], truncated: false },
      }),
    ),
  );
  try {
    const log = await screen.findByRole("log");
    expect(log.textContent).toBe(line);
    // jsdom 不计算外部样式；同时验证类绑定和该规则的声明，守住长行换行及宽度边界。
    expect(log.classList.contains("jobs-log")).toBe(true);
    const fsModule = "node:fs/promises";
    const fs = (await import(fsModule)) as {
      readFile: (path: string, encoding: "utf8") => Promise<string>;
    };
    const css = await fs.readFile("src/jobs/jobs.css", "utf8");
    const rule = css.match(/\.jobs-log\s*\{([^}]*)\}/)?.[1] ?? "";
    expect(rule).toMatch(/(?:^|;)\s*white-space\s*:\s*pre-wrap\s*;/);
    expect(rule).toMatch(/(?:^|;)\s*overflow-wrap\s*:\s*anywhere\s*;/);
    expect(rule).toMatch(/(?:^|;)\s*max-width\s*:\s*100%\s*;/);
    expect(rule).toMatch(/(?:^|;)\s*min-width\s*:\s*0\s*;/);
  } finally {
    view.close();
  }
});
```

### 3. 变异抽查

执行的命令：

```bash
cp src/web/src/jobs/jobs.css /tmp/ui-07-jobs.css && trap 'cp /tmp/ui-07-jobs.css src/web/src/jobs/jobs.css' EXIT; sed -i '/  white-space: pre-wrap;/d' src/web/src/jobs/jobs.css; cd src/web; node_modules/.bin/vitest run src/jobs/Pages.test.tsx -t '评审3：作业日志长行在有界日志框内换行'
```

失败输出原文：

```text
 RUN  v5.0.5 /home/shawn/桌面/robot-data-platform.wt/ui-style/src/web

 ❯ src/jobs/Pages.test.tsx (22 tests | 1 failed | 21 skipped) 421ms
   × 评审3：作业日志长行在有界日志框内换行 418ms

⎯⎯⎯⎯⎯⎯⎯ Failed Tests 1 ⎯⎯⎯⎯⎯⎯⎯

 FAIL  src/jobs/Pages.test.tsx > 评审3：作业日志长行在有界日志框内换行
AssertionError: expected '\n  overflow-wrap: anywhere;\n  max-w…' to match /(?:^|;)\s*white-space\s*:\s*pre-wrap\…/

- Expected:
/(?:^|;)\s*white-space\s*:\s*pre-wrap\s*;/

+ Received:
"
  overflow-wrap: anywhere;
  max-width: 100%;
  min-width: 0;
  max-height: 480px;
  overflow: auto;
  background: var(--rdp-subtle);
  border-radius: var(--rdp-radius-small);
  padding: var(--rdp-space-4);
  margin: 0;
  font-family: var(--rdp-mono);
  font-size: 12px;
"

 ❯ src/jobs/Pages.test.tsx:889:18
    887|     const css = await fs.readFile("src/jobs/jobs.css", "utf8");
    888|     const rule = css.match(/\.jobs-log\s*\{([^}]*)\}/)?.[1] ?? "";
    889|     expect(rule).toMatch(/(?:^|;)\s*white-space\s*:\s*pre-wrap\s*;/);
       |                  ^
    890|     expect(rule).toMatch(/(?:^|;)\s*overflow-wrap\s*:\s*anywhere\s*;/);
    891|     expect(rule).toMatch(/(?:^|;)\s*max-width\s*:\s*100%\s*;/);

⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯[1/1]⎯


 Test Files  1 failed (1)
      Tests  1 failed | 21 skipped (22)
   Start at  02:51:42
   Duration  2.82s (import 49%, environment 20%, tests 15%, transform 9%, setup 6%)

cp: cannot create regular file 'src/web/src/jobs/jobs.css': No such file or directory
```

随后从工作区根目录手动撤回变异：

```bash
cp /tmp/ui-07-jobs.css src/web/src/jobs/jobs.css
```

### 4. 最后一次 `make check`

命令：

```bash
make check > /tmp/ui-07-make-check.log 2>&1
```

末尾输出原文：

```text
================= 2757 passed, 8 warnings in 101.97s (0:01:41) =================
[7/12] OpenAPI 过期检查
✨ openapi-typescript 7.13.0
🚀 /tmp/tmp.0TKPRL19K3/openapi.json → /tmp/tmp.0TKPRL19K3/schema.d.ts [146.1ms]
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
   Start at  02:54:15
   Duration  13.79s (tests 57%, import 19%, environment 16%, transform 6%, setup 2%)
```

`make check` 退出码为 0；pytest 有 8 条弃用警告。