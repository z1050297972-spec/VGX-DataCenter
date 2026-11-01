## 1. 改动清单

改动留在工作区，未 `git add`、未提交；未安装依赖或访问外网。

- `src/rdp/jobs/downloads/job.py`：实现下载编排、受控跳转、周期复探、调参应用、续跑跳过及模型目标处理。
- `src/rdp/jobs/downloads/adapters.py`：实现 aria2 进程与 JSON-RPC、curl 兜底、Range 单跳传输和文件散列适配器。
- `src/rdp/jobs/downloads/adjustments.py`：实现下载调参的版本化数据库通道。
- `src/rdp/jobs/downloads/_context.py`：为下载适配器绑定当前作业的取消、复探和调参上下文。
- `src/rdp/jobs/downloads/plan.py`：扩展内部隔离请求能力，保留第 01 张公开传输的默认签名和行为。
- `src/rdp/jobs/downloads/_http_child.py`：支持受控 Range 请求在服务端返回 `200` 时只读取首字节。
- `src/rdp/jobs/processes.py`：增加可由 RPC 驱动的受管长进程和秘密标准输入支持，复用 M0 进程组清理。
- `src/rdp/jobs/scheduling.py`：拒绝将下载作业的并发覆盖设为大于 1。
- `src/rdp/jobs/models.py`：同步调参表限速上限。
- `src/rdp/infra/db/migrations/versions/v0013_download_adjustments.py`：为调参表限速 CHECK 加入 10 GiB/s 上限。
- `src/rdp/ops/runtime.py`：仅在 worker 装配下载计划、传输、进程、校验和调参依赖。
- `tests/test_download_job_contract.py`：移除原位置的测试清单。
- `tests/jobs/downloads/test_job.py`：迁入测试，完成收窄后的关键测试，删除清单外仍跳过的骨架测试。
- `tests/test_ops_runtime.py`：验证 worker 装配下载依赖、Web 不获得执行能力。

## 2. `make check`

最后一次运行的命令：

```bash
make check > /tmp/m2-downloads-final-check.log 2>&1; status=$?; tail -35 /tmp/m2-downloads-final-check.log; exit "$status"
```

末尾输出原文：

```text
.venv/lib/python3.12/site-packages/fastapi/testclient.py:1
.venv/lib/python3.12/site-packages/fastapi/testclient.py:1
.venv/lib/python3.12/site-packages/fastapi/testclient.py:1
.venv/lib/python3.12/site-packages/fastapi/testclient.py:1
.venv/lib/python3.12/site-packages/fastapi/testclient.py:1
.venv/lib/python3.12/site-packages/fastapi/testclient.py:1
.venv/lib/python3.12/site-packages/fastapi/testclient.py:1
  /home/shawn/桌面/robot-data-platform.wt/m2-downloads/.venv/lib/python3.12/site-packages/fastapi/testclient.py:1: StarletteDeprecationWarning: Using `httpx` with `starlette.testclient` is deprecated; install `httpx2` instead.
    from starlette.testclient import TestClient as TestClient  # noqa

-- Docs: https://docs.pytest.org/en/stable/how-to/capture-warnings.html
================= 2703 passed, 8 warnings in 95.41s (0:01:35) ==================
[7/11] OpenAPI 过期检查
✨ openapi-typescript 7.13.0
🚀 /tmp/tmp.Z1Hs3dQyUv/openapi.json → /tmp/tmp.Z1Hs3dQyUv/schema.d.ts [119.2ms]
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


 Test Files  39 passed (39)
      Tests  370 passed (370)
   Start at  00:57:12
   Duration  10.28s (tests 56%, import 22%, environment 20%, transform 1%)

```

最终退出码为 0。第一次完整检查因类型标注失败、第二次因私有构造函数缺少职责说明失败，修正后重跑；之后又修正了失败进度回退问题并重新运行了上面的最终检查。并未并发运行多份检查。

## 3. 契约变更申请、依赖申请

- 契约变更申请：无；首跳受控 Range 传输按本轮批准方案实现。
- 依赖申请：无。

## 4. 拿不准、需要评审决定的地方

- **已批准的重定向残余风险仍在**：预解析和 aria2 实际请求之间有时间窗。每 60 秒复探可以缩短风险窗口，但不能证明窗口内 aria2 绝不会收到并跟随新的重定向。
- 按本轮收窄范围，续跑通过已有文件的大小和哈希判断是否跳过，**没有接入逐文件计数检查点或校验清单写入**。因此重提大文件可能需要重新计算哈希。
- 按收窄范围，文件校验最终失败时记录失败条目；原较宽方案中“删除后再重下一次”的独立流程未实现。
- 多文件并发时，当前显示的进行中字节和速度来自正在轮询的文件，并非所有活动文件的实时合计。
- 目录分量通过 `O_NOFOLLOW` 检查，但外部工具最终仍按路径打开文件；安全性依赖平台区只有 worker 写入这一运行假设。若不可信进程也能并发替换目录，仍有检查与打开之间的竞态。
- 本机集成测试实际启动了 aria2c 和仅监听 `127.0.0.1` 的服务器；遵守本票禁网要求，**没有对真实镜像或 gated 仓库做联网演练**。

## 5. 先红后绿

本轮新去掉跳过的测试：

- `test_secret_redaction`：首次直接通过；参数拒绝秘密字段及所需适配器行为已在前一轮实现。本轮随后补充了 aria2 启动 argv 的替身断言，仍通过。
- `test_cancel_resume[cancel]`：首次直接通过；前一轮的文件校验跳过和清理路径已覆盖该场景。
- `test_cancel_resume[crash]`：首次直接通过；随后补充 `RESUME` 模式和上次进度，仍通过。原 `test_crash_resume` 已合并进此参数化测试。
- `test_model_rename`：首次失败，模型目标目录尚未产生；实现同文件系统原子不覆盖改名后通过。原 `test_no_overwrite` 已合并进此测试。