**1. 本轮改动清单**

- `scripts/setup.sh`：修复有限重试、GitHub 限流诊断、pnpm 归档安装、版本比较及非交互缺配置检查。
- `tests/setup_support.py`：模拟真实 uv 输出、pnpm tar.gz、TLS 错误、HTTP 状态及响应头。
- `tests/test_ops_setup_script.py`：为工具测试补齐有效配置前置条件，更新手动重试相关断言。
- `tests/test_ops_setup_downloads.py`：新增 32 项回归测试。

未暂存、未提交；临时检查日志已删除。

**2. `make check`**

本轮仅运行一次，退出码 0：**pytest 2087 passed / 0 skipped；Vitest 250 passed / 0 skipped**。

```bash
make check > /tmp/rdp-setup-review2-check.log 2>&1
```

末尾输出原样：

```text
================= 2087 passed, 1 warning in 307.51s (0:05:07) ==================
[7/11] OpenAPI 过期检查
✨ openapi-typescript 7.13.0
🚀 /tmp/tmp.yMFFpyYlhZ/openapi.json → /tmp/tmp.yMFFpyYlhZ/schema.d.ts [70.6ms]
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
   Start at  22:23:32
   Duration  7.13s (tests 50%, environment 29%, import 20%)
```

运行前 `git status --porcelain --untracked-files=all`：

```text
 M scripts/setup.sh
 M tests/setup_support.py
 M tests/test_ops_setup_script.py
?? tests/test_ops_setup_downloads.py
```

运行后：

```text
 M scripts/setup.sh
 M tests/setup_support.py
 M tests/test_ops_setup_script.py
?? tests/test_ops_setup_downloads.py
```

**3. 契约变更申请、依赖申请**

无新增申请。帮助仅按本轮授权更正一行：

原文：
```text
pnpm：pnpm/pnpm官方GitHub release的pnpm-linux-<架构>独立可执行文件，不依赖corepack。
```

现文：
```text
pnpm：pnpm/pnpm官方GitHub release的pnpm-linux-<架构>.tar.gz（官方 tar.gz，glibc 版），不依赖corepack。
```

其余帮助未改；实现注释同步说明重试分类、版本边界及归档定位规则。

**4. 拿不准的地方**

无待决事项。

- 使用手动分类重试，关闭 curl 自身重试；每次文件下载最多重试两次，重试和重定向共用顶部时间预算。
- 所有 4xx 均不重试；403/429 含限流文字时报告 reset 时间，缺失或非法时明确说明时间未知。
- pnpm 必须在根目录或下一层找到唯一普通可执行文件；未知、歧义或不安全结构明确失败。

本轮没有联网或真实安装，实际发行包演练由执行线继续验收。

**5. 本轮先红后绿**

五项缺陷均先复现失败，再修复。以下参数化分支全部最终通过。

- `test_missing_noninteractive_config_stops_before_tools`：红，先尝试下载并返回 1，而非直接返回 2。
- `test_uv_real_version_output_is_accepted[True/False]`：两项均红，分别误判已有 uv、拒绝新安装 uv 的平台后缀。
- `test_pnpm_official_archive_layouts[root/pnpm-linux-x64]`：两项均红，旧资产名无法匹配官方 tar.gz。
- `test_tls_failure_retries_then_verifies_download`：红，首次 TLS 错误后立即失败。
- `test_github_rate_limit_reports_reset_without_retry[403/429]`：两项均红，缺少限流和重试时间提示。
- `test_http_client_error_is_not_retried_after_body_timeout`：红，已收到 403 后仍因读取超时重试三次。
- `test_retry_classification_is_bounded`：7 项初绿，已实现的分类和次数限制覆盖传输错误、证书错误及 HTTP 错误。
- `test_download_total_budget_covers_blocked_request`：初绿，外层 timeout 已限制阻塞请求。
- `test_total_budget_is_shared_by_tls_retries`：初绿，重试已共用同一开始时间。
- `test_rate_limit_without_valid_reset_is_explicit`：2 项初绿，限流实现已包含缺失／非法时间回退。
- `test_version_comparison_requires_token_boundary`：6 项初绿，共用比较函数已拒绝相近版本及预发行后缀。
- `test_pnpm_rejects_unexpected_or_unsafe_archive`：4 项初绿，入口唯一性、深度、链接和资产名检查已覆盖。
- `test_verified_archive_still_requires_matching_version`：2 项初绿，归档通过摘要校验后仍执行版本自检。

既有一键脚本测试补齐前置条件后，61 项回归全部通过。