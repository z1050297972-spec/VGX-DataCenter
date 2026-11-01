**未完成实现；已按“需要修改已批准契约时停止”的要求停下。** 当前只完成了部分评审决定对应的契约调整，下载执行、worker 装配和 TDD 尚未开始。

## 1. 改动清单

- `src/rdp/jobs/downloads/job.py`：加入限速上限、重定向跳数和复探间隔常量；调整相关契约说明；删除自适应 429 降并发函数。
- `src/rdp/infra/db/migrations/versions/v0013_download_adjustments.py`：为两个限速列的 CHECK 加入 10 GiB/s 上限。
- `src/rdp/jobs/models.py`：同步 ORM 的限速 CHECK 和字段说明。
- `tests/test_download_job_contract.py`：移除原位置的测试文件。
- `tests/jobs/downloads/test_job.py`：迁入测试清单，删除自适应 429 测试；其余测试仍为跳过状态。

改动均留在工作区，未暂存、未提交。

## 2. `make check`

最后一次运行的命令：

```bash
make check > /tmp/m2-downloads-review-check.log 2>&1; status=$?; tail -25 /tmp/m2-downloads-review-check.log; exit "$status"
```

末尾输出原文：

```text
SKIPPED [1] tests/jobs/downloads/test_job.py:163: 契约骨架待实现
=========== 2665 passed, 32 skipped, 8 warnings in 107.92s (0:01:47) ===========
[7/11] OpenAPI 过期检查
✨ openapi-typescript 7.13.0
🚀 /tmp/tmp.vYdlAdLjR3/openapi.json → /tmp/tmp.vYdlAdLjR3/schema.d.ts [123.3ms]
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
   Start at  20:29:37
   Duration  12.40s (tests 57%, import 22%, environment 21%, transform 1%)

```

退出码为 0，但 **32 项下载测试仍被跳过**，不满足本票完成条件。临时检查日志已删除。

## 3. 契约变更申请、依赖申请

**契约变更申请：需要明确 CDN 跳转请求使用的传输边界。**

已批准的第 01 张契约在 `src/rdp/jobs/downloads/plan.py:194-216` 指定 `HttpTransport` **仅连接镜像**；`UrllibTransport.request` 在第 252–256 行实际拒绝非 `hf-mirror.com` 的主机。本次决定则要求从镜像 `resolve` 地址逐跳请求，允许跳往镜像的 CDN，直到获得 200/206。

因此，使用第 01 张的公开传输逐跳访问 CDN，会违反它已批准的对外行为。建议选择其一：

1. **推荐：保持第 01 张不变**，首跳继续使用其传输；另批准下载 worker 的可注入 CDN 单跳传输，用于已经通过 `validate_download_redirect` 的后续 HTTPS 地址，不携带 token、不跟随跳转。
2. 批准扩展第 01 张 `HttpTransport` / `UrllibTransport` 的契约，使其允许经校验的 CDN 地址。

我没有擅自选择或实现这两种变更。

**依赖申请：无。**

## 4. 拿不准、需要评审决定的地方

- 请确认上述 CDN 后续跳转的传输方案。确认前，逐跳预解析、对应替身测试和本机集成测试均无法按当前两个契约同时实现。
- 工作区的契约调整仍不完整：例如下载执行器、调参持久化、续跑检查点、并发上限校验和真实 worker 装配均未实现；现有测试清单除删除 429 项外仍是骨架。
- 本次未访问外网、未安装依赖，也未修改第 01 张的已批准契约。

## 5. 先红后绿

**尚无。** 因发现上述已批准契约冲突而停止，尚未去掉任何测试的跳过，也未进行单测的首次红灯运行。