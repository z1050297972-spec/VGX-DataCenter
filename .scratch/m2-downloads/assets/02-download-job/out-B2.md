## 1. 改动清单

**本票尚未完成。** 执行中发现首跳响应读取要求与第 01 张已批准的公开行为冲突，已按派工 B 的停止条件停下，等待第 3 块的决定。当前是未完成的工作区改动，**不要将下载作业用于生产**。

- `src/rdp/jobs/downloads/job.py`：补充后续单跳传输契约、限速和跳转常量；实现部分参数转换、重定向校验、缓存读取和作业编排。
- `src/rdp/jobs/downloads/adapters.py`：新增文件散列、后续 HTTPS 单跳传输及 aria2 配置绑定的部分适配器。
- `src/rdp/jobs/downloads/adjustments.py`：新增 SQLite 调参通道的部分实现，包括版本化请求和确认。
- `src/rdp/jobs/downloads/plan.py`：为共用的内部隔离请求函数增加仅取首字节选项；第 01 张公开传输的默认调用行为未改。
- `src/rdp/jobs/downloads/_http_child.py`：支持内部隔离请求按需只读取首字节。
- `src/rdp/jobs/scheduling.py`：拒绝将下载类型并发覆盖配置为大于 1。
- `src/rdp/jobs/models.py`：为调参表限速 CHECK 增加 10 GiB/s 上限。
- `src/rdp/infra/db/migrations/versions/v0013_download_adjustments.py`：同步迁移中的限速 CHECK。
- `tests/test_download_job_contract.py`：移除原位置的测试清单。
- `tests/jobs/downloads/test_job.py`：迁入测试清单，删除自适应 429 测试，并逐项实现了部分测试。

改动未暂存、未提交；手工创建的临时检查日志已删除。

## 2. `make check`

最后一次运行：

```bash
make check > /tmp/m2-final-check.log 2>&1; status=$?; tail -25 /tmp/m2-final-check.log; exit "$status"
```

末尾输出原文：

```text
SKIPPED [1] tests/jobs/downloads/test_job.py:601: 契约骨架：本机集成测试待实现
=========== 2686 passed, 15 skipped, 8 warnings in 91.91s (0:01:31) ============
[7/11] OpenAPI 过期检查
✨ openapi-typescript 7.13.0
🚀 /tmp/tmp.YTXeEMPzjB/openapi.json → /tmp/tmp.YTXeEMPzjB/schema.d.ts [117.1ms]
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
   Start at  21:20:01
   Duration  10.64s (tests 56%, import 22%, environment 20%, transform 1%)

```

命令退出码为 0，但 **15 项下载测试仍跳过，包括本机 aria2 集成测试**，不满足交付验收。

## 3. 契约变更申请、依赖申请

**契约变更申请：请决定首跳遇到忽略 Range 的 `200` 响应时，允许改变哪一项要求。**

第 01 张的 `UrllibTransport.request` 在 `plan.py:258` 调用原有内部请求，默认会读取响应体直到 EOF 或达到响应体上限。若镜像忽略 `Range: bytes=0-0` 并以 `200` 返回大文件，它会继续读取，而不是只取 1 字节；超过上限时会失败。

这与同时要求“首跳仍走第 01 张传输”“`200` 是终点”“只取 1 字节”及“不改变第 01 张公开行为”冲突。建议二选一：

1. **推荐：批准下载作业首跳使用新的受控 Range 单跳传输**。它只允许镜像主机、仅首跳携带 token，并复用现有子进程隔离；第 01 张公开传输保持不变。
2. 批准第 01 张传输对 `GET` + `Range: bytes=0-0` 的响应行为增加特例：即使服务端返回 `200`，也只读取首字节。

后续 CDN 单跳的首字节读取机制已部分实现；上述选择尚未擅自决定。

**依赖申请：无。**

## 4. 拿不准、需要评审决定的地方

- 当前 `_DownloadRun` 是未完成的 TDD 中间实现，尚未满足安全路径处理、周期复探、续跑检查点、完整失败重试和生产装配要求；已有的测试通过不能证明这些行为安全。
- `Aria2Supervisor` 目前只保存配置，还没有真实进程/RPC 实现；curl 适配器和 worker 入口装配也未完成。
- 本机 aria2c + `127.0.0.1` HTTP 集成测试尚未实现；余下骨架测试不能作为验收证据。
- 未访问外网、未安装依赖，未提交改动。

## 5. 先红后绿

以下为本轮**首次单独运行**的结果；“直接通过”均不是红灯：

- `test_parameter_bounds`：直接通过；参数模型及本轮批准的边界已存在。
- `test_no_token`：直接通过；骨架模型已有 `extra="forbid"`。
- `test_type_concurrency_override_cannot_exceed_one`：失败，未抛 `InputError`；实现校验后通过。
- `test_validate_download_redirect_rejects_official_and_unsafe`：`NotImplementedError`；实现后通过。
- `test_request_from_parameters_preserves_download_selection`：`NotImplementedError`；实现后通过。
- `test_cache_invalidation`：`NotImplementedError`；实现后通过。
- `test_lfs_verify`：适配器模块不存在；实现后通过。
- `test_blob_verify`：直接通过；上一项已实现同一散列适配器。
- `test_followup_transport_rejects_non_https_and_userinfo`：适配器类不存在；实现后通过。
- `test_redirect_token`：预解析函数不存在；实现后通过。
- `test_retry_bound`：直接通过；上一项已实现跳转次数限制。
- `test_adjustment_race`：首次因测试夹具导入名错误失败；修正夹具后因通道类不存在失败，实现后通过。
- `test_adjustment_channel_initializes_once_without_overwriting`：缺少初始化方法；实现后通过。
- `test_isolated_fakes`：`NotImplementedError`；加入部分编排后通过。
- `test_outcome_success`：累计字节和条目数错误；修正后通过。
- `test_outcome_skipped`：已完成文件仍被加入 aria2；加入跳过分支后通过。
- `test_outcome_partial`：文件失败被当成 `DefectError`；加入部分失败处理后通过。
- `test_outcome_failure`：直接通过；上一项已实现相同失败计数路径。
- `test_aria2_executable_comes_from_config`：适配器类不存在；加入配置绑定后通过，**尚未验证真实进程启动**。
- `test_mirror_308`：执行器为 `NotImplementedError`；接入计划调用后通过。
- `test_aria_redirect`：不安全跳转的 `InputError` 未转为文件失败；加入处理后通过。