## 逐条处理结果

1. **token 主机限制**：新增参数化测试，分别覆盖首轮加入和签名过期后重解析时，最终地址为镜像或 CDN 的四种组合。镜像地址携带 token，CDN 地址传给 RPC 的 token 为 `None`。变异验证中，分别让首轮或重解析总是传 token、同时移除适配器拒绝时，新测试均失败。

2. **重定向跳数**：补充第五跳返回 `200` 时成功、仍返回合法 `302` 时失败的边界测试，并断言不会访问第六跳。  
   **单独把 `range(MAX_REDIRECT_HOPS + 1)` 改成 `range(100)` 仍会通过**：循环内部另有 `hop == MAX_REDIRECT_HOPS` 守卫，该单行变异不改变可观察行为。将循环上界和这个独立守卫同时放宽后，超限测试失败。实现没有因此修改。

3. **空模型目标不覆盖**：新增竞争场景测试：目标在启动检查后、最终改名前出现，且是空目录。测试断言操作失败、目标目录 inode 不变、暂存保留。把 `RENAME_NOREPLACE` 标志改为 `0` 后，该测试失败。

本轮只保留了测试改动；临时变异均已恢复，未暂存、未提交。

## `make check`

最后一次运行的命令：

```bash
make check > /tmp/m2-downloads-review-final.log 2>&1; status=$?; tail -35 /tmp/m2-downloads-review-final.log; exit "$status"
```

末尾输出原文：

```text
.venv/lib/python3.12/site-packages/fastapi/testclient.py:1
.venv/lib/python3.12/site-packages/fastapi/testclient.py:1
.venv/lib/python3.12/site-packages/fastapi/testclient.py:1
.venv/lib/python3.12/site-packages/fastapi/testclient.py:1
.venv/lib/python3.12/site-packages/fastapi/testclient.py:1
.venv/lib/python3.12/site-packages/fastapi/testclient.py:1
.venv/lib/python3.12/site-packages/fastapi/testclient.py:1
  /home/shawn/桌面/robot-data-platform.wt/m2-downloads/.venv/lib/python3.12/site-packages/fastapi/testclient.py:1: StarletteDeprecationWarning: Using `httpx` with `starlette.testclient` is deprecated; install `httpx2` instead.
    from starlette.testclient import TestClient as TestClient  # noqa

-- Docs: https://docs.pytest.org/en/stable/how-to/capture-warnings.html
================= 2710 passed, 8 warnings in 94.60s (0:01:34) ==================
[7/11] OpenAPI 过期检查
✨ openapi-typescript 7.13.0
🚀 /tmp/tmp.gPM4mdinJN/openapi.json → /tmp/tmp.gPM4mdinJN/schema.d.ts [118.8ms]
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

 RUN  v5.0.5 /home/shawn/桌面/robot-data-platform.wt/m2-downloads/src/web


 Test Files  39 passed (39)
      Tests  370 passed (370)
   Start at  01:08:45
   Duration  10.69s (tests 55%, import 22%, environment 21%, transform 1%)

```

退出码为 0；临时检查日志已删除。