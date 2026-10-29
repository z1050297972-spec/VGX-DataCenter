**1. 本轮改动清单**

- `scripts/setup.sh`：固定四个官方 SHA256，改用 releases/download；删除 API 元数据解析和专用限流诊断，保留通用 403/429 提示。
- `tests/setup_support.py`：假 curl 禁止 API 请求；本地归档只替换临时脚本副本的摘要，使用真实 SHA256 校验。
- `tests/test_ops_setup_downloads.py`：验证官方摘要、直接下载、两种架构、摘要不符及官方重定向；改写 API 专用测试。
- `tests/test_ops_setup_script.py`：更新固定摘要与非法重定向回归测试。

未暂存、未提交；临时检查日志已删除。

**2. `make check`**

本轮仅运行一次，退出码 0：**pytest 2103 passed / 0 skipped；Vitest 250 passed / 0 skipped**。

```bash
make check > /tmp/rdp-setup-review4-check.log 2>&1
```

末尾输出原样：

```text
================= 2103 passed, 1 warning in 332.22s (0:05:32) ==================
[7/11] OpenAPI 过期检查
✨ openapi-typescript 7.13.0
🚀 /tmp/tmp.oxgc1MLcyb/openapi.json → /tmp/tmp.oxgc1MLcyb/schema.d.ts [72.1ms]
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

 RUN  v5.0.5 /home/shawn/桌面/robot-data-platform.wt/m0-11-ops-entry-systemd/src/web


 Test Files  22 passed (22)
      Tests  250 passed (250)
   Start at  00:19:42
   Duration  7.87s (tests 49%, environment 29%, import 21%)
```

运行前 `git status --porcelain --untracked-files=all`：

```text
 M scripts/setup.sh
 M tests/setup_support.py
 M tests/test_ops_setup_downloads.py
 M tests/test_ops_setup_script.py
```

运行后：

```text
 M scripts/setup.sh
 M tests/setup_support.py
 M tests/test_ops_setup_downloads.py
 M tests/test_ops_setup_script.py
```

**3. 契约变更、依赖申请**

按本轮决定实施，无额外契约申请、无新增依赖。

帮助原句：

```text
uv：astral-sh/uv官方GitHub release的uv-<target>.tar.gz。
pnpm：pnpm/pnpm官方GitHub release的pnpm-linux-<架构>.tar.gz（官方 tar.gz，glibc 版），不依赖corepack。
```

新句：

```text
uv：使用脚本内固定的SHA256，从github.com/astral-sh/uv/releases/download/<版本>/uv-<target>.tar.gz下载。
pnpm：使用脚本内固定的SHA256，从github.com/pnpm/pnpm/releases/download/v<版本>/pnpm-linux-<架构>.tar.gz下载（官方 tar.gz，glibc 版），不依赖corepack。
```

后续 API metadata/digest 说明替换为：

```text
uv/pnpm：固定摘要按工具和架构维护；升级版本须同步更新版本表和SHA256表。
不请求GitHub API；缺少有效固定摘要就拒绝，绝不跳过校验。
```

版本表上方已注明升级时必须同时更新两张表。Node 的 SHASUMS256.txt 方式未改。

**4. 拿不准的地方**

无待决事项。保留通用 403/429“被拒绝或限流”提示，不再解释为 API 配额耗尽或报告 API reset 时间。所有 4xx 仍不重试。

本轮未联网；真实下载演练由执行线继续验收。

**5. 本轮先红后绿**

- `test_release_downloads_do_not_use_api[uv/pnpm]`：两项均红，实际请求仍指向 API；修复后通过。
- `test_pinned_release_digests_match_approved_values`：红，缺少固定摘要表；补齐后通过。
- `test_fixed_digest_mismatch_never_publishes[uv/pnpm]`：两项初绿，既有 SHA256 拒绝机制已适用于固定表。
- `test_architecture_selects_pinned_glibc_archive`：四项初绿，固定表与既有架构映射正确对应。
- `test_official_asset_redirect_preserves_digest_check`：两个主机均初绿，复用了既有安全重定向和摘要校验。
- `test_release_fixed_digest`：初绿，固定表读取已拒绝缺失或非法摘要。
- `test_rejects_untrusted_release_redirects`：初绿，HTTPS/主机白名单已拒绝 HTTP、第三方及 API 重定向。
- `test_download_denied_or_throttled_is_explicit[403/429]`：两项初绿，通用错误分支已随入口修复完成。

API 专用的 reset 时间测试已删除；其余版本、归档安全、TLS 重试和预算测试已迁移到直接下载路径并通过。