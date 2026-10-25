**1. 改动清单**

- `src/rdp/infra/ids.py`：搬入编号常量和两个校验函数，新增无锚点核心正则。
- `src/rdp/infra/db/validation.py`：只保留数据库 CHECK 和 `invalid_field`，无转发别名。
- `src/rdp/infra/logging.py`：从 `ids` 导入编号校验。
- `src/rdp/api/errors.py`：从 `ids` 导入编号规则。
- `src/rdp/api/error_details.py`：从 `ids` 导入编号规则。
- `src/rdp/infra/db/models.py`：从 `ids` 导入编号长度。
- `src/rdp/infra/db/records.py`：从 `ids` 导入编号长度和来源识别函数。
- `src/rdp/infra/db/migration.py`：独立定义备份 UUID 后缀和文件名正则。
- `pyproject.toml`：仅新增指定的 forbidden 合同及批准说明。
- `tests/test_ids.py`：新增编号直接测试和正则字面值回归测试。
- `tests/test_db_migration.py`：新增备份文件名测试，原有测试断言未变。

已核对函数签名、函数体、函数 docstring 和原有常量值完全一致。未暂存、未提交、未联网或安装依赖；临时文件已清理。

**2. `make check`**

仅运行一次，命令：

```text
make check
```

退出码 `0`。pytest：557 passed、0 skipped；Vitest：77 passed、0 skipped。末尾输出原样如下：

```text
======================= 557 passed, 1 warning in 25.56s ========================
[7/11] OpenAPI 过期检查
✨ openapi-typescript 7.13.0
🚀 /tmp/tmp.ohGqHUcSFG/openapi.json → /tmp/tmp.ohGqHUcSFG/schema.d.ts [19.8ms]
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


 Test Files  9 passed (9)
      Tests  77 passed (77)
   Start at  06:57:16
   Duration  1.48s (environment 40%, tests 31%, import 28%, transform 1%, setup 1%)
```

运行前 `git status --porcelain --untracked-files=all`：

```text
 M pyproject.toml
 M src/rdp/api/error_details.py
 M src/rdp/api/errors.py
 M src/rdp/infra/db/migration.py
 M src/rdp/infra/db/models.py
 M src/rdp/infra/db/records.py
 M src/rdp/infra/db/validation.py
 M src/rdp/infra/logging.py
 M tests/test_db_migration.py
?? src/rdp/infra/ids.py
?? tests/test_ids.py
```

运行后 `git status --porcelain --untracked-files=all`：

```text
 M pyproject.toml
 M src/rdp/api/error_details.py
 M src/rdp/api/errors.py
 M src/rdp/infra/db/migration.py
 M src/rdp/infra/db/models.py
 M src/rdp/infra/db/records.py
 M src/rdp/infra/db/validation.py
 M src/rdp/infra/logging.py
 M tests/test_db_migration.py
?? src/rdp/infra/ids.py
?? tests/test_ids.py
```

**3. 契约变更申请、依赖申请**

均无。现有 docstring 仅改写 `db/validation.py` 的模块说明；新增 `ids.py` 的模块说明。函数契约 docstring 原样搬移；新测试新增各自的说明。

**4. 需要评审决定的地方**

无。

**5. 新测试首次单独运行结果**

- `test_is_request_id`：`21 passed in 0.01s`
- `test_error_source_kind`：`28 passed in 0.01s`
- `test_error_id_pattern_unchanged`：`1 passed in 0.01s`
- `test_backup_filename_pattern`：`1 passed in 0.18s`

本次是既有正确实现的纯搬移，新测试首次通过符合预期，没有故意改错实现制造红灯。