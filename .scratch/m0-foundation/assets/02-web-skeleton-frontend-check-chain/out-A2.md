**1. 改动清单**

A2 契约骨架已完成，改动留在工作区，未暂存、未提交。

| 文件 | 改动 |
|---|---|
| `.gitignore` | 忽略前端依赖及其内部缓存。 |
| `Makefile` | 接入前端四步检查，预留第七步；扩展 `fmt`，新增 `api-types`。 |
| `pyproject.toml` | 启用外部包检查，新增基础层禁止依赖 Web 框架的合约。 |
| `scripts/check_contracts.py` | 仅更新 W3 的 `check_file` 契约，未改实现。 |
| `src/rdp/api/__init__.py` | `create_app` 签名、六项契约及桩。 |
| `src/rdp/api/health.py` | 健康响应模型、处理函数契约及桩。 |
| `src/rdp/api/openapi_export.py` | 确定性导出及命令行入口契约、桩。 |
| `src/web/tsconfig.json` | TypeScript 严格检查与无产物配置。 |
| `src/web/eslint.config.js` | 类型、React Hooks、复杂度、豁免和 TSDoc 规则。 |
| `src/web/vite.config.ts` | React、8600 端口代理、jsdom 和线程池配置。 |
| `src/web/.prettierrc.json` | 前端格式规范。 |
| `src/web/.prettierignore` | 排除生成文件、锁文件、依赖和构建产物。 |
| `src/web/index.html` | 中文页面入口及挂载容器。 |
| `src/web/src/main.tsx` | 应用挂载契约及桩。 |
| `src/web/src/router.tsx` | 单首页的代码式路由树及父路由契约桩。 |
| `src/web/src/api/client.ts` | 可注入 fetch 的客户端工厂契约及桩。 |
| `src/web/src/api/health.ts` | 健康请求、超时及取消契约桩。 |
| `src/web/src/api/openapi.json` | A2 健康接口契约草稿。 |
| `src/web/src/api/schema.d.ts` | 从草稿离线生成，未手改。 |
| `src/web/src/useHealth.ts` | 查询、缓存及失败状态契约桩。 |
| `src/web/src/HealthPage.tsx` | 页面属性、展示契约及桩。 |
| `src/web/src/api/client.test.ts` | 客户端契约的跳过清单。 |
| `src/web/src/api/health.test.ts` | 请求、失败、超时和取消的跳过清单。 |
| `src/web/src/useHealth.test.tsx` | 查询和缓存的跳过清单。 |
| `src/web/src/HealthPage.test.tsx` | 页面加载、成功、失败的跳过清单。 |
| `src/web/src/router.test.tsx` | 首页路由的跳过清单。 |
| `src/web/src/main.test.tsx` | 挂载入口的跳过清单。 |
| `tests/test_web_app.py` | 接口、托管和目录错误的跳过清单。 |
| `tests/test_openapi_export.py` | 导出及 CLI 的跳过清单。 |
| `tests/test_contract_scope.py` | W3 路径范围的跳过清单。 |

**2. `make check`**

最后一次命令：`make check`，退出码 **0**。末尾原样输出：

```text
======================== 61 passed, 34 skipped in 3.63s ========================
# A2 的导出函数是契约桩；派工 B 在此接入 [7/11] OpenAPI 过期检查。
# B 将导出与生成结果写入临时目录并逐字节比较，不改入库文件。
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


 Test Files  6 skipped (6)
      Tests  19 skipped (19)
   Start at  00:44:45
   Duration  424ms (environment 97%, import 2%, worker 1%, transform 1%)

```

运行前，`git status --porcelain --untracked-files=all`：

```text
 M .gitignore
 M Makefile
 M pyproject.toml
 M scripts/check_contracts.py
 M src/rdp/api/__init__.py
?? src/rdp/api/health.py
?? src/rdp/api/openapi_export.py
?? src/web/.prettierignore
?? src/web/.prettierrc.json
?? src/web/eslint.config.js
?? src/web/index.html
?? src/web/src/HealthPage.test.tsx
?? src/web/src/HealthPage.tsx
?? src/web/src/api/client.test.ts
?? src/web/src/api/client.ts
?? src/web/src/api/health.test.ts
?? src/web/src/api/health.ts
?? src/web/src/api/openapi.json
?? src/web/src/api/schema.d.ts
?? src/web/src/main.test.tsx
?? src/web/src/main.tsx
?? src/web/src/router.test.tsx
?? src/web/src/router.tsx
?? src/web/src/useHealth.test.tsx
?? src/web/src/useHealth.ts
?? src/web/tsconfig.json
?? src/web/vite.config.ts
?? tests/test_contract_scope.py
?? tests/test_openapi_export.py
?? tests/test_web_app.py
```

运行后，同一命令输出：

