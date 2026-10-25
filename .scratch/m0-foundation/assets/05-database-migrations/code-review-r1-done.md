# /code-review：m0-05 r1-done

- 探针工作目录检出 `refs/rdp/m0-05/r1-done`（`8bf1ad9`），基点 `main`（`d767aac`）。diff 共 40 个文件；本轮相对 `B-done`（`86412ee`）改了 19 个文件。
- Spec 依据：工单 `05-database-migrations.md`（含修复清单 r1 的 13 条）。最终回复看的是 `assets/…/out-r1.md`。
- Standards 依据：`CODING_STANDARDS.md`、`AGENTS.md`、`CLAUDE.md`，外加 Fowler 坏味道基线。
- 两个轴各由一个只读子 agent 完成。我抽查了其中关键的几处，抽查过的标【复核】。
- Spec 子 agent 用 `-p no:cacheprovider` 跑了相关测试和全量 pytest，结果 505 passed，跑完 `git status` 不变。

## 1. 修复清单 13 条逐条

| # | 结论 | 证据 |
|---|---|---|
| 1 | 已落实 | `tests/test_db_migration.py:368`。用 +08:00 和 −06:00 两个时刻，换算成 UTC 是同一时刻。下一版迁移故意失败，让两次备份面对同一 revision。断言两份备份的 UTC 前缀相同、文件名不同，目录里正好这 2 份。 |
| 2 | 已落实 | `tests/test_db_migration.py:486`。放了 6 份平台备份，加人工文件、`.partial`、一个时间最早（2020）的软链接；`migrate` 后共 7 份，只删最旧的 2 份，留 5 份。其余文件内容不变，软链接目标不变，并断言了整个目录的文件名集合。 |
| 3 | 已落实 | `tests/test_api_database.py:365`。用 `pytest.raises(SQLAlchemyError)` 直接断言写入失败，再断言得到带诊断的 `DefectError`。 |
| 4 | 已落实 | `tests/test_api_database.py:517`。有引擎、无引擎两种应用都走真实应用，覆盖 400、409、502、422；404 只在有引擎时测，无引擎时另测 500。`:554` 断言日志里没有"完整报错持久化失败"。`report or ""` 已删【复核】。注意：代替它的是 `src/rdp/api/errors.py:523-525` 的裸 `RuntimeError` 分支，这一支到不了，也没有测试（见 Standards）。 |
| 5 | 已落实 | `tests/test_api_database.py:119`。缺失、没有版本表、落后、领先或未知四种情况都经过 `create_app(..., database=engine)`，每种都断言 `InputError` 和"先运行 migrate"。"落后"的造法是复制迁移目录、加一个 0002，再 monkeypatch `migration.__file__`。做法绕，但有效。 |
| 6 | 已落实 | `tests/test_db_connection.py:368`。一个子进程先持有写锁；另一个子进程发出 `BEGIN IMMEDIATE` 后，断言 0.5 秒内还没完成。放锁后用 monotonic 量出等待时长在 0.4–5 秒之间，最后表里有 2 行。 |
| 7 | 已落实 | `tests/test_api_database.py:786` 精确构造 N−1、N、N+1 三档长度。`:803` 走真实 HTTP：日志里的报告段和表里的 `report` 逐字相同，都以截断标记结尾，长度都不超过上限。 |
| 8 | 已落实 | `tests/test_db_migration.py:313` 把迁移建出的 `sqlite_master.sql` 和用模型 MetaData 在另一个空库里建出的做比较，比较前规范化空白。迁移脚本 `v0001_error_reports.py:56` 里的 CHECK 仍是冻结的字面量，没有引用共享常量，所以这个比较不是自己比自己。 |
| 9 | 基本落实（有尾巴） | 诊断文案改用了 `BUSY_TIMEOUT_MS`（`src/rdp/infra/db/_errors.py:43,46`）。`ERROR_PERSIST_TIMEOUT_S = BUSY_TIMEOUT_MS / 1000 + 1.0`（`src/rdp/api/errors.py:465`）【复核】。`records.py:156` 改用 `MAX_RETENTION_DAYS`。`MAX_SQLITE_INTEGER` 在 `validation.py:19` 和 `errorDetails.ts:14` 各定义一次，并注明"SQLite 有符号 64 位整数上限"【复核】。尾巴有两处：`connection.py:58,218,230`、`migration.py:235` 的 docstring 仍写死"5000 毫秒"，而上轮 Standards 点过 `translate_database_error` 的 docstring；`errors.py:464` 的注释仍写"5 秒"。 |
| 10 | 已落实 | `src/rdp/infra/db/migration.py:382,385`，备份用的两个连接都传了 `timeout=BUSY_TIMEOUT_MS / 1000`。 |
| 11 | 已落实 | `errorDetails.ts` 改用 `queryClient.query`，`no-deprecated` 豁免已删（`src`、`tests` 里 grep 不到）【复核】。参数名和 `@param` 都去掉了 `_` 前缀；`boundedText` 改成逐项计数。 |
| 12 | 已落实（诊断质量有瑕疵） | `rdp.api` 改为 import 公开模块 `rdp.infra.db.validation`。"只读会话写入"的判断只剩 `_errors.py:57-68` 的 `readonly_write_error` 一处，`records.py:178` 复用它。备份文件名复用 `format_utc_text`。两个测试文件共用 `tests/db_support.py` 的 `reap_processes`。Python 侧的编号格式集中在 `validation.py`。瑕疵：`_errors.py:68` 构造诊断时错误码写死为 `0`，诊断里显示"安全错误码=0"，规则也借用了通用的存储约束文案，没有如实写"只读会话写入"和 SQLITE_READONLY【复核】。 |
| 13 | 已落实 | `out-r1.md` 有五块。第 5 块逐个说明了本轮 10 个测试、B 的 173 个后端测试和 22 个前端测试，每个一开始就通过的测试都写了原因。 |

