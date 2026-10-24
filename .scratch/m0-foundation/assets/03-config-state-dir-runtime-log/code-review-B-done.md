# /code-review main（探针工作目录，快照 refs/rdp/m0-03/B-done = 9dce202）

两轴由两个只读子 agent 分别评审，原文如下（轻度整理）。

## Standards

**硬违规**
1. AGENTS 规则 7 / CS 9.1：`src/rdp/infra/logging.py:446-452` `_local_time` 重写了"拒绝 naive/utcoffset 为 None 再 astimezone(UTC)"，与已有的 `rdp.infra.timeutil.ensure_utc` 等价（含 ValueError、OverflowError 语义），Duplicated Code。应改为 `ensure_utc(source.now()).astimezone(zone)`；模块注释也没写为何不复用。
2. CS 4.2 / 9.1：`config.py:164` 用 `str(error).rsplit("(at ", 1)` 从异常文本切行列号，依赖 tomllib 文案。Python 3.12 的 `TOMLDecodeError` 没有 `lineno/colno`（3.14 才加），做法可能站得住，但没有注释说明原因和文案变了的后果。
3. CS 4.2：`config.py:21` 注释"待骨架评审确认"已过时（骨架已通过）。

**判断项**
- Refused Bequest：`_DailyFileHandler` 绕过 `TimedRotatingFileHandler.__init__`，直接调 `FileHandler.__init__`，父类的 when/interval/suffix 等未初始化；模块头写了理由，不算违规。
- CS 2.6：`shouldRollover` 启动清理的 `Path(filename).unlink()` 不处理 `FileNotFoundError`，列目录与删除之间被删会丢当条记录；建议 `missing_ok=True`。
- CS 5.x：默认 `_local_timezone` 每条记录打开并 resolve 一次 `/etc/localtime`，契约要求如此，但代价没写进注释。
- Mysterious Name / Feature Envy：`config.py:225` `_validate_location` 借用 `validate_state_dir` 校验 home 和 RDP_CONFIG；`home / ".local/share/rdp"` 在 171、173 行重复，宜提成具名常量。
- Primitive Obsession：`logging.py` 260、417、439、461 行的正则字面量没有具名、没有出处；uuid4 规则与 `api/__init__.py` 的生成规则隐式耦合。
- CS 7.5：`tests/conftest.py` 没有恢复 `rdp.infra.logging._installed_handlers`，跨测试留下已关闭的 handler 引用。

**通过**：8.3（新增豁免只有两处 `# noqa: S104`，单条规则、有理由）、9.2、6.3、6.4、6.5、6.10、2.8、7.5、7.1 抽查。

## Spec

**(a) 缺失或部分满足**
1. 验收 4：`tests/test_web_app.py:332` `test_concurrent_request_ids` 只比对 `request_id_context.get()`，没比对写进 `web.log` 的行，docstring 名不副实。
2. 验收 7：uvicorn 启动和报错日志走同一套格式，只靠契约要求第 11 张传 `log_config=None, access_log=False`，没有真实 `uvicorn.run` 的测试。建议写进第 11 张验收。
3. 验收 1：未知项的实际值一律 `<已隐藏>`（防口令泄露），与工单字面"实际值"不一致，负责人应知情。

**(b) 工单没要求的**
1. `_create_directory` 把缺失的祖先目录也建成 0700（契约里写了）。
2. `log_state_warnings` 不受日志级别约束（契约里写了）。
3. 同名归档追加合并、启动后第一条日志清理过期归档、时区变化后重算零点：防御性扩展。

**(c) 实现有偏差**
1. 保留口径：`cutoff = 今天 - retention_days`，严格早于才删；`retention_days=30` 留 30 个日期归档（today-30…today-1）加当天活动文件。需确认口径。
2. 重启后归档日期：重启时 `_interval_start` 取启动当天；已有的 `web.log` 若是前几天的内容，下一次零点会整体归档成重启当天的日期（`tests/test_logging.py:517` 钉住了）。
3. `_local_timezone` 直接读 `/etc/localtime`，不看 `TZ` 环境变量；每条记录读两三次。

**核对通过**：验收 2、3、5、6，验收 7 的头与日志编号一致（测试路由，符合 P3）。
