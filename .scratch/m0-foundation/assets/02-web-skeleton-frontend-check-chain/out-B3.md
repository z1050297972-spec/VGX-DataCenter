**1. 改动清单**

派工 B 已完成：**十一条检查全绿，pytest 100 passed，Vitest 19 passed，无骨架跳过**。改动留在工作区，未暂存、未提交。

| 文件 | 改动 |
|---|---|
| `Makefile` | 接入第七步过期检查，与 `api-types` 共用生成命令。 |
| `scripts/check_contracts.py` | 实现 W3，按解析后的实际路径限定测试豁免。 |
| `src/rdp/api/__init__.py` | 实现应用工厂、目录校验、API 边界和 SPA 托管。 |
| `src/rdp/api/health.py` | 返回固定健康响应。 |
| `src/rdp/api/openapi_export.py` | 实现确定性原子导出及 CLI。 |
| `src/web/.prettierignore` | 更新真正导出文件的说明。 |
| `src/web/eslint.config.js` | 按 G2 启用参数名检查，移除无参函数的参数标签要求。 |
| `src/web/vite.config.ts` | 接入 Vitest 环境适配文件，更新线程池说明。 |
| `src/web/src/api/client.ts` | 实现可注入传输的客户端工厂。 |
| `src/web/src/api/health.ts` | 实现响应校验、超时和取消。 |
| `src/web/src/api/openapi.json` | 替换为真实 FastAPI 导出。 |
| `src/web/src/api/schema.d.ts` | 从真实导出重新生成。 |
| `src/web/src/useHealth.ts` | 实现查询、缓存隔离和 G1 行为。 |
| `src/web/src/HealthPage.tsx` | 实现加载、成功、失败展示及稳定客户端。 |
| `src/web/src/router.tsx` | 实现首页路由，移除 `getRootRoute` 桩。 |
| `src/web/src/main.tsx` | 仅保留浏览器挂载入口。 |
| `src/web/src/mountWeb.tsx` | 迁入并实现原签名、原 TSDoc 的挂载函数。 |
| `src/web/src/testSetup.ts` | 补齐 jsdom 的相对 URL Request 和滚动方法；不修改 fetch。 |
| `src/web/src/api/client.test.ts` | 实现客户端测试。 |
| `src/web/src/api/health.test.ts` | 实现请求、错误、超时和取消测试。 |
| `src/web/src/useHealth.test.tsx` | 实现查询状态、缓存、刷新和取消测试。 |
| `src/web/src/HealthPage.test.tsx` | 实现页面四项测试。 |
| `src/web/src/router.test.tsx` | 验证首页路由。 |
| `src/web/src/main.test.tsx` | 验证空容器及真实挂载流程。 |
| `tests/test_web_app.py` | 实现原清单，补充 API 方法边界和 `404.html` 回退测试。 |
| `tests/test_openapi_export.py` | 实现原清单、G3 两种失败测试和帮助参数边界测试。 |
| `tests/test_contract_scope.py` | 实现 W3 六项测试。 |
| `tests/test_check_contracts.py` | 将旧的全局测试豁免断言更新为 W3 规则。 |

依赖表、锁文件、钩子未改；没有 asyncio 或 socket 补丁。

**2. `make check`**

最后命令：`timeout 600s make check`，退出码 **0**。末尾原样输出：

```text
======================== 100 passed, 1 warning in 4.96s ========================
[7/11] OpenAPI 过期检查
✨ openapi-typescript 7.13.0
🚀 /tmp/tmp.dALfG3gZFh/openapi.json → /tmp/tmp.dALfG3gZFh/schema.d.ts [12.1ms]
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

 RUN  v5.0.5 /home/shawn/桌面/robot-data-platform.wt/m0-02-web-skeleton-frontend-check-chain/src/web


 Test Files  6 passed (6)
      Tests  19 passed (19)
   Start at  07:59:31
   Duration  1.06s (environment 41%, tests 29%, import 28%, transform 2%, setup 1%)

```

