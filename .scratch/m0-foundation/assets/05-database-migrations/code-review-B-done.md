# /code-review：m0-05 B-done

- 探针工作目录检出 `refs/rdp/m0-05/B-done`（`86412ee`），基点 `c188444`（依赖提交），diff 35 个文件。
- Spec：工单 `05-database-migrations.md`（含 F1–F3、骨架评审、B1–B3）、M0 spec 第 05 行、第 4 张 E2。
- Standards：`CODING_STANDARDS.md`、`AGENTS.md`，加 Fowler 坏味道基线。
- 两轴各由一个子 agent 只读完成；下面是原文，执行线只做了排版。执行线复核过的结论标【复核】。

## Standards

### 必须改
1. **测试的 docstring 和测试内容对不上（AGENTS 规则 5，CODING_STANDARDS 7.1）。**【复核：属实，并且变异"去掉随机后缀"漏网】`tests/test_db_migration.py:346` `test_backup_filename` 的 docstring 写的是"注入非 UTC 时刻规范为 UTC 文件名"，但两次调用传的都是 `tzinfo=UTC`；两次备份的 revision 也不同，所以文件名本来就不会撞。整个迁移测试文件里没有一处用非 UTC 偏移。改法：传入 +08:00 或 −06:00 的时刻，断言文件名里的时间戳已经换成 UTC；再造"同一时刻、同一 revision"的两次备份。

### 判断题
- **4.3 / 5.5：超时常量和文案各写一份。** `connection.py` 定义了 `BUSY_TIMEOUT_MS`，但 `_database_problem` 的 actual、expected 文案和 `translate_database_error` 的 docstring 都直接写死"5000 毫秒"。`errors.py` 的 `ERROR_PERSIST_TIMEOUT_S = 6.0` 在注释里写"5 秒之外留 1 秒"，却没有从 `BUSY_TIMEOUT_MS` 推导出来。`records.py:155` 的"1 至 3650"同理，应引用 `MAX_RETENTION_DAYS`。
- **4：魔数没有命名、没有注释。** `_validation.py:19` 的 `9223372036854775807`、`errorDetails.ts:47` 的 `9223372036854775807n`，都应写成具名常量并注明"SQLite 有符号 64 位上限"。
- **5.5：备份连接没有显式超时。** `migration.py:385-386` 备份用的两个 `sqlite3.connect` 依赖默认 5 秒，不像 `_read_revision` 那样传 `BUSY_TIMEOUT_MS`。
- **7.5：测试要真等约 5 秒**（`test_db_migration.py:594` 断言 4–10 秒，`test_db_connection` 也用真实锁等待）。验证的是 SQLite 的真实行为，可以接受，但测试慢，而且对机器负载敏感。
- **8.3：新增一条豁免。** `errorDetails.ts:140` 的 `eslint-disable-next-line @typescript-eslint/no-deprecated`。【复核：TanStack Query 5.104.5 把 `fetchQuery` 标成了弃用，提示改用 `queryClient.query(options)`】已弃用的 API 应该在契约里换掉，不该靠豁免保留。
- **10.5：前端拼了一段详情正文**（`errorDetails.ts:161` `detailsText`）。这不是诊断，可以接受。
- **1.x：跨包引用私有模块。** `rdp.api.errors` 和 `rdp.api.error_details` 都 import 了 `rdp.infra.db._validation`。应改为公开导出。

### 坏味道（判断题）
- **Duplicated Code / Shotgun Surgery。**
  - 编号格式的正则写了 6 份：`_validation.py:17`、`error_details.py:209`、`migration.py:445`、`models.py:248` 的 CHECK、`v0001` 的 CHECK、`errorDetails.ts:46`。迁移脚本那份要冻结、不能引用模型，这是合理的；其余几份可以收拢。
  - "只读会话写入 → DefectError"的判断在 `connection.py:173` 和 `records.py:177` 各写一遍。
  - `isoformat().replace("+00:00","Z")` 在 `utc.py` 和 `migration.py:366` 各写一遍。
  - 测试里回收子进程的代码 `_reap`（`test_db_connection`）在 `test_db_migration:566` 又内联抄了一遍。
