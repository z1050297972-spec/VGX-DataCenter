## 处理结果

1. **筛选模式尾部斜杠**：分别新增包含和排除模式测试，验证 `meta/` 只匹配该目录下的文件。临时去掉各自的补星逻辑后，对应测试均失败；验证后已恢复原实现。
2. **容量余量与边界**：新增测试，验证可用空间介于待下载量和“待下载量＋余量”之间时拒绝计划、诊断包含余量；恰好等于两者之和时通过。临时去掉余量、以及将 `<` 改为 `<=` 后，测试均失败；验证后已恢复原实现。
3. **副作用契约**：在 `UrllibTransport.request` 的 `Side Effects:` 中补充了隔离子进程的启动、回收及超时终止说明。

改动留在工作区，未暂存或提交。

## `make check`

最后一次运行命令：

```bash
make check > /tmp/m2-download-review-check.log 2>&1
```

退出码为 0，末尾输出原样如下：

```text
================= 2530 passed, 8 warnings in 78.97s (0:01:18) ==================
[7/11] OpenAPI 过期检查
✨ openapi-typescript 7.13.0
🚀 /tmp/tmp.vTHMbTIElv/openapi.json → /tmp/tmp.vTHMbTIElv/schema.d.ts [104.1ms]
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


 Test Files  34 passed (34)
      Tests  329 passed (329)
   Start at  19:42:59
   Duration  10.10s (tests 50%, environment 28%, import 21%, transform 1%)
```

临时检查日志已删除。