**1. 改动清单**

契约骨架已完成，留在 `t/m0-05-database-migrations` 工作区，未暂存、未提交。新增函数保持占位；持久化和前端回调尚未接通，已有测试行为保持。

以下路径均相对当前工作目录：

| 文件 | 改动 |
|---|---|
| `src/rdp/infra/db/__init__.py` | 声明数据库包职责与模块边界。 |
| `src/rdp/infra/db/connection.py` | 引擎、事务工作单元、四类数据库异常转换契约。 |
| `src/rdp/infra/db/utc.py` | UTC 文本列类型及拒绝、异常包装契约。 |
| `src/rdp/infra/db/models.py` | 共享 MetaData、命名规则、报错表、文本上限。 |
| `src/rdp/infra/db/records.py` | 报错快照模型及写入、查询、过期清除契约。 |
| `src/rdp/infra/db/migration.py` | 编程式配置、版本检查、升级、备份及失败残留契约。 |
| `src/rdp/infra/db/migrations/__init__.py` | 包内迁移资源边界。 |
| `src/rdp/infra/db/migrations/env.py` | 在线连接复用、batch 模式及日志隔离契约。 |
| `src/rdp/infra/db/migrations/versions/__init__.py` | 版本脚本包声明。 |
| `src/rdp/infra/db/migrations/versions/v0001_error_reports.py` | 首次建表及显式拒绝降级的骨架。 |
| `src/rdp/infra/config.py` | 增加 `[errors].retention_days` 模型声明。 |
| `src/rdp/api/__init__.py` | 增加可选数据库参数，登记详情路由和响应模型。 |
| `src/rdp/api/database.py` | 数据库装配、读写请求会话依赖契约。 |
| `src/rdp/api/error_details.py` | 查询接口及 404、422 异常子类。 |
| `src/rdp/api/errors.py` | 独立异步报错持久化骨架及既有契约变更提案。 |
| `src/web/src/api/errorDetails.ts` | 使用生成类型的详情请求、加载回调骨架。 |
| `src/web/src/api/errorDetails.test.ts` | 17 项跳过的详情契约测试。 |
| `src/web/src/HealthPage.tsx` | 补充稳定回调接入契约，保留现有实现。 |
| `src/web/src/HealthPage.test.tsx` | 增加 5 项跳过的接入测试。 |
| `src/web/src/api/openapi.json` | 经 `make api-types` 重新生成。 |
| `src/web/src/api/schema.d.ts` | 经 `make api-types` 重新生成。 |
| `tests/test_db_connection.py` | 连接、事务、两进程、异常分类清单。 |
| `tests/test_db_utc.py` | UTC 格式、精度、非法值及包装清单。 |
| `tests/test_db_records.py` | 模型约束、读写及清除边界清单。 |
| `tests/test_db_migration.py` | 版本、迁移、备份内容、并发及失败清单。 |
| `tests/test_db_config.py` | 默认值、配置范围、未知项拒绝清单。 |
| `tests/test_api_database.py` | 应用装配、会话、查询和唯一报告清单。 |

未修改受保护文件、规划文档或 `.git`，未安装依赖、未执行联网命令。未创建需保留的临时试验文件。

**2. `make check`**

最后一次执行命令原样：

```bash
.venv/bin/ruff format src/rdp/infra/db/migration.py tests/test_db_migration.py && make check
```

退出码 `0`，十一步全部通过。末尾输出原样：

```text
================= 329 passed, 172 skipped, 1 warning in 6.69s ==================
[7/11] OpenAPI 过期检查
✨ openapi-typescript 7.13.0
🚀 /tmp/tmp.tsbeAsx9wT/openapi.json → /tmp/tmp.tsbeAsx9wT/schema.d.ts [20ms]
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

 RUN  v5.0.5 /home/shawn/桌面/robot-data-platform.wt/m0-05-database-migrations/src/web


 Test Files  8 passed | 1 skipped (9)
      Tests  55 passed | 22 skipped (77)
   Start at  04:46:14
   Duration  1.47s (environment 46%, tests 27%, import 25%, transform 1%, setup 1%)
```

