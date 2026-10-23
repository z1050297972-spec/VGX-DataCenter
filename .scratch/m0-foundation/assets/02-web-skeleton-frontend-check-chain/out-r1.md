六条均已修复，**十一条检查全绿：pytest 101 passed，Vitest 19 passed**。本轮仅改指定的六个文件，已批准的生产契约未改，未暂存、未提交。

1. SPA 回退现在只处理非 `/api` 路径的 GET 404；API 404 保留原 `detail` 和响应头。
2. 非 GET 分支返回通用 404 JSON，不再调用 `_unknown_api()`。
3. 原子替换改用 `Path.replace`，删除 `PTH105` 豁免；docstring 保持不变。
4. `test_health_response` 改用 `_request()`，删除类型豁免和无用的 `tmp_path`。
5. 路由测试使用同一路由树创建独立 router，并断言模块单例的历史和状态未变。
6. 删除重复 `resolve()`、修正 StaticFiles 默认行为注释、合并 `.prettierignore` 理由；说明保留显式计时器是为了在请求提前结束时主动清理，继续支持假时钟验证。

新增测试 `test_api_404_preserves_detail` 已先红后绿。首次单独运行时，**预期 404，实际得到 200**；修复后用同一命令通过：

```text
timeout 120s .venv/bin/pytest tests/test_web_app.py::test_api_404_preserves_detail -q --tb=short
```

最终命令：`timeout 600s make check`，退出码 **0**。末尾原样输出：

```text
======================== 101 passed, 1 warning in 4.77s ========================
[7/11] OpenAPI 过期检查
✨ openapi-typescript 7.13.0
🚀 /tmp/tmp.rGRoAtxciC/openapi.json → /tmp/tmp.rGRoAtxciC/schema.d.ts [11.9ms]
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
   Start at  08:32:33
   Duration  1.12s (environment 43%, tests 29%, import 27%, transform 1%, setup 1%)

```

检查前后 `git status --porcelain --untracked-files=all` 完全相同。临时样例已清理，`pgrep -af '[p]ytest'` 无输出。唯一警告仍是既有的 `StarletteDeprecationWarning`。