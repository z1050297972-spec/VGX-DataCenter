**1. 逐条处理结果**

1. 新增等待过期重新计数测试，验证第二轮仍为四次 401、第五次 429；docstring 注明登录与本人改密共用计数逻辑。临时变异为 `count = row.failed_attempts`，失败输出：
   ```text
   E   AssertionError: assert <HTTPStatus.TOO_MANY_REQUESTS: 429> == 401
   ```
2. 新增业务授权过期测试，覆盖恰满 7 天及之后，断言认证失败且账号、会话无写入。临时变异为 `> SESSION_IDLE_TIMEOUT * 2`，两个用例均失败：
   ```text
   E   Failed: DID NOT RAISE AuthenticationError
   ```
   两处变异均已恢复，新测试全部通过。
3. 更新 `rdp.api.errors` 模块简表：明确 S1 兜底、405 的 `Allow`，补齐 502 的哈希资源繁忙及排队超时，并注明以主仓库规范 6.2 为准。
4. 补上成员重置口令返回 **403** 及“需要管理员权限”的断言。
5. `workers` 在 `try` 前初始化，逐项保存提交的 Future，保留 `finally` 回收。

本轮只改三个文件；临时目录已删除，未暂存、未提交。

**2. `make check`**

命令：`make check`。十一步全绿，pytest、Vitest 均 **0 skipped**。末尾输出原样：

```text
======================= 880 passed, 1 warning in 58.92s ========================
[7/11] OpenAPI 过期检查
✨ openapi-typescript 7.13.0
🚀 /tmp/tmp.xG5vmG8KIv/openapi.json → /tmp/tmp.xG5vmG8KIv/schema.d.ts [37.4ms]
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

 RUN  v5.0.5 /home/shawn/桌面/robot-data-platform.wt/m0-06-accounts-login-sessions/src/web


 Test Files  12 passed (12)
      Tests  127 passed (127)
   Start at  13:25:37
   Duration  4.60s (tests 45%, environment 33%, import 21%)
```

**3. 契约变更申请**

无。

**4. 拿不准的地方**

无。