唯一 warning 是既有 Starlette TestClient 弃用提示。新增跳过项是契约清单，不代表数据库功能已经验证通过。

运行前的 `git status --porcelain --untracked-files=all` 原样：

```text
 M src/rdp/api/__init__.py
 M src/rdp/api/errors.py
 M src/rdp/infra/config.py
 M src/web/src/HealthPage.test.tsx
 M src/web/src/HealthPage.tsx
 M src/web/src/api/openapi.json
 M src/web/src/api/schema.d.ts
?? src/rdp/api/database.py
?? src/rdp/api/error_details.py
?? src/rdp/infra/db/__init__.py
?? src/rdp/infra/db/connection.py
?? src/rdp/infra/db/migration.py
?? src/rdp/infra/db/migrations/__init__.py
?? src/rdp/infra/db/migrations/env.py
?? src/rdp/infra/db/migrations/versions/__init__.py
?? src/rdp/infra/db/migrations/versions/v0001_error_reports.py
?? src/rdp/infra/db/models.py
?? src/rdp/infra/db/records.py
?? src/rdp/infra/db/utc.py
?? src/web/src/api/errorDetails.test.ts
?? src/web/src/api/errorDetails.ts
?? tests/test_api_database.py
?? tests/test_db_config.py
?? tests/test_db_connection.py
?? tests/test_db_migration.py
?? tests/test_db_records.py
?? tests/test_db_utc.py
```

运行后的同一命令输出原样：

```text
 M src/rdp/api/__init__.py
 M src/rdp/api/errors.py
 M src/rdp/infra/config.py
 M src/web/src/HealthPage.test.tsx
 M src/web/src/HealthPage.tsx
 M src/web/src/api/openapi.json
 M src/web/src/api/schema.d.ts
?? src/rdp/api/database.py
?? src/rdp/api/error_details.py
?? src/rdp/infra/db/__init__.py
?? src/rdp/infra/db/connection.py
?? src/rdp/infra/db/migration.py
?? src/rdp/infra/db/migrations/__init__.py
?? src/rdp/infra/db/migrations/env.py
?? src/rdp/infra/db/migrations/versions/__init__.py
?? src/rdp/infra/db/migrations/versions/v0001_error_reports.py
?? src/rdp/infra/db/models.py
?? src/rdp/infra/db/records.py
?? src/rdp/infra/db/utc.py
?? src/web/src/api/errorDetails.test.ts
?? src/web/src/api/errorDetails.ts
?? tests/test_api_database.py
?? tests/test_db_config.py
?? tests/test_db_connection.py
?? tests/test_db_migration.py
?? tests/test_db_records.py
?? tests/test_db_utc.py
```

**3. 契约变更申请、依赖申请、受保护文件申请**

契约变更申请：

- **第 3 张配置**：新增 `PlatformConfig.errors.retention_days`，TOML 节为 `[errors]`，默认 30，严格整数范围 1–3650，单位为 UTC 的固定 24 小时。继续拒绝未知项。
- **第 3/4 张应用工厂**：签名改为 `create_app(web_dist, *, database: Engine | None = None)`；非空时返回前检查版本，调用者负责引擎生命周期。新增详情路由、数据库异常及请求期数据库副作用。
- **第 4 张报告边界**：`handle_error`、`ErrorBoundary` 拟共用异步报告函数，缺陷使用独立事务落表；最多额外等待约 6 秒，持久化失败仅追加一次 ERROR，不覆盖原响应。
- **第 4 张 D2**：报告拟限制为 262144 个 Unicode 字符，保留前缀并追加明确截断标记；日志和数据库使用同一次格式化结果。**这改变了原先不截断的承诺，须评审批准。**
- **第 4 张页面**：`HealthPage` 拟提供稳定的详情加载回调；404、失败和超时沿用卡片固定提示。

`StatePaths`、`ProblemResponse.error_id` 不改。上述持久化和前端接入行为仍未实现。

依赖申请：**无**。  
受保护文件申请：**无**；现有 import-linter 已覆盖新包，不需要 `[tool.alembic]`。

