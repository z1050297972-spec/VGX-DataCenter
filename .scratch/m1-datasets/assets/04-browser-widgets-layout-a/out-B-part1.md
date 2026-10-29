**1. 改动清单**

前半段检查点完成，改动留在工作区，未暂存、未提交。

- 新增 `/datasets` 布局 A：两棵树、列表、标签/FPS 筛选、详情、跨视图跳转、一致性面板、重新检查并进入作业页。
- 三份 JSON 可打开；子任务按需请求，Worker 解析，原文分页显示。
- 业务页面按路由拆包；主入口 **50.51 kB**，最大块 **251.48 kB**，无构建警告。
- 新增 11 项通过测试、8 项明确跳过。变异抽查 2/2 捕获错误。
- 仅修改允许范围；临时试验文件已删除。

**2. `make check`**

退出码 **0**。pytest 汇总及末尾输出：

```text
================= 2276 passed, 8 warnings in 75.67s (0:01:15) ==================

[10/11] Prettier
Checking formatting...
All matched files use Prettier code style!
[11/11] Vitest

 Test Files  25 passed | 1 skipped (26)
      Tests  261 passed | 8 skipped (269)
   Duration  7.85s
```

8 条 warning 来自 FastAPI TestClient 的依赖弃用提示。

**3. 契约变更申请、依赖申请**

均无。后端和 OpenAPI 未修改，生成类型过期检查通过。

**4. 执行线演练与剩余工作**

在本工作目录根部，用独立配置指定临时 `state_dir`、端口如 `8618`：

```bash
(cd src/web && node_modules/.bin/vite build)
RDP_CONFIG=/tmp/m1-04-drill/config.toml PYTHONPATH="$PWD/src" .venv/bin/python -m rdp migrate
RDP_CONFIG=/tmp/m1-04-drill/config.toml PYTHONPATH="$PWD/src" .venv/bin/python -m rdp web
```

另一终端用相同配置运行 `python -m rdp worker`。登录后进入 `/datasets`。

- 使用第 02 张完成第二段扫描的索引及存储根配置。第 03 张早期演练使用不存在的存储根，标签/FPS 只有“未知”。
- 打开 `libero_10` 后，用“跨视图跳转”；“重新检查”成功提交后自动进入作业详情。
- 最大子任务文件在 `agibot_world_2026`，既有记录为 **14,090,470 字节**。
- **真实浏览器长任务表现尚待执行线验证**；当前证明的是 Worker 路径和有界分页。

下一段的 8 项已在 `checkpoint.test.ts` 跳过：离线提示、过期重扫、型号映射、其余筛选与分页、14 项 Markdown、链接与数据块、统计大小、异常及生命周期补测。

**5. 先红后绿**

新增已启用测试均单独先红后绿，无首次即绿：

- 菜单、两棵树、列表数量：缺少入口 → 通过。
- 型号标签筛选：缺少筛选控件 → 通过。
- 数字 FPS URL 与交互：缺少 FPS 控件 → 通过。
- 非法 FPS：缺少错误提示 → 通过。
- 详情与跨视图跳转：缺少详情 → 通过。
- 一致性面板：缺少面板入口 → 通过。
- 重新检查与作业跳转：缺少按钮 → 通过。
- 14 MB 按需请求、Worker、分页及释放：缺少打开入口 → 通过。
- 两份现场 JSON：缺少打开入口 → 通过。
- Worker 解析及末页保留：无消息响应 → 通过。
- Worker 坏 JSON：抛出解析异常 → 保留原文并标记无效，通过。