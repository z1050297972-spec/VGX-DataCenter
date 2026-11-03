# 布局优化三：其余全部页面，以及诊断组件类名归位

Status: done

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

### 2026-11-02 开票与派工（执行线）

- 负责人授权整套流程做完再联系（"把所有的都做完，再合并、升级"）。
- 工作目录 `~/桌面/robot-data-platform.wt/ui-style`，分支 `t/ui-05-layout`，从 main@c89fc1f 开。
- 派工 A：Codex gpt-6.1-terra high，单元 `rdp-codex-ui-05`，超时 180 分钟，日志 `~/.cache/rdp-dispatch/ui-05/`。
- 第一次派工 2026-11-02 20:31 前后失败：Codex 连不上模型服务（Network is unreachable，504），工作区没被改动。网络恢复后原样重派，单元同名，失败日志放在 `~/.cache/rdp-dispatch/ui-05/failed-1/`。

### 2026-11-02 评审 1（执行线）

- Codex 自报"未完成"。文件归属没问题，只改了 `src/web/src/` 下的 tsx 和 css；`make check` 全绿，前端 380 passed。
- tsx 的 diff 过滤后逐处看过，没有逻辑改动。展示上的调整都允许：审计表单 `layout` 从 inline 改成 vertical、新建账号用了 `type="primary"`、加了 `ellipsis`、首页标题写"概览"。
- 截图在 `~/.cache/rdp-ui-preview/shots/t05/`。网络与资源、调度、账号两张卡片的分组都到位了。
- 打回 7 条：
  1. 阻塞：操作日志的筛选卡横向溢出页面；
  2. 页头间距太大，各模块各写一套，改成 `shell.css` 里的全局页头类，面包屑写两级；
  3. 卡片里还在用 h2/h3 大标题；
  4. 下载页按钮挤在一起；
  5. 存储根的路径被截断，违反追问记录第 8 条；
  6. 首页状态卡太窄；
  7. 错误状态下仍有卡片嵌套。
- 修复轮 R1，单元 `rdp-codex-ui-05-r1`。

### 2026-11-02 评审 2（执行线）

- R1 自报全部完成，7 条都看过，到位。错误状态下有三处诊断仍留在所属卡片内：暂存区、镜像检查、调度的 GPU 条目。评审接受，诊断跟着它说明的内容放更清楚。
- 新加了溢出检查脚本 `~/.cache/rdp-ui-preview/overflow.mjs`，检查 18 个页面在 1280、1440、390 三种宽度下有没有横向溢出。1280 和 1440 全部通过。之前截图里存储根在 1280 被截断，是截图脚本切换宽度时页面还没重排造成的，不是页面问题。
- 打回 1 条：手机宽度下 `/accounts`、`/scheduling`、`/jobs` 横向溢出。`/jobs` 是第 04 张的页面，一并修。
- 修复轮 R2，单元 `rdp-codex-ui-05-r2`。

### 2026-11-02 评审 3 与合并（执行线）

- R2 把三个页面的单列 Grid 改成 `minmax(0, 1fr)`，容器加了 `min-width: 0`，窄屏下页头分行排。用 `overflow.mjs` 复测：18 个页面在 1280、1440、390 三种宽度下都没有横向溢出。
- 实现提交 `7f877ba`；合并提交 `de767d2`，钩子跑的 `make check` 全绿。负责人这次的授权是整套做完再联系，所以评审通过后直接合并。工作目录和分支已删除。