**4. 已定方案与需要评审拍板的地方**

| 项目 | 骨架中的选择及理由 |
|---|---|
| 事务开始 | 按本地 SQLAlchemy 源码，关闭驱动自动 BEGIN；写会话在首次读前 `BEGIN IMMEDIATE`，避免 WAL 读后写升级立即失败。 |
| 连接设置 | 每个新连接在事务外设置 WAL、外键和 `busy_timeout=5000`；使用 NullPool，避免增加连接池等待。 |
| 异常分类 | BUSY/LOCKED、约束冲突归 ConflictError；库损坏归 InputError；权限、磁盘、I/O 归 ExternalError；编程错误归 DefectError。数据库层不记日志。 |
| 会话退出 | 正常提交，异常回滚；业务异常原对象传播。清理再失败时保留主异常，并明确结果可能未知。 |
| UTC | 固定 27 字符、六位微秒、末尾 Z。naive、换算溢出、坏存量文本均拒绝；写入异常可能被 StatementError 包装，契约明确解包。 |
| 表与编号 | 共用一个 MetaData；错误编号直接作主键。请求为 uuid4 hex，作业为规范正整数文本，来源种类单独保存；同编号不覆盖。 |
| 报告上限 | 262144 字符，摘要 512 字符；报告截断只在格式化边界做一次。上限及有损行为需要批准。 |
| 清除边界 | 删除严格早于 `now - retention_days` 的记录；等于截止时刻和未来记录保留。 |
| 迁移环境 | 编程式 Config 指向包内脚本；复用连接，开启 batch 和事务化 DDL，不改全局日志。手写脚本，不提供模板。 |
| 降级 | 保留 `downgrade()`，显式抛 InputError，指向人工备份恢复，避免误执行。 |
| 首次迁移 | 文件不存在算待迁移，但不备份不存在的空库；已有空库先备份。非空无版本库拒绝初始化。 |
| 备份位置与权限 | db 模块计算 `root/backups`，不改 StatePaths；新目录 0700，备份及临时文件 0600。 |
| 备份与保留 | 使用 SQLite backup，完成后原子发布；按文件名 UTC 时间保留最新 5 份，只删平台命名普通文件，采用有界扫描。 |
| 迁移失败 | 备份失败不升级；升级失败回滚并保留完整备份；清理失败明确留下 `.partial` 或超过 5 份备份。不会自动覆盖原库恢复。 |
| 并发迁移 | 对状态根目录 fd 使用非阻塞 flock，第二个 migrate 立即冲突；要求运维先停止 Web/worker，目录锁不能阻止普通业务写入。 |
| 版本检查 | 只读比较迁移图，不按字符串排序。缺失、落后、领先或未知版本均拒绝启动，并给出 migrate／匹配代码的操作提示。 |
| Web 会话 | 本地 FastAPI 源码确认 `scope="function"` 在发送响应前退出，路由异常可回传 yield。流式正文和后台任务不能继续使用业务 Session。 |
| 报错持久化 | `asyncio.to_thread` 内独立会话，异步等待最多约 6 秒；超时不能强杀线程，可能稍后落表，关闭引擎前须等待在途线程。 |
| 查询与页面 | 详情 404 带诊断，非法编号 422；本票暂不鉴权，第 6 张加所有登录账号可看。前端首次展开才查询，沿用 5 秒超时。 |

需要特别拍板的限制：

- `database=None` 保留了旧调用兼容性，但工厂无法区分离线调用与生产漏传；第 11 张入口必须显式传引擎。
- 未知异常的原有 500 可能先发送、报错随后落表，立即查询可能短暂 404。
- SQLite 备份预算和线程超时都不能强制终止永久阻塞的磁盘系统调用。
- 两个 yield 依赖的骨架暂用 `Returns:`；实现出现 `yield` 后改为 `Yields:`，迭代语义不变。前端 5 条参数未使用豁免也须在实现时删除。
- 主仓库 `GLOSSARY.md` 暂无平台状态目录、请求编号、作业编号的独立条目；本次沿用 S1 和第 3、4 张既有契约，文档补充交 Claude。