评审发现下面的问题，逐条修复，别处不动。修复清单原文也在工单 /home/shawn/桌面/robot-data-platform/.scratch/m0-foundation/issues/03-config-state-dir-runtime-log.md 的 Comments 最后一条（用绝对路径读主仓库目录的版本）。

1. 问题：有一个过期归档删不掉时，之后的每一条日志都会丢。评审用 `unittest.mock.patch.object(Path, "unlink", …)` 让 `web.log.<日期>` 的删除一直抛 `PermissionError`，跨零点前后写 6 条，`web.log` 是空的：`shouldRollover`（启动清理）和 `doRollover` 里的删除报错，每条记录都经 `handleError` 被丢掉，`rolloverAt` 也不前进。试验脚本见 /home/shawn/桌面/robot-data-platform/.scratch/m0-foundation/assets/03-config-state-dir-runtime-log/exp-B-done-unlink.py。位置：`src/rdp/infra/logging.py` 的 `_DailyFileHandler.shouldRollover`、`doRollover`、`getFilesToDelete` 附近。期望：删除单个过期归档报 `OSError`（含 `PermissionError`，以及列目录和删除之间文件已被删掉的 `FileNotFoundError`）时跳过这个文件，当条和之后的记录照常写进活动文件；切分照常完成（`rolloverAt` 前进、活动文件重开）；删不掉的归档留着，下一次切分或下一次启动再试。先写测试看到它失败：持续删不掉时，跨零点前后的多条记录都在文件里；删除时文件已不存在，当条记录不丢。`configure_logging` 的 `Side Effects:` 补一句"删不掉的过期归档跳过并留下，下次切分或启动再试"（评审已批准这处补充说明，不用另写契约变更申请）。
2. 问题：重复实现（AGENTS.md 规则 7，CODING_STANDARDS 9.1）。位置：`src/rdp/infra/logging.py` 的 `_local_time`。期望：改用已有的 `rdp.infra.timeutil.ensure_utc(source.now())` 再 `.astimezone(zone)`；`ValueError`、`OverflowError` 的语义不变，现有测试照过。
3. 问题：从异常文本里解析 TOML 的行列号，没写理由（CODING_STANDARDS 4.2）。位置：`src/rdp/infra/config.py` 约 164 行 `str(error).rsplit("(at ", 1)`。期望：注释写明 Python 3.12 的 `tomllib.TOMLDecodeError` 没有 `lineno`/`colno` 属性（3.14 才加），所以只能从文案里取；文案变了、取不到位置时仍然报一条合格的 `ValueError`（含文件、`<document>`、期望），用一个测试钉住这条退路（例如替身异常的文案里没有 `(at `）。
4. 问题：过时注释。位置：`src/rdp/infra/config.py` 约 21 行"待骨架评审确认"。期望：骨架关卡已通过，改成定下来的理由（上限 3650 天防误填）。
5. 问题：验收 4 的测试没看日志。位置：`tests/test_web_app.py` 的 `test_concurrent_request_ids`。期望：两个交错的并发请求各自在请求里写一条业务日志，断言日志里记下的 `request_id`（经 `configure_logging` 写进 tmp_path 下的文件，或用 `RuntimeFormatter` 格式化的 handler 收到的行）和各自响应头的 `X-Request-ID` 一致、不串；docstring 和断言一致。这是改测试，不是改实现，所以这个测试改完一开始就会通过，在最终回复里说明。
6. 问题：测试没恢复模块状态（CODING_STANDARDS 7.5）。位置：`tests/conftest.py`。期望：一并保存和恢复 `rdp.infra.logging._installed_handlers`，测试之间不留已关闭的 handler 引用。
7. 问题：字面量没有具名（CODING_STANDARDS 4.6）。期望：`config.py` 里重复的 `home / ".local/share/rdp"`（约 171、173 行）和默认配置相对路径 `.config/rdp/config.toml` 提成具名常量，注释写出处（M0 spec S1、工单「范围」）；`logging.py` 里请求编号、字段键、归档日期后缀、安全字符串的正则提成具名常量，请求编号那条注明它对应 `src/rdp/api/__init__.py` 里生成的 `uuid4().hex`。
8. 问题：默认时区每条记录读一次 `/etc/localtime`，代价没写。位置：`src/rdp/infra/logging.py` 的 `_local_timezone`。期望：不改行为（已获批的契约：系统时区修改在下条记录生效），只在注释里写明代价（每条日志要读两三次这个小文件）、为什么接受（v1 的日志量小），以及为什么不看 `TZ` 环境变量（负责人 P1 决定按本机时区写；第 11 张的 systemd 单元不设 `TZ`）。

已获批的签名、类型和 docstring 不改（第 1 条的那句补充除外）。确实要改别的契约时停下，在最终回复里写契约变更申请。修第 1、3 条时先写测试、单独跑看到它失败，再改实现。

修完后 `make check` 全绿。

边界：
- 只改 `src/`、`tests/`。本票允许改的受保护文件：`pyproject.toml`（只在 ruff、basedpyright 需要时调整配置，每条写理由；依赖表不动）。
- 改动留在工作区，不要 `git add`，也不要提交。
- 不读取 `~/桌面/data_check` 和 `~/桌面/Data_Collection_System-main`，不碰 `/mnt`。
- 不安装任何东西，不访问网络（沙箱为了跑测试开了网络权限，但这张票用不到网络；评审会查运行日志，出现安装或联网的命令整轮打回）。需要新依赖时停下，在最终回复里写依赖申请（AGENTS.md 规则 7）。
- 自己在 `/tmp` 或别处建的试验文件，交付前删掉。测试不碰真实的 `~/.config/rdp`、`~/.local/share/rdp`，不写 `.git/info/exclude`。

最终回复：逐条写处理结果（新增或改了哪些测试，第 1、3 条的测试第一次运行的失败输出）；`make check` 最后一次运行的命令和末尾输出，原样贴出；再原样贴出跑之前和跑之后的 `git status --porcelain --untracked-files=all`。
