**1. 改动清单**

契约骨架已完成；新增函数体均为 `raise NotImplementedError`，新增测试均跳过。改动留在工作区，未暂存、未提交。

- [config.py](/home/shawn/桌面/robot-data-platform.wt/m0-03-config-state-dir-runtime-log/src/rdp/infra/config.py)：不可变配置模型、来源信息、配置读取与错误转换契约。
- [state.py](/home/shawn/桌面/robot-data-platform.wt/m0-03-config-state-dir-runtime-log/src/rdp/infra/state.py)：不可变路径布局、文件名常量、目录初始化契约。
- [logging.py](/home/shawn/桌面/robot-data-platform.wt/m0-03-config-state-dir-runtime-log/src/rdp/infra/logging.py)：格式化、可注入时间、切分、上下文、uvicorn 接管及默认配置提示契约。
- [api/__init__.py](/home/shawn/桌面/robot-data-platform.wt/m0-03-config-state-dir-runtime-log/src/rdp/api/__init__.py)：请求编号中间件骨架，补充 `create_app` 契约；保留原签名和实现，第二步接入。
- [test_config.py](/home/shawn/桌面/robot-data-platform.wt/m0-03-config-state-dir-runtime-log/tests/test_config.py)：24 项配置测试清单。
- [test_state.py](/home/shawn/桌面/robot-data-platform.wt/m0-03-config-state-dir-runtime-log/tests/test_state.py)：17 项状态目录测试清单。
- [test_logging.py](/home/shawn/桌面/robot-data-platform.wt/m0-03-config-state-dir-runtime-log/tests/test_logging.py)：58 项日志测试清单。
- [test_web_app.py](/home/shawn/桌面/robot-data-platform.wt/m0-03-config-state-dir-runtime-log/tests/test_web_app.py)：保留既有测试，增加15项中间件测试清单。

未修改 `pyproject.toml`，未安装、未联网，未创建需手动清理的试验文件。

**2. `make check`**

最后一次命令：

```text
make check
```

十一项全部通过。末尾输出原文：

```text
================= 101 passed, 114 skipped, 1 warning in 4.84s ==================
[7/11] OpenAPI 过期检查
✨ openapi-typescript 7.13.0
🚀 /tmp/tmp.QCgz79mEZZ/openapi.json → /tmp/tmp.QCgz79mEZZ/schema.d.ts [11.8ms]
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

 RUN  v5.0.5 /home/shawn/桌面/robot-data-platform.wt/m0-03-config-state-dir-runtime-log/src/web


 Test Files  6 passed (6)
      Tests  19 passed (19)
   Start at  09:23:51
   Duration  1.03s (environment 42%, tests 29%, import 27%, transform 1%, setup 1%)
```

114 项跳过均属于本次骨架；warning 是既有 TestClient 的 httpx 弃用提示。

最后一次运行前，`git status --porcelain --untracked-files=all`：

```text
 M src/rdp/api/__init__.py
 M tests/test_web_app.py
?? src/rdp/infra/config.py
?? src/rdp/infra/logging.py
?? src/rdp/infra/state.py
?? tests/test_config.py
?? tests/test_logging.py
?? tests/test_state.py
```

运行后，同一命令输出：

```text
 M src/rdp/api/__init__.py
 M tests/test_web_app.py
?? src/rdp/infra/config.py
?? src/rdp/infra/logging.py
?? src/rdp/infra/state.py
?? tests/test_config.py
?? tests/test_logging.py
?? tests/test_state.py
```

**3. 契约变更申请、依赖申请**

无。`create_app` 的文档补充属于本次明确授权范围。

**4. 契约取舍与待评审事项**

- **配置文件缺失**：显式 `RDP_CONFIG` 指定文件不存在时报 `FileNotFoundError`，避免路径拼错后悄悄启动。未设置或为空串才使用缺省路径；缺省文件缺失时全部使用默认值。
- **路径和范围**：状态目录只接受绝对路径或用注入 home 展开的 `~`、`~/`，拒绝相对路径和 `..`。端口取 `1–65535`；级别限定四个大写值；保留期取 `1–3650` 天，上限十年是防误填的提案。host 仅做字符串约束，可绑定性留给启动入口。
- **配置错误与敏感值**：暂用内建 `ValueError/OSError`，不提前建立第4张的异常体系。pydantic 错误逐项转换并保留原因链；只回显本票已知字段的标量值，未知项和容器显示 `<已隐藏>`。这是对“实际值回显”的安全限制，未来敏感字段不得加入白名单。
- **默认配置提示**：第11张入口依次读配置、建目录、配置日志，再调用一次 `log_config_source`。提示为 INFO，遵循阈值；WARNING/ERROR 配置下不会落盘，这一点请评审确认。
- **状态目录**：数据库名提案为 `rdp.sqlite3`，锁文件为 `worker.lock`。已有目录只检查，不纠正权限；新建目录最终为 `0700`。失败保留已建空目录，方便重试；不创建数据库和锁文件。
- **日志文本**：明细每行缩进四个空格；含空格、等号、换行等字符的字段值用 JSON 双引号和转义表示。字段排序固定，关联编号追加在末尾。
- **时间与切分**：通过 `LogTime` 注入时钟和时区，由标准 handler 子类适配。按当地日历天判断过期，截止日保留，活动文件另计；跨零点首条日志才切分。同名归档追加合并，避免覆盖。运行期日志 I/O 失败沿用 `handleError`，可能丢记录；关闭其 stderr 错误输出以符合 systemd 约定。
- **重复配置及 uvicorn**：替换旧输出、关闭本模块旧 handler，避免重复写；初始化失败保留旧配置。接管三个 uvicorn logger；第11张须传 `log_config=None, access_log=False`，防止启动时覆盖。
- **请求编号**：服务端生成 `uuid4().hex`，忽略客户端编号，避免伪造关联。中间件包在完整框架栈之外，覆盖框架500响应、流式响应和后台任务。本轮仅交骨架，尚未接入现有工厂。
- **局部豁免**：一条 `S104` 对应工单指定的 `0.0.0.0`；两条 `reportUnusedClass` 对应尚未接入的私有骨架，第二步接入后删除。未放宽检查配置。
- **演示歧义**：验收9要求两次健康请求产生两条日志，验收7又禁止访问日志。当前契约不自动记录健康请求；建议演示使用主动写业务日志的测试路由，由评审决定。

`create_app` docstring 仅新增以下三处，原文未删改：

> Returns：应用包含 RequestIdMiddleware，包在框架错误处理中间件之外；每次 HTTP 请求生成 uuid4().hex 请求编号，忽略客户端同名头，所有已发送响应含唯一 X-Request-ID。

> Side Effects：请求处理期间绑定 request_id contextvar，业务日志自动关联响应编号，退出时恢复；中间件本身不产生访问日志，包含 /api/health；不在应用工厂配置全局 logger。

> Time Semantics：请求绑定持续到下游 ASGI 调用结束（含流式响应、后台任务），异常或取消也恢复。