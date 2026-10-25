# Codex 派工与评审手册

> **状态**：2026-10-23 定稿，依据是 M0 第 1 张工单「仓库骨架和检查链」第一次跑通流水线的情况。以后由 `/retro` 修订。
>
> 本手册取代「Codex 协作规程」（`.scratch/platform-v1/issues/08-codex-workflow.md`）的 Answer，两者不一致时以本手册为准。
>
> 实测过的 Codex 行为见 `docs/brief/0006`、`0009`。本手册里的命令按 codex-cli 0.163.0 写。

## 1. 分工

规划和执行并行：

| 谁 | 做什么 | 在哪里写、在哪里提交 |
|---|---|---|
| 主会话 | 走图、写规划。把两个关卡（骨架"通过"、最后"合并"）交给负责人，把负责人的原话和时间记进工单的 Comments。负责人说"合并"后做合并（3.7）。每张决策票关闭时提交规划改动 | 主仓库目录。主仓库目录里的提交和合并只由主会话做 |
| 执行线（后台 agent） | 派 Codex；做评审的跑腿工作：重跑检查、核对文件归属、对比契约、跑 `/code-review`；起草骨架摘要和完工汇报 | 只在该票的工作目录里提交。在主仓库目录里只写该票的工单文件和 assets 目录，不提交 |
| 负责人 | 骨架"通过"或"改"；最后"合并" | — |
| Codex | 契约骨架、TDD 实现、修复 | 只在工作目录里写，不能提交（0009） |

- **一次只做一张实现票。** 开票前扫一遍 `.scratch/m*/issues/*.md` 的 `Status:` 行，确认没有别的实现票处在 `in-progress`、`in-review` 或 `changes-requested`。
  - **例外：下一张可以提前开**（2026-10-25 起，负责人要求提速、不降质量）。前一张已经做了实现提交、只等负责人说"合并"时，下一张从前一张的分支开（`git worktree add -b t/<下一张> <工作目录> t/<前一张>`），派工 A 照常进行。前一张合并后，下一张的分支已经包含它，不用变基；负责人在合并关卡要求修改时，下一张停在当前步骤，等前一张改完再 `git rebase` 到新的实现提交上，重跑 `make check`。同时在进行的实现票最多两张，而且前一张必须已经过了评审。
- **执行线到关卡就交回主会话，然后停下。** 关卡过后，主会话续接同一个执行线，或者新开一个；新开的先读工单的 Comments，接上进度。
- **Comments 做完一步记一步**，写法和规划票一致，例如：`- 2026-10-22，派工 B。会话 <编号>，快照 refs/rdp/m0-01/B，提示 assets/01-repo-skeleton-check-chain/prompt-B.md，运行日志 <路径>。结论：……`

**执行线要能承受中断。**

- 2026-10-22，后台 agent 曾因 Claude 的使用额度用完（HTTP 429）中途停下。已做的工作都还在，额度恢复后续接，从停下的地方继续。
- 所以每一步的产物都落到文件里，不只留在 agent 的上下文里：
  - 派工提示和 Codex 的最终回复在 assets。
  - 会话编号、快照名、检查结果、评审结论在工单的 Comments。
- 接手时（续接或新开），先读 Comments 的最后一条，再确认上一步的产物都在：
  - **上一轮 Codex 跑完没有**：运行日志最后一条是 `turn.completed`，`-o` 文件存在。还在跑（`pgrep -af 'codex exec'` 的输出里有这张票的会话编号或工作目录）就等它结束。没跑完就退出了的，按第 9 节"模型网关断开"的第 1 步续接那个 Codex 会话，不另开新会话。
  - **快照和提交做了没有**：`git -C <工作目录> log -1 --format=%s`、`git -C <工作目录> for-each-ref refs/rdp/<票>/`。

## 2. 命名与位置