```text
 M .gitignore
 M Makefile
 M pyproject.toml
 M scripts/check_contracts.py
 M src/rdp/api/__init__.py
?? src/rdp/api/health.py
?? src/rdp/api/openapi_export.py
?? src/web/.prettierignore
?? src/web/.prettierrc.json
?? src/web/eslint.config.js
?? src/web/index.html
?? src/web/src/HealthPage.test.tsx
?? src/web/src/HealthPage.tsx
?? src/web/src/api/client.test.ts
?? src/web/src/api/client.ts
?? src/web/src/api/health.test.ts
?? src/web/src/api/health.ts
?? src/web/src/api/openapi.json
?? src/web/src/api/schema.d.ts
?? src/web/src/main.test.tsx
?? src/web/src/main.tsx
?? src/web/src/router.test.tsx
?? src/web/src/router.tsx
?? src/web/src/useHealth.test.tsx
?? src/web/src/useHealth.ts
?? src/web/tsconfig.json
?? src/web/vite.config.ts
?? tests/test_contract_scope.py
?? tests/test_openapi_export.py
?? tests/test_web_app.py
```

前后完全相同。`make fmt` 通过；`make api-types` 按 A2 预期因 `main()` 抛出 `NotImplementedError` 失败，未覆盖草稿。

**3. 契约变更申请、依赖申请**

无。W3 文档变更按已批准要求执行；依赖表和锁文件未改。

**4. 拿不准、需要评审决定的地方**

本次新增契约中的以下选择请随骨架评审确认：

- 构建目录或入口缺失：创建应用时抛 `FileNotFoundError`；目录路径实际为文件：`NotADirectoryError`；入口不是普通文件或越界：`ValueError`。
- 健康请求超时 **5000 ms**，缓存有效期 **1000 ms**；不轮询、不自动重试、不因窗口聚焦刷新。
- 导出先序列化再写文件；写入失败可能留下截断文件，调用方丢弃失败产物。
- W3 按解析后的绝对路径判断所属仓库的 `tests/`，不依赖当前工作目录。

A2 的业务函数均未实现，跳过的测试不代表功能已验证。违规提交和钩子试验仍由 Claude 完成。

**5. 检查配置的要点**

- **TypeScript**：`strict`、`noUncheckedIndexedAccess`、`isolatedModules`、`verbatimModuleSyntax`；ES2022、Bundler 模块解析、React JSX。`noEmit: true`、`incremental: false`，不生成 `.tsbuildinfo`。按已确认环境采用 `skipLibCheck: true`，跳过声明文件内部检查，源码仍严格检查。
- **ESLint**：`strictTypeChecked`、React Hooks flat recommended；复杂度 ≤ 10、参数 ≤ 5、语句 ≤ 40。禁止 console、直接 fetch 及 `window/self/globalThis.fetch`。
- **豁免检查**：多余豁免报错；启用 `no-unlimited-disable`、`require-description`；禁止 `@ts-ignore`、`@ts-nocheck`，`@ts-expect-error` 要有至少三个字符的说明。
- **局部放宽**：五个契约桩各有一条带理由的 `no-unused-vars` 豁免，B 使用参数后删除；默认 fetch 读取处有单条 `no-restricted-globals` 豁免。没有关闭严格类型或 Hooks 规则。
- **TSDoc**：不启用 `check-param-names`，使无参函数可以保留 `@param 无 - 无参数`；真实参数缺文档仍由 `require-param` 检查。
- **Prettier**：行宽 100、两空格、分号、双引号、尾逗号、LF。
- **忽略**：ESLint 排除依赖、构建产物及 `schema.d.ts`；Prettier 另排除锁文件和 `openapi.json`。两个生成文件由生成器保持格式，避免与逐字节过期检查冲突。
- **import-linter**：启用 `include_external_packages`，禁止 `rdp.infra` 依赖 `fastapi`、`starlette`、`uvicorn`，预留领域包登记位置。
- **ruff / basedpyright**：未调整。钩子未改。

**6. TSDoc 规则与 Vitest**

| 契约项 | 必须出现 | 不能为空 |
|---|---|---|
| 首行职责 | `require-jsdoc` + `require-description` | `require-description` + `match-description` |
| `@param` | `require-tags`；实际参数另由 `require-param` 核对 | `require-param-description` + `match-description` |
| `@returns` | `require-tags` | `match-description` |
| `@throws` | `require-tags` | `match-description` |
| `@sideEffects` | `require-tags` | `match-description` |
| `@timeSemantics` | `require-tags` | `match-description` |

以上规则均为 `jsdoc/*`。非空表达式为 `\S`，已实测缺项、空白、箭头函数缺文档、第二个函数漏标签均失败；中文、`@throws 无` 和合法单条豁免通过。六项存在与非空没有未覆盖项；职责是否准确、单位和取值范围是否完整仍需人工评审。

Vitest 使用 **`threads`** 池，在沙箱里实际运行成功，**6 个测试文件、19 个测试全部按骨架要求跳过**。TSDoc 探针通过内存 `lintText` 执行，未留下试验文件。