- **Repeated Switch / Primitive Obsession。** `_migration_external` 用 `stage == "清理旧备份"` 这个字符串来决定后果文案。
- **Mysterious Name。**
  - `errorDetails.ts` 里实际用到的参数都带 `_` 前缀（`_client`、`_errorId`、`_signal`），通常这个前缀表示"未使用"。
  - `boundedText` 里的 `count += character.length > 0 ? 1 : 0` 永远加 1。
- **死代码。** `errors.py` 的 `report=report or ""`：空串过不了 `min_length=1`，会被 `except Exception` 吞掉。缺陷路径上 `report` 也不会是 None。
- **小问题。** `_migrate_locked` 里 `migration_config` 和 `ScriptDirectory.from_config` 重复构造了 3 次。
- **没有发现违规的〔审〕项**：中间层不打日志；logger 写法统一；日志里没有敏感信息；时间列都用 `UTCDateTime`；测时长用 monotonic；备份用临时文件加原子替换；旧备份清理有上界；没有重复造轮子（`fcntl.flock`、`sqlite3.backup`、Alembic）；测试都有 docstring，只用 `tmp_path`。

## Spec

总体：验收 1–8 都有实现，大多由真实临时库、真实子进程或真实 Alembic 来测。B1、B2、F1–F3 的实现与决策一致。迁移只建 `error_reports` 一张表；`downgrade()` 一律拒绝；`[errors] retention_days` 默认 30；查报错接口 404 是 InputError 子类且带诊断，格式不对返回 422；`HealthPage` 已把加载器传给 `loadDetails`；受保护文件没动。

### (a) 缺失或不完整
1. **验收 7**【复核：属实】：`tests/test_api_database.py:116-125` 的 `test_configure_version` 只测了"库文件不存在"。docstring 写着"缺失/无版本/落后/领先/未知"，测试体里只有缺失一种。"落后"只在 `check_database_version` 那一层测过（`tests/test_db_migration.py:141`），没有经过 `create_app` 测。
2. **验收 2"两个进程同时写……都成功"**【复核：属实】：`tests/test_db_connection.py:367-389` 只是先后启动两个只做一次短插入的进程，没有让两个写事务真正重叠（一方持锁、另一方等锁之后成功）。docstring 说"事件协调先后"，代码里并没有 Event。
3. **B2"日志和数据库存同一份"**：截断情形没有端到端验证。`test_report_same_text`（`test_api_database.py:469`）只测了不超长的报告。`test_report_bound`（`:725-731`）的 docstring 写的是 N-1/N/N+1 三档，实际只测了 small 和一个超长值。
4. **验收 5**：`test_compare_metadata` 是真比的，但 Alembic 不比较 CHECK 约束，而 `models.py` 和 `v0001` 各手抄了一份 CHECK SQL，以后两边漂移，这个检查发现不了。建议加一条比较 `sqlite_master.sql` 的测试，或者后续票注意。

### (b) 工单没要求的行为（都小，可以接受）
- 额外的只读会话依赖 `get_read_session`（`query_only`）。
- `migrate` 的 flock 互斥、备份耗时预算、不传数据库时查报错返回 502，都写进了已获批的骨架。

### (c) 实现了但看起来有问题
1. **`BACKUP_TIMEOUT_S = 5.0` 是整个备份的总耗时上限**（`migration.py:53,376-378`），超过 5 秒就拒绝升级。B3 已要求先停服务，不会有锁等待，备份耗时只随库的大小增长。M1 数据集索引入库后库变大，`migrate` 可能每次都超时。
2. **没有 WAL 文件时用 `immutable=1` 读版本**（`migration.py:184`），依赖 B3"服务已停"。运维违反 B3 时，读到的版本可能是旧的，应写进手册"数据库"一节的警告里。
3. **显式抛出的 DefectError 要等报错表写完（最多约 6 秒）才返回 500**，契约里写了，但会拉长出错时的响应时间，值得在完工汇报里提。