| 东西 | 写法或位置 | 例子 |
|---|---|---|
| 票的简称 `<票>` | `m<N>-<NN>` | `m0-01` |
| 分支 | `t/<票>-<slug>` | `t/m0-01-repo-skeleton-check-chain` |
| 工作目录 | `~/桌面/robot-data-platform.wt/<票>-<slug>` | `~/桌面/robot-data-platform.wt/m0-01-repo-skeleton-check-chain` |
| 工单 | 主仓库目录的 `.scratch/m<N>-<名>/issues/<NN>-<slug>.md` | `.scratch/m0-foundation/issues/01-repo-skeleton-check-chain.md` |
| assets | 主仓库目录的 `.scratch/m<N>-<名>/assets/<NN>-<slug>/`，放 `prompt-<派工名>.md` 和 `out-<派工名>.md` | `.scratch/m0-foundation/assets/01-repo-skeleton-check-chain/` |
| 运行日志、stderr | 执行线的临时目录（scratchpad），路径记进 Comments。JSONL 太大，不进仓库 | `ev-B.jsonl`、`err-B.txt` |
| 派工名 | `A`、`B`、`r1`–`r3`（打回第几轮）；派工 A 拆段时用 `A1`、`A2` | |
| 快照 | 派工前拍 `refs/rdp/<票>/<派工名>`，评审开始时拍 `refs/rdp/<票>/<派工名>-done` | `refs/rdp/m0-01/B-done` |

## 3. 实现票流水线

### 3.1 开票（执行线）

1. 确认工单是 `Status: ready-for-agent`，并且没有别的实现票在进行中（第 1 节）。
2. Status 改成 `in-progress`。
3. `git -C <主仓库目录> worktree add -b t/<票>-<slug> <工作目录> main`
4. 在工作目录里装依赖：`uv sync --frozen`，再在 `src/web/` 里跑 `pnpm install --frozen-lockfile`。沙箱虽然为了跑测试开了网络权限（0012），安装仍然只由执行线在沙箱外做。
5. 在工作目录里跑一次 `make check`。

M0 第 1 张票开票时还没有 `pyproject.toml` 和 `make check`，第 4、5 步按那张票自己的步骤做。

**完成**：工作目录的 `git status --porcelain` 为空，`make check` 全绿。基线是绿的，之后出现的红才能算到这次改动头上。

### 3.2 派工 A：契约骨架（执行线）

1. 按第 7 节的模板写 `prompt-A.md`。工单把派工 A 拆成几段时（例如 M0 第 1 张票的 A1、A2），每段交什么写在工单里，提示里写明本次只做哪一段；后面几段用续接命令。
2. 拍快照 `A`（5.2）。
3. 后台派工，用第 4 节的"新会话"命令。
4. 在 Comments 记一条：会话编号、派工名、命令、提示文件、运行日志的路径。

**完成**：Codex 已退出，运行日志最后一条是 `turn.completed`，`out-A.md` 存在，会话编号已记进 Comments。

### 3.3 骨架关卡

执行线：

1. 在工作目录里重跑 `make check`。
2. 核对文件归属，查运行日志（3.5 的第 2、5 项）。
3. 对照工单、`GLOSSARY.md`、ADR 和 `CODING_STANDARDS.md` 第 3 条审骨架：每个公开函数六项写全、内容合格；测试清单覆盖每个契约行为（`CODING_STANDARDS.md` 7.1）。
4. 拍快照 `A-done`。把一页摘要（6.1）写进 Comments，Status 改成 `in-review`，交回主会话。

主会话：把摘要交给负责人，把负责人的原话和时间记进 Comments。

- 负责人说"通过"：执行线做契约提交（`契约：<票名>`，5.1），Status 改回 `in-progress`，进入 3.4。
- 负责人说"改"：按 3.6 的第 1、2 步发修复轮，计一轮打回（6.3）；Codex 交回以后，回到本节第 1 项。

**完成**：工作目录最新的提交是 `契约：<票名>`，工作目录干净。

### 3.4 派工 B：TDD 实现（执行线）

1. 按第 7 节的模板写 `prompt-B.md`，拍快照 `B`。
2. 先 `cd <工作目录>`，再用第 4 节的"续接"命令派工。
3. 在 Comments 记一条。

