# M0 遗留事项

两轴评审里不打回的判断题和坏味道（`docs/agents/codex-workflow.md` 3.5「什么算不通过」）。里程碑结束前由 `/retro` 处理：改进编码规范，或者单开一张整理票。

## 第 5 张 数据库与迁移（r1-done 评审）

- **请求编号规则的归属**：规则放在 `rdp.infra.db.validation`，`rdp.infra.logging` 因此依赖数据库包。应移到 `rdp.infra` 下一个中立的模块。第 6 张开工前定。
- **公开辅助函数只有间接覆盖**：`utc.format_utc_text`、`validation.py` 的三个公开函数，docstring 写的拒绝条件没有直接用例（7.1 判定偏宽）。
- **重复**：`BUSY_TIMEOUT_MS / 1000` 出现 4 次，可以定义 `BUSY_TIMEOUT_S`；`Path(url.database or "未知数据库")` 有 5 处。
- **正则靠切片去锚点**：`REQUEST_ID_PATTERN[1:-1]`；`migration.py` 拿请求编号的规则去匹配备份文件名里的 uuid 后缀，两个概念绑在了一起。
- **前端**：`errorDetails.ts` 和 `problems.ts` 各写一份请求编号正则；`{0,18}` 没有从 `MAX_SQLITE_INTEGER` 推出来；`staleTime`、`gcTime` 没写成具名常量。
- **遗留写法**：`migration.py` 用字符串 `"清理旧备份"` 决定后果文案（Repeated Switch）；`migration_config` 和 `ScriptDirectory.from_config` 重复构造；`is_request_id` 可以改成返回 `TypeIs`。
- **报负责人、要改含义的**：`BACKUP_TIMEOUT_S = 5.0` 是整个备份的总时长上限，M1 库变大以后可能超时；显式抛出的程序缺陷最多等约 6 秒才返回 500；没有 WAL 文件时用 `immutable=1` 读版本，依赖"先停服务"（B3）。
- **页面**：完整报错的 traceback 长行撑出 `DiagnosticCard` 边框（`demo-r2-done.png`），`<pre>` 需要横向滚动或换行。
- **数据库文件权限**：`rdp.sqlite3` 新建为 0644（随 umask），里面有完整报错。状态目录根是 0700 时外人进不去，但工单没写库文件的权限，第 11 张部署时确认。
