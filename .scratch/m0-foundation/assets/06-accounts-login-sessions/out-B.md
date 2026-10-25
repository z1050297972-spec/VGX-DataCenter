**1. 改动清单**

实现尚未完成。发现前端契约职责冲突后，按本轮第 2 条要求停下申请变更。

- `src/rdp/accounts/security.py`：实现构造器的默认/注入 hasher 和假哈希最小路径；并发限制、错误处理等仍待实现。
- `tests/test_accounts.py`：完成前三个构造器测试，其余清单未展开。

未暂存、提交、联网或安装依赖；未另建试验文件。

**2. 检查结果**

尚未运行最终 `make check`，不能宣称全票通过。

本轮相关测试命令：

```text
.venv/bin/pytest tests/test_accounts.py
```

末尾输出：

```text
======================== 3 passed, 191 skipped in 0.12s ========================
```

相关测试运行前 `git status --porcelain --untracked-files=all`：

```text
 M src/rdp/accounts/security.py
 M tests/test_accounts.py
```

运行后：

```text
 M src/rdp/accounts/security.py
 M tests/test_accounts.py
```

**3. 契约变更申请、依赖申请**

需要调整 [accounts.ts](/home/shawn/桌面/robot-data-platform.wt/m0-06-accounts-login-sessions/src/web/src/api/accounts.ts) 的副作用归属：

| 当前承诺 | 建议调整 |
|---|---|
| `login` 等 HTTP 函数清空表单秘密 | 由对应页面在请求结束时清空表单及 mutation 中的秘密引用。 |
| `logout` 成功后清缓存并导航 | 由 `AccountMenu` 完成；401 继续通过已约定的 `onUnauthorized` 处理。 |
| 写操作函数使身份或列表缓存失效 | 由页面的 mutation 成功回调操作当前 `QueryClient`。 |
| `fetchCurrentAccount` 设置 Query 行为 | 函数只负责 GET；查询配置由 `AccountLayout` 持有。 |
| `listAccounts` 取消旧分页请求 | 页面取消旧请求；函数继续遵守传入的取消信号。 |

原因：这些函数只接收客户端、载荷和 `AbortSignal`，没有表单、`QueryClient` 或导航对象；而 `mountWeb` 创建的是独立 `QueryClient`。页面契约已承诺上述行为，建议保留页面行为和现有函数签名，纠正 HTTP 函数的职责说明。

这会改变函数自身承诺的副作用，因此没有擅自当作措辞修改。

**实际修改的生产 docstring/TSDoc：无。**  
依赖申请：无。

**4. 需要评审决定的地方**

请批准上述职责归属调整后继续。停止依据是你本轮要求：“已获批的签名、类型和 docstring 不改；确实要改时停下来写进最终回复的契约变更申请。”

**5. 先红后绿记录**

- `test_codec_init_default`：首次失败，构造器抛 `NotImplementedError`；最小实现后通过。
- `test_codec_init_injected`：首次通过；前一个测试的实现已支持保存注入的 hasher。
- `test_codec_init_dummy`：首次通过；同一实现已生成一次随机假哈希。随后通过随机源边界及公开验证接口核对，并检查输出不泄漏测试原文，仍通过。