**完成**：同 3.2。

### 3.5 评审（执行线）

不采信 Codex 的自述，依次做：

1. **重跑**：在工作目录里跑 `make check`，记下用时。
2. **文件归属**（规则 3）：
   - 工作目录：`git status --porcelain --untracked-files=all` 的每一行，都在 `src/`、`tests/` 下，或者是工单写明允许改的受保护文件。
   - 主仓库目录：里面允许有还没提交的规划改动，但规划文件以外不能有改动。`git -C <主仓库目录> status --porcelain -- src tests` 必须为空。再用下面这条把范围放到所有非规划文件，受保护文件也在内，输出同样必须为空：

     ```bash
     git -C <主仓库目录> status --porcelain --untracked-files=all -- . \
       ':!.scratch' ':!docs' ':!GLOSSARY.md' ':!AGENTS.md' ':!CLAUDE.md'
     ```

     续接时忘了先 `cd`，Codex 就会把文件写进主仓库目录（0009），这条能抓到。
   - 越界直接打回。
3. **对比契约**：`git -C <工作目录> diff <契约提交> -- <骨架涉及的文件>`。已获批的签名、类型和 docstring 没有变化；有变化按 6.2 处理。
4. **先红后绿**：提示里仍然要求 Codex 逐个测试单独先跑、并在最终回复第 5 块说明一开始就通过的测试。评审不再从运行日志逐条解析，改用**变异抽查**验证测试真能区分对错：对本票每个公开函数的关键行为（报错条件、边界、副作用、时间语义）各做一处变异，脚本放 assets（`mutation_probe.py`，输出 `mutation_probe-<快照名>.txt`），每个变异改完立即还原。漏掉的变异，排除等价变异以后，每个都进修复清单。第 5 块缺失、或者说明对不上的，也进修复清单。修复轮复用上一轮的脚本，只补新增的行为。
5. **运行日志**：`grep -nE 'data_check|Data_Collection_System' <运行日志>` 没有结果，因为沙箱的读权限挡不住两个旧项目（0009）。出现 `/mnt` 的命令逐条看一遍。再查安装和联网命令（0012），有一条就整轮打回：

   ```bash
   grep -nE '"command":"[^"]*\b(pip|npm|npx|curl|wget|uv (add|pip)|pnpm (add|install)|git (clone|fetch))\b' <运行日志>
   ```

   命中的是 `pnpm install --frozen-lockfile` 时不算违规，但要确认锁文件没变。
6. **两轴评审**：拍快照 `B-done`（修复轮是 `r<N>-done`），在检出这个快照的探针工作目录里（5.2）跑 `/code-review main`，并把主仓库目录里的工单路径给它当 spec。涉及同步、录制、转换的模块，再跑 `algorithm-code-review`。
   - 要在探针工作目录里跑，是因为 `/code-review` 比较的是 `main...HEAD` 之间的提交，而这时实现还没有提交。
7. **违规试验**：在同一个探针工作目录里放进违规，确认每种都在对应的那一步失败。按 ruff 输出里的规则名（例如 `print`）匹配，不按规则码匹配，因为同一条规则在不同版本里可能换码。试验用例和输出放进 assets。
   - 违规试验测的是检查链本身，不是本票代码。**只在本票改了检查链时做**：`Makefile`、`scripts/`、`.githooks/`、`pyproject.toml` 里 ruff、basedpyright、import-linter、pytest 的配置段，`src/web/` 下 ESLint、Prettier、tsc、Vitest 的配置。而且只试本票新加或改过的那几条规则（例如新登记的 import-linter 依赖方向），再加一条"钩子拒绝带 print 的提交"做冒烟。检查链没动的票，这一项记"检查链未改，不做"。
8. **记录**：每项的结论写进 Comments，不通过的整理成修复清单。

**什么算不通过**（2026-10-25 起）。只有阻塞问题进修复清单、触发打回：

