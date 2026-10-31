## 1. 改动清单

- `src/rdp/jobs/downloads/plan.py`：实现镜像探测、有限重试、版本解析、分页清单、预览、筛选、安全路径、token 读取和容量预检；落实模型自选子目录及请求总时长、响应体上限契约。
- `src/rdp/jobs/downloads/_http_child.py`：新增单次 HTTP 请求的隔离子进程入口；使用无代理 opener、不跟随重定向，限制响应体并保留分页头。
- `tests/jobs/downloads/test_plan.py`：完成原先 19 条跳过测试，并增加中文路径、控制字符、超时、容量检查、软链接及子进程异常退出等边界测试；测试使用替身，不访问网络。

工作区改动未暂存、未提交。本次续接中，子进程异常退出测试先前因未拒绝非零退出码失败，补充检查后通过。

## 2. `make check`

最后一次运行命令：

```bash
make check > /tmp/m2-download-check-resume.log 2>&1
```

退出码为 0。末尾输出原样如下：

```text
================= 2527 passed, 8 warnings in 88.78s (0:01:28) ==================
[7/11] OpenAPI 过期检查
✨ openapi-typescript 7.13.0
🚀 /tmp/tmp.3yTa5TDOSj/openapi.json → /tmp/tmp.3yTa5TDOSj/schema.d.ts [102ms]
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
   Start at  19:30:16
   Duration  9.77s (tests 50%, environment 27%, import 22%, transform 1%)
```

下载计划测试中没有剩余 `pytest.skip`。临时检查日志已删除。

## 3. 契约变更申请、依赖申请

- **契约变更申请**：建议在 `UrllibTransport.request` 的已批准 `Side Effects:` 中补充“启动并回收单次请求隔离子进程；超时终止子进程”。这是为保障请求总时长而采用的实现，当前未擅自修改该已批准段落。
- **依赖申请**：无；新增实现使用标准库和现有平台组件。

## 4. 拿不准、需要评审决定的地方

- 真实镜像网络链路、响应和下载演练未执行；本轮按要求只使用 HTTP 替身，留待负责人演练。
- 容量预检复用 `StorageAccessChecker` 的预算和取消机制。若底层 NFS 内核调用卡住，已有设计中的 daemon 线程可能在超时返回后继续存活；NAS 挂载策略明确后仍需评估这一风险。
- 新增两处**单规则**豁免：`S603` 用于固定解释器及固定模块命令，凭据经标准输入传递；`S310` 用于已在父进程限制为镜像 HTTPS 地址且不跟随重定向的请求。两处旁边均有理由注释。
- 检查链的 8 条 warning 来自现有 FastAPI/Starlette TestClient 弃用提示；未安装或修改依赖。

## 5. 先红后绿

以下仅列本轮新去掉跳过的 19 条测试；“首次通过”均为前一个纵切片已覆盖该行为。

- `test_mirror_head_redirect_to_official`：首次失败，镜像探测尚未实现。
- `test_mirror_api_redirect_to_official`：首次通过；首页重定向切片已实现两次探测及重定向拒绝。
- `test_no_proxy_or_redirect_in_default_transport`：首次失败，默认传输尚未实现。
- `test_three_page_tree_uses_pinned_commit`：首次失败，清单分页尚未实现。
- `test_429_then_success`：首次通过；镜像探测切片已实现共用的 429 重试。
- `test_retries_exhausted`：首次通过；共用重试器已限制次数并报告耗尽。
- `test_gated_without_token`：首次失败，版本解析尚未实现。
- `test_disabled_repository`：首次通过；版本解析切片已包含 disabled 检查。
- `test_lfs_and_git_files`：首次通过；分页切片已解析普通文件和 LFS 校验值。
- `test_token_never_leaks`：首次通过；此前已实现的计划与错误边界未回显 token。
- `test_dataset_preview_from_pinned_info`：首次失败，数据集预览读取尚未实现。
- `test_model_has_no_dataset_preview`：首次失败，计划编排尚未实现。
- `test_insufficient_capacity_diagnostic`：首次失败，容量不足时尚未拒绝计划。
- `test_complete_files_reduce_remaining_by_size_only`：首次失败，尚未扣除大小匹配的暂存文件。
- `test_readonly_or_offline_root_rejected`：首次通过；计划编排已复用存储根检查器。
- `test_untrusted_pagination_target`：首次通过；分页切片已限制下一页主机和路径。
- `test_untrusted_file_paths_and_symlinks`：首次通过；清单路径校验和不跟随软链接的容量检查已实现。
- `test_slow_response_exceeds_total_deadline`：首次失败，慢响应尚未触发总时长限制。
- `test_response_exceeds_body_limit`：首次失败，响应体超限尚未被拒绝。