**1. 改动清单**

- 移除 `ui.maxSize`，保留完整 UI 依赖组，修复正式构建白屏。
- 补齐原 8 类验收：离线、过期重扫、型号映射、筛选分页、14 项 Markdown、链接与数据块、统计大小、异常与生命周期。
- 修复 Worker 重复释放；3 项变异抽查均捕获错误。
- 未暂存、未提交，无后端修改。

正式构建输出：

```text
文件                              大小 kB
json.worker-DuNK66Bi.js              0.30
rolldown-runtime-WkwZ5CU-.js          0.59
Pages-DpjpInlM.js                    1.74
_actions-tCDC35Pd.js                 2.44
progress-CdON3VAn.js                 3.63
Pages-AGNrQdAL.js                    6.01
Pages-BmLvd171.js                    7.10
Pages-Biypi4ei.js                    7.68
Pages-LQoTvEur.js                   19.97
index-CI2lzZTZ.js                   50.27
link-P-wuBE_q.js                    65.31
react-runtime-AyOTluXZ.js          218.75
DiagnosticCard-BE8oWh3t.js         228.26
ui-DunVPubI.js                    763.53
Pages-CzGtOmtV.css                   0.72
index.html                          0.90
```

主入口低于 500 kB；保留 vendor 超过 500 kB 的警告，未提高全局阈值。

**2. 连续三次 `make check`**

源码保持不变，三次退出码均为 **0，0 skipped**：

```text
第1次：2276 passed, 8 warnings in 79.60s
       Vitest: 272 passed (272)

第2次：2276 passed, 8 warnings in 74.47s
       Vitest: 272 passed (272)

第3次：2276 passed, 8 warnings in 77.67s
       Vitest: 272 passed (272)
```

第三次末尾：

```text
All matched files use Prettier code style!
[11/11] Vitest

 Test Files  26 passed (26)
      Tests  272 passed (272)
   Duration  8.02s
```

**3. 契约变更申请、依赖申请**

均无。OpenAPI 未变，生成类型检查通过。

**4. 浏览器验证与执行线事项**

使用 Chrome、正式 `dist`、`127.0.0.1:18764` 静态服务及未登录替身接口验证。修复前复现相同 `ESC` 异常；修复后 **Uncaught 为 0**，DOM 包含：

```html
<label for="login_name" class="ant-form-item-required" title="登录名">登录名</label>
<input autocomplete="username" id="login_name" aria-required="true"
       class="ant-input css-eofgey ant-input-outlined css-var-root ant-input-css-var"
       type="text" value="">
<label for="password" class="ant-form-item-required" title="口令">口令</label>
<input autocomplete="current-password" id="password" aria-required="true"
       class="ant-input css-eofgey" type="password">
```

代码内已无待补的跳过项；真实导航层的完整浏览演练仍由执行线复验。

收尾有两项限制：静态服务工具会话中断后，**18764 仍在监听**，需执行线定位并停止；工具初始化产生了根目录 **0 字节 `.aws`**，删除被沙箱挂载限制拒绝（`Device or resource busy`），也需执行线清理。其余临时副本、日志和浏览器配置已删除。

**5. 先红后绿**

- 正式构建登录页：空白、`ESC` 异常 → 表单出现、无 Uncaught。
- 离线提示与旧大小：缺少提示 → 通过。
- 详情／子任务过期重扫：缺少过期提示 → 通过。
- 型号映射与更多筛选：缺少型号控件 → 通过。
- 来源、未知值、分页与目录：缺少来源控件 → 通过。
- 规范副本 14 项 Markdown：缺少信息区域 → 通过。
- 链接时间与数据块标签：缺少数据块区域 → 通过。
- 统计大小及防重复提交：缺少按钮 → 通过。
- Worker 故障／超时：重复释放两次 → 仅释放一次，通过。
- 请求失败：首次即绿，既有统一诊断和禁止重试已覆盖。
- 切入口取消：首次即绿，既有 Query 取消机制已覆盖。
- 换号清理：首次即绿，既有账号隔离和卸载机制已覆盖。