`make api-types` 后紧接 `make check-api-types` 的输出：

```text
.venv/bin/python -m rdp.api.openapi_export "src/web/src/api/openapi.json" && src/web/node_modules/.bin/openapi-typescript "src/web/src/api/openapi.json" -o "src/web/src/api/schema.d.ts"
✨ openapi-typescript 7.13.0
🚀 src/web/src/api/openapi.json → src/web/src/api/schema.d.ts [11.9ms]
✨ openapi-typescript 7.13.0
🚀 /tmp/tmp.7w7WMftTLA/openapi.json → /tmp/tmp.7w7WMftTLA/schema.d.ts [11.8ms]
OpenAPI 与生成类型均未过期
```

检查前的 `git status --porcelain --untracked-files=all`：

```text
 M Makefile
 M scripts/check_contracts.py
 M src/rdp/api/__init__.py
 M src/rdp/api/health.py
 M src/rdp/api/openapi_export.py
 M src/web/.prettierignore
 M src/web/eslint.config.js
 M src/web/src/HealthPage.test.tsx
 M src/web/src/HealthPage.tsx
 M src/web/src/api/client.test.ts
 M src/web/src/api/client.ts
 M src/web/src/api/health.test.ts
 M src/web/src/api/health.ts
 M src/web/src/api/openapi.json
 M src/web/src/api/schema.d.ts
 M src/web/src/main.test.tsx
 M src/web/src/main.tsx
 M src/web/src/router.test.tsx
 M src/web/src/router.tsx
 M src/web/src/useHealth.test.tsx
 M src/web/src/useHealth.ts
 M src/web/vite.config.ts
 M tests/test_check_contracts.py
 M tests/test_contract_scope.py
 M tests/test_openapi_export.py
 M tests/test_web_app.py
?? src/web/src/mountWeb.tsx
?? src/web/src/testSetup.ts
```

检查后的同一命令输出：

```text
 M Makefile
 M scripts/check_contracts.py
 M src/rdp/api/__init__.py
 M src/rdp/api/health.py
 M src/rdp/api/openapi_export.py
 M src/web/.prettierignore
 M src/web/eslint.config.js
 M src/web/src/HealthPage.test.tsx
 M src/web/src/HealthPage.tsx
 M src/web/src/api/client.test.ts
 M src/web/src/api/client.ts
 M src/web/src/api/health.test.ts
 M src/web/src/api/health.ts
 M src/web/src/api/openapi.json
 M src/web/src/api/schema.d.ts
 M src/web/src/main.test.tsx
 M src/web/src/main.tsx
 M src/web/src/router.test.tsx
 M src/web/src/router.tsx
 M src/web/src/useHealth.test.tsx
 M src/web/src/useHealth.ts
 M src/web/vite.config.ts
 M tests/test_check_contracts.py
 M tests/test_contract_scope.py
 M tests/test_openapi_export.py
 M tests/test_web_app.py
?? src/web/src/mountWeb.tsx
?? src/web/src/testSetup.ts
```

前后完全相同。`pgrep -af '[p]ytest'` 无输出；本轮临时样例已清理。

**3. 契约变更申请、依赖申请**

无新增申请。

G3 仅修改了 `export_openapi` 的 `Raises:`、`Side Effects:`；`main` 继续引用其失败语义，docstring 未改。改后的原文：

```text
    Raises:
        OSError: 输出父目录不存在、目标是目录、无写权限，或创建、写入、替换、清理临时文件失败。
        TypeError: create_app(None).openapi() 含无法序列化为 JSON 的值。
        ValueError: OpenAPI 含非有限数，无法输出标准 JSON。

    Side Effects:
        先完整序列化 create_app(None).openapi()，再写同目录临时文件；键排序，缩进为 2 个空格，
        ensure_ascii=False、allow_nan=False，末尾一个换行，编码 UTF-8。
        临时文件关闭成功后用 os.replace 原子替换目标；序列化、写入或替换失败时目标保持原样，
        并删除临时文件。若文件系统连清理也拒绝，抛出该 OSError，不把清理失败伪装成成功。
        不创建服务器或 socket，不访问导航层和存储根；成功后只保留指定输出文件。
```

