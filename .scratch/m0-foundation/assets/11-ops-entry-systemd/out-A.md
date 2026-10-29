**1. 改动清单**

契约骨架已完成。新增 25 个 Python 函数/方法均只写 `raise NotImplementedError`；新增测试显式跳过，`0006` 未激活。改动留在工作区，未暂存、未提交；本轮临时文件已清理。

| 文件 | 改动 |
|---|---|
| `pyproject.toml` | 登记 `rdp = "rdp.cli:main"`。 |
| `Makefile` | 分别检查两个脚本的 Bash 语法。 |
| `scripts/install.sh` | 安装步骤、帮助文本和失败处理结构。 |
| `scripts/upgrade.sh` | 升级、停服、二次检查及失败处理结构。 |
| `scripts/systemd/rdp-web.service` | Web 用户服务模板。 |
| `scripts/systemd/rdp-worker.service` | worker 模板，含进程组清理和停止期限。 |
| `src/rdp/__main__.py` | `sys.exit(main())` 进程包装。 |
| `src/rdp/cli.py` | 顶层入口及 Web 适配契约。 |
| `src/rdp/ops/cli.py` | argparse、命令分派及维护命令契约。 |
| `src/rdp/ops/runtime.py` | 配置、日志、数据库、调度和存储装配契约。 |
| `src/rdp/ops/lifecycle.py` | worker 启停、信号及资源释放契约。 |
| `src/rdp/ops/status.py` | 活跃作业、worker 锁和端口检查契约。 |
| `src/rdp/ops/worker.py` | 增加可注入日志时钟参数。 |
| `src/rdp/api/__init__.py` | 增加版本快照参数及接口登记契约。 |
| `src/rdp/api/production.py` | Web 装配、uvicorn 参数和关闭顺序契约。 |
| `src/rdp/api/shutdown.py` | 在途报错写入跟踪和限时排空契约。 |
| `src/rdp/api/version.py` | 只读版本接口及响应模型。 |
| `src/rdp/api/job_schemas.py` | 作业响应增加平台版本字段。 |
| `src/rdp/infra/logging.py` | 更新已批准的 R1 启动补归档契约。 |
| `src/rdp/infra/version.py` | 部署布局和版本读取契约。 |
| `src/rdp/infra/db/migrations/pending/__init__.py` | 隔离未激活迁移。 |
| `src/rdp/infra/db/migrations/pending/v0006_platform_version.py` | 版本列升级、降级契约。 |
| `src/rdp/jobs/execution.py` | 执行依赖增加版本快照字段。 |
| `src/rdp/jobs/types.py` | 作业记录增加平台版本字段。 |
| `src/rdp/jobs/version_models.py` | 尚未接入活动表的版本列声明。 |
| `src/rdp/jobs/versioning.py` | 领取事务内记录执行版本的契约。 |
| `src/web/src/api/version.ts` | 版本请求契约。 |
| `src/web/src/usePlatformVersion.ts` | 版本缓存查询契约。 |
| `src/web/src/VersionFooter.tsx` | 页脚版本组件契约。 |
| `src/web/src/VersionFooter.test.tsx` | 7 项跳过的前端测试。 |
| `src/web/src/api/openapi.json` | 更新作业版本字段的生成 schema。 |
| `src/web/src/api/schema.d.ts` | 更新生成类型。 |
| `tests/test_ops_cli.py` | 命令、退出码、账号恢复测试清单。 |
| `tests/test_ops_runtime.py` | 生产装配及失败清理测试清单。 |
| `tests/test_ops_web_lifecycle.py` | 日志接管、报错线程与关闭顺序测试清单。 |
| `tests/test_ops_worker_entry.py` | 信号、退出码、锁和 worker 装配测试清单。 |
| `tests/test_ops_logging_startup.py` | mtime、本地日历及归档故障测试清单。 |
| `tests/test_ops_version.py` | 版本读取、接口及作业版本测试清单。 |
| `tests/test_ops_version_migration.py` | `0006` 迁移测试清单。 |
| `tests/test_ops_deploy_scripts.py` | 假命令部署流程及单元模板测试清单。 |
| `tests/test_jobs_scheduling_migration.py` | 保留 0005 激活检查，明确允许未激活的 0006 暂存。 |

**2. `make check`**

最后一次命令：

```text
make check
```

退出码为 **0**。pytest 摘要原文：

```text
=========== 1811 passed, 115 skipped, 1 warning in 125.89s (0:02:05) ===========
```

末尾输出原文：

```text
[10/11] Prettier
cd src/web && node_modules/.bin/prettier --check .
Checking formatting...
All matched files use Prettier code style!
[11/11] Vitest
cd src/web && node_modules/.bin/vitest run

 RUN  v5.0.5 /home/shawn/桌面/robot-data-platform.wt/m0-11-ops-entry-systemd/src/web


 Test Files  21 passed | 1 skipped (22)
      Tests  243 passed | 7 skipped (250)
   Start at  07:48:32
   Duration  7.00s (tests 49%, environment 31%, import 19%)
```

**3. 契约变更申请、依赖申请**

按允许先添加参数或字段的边界，申请确认：

- `create_app` 增加可选 `platform_version`。
- `run_worker` 增加可选 `log_time`。
- `ExecutorDependencies` 增加可选 `platform_version`。
- `JobRecord`、`JobResponse` 增加可空 `platform_version`。

R1 沿用已有批准。依赖申请：**无**。

**4. 拿不准、需要评审决定的地方**

**需负责人决定：**

- 现有重置口令已满足会话撤销、强制改密和一条操作日志，但身份固定为 **“运维”**，数据库约束也如此，尚不满足 **“运维命令”**。本轮未改旧契约。建议批准新运维记录使用“运维命令”，保留历史“运维”，同步扩展身份校验及迁移约束。

其他设计选择请评审：

- **入口位置**：最终组合放在 `rdp.cli`；公共装配仍在 `rdp.ops`。原因是现有检查禁止 `api`、`ops` 相互依赖，无需放宽受保护配置。
- **部署与版本**：从包位置推导 `src/web/dist`；构建文件为部署根的 `rdp-build.json`。缺失显示“未知”，损坏或权限错误明确失败。
- **状态命令**：采用 `status --active-jobs / --worker-stopped / --check-port`。升级停服前后各检查一次作业；`--no-systemd` 不自动停止前台实例。
- **版本显示**：新增受认证保护的 `/api/version`，页脚显示在完成登录和改密的业务页面；登录、强制改密页面不展示。
- **作业版本**：单列保存最近一次实际领取的版本，恢复领取时更新；历史未知为 NULL。
- **停止期限**：worker 45 秒；Web 360 秒，覆盖请求宽限、Python 执行器收尾和报错排空。uvicorn 显式传 `workers=1`，避免 `WEB_CONCURRENCY` 改变进程数。
- **检查豁免**：前端有 4 条仅针对未使用参数的 ESLint 豁免，原因是契约函数只抛异常；使用参数后删除。