**1. 改动清单**

契约骨架已完成，改动留在工作区，未暂存、未提交。新增测试按要求跳过，样本生成留到实现阶段。

| 文件 | 改动 |
|---|---|
| `src/rdp/infra/config.py` | 增加存储配置、默认常量及校验契约。 |
| `src/rdp/infra/storage.py` | 定义挂载解析、设备身份、状态、超时检查和系统适配器骨架。 |
| `src/rdp/jobs/registry.py` | 增加 `StorageUse`、作业存储声明及启动核对契约。 |
| `src/rdp/jobs/execution.py` | 增加必填存储依赖，补充执行前检查契约。 |
| `src/rdp/jobs/storage.py` | 增加作业存储前置检查骨架。 |
| `src/rdp/api/storage.py` | 增加依赖装配、鉴权依赖和 GET 接口骨架。 |
| `src/rdp/api/storage_schemas.py` | 定义响应模型及状态一致性契约。 |
| `src/rdp/api/__init__.py` | 登记存储根接口。 |
| `src/web/src/api/openapi.json` | 通过 `make api-types` 更新。 |
| `src/web/src/api/schema.d.ts` | 通过 `make api-types` 更新。 |
| `src/web/src/api/storage.ts` | 增加请求骨架及生成类型别名。 |
| `src/web/src/api/storage.test.ts` | 增加传输契约跳过测试。 |
| `src/web/src/storage/queries.ts` | 定义查询与手动刷新契约。 |
| `src/web/src/storage/Pages.tsx` | 定义只读页面契约。 |
| `src/web/src/storage/Pages.test.tsx` | 增加展示、权限和查询生命周期跳过测试。 |
| `src/web/src/router.tsx` | 增加 `/storage-roots` 路由。 |
| `src/web/src/accounts/Pages.tsx` | 增加存储根菜单入口。 |
| `tests/nav_manifest.py` | 定义清单格式、展开函数及返回类型。 |
| `tests/fixtures/nav/manifest.schema.json` | 从清单模型生成 JSON Schema。 |
| `tests/conftest.py` | 增加 `fake_nav` fixture 骨架。 |
| `tests/test_storage_config.py` | 增加配置契约跳过测试。 |
| `tests/test_storage.py` | 增加挂载、设备号、超时和失败行为跳过测试。 |
| `tests/test_jobs_storage.py` | 增加作业拦截与依赖约束跳过测试。 |
| `tests/test_storage_api.py` | 增加 API 权限、错误和 OpenAPI 跳过测试。 |
| `tests/test_fake_nav.py` | 增加布局、引用、追溯和真实路径隔离跳过测试。 |
| `tests/job_process_support.py` | 显式传入 `storage=None`。 |
| `tests/jobs_execution_support.py` | 显式传入 `storage=None`。 |
| `tests/jobs_gpu_support.py` | 显式传入 `storage=None`。 |
| `tests/jobs_navigation_support.py` | 显式传入 `storage=None`。 |
| `tests/jobs_schedules_support.py` | 显式传入 `storage=None`。 |
| `tests/jobs_scheduling_execution_support.py` | 显式传入 `storage=None`。 |
| `tests/test_jobs_registry.py` | 适配新增必填依赖。 |
| `tests/test_jobs_service.py` | 适配新增必填依赖。 |
| `tests/test_jobs_worker.py` | 适配新增必填依赖。 |

**2. `make check`**

最后运行命令：

```text
make check
```

退出码为 **0**。Python 汇总原文：

```text
=========== 1681 passed, 83 skipped, 1 warning in 121.12s (0:02:01) ============
```

末尾输出原文：

```text
 Test Files  19 passed | 2 skipped (21)
      Tests  228 passed | 15 skipped (243)
   Start at  18:14:48
   Duration  7.03s (tests 48%, environment 33%, import 18%, transform 1%)
```

**3. 契约变更申请、依赖申请**

增量契约申请：

- `PlatformConfig` 增加 `nav_root`、`storage_roots`、`storage`；`load_config` 扩展相应输入契约。
- `JobDefinition` 增加默认空的 `storage` 字段。
- `ExecutorDependencies` 增加无默认值的必填关键字 `storage`；无存储声明时允许显式 `None`。
- `JobRegistry.register` 补充存储声明形状校验契约。

依赖申请：**无**。

**4. 需要评审决定的地方**

- 超时范围暂定 **0.1–60 秒**，默认仍为 10 秒。
- 挂载表读取或解析失败、设备元数据读取失败按 `ExternalError` 处理；API 返回统一 502，不伪装成“没挂载”。
- 根名核对放在全部类型登记完成后、启动前统一进行。这样保留既有临时登记校验用途，未知根仍阻止启动。
- 来源绝对路径用 `source_path_parts` 无损记录，避免 fixtures 出现真实挂载路径文本；该字段禁止用于文件访问。
- 前端请求骨架有一条单行 `no-unused-vars` 豁免：必填参数必须保留，函数体又只能抛未实现异常；实现时移除。