## 2. Standards 轴新发现

### 硬性违规（判定偏宽，可以商量）

1. **CODING_STANDARDS 7.1，本轮新引入：新增公开函数没有直接测试。**
   - `src/rdp/infra/db/utc.py:100` `format_utc_text`，以及 `src/rdp/infra/db/validation.py:37/58/84` 的三个函数，在 `tests/` 里都没有直接引用【复核：grep 无结果】。
   - 它们 docstring 里写的拒绝条件（ValueError、OverflowError 等）没有对应用例。
   - 这些函数只是被间接覆盖。
2. **CODING_STANDARDS 3.3.2 / 4.4，上轮遗留：docstring 和实现对不上。**
   - `connection.py:47` 说路径非法时诊断带"路径规则"，`:62` 实际借用的是 `database_problem(..., 0)`，规则成了"存储及结构约束"，实际成了"安全错误码=0"。
   - 第 9 条尾巴里那几处 docstring 写死的"5000 毫秒"也属于这一类。

### 判断题 / 坏味道

- **Duplicated Code（新）。**
  - `BUSY_TIMEOUT_MS / 1000` 出现 4 次：`migration.py:187,382,385`、`errors.py:465`。建议定义一个 `BUSY_TIMEOUT_S`。
  - `Path(...url.database or "未知数据库")` 有 5 处：`connection.py:169,183,189`、`_errors.py:67`、`records.py:177`。
- **Primitive Obsession（新）。** `REQUEST_ID_PATTERN[1:-1]` 靠切片去掉锚点（`validation.py:26`、`migration.py:445`）【复核】。`migration.py:445` 还拿请求编号的规则去匹配备份文件名里的 uuid 后缀，把两个不相关的概念绑在了一起。
- **Feature Envy / 归属不当（新）。** 请求编号的规则放在了 `rdp.infra.db.validation`，导致 `src/rdp/infra/logging.py:27` 也要依赖数据库包【复核】。import-linter 不拦。
- **6.1 诊断质量（新）。** 就是第 12 条的瑕疵：`_errors.py:68` 写死 `code=0`，丢掉了 SQLITE_READONLY；同一行的 `cast` 可以用重载代替。
- **6.2 / 死代码（新）。**
  - `errors.py:523-525` 在日志写完之后抛裸 `RuntimeError("程序缺陷报告不能为空")`，不属于四类异常。这一支实际到不了，也没有测试。
  - `errors.py:185` 的 `or request_id is None` 是多余的，`is_request_id` 改成返回 `TypeIs` 就能省掉。
- **前端（遗留）。**
  - `errorDetails.ts:49` 的请求编号正则和 `problems.ts:232` 各写一份。
  - `:50` 的 `{0,18}` 是写死的，没有从 `MAX_SQLITE_INTEGER` 推出来。
  - `errorDetails.ts:147-149` 的 `staleTime: 0`、`gcTime: 0` 没有写成具名常量（10.3）。
- **遗留未改。**
  - Repeated Switch：`migration.py:434/462` 用字符串 `"清理旧备份"` 决定后果文案。
  - `migration_config` 和 `ScriptDirectory.from_config` 在 `migration.py:285-304` 重复构造。
  - `errors.py:516` 的 `raise DefectError()` 不带诊断，B-done 时就有，不是本轮引入的。
- 上轮 Standards 的"必须改"（`test_backup_filename` 名不副实）已解决，见第 1 条。没有发现新增的 lint 豁免。

## 3. Spec 轴新发现

- **(a) 缺失或部分实现**：没有。验收 1–8 和 B1–B3 不变，没有发现回归。验收 9（手册）归主会话，验收 10（演示）归执行线，都不在本次代码 diff 里。
- **(b) 范围蔓延**：`src/rdp/infra/logging.py` 改成 import `rdp.infra.db.validation`，日志模块开始依赖数据库包。这是第 12 条"编号格式只留一处"带出来的，需要决定共享的编号规则是否应该移出 `db` 包，比如放到 `rdp.infra` 下的一个中立模块。
- **(c) 实现有瑕疵（轻微）**：
  - `_errors.py:68` 只读写入诊断的错误码是 0，会误导排查。
  - `errors.py:523-525` 新增的空报告分支到不了，也没有测试。
  - 第 5 条"落后"那种情况靠 monkeypatch `migration.__file__`，比较脆，但有效。

## 4. 是否可以通过

**建议通过（有条件）。** 修复清单 13 条都已落实，没有阻塞项。第 9 条有尾巴，第 12 条的诊断有瑕疵，但都不影响这一条要求本身成立。没有发现功能或测试缺口，也没有回归。

不阻塞、但建议在合并前顺手修掉，或者记进下一张票的事项：

1. `_errors.py:68` 只读写入诊断写入真实码 `SQLITE_READONLY`，规则和实际文案改成"只读会话不得写入"（6.1）。
2. `errors.py:523-525` 的裸 `RuntimeError` 死分支：删掉，或者改成带诊断的 `DefectError` 并补测试（6.2）。
3. `connection.py:58,218,230`、`migration.py:235` 的 docstring 和 `errors.py:464` 的注释，不再写死"5000 毫秒"和"5 秒"。
4. 决定请求编号规则放在哪里，避免 `infra.logging` 依赖 `infra.db`。
5. 给 `format_utc_text` 和 `validation.py` 的公开函数补直接测试（7.1）。

如果负责人把第 1、2 条视为必须修（6.1 / 6.2 是文档化标准），那就要再开一轮。这两条改动很小。