已核对：后端公开函数的签名、类型不变，除 G3 外的原有公开契约文档不变。

**4. 拿不准、需要评审决定的地方**

无待决阻塞。保留了要求记录的上游警告，未为它修改依赖或配置：

```text
StarletteDeprecationWarning: Using `httpx` with `starlette.testclient` is deprecated; install `httpx2` instead.
```

**5. 先红后绿**

下列测试最终全部通过。“首次绿”均单独运行过，原因逐项列明。

| pytest 测试 | 首次结果 |
|---|---|
| `test_health_response` | 上轮红：`create_app` 桩；本轮复跑绿。 |
| `test_health_openapi` | 首次绿：健康接口已注册响应模型。 |
| `test_api_only_root` | 首次绿：FastAPI 默认首页 404。 |
| `test_spa_root` | 红：首页返回 404。 |
| `test_spa_nested_route` | 红：不存在的前端路由返回 404。 |
| `test_static_file` | 首次绿：StaticFiles 已负责文件传输。 |
| `test_unknown_api` | 红：未知 API 回退为首页 200。 |
| `test_non_get_no_fallback` | 红：HEAD 被回退为 200。 |
| `test_static_boundary` | 首次绿：StaticFiles 已限制越界路径和软链接。 |
| `test_missing_dist` | 红：抛 RuntimeError，异常类型不符合契约。 |
| `test_dist_is_file` | 红：抛 RuntimeError，未按契约拒绝普通文件。 |
| `test_missing_index` | 红：创建时未检查入口缺失。 |
| `test_index_is_directory` | 红：入口为目录时未报错。 |
| `test_index_symlink_outside` | 红：未拒绝越界入口软链接。 |
| `test_dist_permission_error` | 首次绿：显式 stat 已保留权限错误。 |
| `test_relative_dist` | 红：切换 cwd 后找不到相对构建目录。 |
| `test_independent_apps` | 首次绿：应用和静态实例已独立创建。 |
| `test_api_namespace_all_methods` | 红：HEAD 可读取 API 路径下的静态文件。 |
| `test_custom_404_does_not_override_spa` | 红：StaticFiles 返回自带 `404.html`。 |
| `test_deterministic_export` | 红：导出函数桩。 |
| `test_export_matches_app` | 首次绿：已直接导出应用 OpenAPI。 |
| `test_overwrite_export` | 首次绿：已有实现只写指定文件，不启动服务。 |
| `test_invalid_output` | 首次绿：标准文件操作已透传路径错误。 |
| `test_serialization_error` | 红：NaN 被默认序列化接受。 |
| `test_atomic_failure[write]` | 红：未使用临时文件，写入故障未触发。 |
| `test_atomic_failure[replace]` | 红：未调用原子替换，替换故障未触发。 |
| `test_cli_success` | 红：CLI 入口桩。 |
| `test_cli_help` | 红：帮助分支抛 SystemExit，未返回 0。 |
| `test_cli_arguments` | 首次绿：argparse 校验及退出码转换已覆盖。 |
| `test_cli_export_error` | 红：失败诊断缺少目标路径，并带 traceback。 |
| `test_cli_stream_error` | 红：argparse 吞掉输出流 OSError。 |
| `test_cli_argv_source` | 首次绿：argparse 已区分显式参数与 None。 |
| `test_cli_help_does_not_hide_unknown_arguments` | 红：帮助参数掩盖未知选项，返回 0。 |
| `test_source_test_prefix` | 红：src 下的 `test_` 仍被跳过。 |
| `test_script_test_prefix` | 首次绿：W3 路径条件已覆盖 scripts。 |
| `test_repository_tests_prefix` | 首次绿：仅仓库 tests 中的 `test_` 获得豁免。 |
| `test_unrelated_tests_directory` | 首次绿：判断实际祖先路径，不按目录名字匹配。 |
| `test_scope_independent_of_cwd` | 首次绿：脚本位置和 resolve 已消除 cwd 影响。 |
| `test_resolved_symlink_scope` | 首次绿：resolve 已按链接目标判定。 |
| `test_test_functions_outside_repository_checked` | 首次绿：按 W3 更新旧回归断言，前述实现已覆盖。 |