- 第 1、2、3、5 项不通过；
- 漏网的变异（第 4 项）；
- 两轴评审里的**硬性违规**（违反 `CODING_STANDARDS.md` 或 `AGENTS.md` 写明的条款），以及 Spec 轴的缺失、错误实现、范围蔓延；
- 第 7 项有违规没被拦住。

两轴评审里的**判断题和坏味道**（重复代码、命名、可以更好的写法）不打回，写进完工汇报的"遗留事项"，并汇总到该里程碑的 `.scratch/<里程碑目录>/followups.md`。里程碑结束前，由 `/retro` 决定哪些改进编码规范，哪些单开一张整理票。同一类判断题在两张票里反复出现的，`/retro` 考虑把它写进编码规范，变成硬性条款。

**完成**：八项都有结论记在 Comments。

- 全部通过：做实现提交（`实现：<票名>`），起草完工汇报（改了什么、测试情况、风险、下一张工单），Status 改成 `in-review`，交回主会话。
- 有不通过的：进入 3.6。

### 3.6 打回（执行线）

1. 修复清单写进 Comments，每条写明问题、位置和期望的结果。Status 改成 `changes-requested`。
2. 按第 7 节的模板写 `prompt-r<N>.md`，拍快照 `r<N>`，Status 改成 `in-progress`，续接派工。
3. 回到 3.5。

轮数怎么算、超过以后怎么升级，见 6.3。

### 3.7 合并（主会话）

负责人说"合并"之后，在主仓库目录里依次做：

1. `git diff --cached --quiet` 返回 0，即暂存区是空的，合并提交里不会夹带规划改动。主仓库目录里没提交的规划改动不影响合并，因为实现分支不碰规划文件。
2. `git merge --no-ff --no-commit t/<票>-<slug>`
3. `uv sync --frozen`；有前端以后，再在 `src/web/` 里跑 `pnpm install --frozen-lockfile`。钩子要在主仓库目录里跑 `make check`，需要一个和合并后锁文件一致的环境。
4. `git commit -m "合并：<票名>"`。`git merge` 自己只触发 `pre-merge-commit` 钩子，不触发 `pre-commit`；先 `--no-commit`、再 `git commit`，`make check` 才会在合并结果上跑。
5. Status 改成 `done`，记进 Comments。
6. 收尾：

   ```bash
   git worktree remove <工作目录>
   git branch -d t/<票>-<slug>
   git for-each-ref --format='%(refname)' refs/rdp/<票>/ | xargs -r -n1 git update-ref -d
   ```

**完成**：main 上有 `合并：<票名>`；工作目录、分支和快照都已删除；Status 是 `done`。

## 4. codex 命令

```bash
# 新会话：派工 A
cd <工作目录>
timeout 90m codex exec -C <工作目录> -s workspace-write \
  -c 'sandbox_workspace_write.network_access=true' \
  -m gpt-6-astra -c 'model_reasoning_effort="high"' \
  --json -o <assets>/out-A.md \
  - < <assets>/prompt-A.md \
  > <临时目录>/ev-A.jsonl 2> <临时目录>/err-A.txt

# 续接同一会话：派工 B、修复轮
cd <工作目录>
timeout 90m codex exec resume \
  -m gpt-6-astra -c 'model_reasoning_effort="high"' \
  -c 'sandbox_mode="workspace-write"' \
  -c 'sandbox_workspace_write.network_access=true' \
  --json -o <assets>/out-B.md \
  <会话编号> - < <assets>/prompt-B.md \
  > <临时目录>/ev-B.jsonl 2> <临时目录>/err-B.txt
```

