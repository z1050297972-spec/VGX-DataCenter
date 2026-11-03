# 布局优化二：作业页、新建数据集表单、accounts/jobs 内联 style 清理

Status: in-progress

分级：直做。理由同第 03 张。硬约束与第 03 张完全相同：tsx 只改布局容器；测试文件一个都不改，原样通过；不加依赖，不自己写组件。

## 依据

- `.scratch/ui-style/layout-decisions.md` 第 3、11、12、13、17、18 条；CODING_STANDARDS 10.14、10.15。
- `followups.md` 第 5 条：M2 合并时遗留的清理（M2 已于 2026-11-01 合并）。
- 视觉参考：`~/.cache/rdp-ui-preview/shots/compare/job-detail-1440-v3.png`、`dataset-new-1440-v3.png`。

## 范围

1. **作业详情**（`jobs/Pages.tsx`）：
   - 页头用 `Breadcrumb`（作业 / 详情）加标题；状态用 `Tag`。
   - 按顺序分四张 `Card`：
     - 概要：提交人、GPU、阶段、用时横向排开，进度条，重新提交；
     - 参数；
     - 日志；
     - 诊断：失败和警告放在 `Collapse` 里，默认收起，标题写条数（如"条目失败 · 共 1 条"）。
   - 收起的内容要留在 DOM 里（`forceRender`），现有测试要求默认可见的不收。
   - 每条诊断里"对象 / 规则 / 实际 / 后果 / 检查"按"字段名：内容"两列对齐。
2. **作业列表**：只调表格和间距。修正"提交示例作业""提交资源示例"两个链接挤在一起的问题，用 `Flex` 加间距。
3. **下载详情**（`jobs/DownloadDetail.tsx`）：按同样的卡片分组调整。
4. **新建数据集表单**（`datasets/CreationScreen.tsx`、`CreationForms.tsx` 等）：每个 `fieldset` 换成带编号标题的 `Card`（"01 基本信息""02 链接"……，按现有字段归类命名）；仍然一页从上往下填，不改成分步。
5. **内联 style 清理**：`accounts/Pages.tsx`、`jobs/Pages.tsx`，以及 M2 新加的下载页组件里的 `style={{…}}` 改成 CSS 类；删掉 `eslint.config.js` 里对这两个文件的临时关闭；把 `no-restricted-syntax` 挪到"后端分支数 ≤ 12…"那段注释的上方（本票允许改 `eslint.config.js`）。

## 验收

1. `git status --porcelain` 只出现 `src/web/src/` 下的 tsx、css，以及 `src/web/eslint.config.js`。
2. `make check` 全绿；测试文件没动。
3. 执行线截图验收：作业列表、作业详情（有失败和警告的示例作业）、下载详情、新建数据集，1440 和 1280 两种宽度。

## Comments

### 2026-11-02 开票与派工（执行线）

- 第 03 张已合并（f496b99），解除阻塞。负责人在第 03 张合并前已经同意"合并后开第 04 张"。
- 工作目录 `~/桌面/robot-data-platform.wt/ui-style`，分支 `t/ui-04-layout`，从 main 开。
- 派工 A：Codex gpt-6.1-terra high，单元 `rdp-codex-ui-04`，日志 `~/.cache/rdp-dispatch/ui-04/`，提示 `assets/04/prompt-A.md`。