Vitest 标题省略共同前缀“验证契约：”。

| Vitest 测试 | 首次结果 |
|---|---|
| 创建客户端不发请求且不修改全局 fetch | 红：客户端工厂桩。 |
| 注入 fetch 收到同源 /api/health 请求且不同客户端相互独立 | 红：Node Request 不接受浏览器相对 URL；补齐测试环境后绿。 |
| 200 和 status=ok 返回生成类型的健康响应 | 红：请求函数桩。 |
| 非 2xx、缺少响应和非法载荷均拒绝 Promise | 红：`status=failed` 被接受。 |
| 传输异常保留失败，不伪装为 ok | 首次绿：Promise 拒绝已自然透传。 |
| HEALTH_TIMEOUT_MS 到期中止请求且不重试 | 红：5000 ms 时信号未中止。 |
| 已取消信号不发请求，运行中取消传播到注入 fetch | 红：预先取消仍发送请求。 |
| QueryClientProvider 内加载、成功和失败状态正确 | 红：hook 桩。 |
| 缓存有效期内不重复请求，过期后重新挂载可获取 | 红：默认缓存有效期为 0，提前重复请求。 |
| 不同注入客户端不共享健康缓存 | 红：第二个客户端读到第一个的成功缓存。 |
| 失败不自动重试，聚焦和时间推进不触发轮询 | 红：聚焦触发第二次请求。 |
| 取消查询将 AbortSignal 传递给请求 | 首次红于断言早于异步通知；改为等待状态更新后绿，原实现已传递信号。 |
| React Testing Library 渲染成功页面显示后端正常 | 红：页面组件桩。 |
| React Testing Library 渲染失败页面显示 Alert 且无成功提示 | 红：没有失败 Alert。 |
| 加载中显示提示，不提前显示成功 | 红：加载时页面为空。 |
| 默认客户端跨重渲染稳定且页面不修改 URL | 红：重渲染新增客户端和缓存条目。 |
| 代码式路由树将 / 映射到健康页面 | 红：父路由桩在初始化时抛错。 |
| 空容器同步报错且不挂载 | 首次绿：桩本来就抛 Error；下一项进一步区分桩与实现。 |
| 有效容器创建 React 根并提供查询和路由上下文 | 首次红于原生 ESM 不支持 spyOn；改用保留真实行为的模块 spy 后，再次红于挂载桩。 |

**6. 检查配置的变化**

G2 后的规则如下，均为 `jsdoc/*`：

| 项目 | 必须出现 | 不能为空 |
|---|---|---|
| 职责 | `require-jsdoc`、`require-description` | `require-description`、`match-description` |
| 真实参数的 `@param` | `require-param`；`check-param-names` 核对名称 | `require-param-description`、`match-description` |
| `@returns` | `require-tags` | `match-description` |
| `@throws` | `require-tags` | `match-description` |
| `@sideEffects` | `require-tags` | `match-description` |
| `@timeSemantics` | `require-tags` | `match-description` |

无参函数不写 `@param`。已实测：无参无标签通过，真实参数漏标签失败，不存在的参数名失败。

过期检查使用 `mktemp -d` 创建临时目录，以同一套生成命令导出 JSON 和类型，用 `cmp -s` 分别逐字节比较。`trap` 在成功、失败或中断时清理目录；不一致时退出失败并提示：

```text
OpenAPI 或生成类型已过期，请运行 make api-types
```

其余规则集和阈值未放宽。五处骨架参数豁免已删除；G3 的直接 `os.replace` 保留一条带理由的 `PTH105` 豁免。