- **模型**：每条 `codex exec` 和 `codex exec resume` 都显式带上 `-m gpt-6-astra -c 'model_reasoning_effort="high"'`，不依赖 `~/.codex/config.toml` 的默认值。2026-10-22 查过 codex-cli 0.163.0 的 `codex exec resume --help`：续接也有 `-m`。以后的版本要是没有，改用 `-c 'model="gpt-6-astra"'`。
- **续接**：`codex exec resume` 没有 `-C` 和 `-s`。续接的会话在执行命令时所在的目录里工作，不在当初 `-C` 指定的目录里（0009）。所以先 `cd` 进工作目录，再用 `-c 'sandbox_mode="…"'` 写明沙箱模式。
- **提示用文件传**：派工提示写进 assets 里的文件，用 `- < prompt.md` 从标准输入传给 Codex，便于存档。
- **会话编号**：运行日志第一条事件 `thread.started` 里的 `thread_id`，即 `grep -o '"thread_id":"[^"]*"' ev-A.jsonl | head -1 | cut -d'"' -f4`。一张实现票只用一个会话；只有 6.3 的升级选了 (b)，才开新会话。
- **跑完的标志**：运行日志最后一条是 `turn.completed`，`-o` 文件存在。
- **后台运行**：用 Bash 的后台方式运行，Codex 退出时会收到通知，不用轮询输出文件。
- **超时**：90 分钟（`timeout 90m`，退出码 124 表示超时）。M0 第 5 张派工 B 在 60 分钟时被中止，当时只差最后一次 `make check`；2026-10-25 起调到 90 分钟，免得白白多算一轮。
- **沙箱**：实现票用 `workspace-write`，并打开 `sandbox_workspace_write.network_access=true`（0012，负责人 2026-10-23 授权）。不打开时沙箱禁止 socket 的发送调用，FastAPI 的测试会一直挂住。代价是 Codex 的命令能上网，所以 3.5 第 5 项要查安装和联网命令。非代码任务不打开，见第 8 节。

## 5. 提交与快照

### 5.1 提交

所有提交都由 Claude 做，都经过钩子 `.githooks/pre-commit`，不加 `--no-verify`，也不用 `-c core.hooksPath=…` 之类的办法绕开钩子。

- 钩子先看暂存了哪些文件：只动了规划文件（`.scratch/`、`docs/`、`GLOSSARY.md`、`AGENTS.md`、`CLAUDE.md`）时，打印一行"仅暂存规划文件，跳过 make check。"后放行；动了其他文件，就跑全量 `make check`（M0 第 1 张工单 D2）。所以主会话提交规划文件不需要 `.venv`。
- `core.hooksPath` 设在共用的 `.git/config` 里，值是相对路径 `.githooks`。没有 `.githooks/` 的分支（例如 `prototype/*`）提交时不跑钩子，这是预期的。

| 时间点 | 提交说明开头 | 内容 | 谁、在哪 |
|---|---|---|---|
| 骨架获批 | `契约：<票名>` | 签名、类型、docstring、跳过的测试清单 | 执行线，工作目录 |
| 新增依赖获批 | `依赖：<包名>（<票名>）` | `pyproject.toml`、锁文件等 | 执行线，工作目录 |
| 评审通过 | `实现：<票名>` | 实现和测试 | 执行线，工作目录 |
| 负责人说"合并" | `合并：<票名>` | `--no-ff` 的合并提交 | 主会话，主仓库目录（3.7） |

- **钩子查的是工作目录里的文件，不是暂存区。** 在工作目录里提交时，把评审过的改动全部一起提交（`git add -A`），不做部分提交。主会话在主仓库目录里提交规划文件时，只 `git add` 要提交的那几个路径。
- **打回期间不提交**：中间状态过不了钩子，改用快照（5.2）记录每一轮。
- **派工 A、B 之前，工作目录必须干净**（`git status --porcelain` 为空），这样派工之后出现的改动全是 Codex 的。修复轮之前，工作目录里是上一轮的改动，靠快照区分这一轮改了什么。
- **规划文件只在主仓库目录里改**：工单、Comments、assets 都在主仓库目录。实现分支上只有代码和依赖文件，合并时不会冲突。
- **新的包管理目录**：第一次引入一种包管理器（例如 M0 第 2 张的 pnpm）时，先确认 `.gitignore` 已经忽略它的安装目录（`node_modules/`），再做依赖提交，否则安装目录会进提交。
- **派工 B 途中要装新依赖**：先拍一个快照，用 `git stash -u` 收起 Codex 的改动；在干净的工作目录里装依赖、做依赖提交（这时是契约提交加上新依赖，钩子能过）；再 `git stash pop`。
- **整轮方向都错、要丢弃工作区的改动时**，先问负责人，不自行回退。

