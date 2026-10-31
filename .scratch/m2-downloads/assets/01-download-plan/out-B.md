## 1. 改动清单

**本次交付的是检查点，不是完整实现。** 预计剩余的 HTTP 总截止时间、分页、重试、容量预检及逐测试 TDD 超过本轮 80 分钟预算，因此停在 `make check` 全绿的位置。

- `src/rdp/jobs/downloads/plan.py`：按批准修改 HTTP 总时长、响应体上限和模型目标目录契约；实现 token 读取、文件筛选、暂存路径及模型权重路径。HTTP 传输、版本解析、清单、预览和计划编排等仍未实现。
- `tests/jobs/downloads/test_plan.py`：完成 6 条测试的单独首次运行和当前通过检查；新增总时长和响应体上限的跳过测试。**仍有 19 条测试跳过**，后续需逐条去跳过、先红后绿实现。

改动留在工作区，未暂存或提交。

## 2. `make check`

最后一次运行命令：

```bash
make check > /tmp/m2-download-check.log 2>&1
```

退出码为 0，末尾输出原样如下：

```text
SKIPPED [1] tests/jobs/downloads/test_plan.py:40: 等待下载计划实现
SKIPPED [1] tests/jobs/downloads/test_plan.py:45: 等待下载计划实现
SKIPPED [1] tests/jobs/downloads/test_plan.py:50: 等待下载计划实现
SKIPPED [1] tests/jobs/downloads/test_plan.py:55: 等待下载计划实现
SKIPPED [1] tests/jobs/downloads/test_plan.py:60: 等待下载计划实现
SKIPPED [1] tests/jobs/downloads/test_plan.py:65: 等待下载计划实现
SKIPPED [1] tests/jobs/downloads/test_plan.py:70: 等待下载计划实现
SKIPPED [1] tests/jobs/downloads/test_plan.py:129: 等待下载计划实现
SKIPPED [1] tests/jobs/downloads/test_plan.py:134: 等待下载计划实现
SKIPPED [1] tests/jobs/downloads/test_plan.py:164: 等待下载计划实现
SKIPPED [1] tests/jobs/downloads/test_plan.py:169: 等待下载计划实现
SKIPPED [1] tests/jobs/downloads/test_plan.py:174: 等待下载计划实现
SKIPPED [1] tests/jobs/downloads/test_plan.py:198: 等待下载计划实现
SKIPPED [1] tests/jobs/downloads/test_plan.py:228: 等待下载计划实现
SKIPPED [1] tests/jobs/downloads/test_plan.py:233: 等待下载计划实现
SKIPPED [1] tests/jobs/downloads/test_plan.py:238: 等待下载计划实现
=========== 2489 passed, 19 skipped, 8 warnings in 85.42s (0:01:25) ============
[7/11] OpenAPI 过期检查
✨ openapi-typescript 7.13.0
🚀 /tmp/tmp.sb0BDReTnc/openapi.json → /tmp/tmp.sb0BDReTnc/schema.d.ts [115.3ms]
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
   Start at  05:42:36
   Duration  14.42s (tests 50%, environment 27%, import 21%, transform 1%)
```

临时日志已删除。检查通过不代表被跳过的行为已验证。

## 3. 契约变更申请、依赖申请

无新增申请；本次契约修改仅涉及负责人已批准的内容。

## 4. 拿不准、需要评审决定的地方

- 当前安全路径段只接受 ASCII 字母、数字、`.`、`_`、`-`，并拒绝空段及 `.`、`..`。这同样用于用户填写的 `target_subdir`；如果权重目录需要中文或空格，需评审允许的字符范围。
- `HTTP_TOTAL_DEADLINE_S` 和 `HTTP_MAX_BODY_BYTES` **目前只有常量和契约，没有运行时保障**。后续实现需特别验证慢速分块响应的总截止时间、资源回收，以及超时和超限的重试行为。
- 数据集请求携带 `target_subdir` 时的拒绝仍依赖尚未实现的 `build_plan`；在线检查、容量预检及不跟随暂存软链接也尚未实现。不可把当前检查点用于下载计划生成。

## 5. 先红后绿

以下是已去掉跳过的测试及其**第一次单独运行**结果；后续完整检查中均通过：

- `test_model_weights_path`：失败，`model_weights_path` 当时抛出 `NotImplementedError`。
- `test_staging_path_reuses_commit`：失败，`staging_path` 当时抛出 `NotImplementedError`。
- `test_bad_repo_id_rejected`：**首次即通过**；此前的模型路径切片已实现了共用的安全段校验。
- `test_include_exclude_fnmatchcase`：失败，`filter_files` 当时抛出 `NotImplementedError`。
- `test_video_and_camera_filters`：失败，当时的筛选实现尚未排除视频路径。
- `test_token_file_missing_and_permission`：失败，`read_token` 当时抛出 `NotImplementedError`。

其余 19 条仍处于跳过状态，尚未进行首次单独运行。