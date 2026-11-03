# 布局优化三：其余全部页面，以及诊断组件类名归位

Status: in-progress

分级：直做。理由同第 03、04 张。硬约束完全相同：tsx 只改布局容器；测试文件一个都不改，原样通过；不加依赖，不自己写组件。

## 依据

- 负责人 2026-11-02："把所有的都做完，再合并、升级，一套流程做完再联系我"。
- `.scratch/ui-style/layout-decisions.md`；CODING_STANDARDS 10.14、10.15；第 03、04 张的评审记录（Comments），里面的坑不要再踩。
- `followups.md` 第 6 条（诊断组件类名）、第 8 条（第二批页面）。
- 现状截图：`~/.cache/rdp-ui-preview/shots/b2v0/`。已完成页面的效果参考：`~/.cache/rdp-ui-preview/shots/final03/`、`final04/`。

## 范围

所有页面统一用第 03、04 张已经定下的骨架：

- **页头**：`Breadcrumb` 加 `Typography.Title`，页面级操作放在标题同一行右侧。
- **筛选卡**：筛选项用 `Row`/`Col` 排，标签在上；筛选和它控制的表格放进同一张卡片，参考 shadcn tasks。
- **内容卡**：一组信息一张 `Card`，不套卡片；每块只有一个主样式按钮。
- **其他**：长 JSON、长路径列单行截断，悬停显示全文；表单卡片限制合适的宽度，不要撑满 1280。

逐页要求：

1. **操作日志、登录日志**（`audit/Pages.tsx`）：
   - "保留天数 / 保存保留期"单独放一张小卡片（或放在页头右侧），和筛选分开；
   - 筛选项用栅格排齐，筛选和表格放进同一张卡片；
   - "下一页"放到表格右下角；
   - "明细"列单行截断，悬停显示全文。
2. **账号管理**（`accounts/Pages.tsx` 的 `AccountsPage`）：
   - 页头"账号管理"，"新建账号"作为主按钮放在右侧（它如果会原地展开表单，就不要放进标题行，按第 03 张的教训处理）；
   - Hugging Face token 一张卡，账号表一张卡；
   - 翻页放到表格右下角；危险按钮保持醒目。
3. **修改口令**（`PasswordPage`）：表单放进一张卡片，宽度适中。登录页（`LoginPage`）第 01 张已经做过，不动。
4. **下载**（`downloads/`）：下载表单一张卡（字段用两列栅格），暂存区一张卡，预览和导入的结果各成一张卡；表单底部的按钮排在一行。
5. **网络与资源**（`monitoring/Pages.tsx`）：
   - 镜像状态、VPN 与代理等卡片用 `Row`/`Col` 两列排，窄屏变一列；
   - 卡片之间的间距统一；
   - 网速这类列表用"名称：值"两列对齐。
6. **调度**（`scheduling/`）、**存储根**（`storage/`）、**导航层恢复**（`navigation/Pages.tsx`）：按骨架整理。
7. **提交示例作业、提交资源示例、回滚**（`jobs/Pages.tsx` 的 `SubmitCountJobPage`、`jobs/Resources`、`navwrites/Revert.tsx`）：表单卡片加页头。
8. **新建链接**（`datasets/CreationPages.tsx` 的 `CreateLinkPage`）：和新增数据集表单保持一致。
9. **首页**（`HealthPage.tsx`）：后端状态放进一张小卡片，加页头（面包屑写"概览"）。
10. **诊断组件类名归位**（followups 第 6 条）：
    - `DiagnosticCard.tsx` 里的 `jobs-diagnostic-*` 类改成 `diagnostic-` 前缀，样式移到 `DiagnosticCard` 自己 import 的 `diagnostic.css`；
    - 作业页那一套浅灰无边框的外观，继续只在作业诊断容器下生效；
    - 其他页面诊断的外观不能变。

## 不做

- 登录页、已完成的数据集、作业和新增数据集页面不动（共用部件改了自动受益的除外）。
- 深色模式：第 06 张做。
- followups 第 7 条（日志内联 style）：要改测试，不做。

## 验收

1. `git status --porcelain` 只出现 `src/web/src/` 下的 tsx 和 css。
2. `make check` 全绿，测试文件没动。
3. 执行线截图验收：上面每一页，1440 和 1280 两种宽度。

## Comments