### 5.2 快照和探针工作目录

快照用一个临时索引，把工作目录拍成一个提交对象，挂在 `refs/rdp/` 下。它不动工作目录的真实索引，不产生分支提交，也不触发钩子。

```bash
# 在工作目录里执行。用法：snap <票> <快照名>，例如 snap m0-01 B-done
snap() {
  local tmp tree
  tmp=$(mktemp -d)
  GIT_INDEX_FILE="$tmp/index" git read-tree HEAD
  GIT_INDEX_FILE="$tmp/index" git add -A
  tree=$(GIT_INDEX_FILE="$tmp/index" git write-tree)
  git update-ref "refs/rdp/$1/$2" "$(git commit-tree "$tree" -p HEAD -m "快照：$1 $2")"
  rm -rf "$tmp"
}
```

- 这一轮改了什么：`git diff --stat refs/rdp/<票>/<名> refs/rdp/<票>/<名>-done`，去掉 `--stat` 看全文。
- **探针工作目录**是检出某个快照的临时工作目录，用来跑 `/code-review`、试违规。里面的改动只用于试验，用完即删，不进任何分支。

  ```bash
  git -C <主仓库目录> worktree add --detach <临时目录>/probe-<票> refs/rdp/<票>/<名>-done
  cd <临时目录>/probe-<票> && uv sync --frozen     # 要跑 make check 时才需要
  # ……试验……
  git -C <主仓库目录> worktree remove --force <临时目录>/probe-<票>
  ```

## 6. 关卡与升级

### 6.1 骨架关卡的一页摘要

按这五块写：

1. 这张票做什么，一句话。
2. 函数清单表：模块、函数、职责（一句话）、会改动什么、什么情况下报错。
3. 测试清单：每个契约行为对应的测试名。测试在骨架阶段就交，测试体先跳过（`pytest.skip`），所以骨架阶段的 `make check` 也能全绿。
4. 需要负责人拍板的问题，最多 3 条，每条附 Claude 的建议。
5. Claude 的结论：建议通过，或者建议改。

### 6.2 契约变更

- Codex 不能自己改已获批的契约。实现时发现要改，就停下来，在最终回复里写"契约变更申请"：哪个函数、改什么、为什么。
- **改变含义的**，回到负责人那里重新过骨架关卡。"改变含义"指参数、返回值、报错条件、副作用、时间语义有变化。
- **只是措辞、笔误、补充说明的**，由 Claude 批准，记进 Comments，汇报时告诉负责人。

### 6.3 打回与升级

- 每次把修复清单发回给 Codex 算一轮，包括 Claude 重跑 `make check` 没过的情况；运行超时也算一轮。
- 模型网关断开后的那一次重试（第 9 节）不算一轮：它没有发修复清单。
- 第 3 轮仍不通过，就停下来，把问题清单和判断交给主会话，由负责人在三种处理里选一种：
  - (a) 再给两轮；
  - (b) Claude 改写契约或者把票拆小，开一个新的 Codex 会话重做（默认建议）；
  - (c) 这张票退回规划。

### 6.4 状态流转

- 实现票派工前，Status 用五个 triage 角色（`docs/agents/triage-labels.md`），其中只有 `ready-for-agent` 能进入派工。
- 派工后的主线是 `in-progress → in-review → done`；打回时走 `in-review → changes-requested → in-progress`。
- 等负责人过骨架、或者等负责人说"合并"时，Status 停在 `in-review`。
- 走图的决策票照旧用 `open / claimed / resolved`，和实现票的状态不混用。

## 7. 派工提示模板

三个模板共用下面这段"边界"，原样贴进每份提示：

