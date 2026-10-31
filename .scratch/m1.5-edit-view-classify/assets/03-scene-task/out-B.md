1. **改动清单**

   完成词表、扫描索引、词表外提示、分类筛选及计数、URL 状态、antd 编辑下拉框、中文名称显示和 A/B/C 场景分组；补充测试及迁移回归。

   共用文件：`registry`、根 `api/__init__.py`、`Details.tsx`、`jobs/Pages.tsx` 均未修改。`api/datasets/__init__.py` 仅更新接口说明；OpenAPI 已生成。无新增依赖，未暂存、未提交。

2. **`make check`**

   ```text
   2580 passed, 8 warnings in 99.29s (0:01:39)
   Test Files  38 passed (38)
   Tests       363 passed (363)
   ```

   全绿、0 skipped。Vite 构建成功，主入口 **56,062 bytes**；`dist` 已删除。1280×900 离线检查覆盖三种布局和编辑抽屉，均无横向滚动条。

3. **契约变更**

   迁移：`0012_scene_task_index`，接 `0011_data_origin`。

   索引新增 `scene`、`tasks`、`robot_model`；`tasks` 非空、默认 `[]`。API 新增分类筛选、计数和词表响应；树新增 `view=scene`、`kind=scene`。任务多选取交集，`unlabeled` 与词表中的 `unknown` 分开。

4. **演练请求、控件及遗留**

   ```http
   GET /api/datasets?scene=kitchen&tasks=pick_place&tasks=wipe_clean
   GET /api/datasets?scene=unlabeled&tasks=unlabeled
   GET /api/datasets/trees?scene=kitchen
   GET /api/datasets/filters
   ```

   aria-label：`筛选场景`、`筛选任务`、`场景`、`任务`、`浏览视图`、`编辑导航层字段`、`预览字段改动`、`确认字段写入`。

   取值约定：缺失、空值及非法类型按未标注；词表外文本保留并提示。真实副本的三个数据集标注演练留给执行线；未访问 `/mnt`。可选“一键建议”未做。

5. **先红后绿**

   索引/API、编辑器、URL 筛选、三布局分组、中文显示及虚拟路径均验证了先红后绿。继承的词表、读取测试接手即绿；冲突任务的 422 用例最初也绿，原因是旧 API 拒绝未知参数。

   三项变异抽查均被抓住：交集改并集、丢失场景索引、提示级别改错；已全部还原。