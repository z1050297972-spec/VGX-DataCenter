## 1. 改动清单

- `src/rdp/jobs/downloads/__init__.py`：声明下载计划领域包的职责和边界。
- `src/rdp/jobs/downloads/plan.py`：定义请求、清单、预览、容量和计划类型，以及可注入 HTTP 传输、镜像探测、版本解析、筛选、路径和预检的契约；函数体均为 `raise NotImplementedError`。
- `tests/jobs/downloads/test_plan.py`：新增 23 条跳过的契约测试清单，覆盖工单验收项及路径安全等边界；尚未实现测试替身或断言。

新包位于现有 `rdp.jobs` 层，沿用现有 import-linter 依赖方向，未修改 `pyproject.toml`。改动留在工作区，未暂存或提交。

## 2. `make check`

最后一次运行命令：

```bash
make check > /tmp/m2-download-check.log 2>&1
```

退出码为 0；末尾输出原样如下：

```text
SKIPPED [1] tests/jobs/downloads/test_plan.py:93: 等待下载计划实现
SKIPPED [1] tests/jobs/downloads/test_plan.py:98: 等待下载计划实现
SKIPPED [1] tests/jobs/downloads/test_plan.py:103: 等待下载计划实现
SKIPPED [1] tests/jobs/downloads/test_plan.py:108: 等待下载计划实现
SKIPPED [1] tests/jobs/downloads/test_plan.py:113: 等待下载计划实现
SKIPPED [1] tests/jobs/downloads/test_plan.py:118: 等待下载计划实现
=========== 2483 passed, 23 skipped, 8 warnings in 75.31s (0:01:15) ============
[7/11] OpenAPI 过期检查
✨ openapi-typescript 7.13.0
🚀 /tmp/tmp.z43OfwCwo9/openapi.json → /tmp/tmp.z43OfwCwo9/schema.d.ts [100.4ms]
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

 RUN  v5.0.5 /home/shawn/桌面/robot-data-platform.wt/m2-downloads/src/web


 Test Files  34 passed (34)
      Tests  329 passed (329)
   Start at  03:06:26
   Duration  9.58s (tests 49%, environment 26%, import 22%, transform 2%, setup 1%)
```

23 条新增测试均按要求跳过；全绿不代表下载计划行为已经实现或验证。临时检查日志已删除。

## 3. 契约变更申请、依赖申请

无。

## 4. 拿不准、需要评审决定的地方

- **演练存储根登记**：`build_plan` 复用现有 `StorageAccessChecker`，没有为 `/tmp` 绕过挂载在线检查；如何登记演练根仍需负责人决定。
- **模型权重落点**：`model_weights_path` 按工单建议约定为 `<存储根>/权重/<命名空间>/<仓库>@<commit前12位>`，不进入导航层；最终落点仍需负责人确认。
- **容量余量**：骨架暂定预留 1 GiB（`SPACE_RESERVE_BYTES`）；这可能使空间较小的演练根无法通过预检，请评审其数值。
- **仓库编号和超时**：暂按恰好两个安全路径段表示 `repo_id`。标准库传输契约中的超时约束连接及每次阻塞读取，**不保证整个响应的总耗时有上限**；请评审是否需要额外的总截止时间。