```markdown
边界：
- 只改 `src/`、`tests/`。本票允许改的受保护文件：<清单；没有写"无">。
- 改动留在工作区，不要 `git add`，也不要提交。
- 不读取 `~/桌面/data_check` 和 `~/桌面/Data_Collection_System-main`，不碰 `/mnt`。
- 不安装任何东西，不访问网络（沙箱为了跑测试开了网络权限，但这张票用不到网络；评审会查运行日志，出现安装或联网的命令整轮打回）。需要新依赖时停下，在最终回复里写依赖申请（AGENTS.md 规则 7）。
- 自己在 `/tmp` 或别处建的试验文件，交付前删掉。
```

**派工 A**（新会话）：

```markdown
你在工单「<票名>」的工作目录 <工作目录>（git worktree，分支 t/<票>-<slug>）里写契约骨架。

先读下面这些。规划文件一律读主仓库目录 <主仓库目录> 里的版本：工作目录里的副本停在开分支的那一刻，可能已经过期，也可能缺少还没提交的文件。
- <主仓库目录>/AGENTS.md
- <主仓库目录>/docs/standards/CODING_STANDARDS.md
- 工单 <主仓库目录>/.scratch/<里程碑目录>/issues/<NN>-<slug>.md，以及它引用的 spec、ADR，和 <主仓库目录>/GLOSSARY.md 里的术语

用 $enterprise-coding。这一步只交契约骨架：
1. 签名、类型和六项 docstring 写全（AGENTS.md 规则 4，CODING_STANDARDS 第 3 条）。函数体只写 `raise NotImplementedError`。
2. 测试清单写成跳过的测试（`pytest.skip`），每个测试的 docstring 写明它验证哪条契约行为。
3. `make check` 跑到全绿。

<边界>

最终回复分四块：
1. 改动清单：每个文件一行，写做了什么。
2. `make check`：最后一次运行的命令和末尾输出，原样贴出。
3. 契约变更申请、依赖申请：没有就写"无"。
4. 拿不准、需要评审决定的地方。
```

**派工 B**（续接）：

```markdown
骨架已获批，契约提交是 <提交号>。现在按测试清单逐个函数实现，用 $tdd 和 $enterprise-coding：
1. 每次去掉一个测试的跳过，先单独运行它（`.venv/bin/pytest <文件>::<测试名>`），看到它失败，再写实现让它通过。去掉跳过就直接通过的测试，在最终回复里逐个列出并说明原因（例如前一个测试的实现已经覆盖了它）。
2. 已获批的签名、类型和 docstring 不改。确实要改时停下，在最终回复里写契约变更申请：哪个函数、改什么、为什么。
3. 最后 `make check` 全绿，测试里不留骨架阶段的跳过。

<边界>

最终回复：同派工 A 的四块，另加第 5 块"先红后绿"：每个测试一行，写它第一次运行的结果（失败的原因，或者为什么一开始就通过）。
```

**修复轮**（续接）：

```markdown
评审发现下面的问题，逐条修复，别处不动：
1. 问题：……；位置：<文件:行>；期望：……
2. ……

修完后 `make check` 全绿。

<边界>

最终回复：逐条写处理结果；`make check` 最后一次运行的命令和末尾输出，原样贴出。
```

## 8. 非代码任务

走图时 AFK 执行的盘点、采集、调研，也派给 Codex（`CLAUDE.md`「走图时的 AFK 执行」）。

| 任务 | 沙箱 | 工作目录 |
|---|---|---|
| 只读取证 | `-s read-only` | 临时目录 |
| 要写脚本或中间文件 | `-s workspace-write` | 临时目录下单独一个子目录。写不到仓库，也写不到 `/mnt` |
| 联网调研 | `-s read-only -c 'web_search="live"'` | 临时目录 |

