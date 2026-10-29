**1. 本轮改动清单**

- `src/rdp/ops/setup_queries.py`：保留重复挂载点的全部记录，统一标记 `stacked_mount`；仍先完整校验每行。
- `scripts/setup.sh`：展示“叠加挂载，无法确认哪一层可见”。
- `tests/fixtures/storage/findmnt-real-2026-10-28.json`：原样复制真实快照，已核对逐字节一致。
- `tests/test_ops_setup_queries.py`：验证真实快照、三个 ext4 根、叠加层及非法输入。
- `tests/test_ops_setup_script.py`：验证问答成功生成配置，以及两个叠加层均不可选。

未暂存、未提交；临时检查日志已删除。

**2. `make check`**

最后一次退出码 0：**pytest 2095 passed / 0 skipped；Vitest 250 passed / 0 skipped**。

首次全量检查被静态审计拒绝：新增断言包含真实路径字面量。已改为从 fixture 读取路径文字，保留独立 UUID 预期，未放宽审计规则；随后重跑全绿。

```bash
make check > /tmp/rdp-setup-review3-check.log 2>&1
```

末尾输出原样：

```text
================= 2095 passed, 1 warning in 313.08s (0:05:13) ==================
[7/11] OpenAPI 过期检查
✨ openapi-typescript 7.13.0
🚀 /tmp/tmp.DIuojud8vx/openapi.json → /tmp/tmp.DIuojud8vx/schema.d.ts [71.1ms]
OpenAPI 与生成类型均未过期
[8/11] tsc
src/web/node_modules/.bin/tsc --project src/web/tsconfig.json --noEmit
[9/11] ESLint
cd src/web && node_modules/.bin/eslint . --max-warnings 0
[10/11] Prettier
cd src/web && node_modules/.bin/prettier --check .
Checking formatting...
All matched files use Prettier code style!
[11/11] Vitest
cd src/web && node_modules/.bin/vitest run

 RUN  v5.0.5 /home/shawn/桌面/robot-data-platform.wt/m0-11-ops-entry-systemd/src/web


 Test Files  22 passed (22)
      Tests  250 passed (250)
   Start at  23:06:07
   Duration  7.35s (tests 50%, environment 30%, import 20%)
```

最后一次运行前 `git status --porcelain --untracked-files=all`：

```text
 M scripts/setup.sh
 M src/rdp/ops/setup_queries.py
 M tests/test_ops_setup_queries.py
 M tests/test_ops_setup_script.py
?? tests/fixtures/storage/findmnt-real-2026-10-28.json
```

运行后：

```text
 M scripts/setup.sh
 M src/rdp/ops/setup_queries.py
 M tests/test_ops_setup_queries.py
 M tests/test_ops_setup_script.py
?? tests/fixtures/storage/findmnt-real-2026-10-28.json
```

**3. 契约变更、依赖申请**

已执行本轮预批的契约变更；无额外申请，无新增依赖。

原句：

> 按挂载点文字排序的不可变元组，允许空；每个挂载点唯一，重复记录拒绝而不猜叠层关系。

新句：

> 按挂载点文字排序的不可变元组，允许空；重复挂载点的所有记录均保留并标为stacked_mount，不猜测哪一层可见，同一挂载点内保持快照顺序。

另补充了“未叠加时”才可选择合法来源，以及字段说明“同一挂载点重复出现时为stacked_mount，所有层均不可选”。测试说明同步移除重复挂载必失败的旧表述。

**4. 拿不准的地方**

无待决事项。仅解析快照元数据，没有访问快照中的挂载路径，也没有调用真实 `findmnt`、`systemctl` 或 `loginctl`。

**5. 本轮先红后绿**

- `test_real_mount_snapshot_preserves_stacked_rows`：红，真实快照触发“挂载点不得重复”；修复后通过。
- `test_questionnaire_continues_with_stacked_mounts`：红，缺少要求的中文原因；补齐展示后通过。
- `test_stacked_valid_sources_are_all_unavailable`：初绿，通用计数逻辑已覆盖合法 ext4/NFS 的叠加情况。
- `test_stacked_rows_still_require_valid_fields[missing-field]`：初绿，保留了逐行完整性校验。
- `test_stacked_rows_still_require_valid_fields[contradictory-options]`：初绿，保留了 ro/rw 校验。
- `test_stacked_rows_still_require_valid_fields[wrong-type]`：初绿，保留了字段类型校验。
- `test_questionnaire_cannot_select_either_stacked_layer[1/2]`：两项初绿，既有选择逻辑已拒绝所有非空不可选原因。
- `test_no_real_mount_access_static`：全量检查时红，路径字面量被拒绝；调整测试断言后通过，审计规则未改。
- 既有非法快照及不可选来源测试：同步契约说明后回归通过。