- **临时目录不是 git 仓库**：命令要加 `--skip-git-repo-check`，否则报 "Not inside a trusted directory"。提示照样用 `- < prompt.md` 从文件传；要是把提示写在命令行参数里，标准输入就接 `< /dev/null`，否则会停在 "Reading additional input from stdin"（标准输入不是终端时，codex 会把它读进来，追加在提示后面，见 `codex exec --help`）。
- 模型参数、提示存档、会话编号、超时同第 4 节。
- **派工提示**写这几项：目标；只读范围；要交付什么（事实清单，每条附命令或来源网址）；禁止碰的路径（两个旧项目）。例子见 `.scratch/platform-v1/assets/11-dataset-contract/codex-facts-prompt.md`。
- **证据**以运行日志（`--json`）里记录的命令和输出为准，不以 Codex 自己的总结为准。用到的命令和输出，由 Claude 整理进 assets。
- **联网调研**：每条事实都要附来源网址。要下载的东西（例如克隆一个仓库来读代码），Codex 做不了，由 Claude 先下到临时目录，再让 Codex 读。
- **复核**：
  - 写进 `docs/` 的每条事实，都要能追到 assets 里的原始输出。
  - 结论性的事实（计数、大小、有没有、版本号），由 Claude 重跑，或者亲自打开来源核对；其余抽查。
  - 抽查发现一处对不上，整份打回重做。
  - 另外查一遍运行日志里的命令，确认没有碰两个旧项目的路径。

## 9. 故障与已知现象

- **模型网关断开**：运行日志或 stderr 里出现 "stream disconnected" 或 "error sending request"。
  1. 只重试一次。有会话编号就续接同一个会话，提示写"上一次运行因模型网关断开而中止，从中断处继续原来的任务"；还没有会话编号就原样重跑。
  2. 还不行，就停下来报告，不再重试，也不自己改代理设置。报告写三样：报错原文；代理相关的环境变量（`env | grep -i _proxy`）；直连和经代理访问网关各自通不通，返回任何 HTTP 状态码都算通：

     ```bash
     curl -sS -m 5 --noproxy '*' -o /dev/null -w '%{http_code}\n' <base_url>
     curl -sS -m 5 -x http://127.0.0.1:7897 -o /dev/null -w '%{http_code}\n' <base_url>
     ```

     网关地址以 `~/.codex/config.toml` 的 `base_url` 为准：2026-10-23 是 `10.1.179.3:8088`，2026-10-24 改成了本机 `127.0.0.1:15721/v1`。
  3. 2026-10-22 实测过一次：经过代理 127.0.0.1:7897 访问网关 192.168.0.180:8088 会超时，直连是通的；后来负责人修好了。
- **Claude 的使用额度用完**（HTTP 429）：执行线会中途停下，处理办法见第 1 节"执行线要能承受中断"。
- **Codex 说"已创建"，文件却不在工作目录里**：续接前没有先 `cd` 进工作目录，文件写进了执行命令时所在的目录（0009）。3.5 第 2 项的主仓库目录检查能抓到。
- **`.git/info/exclude` 是所有工作目录共用的**（`git rev-parse --git-path info/exclude` 指向主仓库的 `.git/`）。只想在某个工作目录里忽略的东西，不要写进去，否则会影响以后所有的票。2026-10-22 提交原型时写错过一次，已经删掉。
- **工作目录里 Codex 连 `git add` 都做不了**（`index.lock': Read-only file system`）：工作目录的索引在主仓库的 `.git/worktrees/` 下，沙箱里只读（0009）。改动只能留在工作区，这是预期的。
- **运行日志开头有一两条 `error` 事件**，说 `disable_response_storage` is ignored：这是本机 `~/.codex/config.toml` 里的旧字段，不影响运行，不算失败。
- **沙箱能读整个文件系统**，包括 `/mnt` 和两个旧项目（0009）。"不读旧项目"只能靠派工提示，加上 3.5 第 5 项的日志检查。
- **`workspace-write` 不开网络时 socket 发不出数据**：`send` 报 `Operation not permitted`，asyncio 的线程唤醒随之挂住，`TestClient` 卡死。实现票派工因此打开 `network_access`（第 4 节，0012）。不要在测试里换别的系统调用绕开，Codex 会拒绝，这样做也确实是在绕过安全控制。
- **只读沙箱里命令行不能联网**（`curl` 报 `failed to open socket: Operation not permitted`），但联网搜索可用（0009）。
