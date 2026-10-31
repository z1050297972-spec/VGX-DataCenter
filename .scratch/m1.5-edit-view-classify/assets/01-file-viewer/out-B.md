**1 改动清单**

后端和前端已完成：目录分页、安全读取、视频 Range、JSON Worker 格式化、文本/图片预览及五段诊断。改动留在工作区，未暂存或提交。

共用文件逐处如下：

- `pyproject.toml`：加强普通浏览查询的存储禁入约束。
- `src/rdp/api/__init__.py`：注册查看器路由。
- `src/rdp/api/production.py`：装配查看器及访问预算。
- `src/rdp/cli.py`：传入存储超时配置。
- `src/rdp/infra/storage.py`：更新查看器例外说明。
- `src/rdp/jobs/datasets/_readonly.py`：增加 `dir_fd`、可选非阻塞打开。
- `Details.tsx`：增加查看入口。
- `JsonViewer.tsx`、`jsonProtocol.ts`、`json.worker.ts`：增加可选格式化，保留数字原词法。
- `json.worker.test.ts`、`tests/test_dataset_api_contract.py`：补充格式化测试及新增接口认证断言。
- `src/web/src/api/openapi.json`、`schema.d.ts`：由 `make api-types` 生成。

**2 `make check` 汇总**

全绿：

```text
pytest: 2561 passed
Vitest: 36 files passed, 353 passed
0 skipped
```

构建通过，主入口 **55.27 kB < 500 kB**，`dist` 已删除。构建器另有公共 `ui` 分块 786.88 kB 的警告。

**3 契约变更申请**

本票授权的 Web 只读存储例外已实现，请执行线同步 ADR 0006 和规范 1.4。

只增扩展：两个 GET 接口、`WebRuntime.storage_options`、`open_fd` 可选参数，以及 JSON 查看器可选 `format`。无新增依赖。

**4 演练所需**

登录后先确认真实编号，以下以 `dataset-14` 为例：

```http
GET /api/datasets/dataset-14/files?link_name=原始数据&path=meta
GET /api/datasets/dataset-14/file?link_name=原始数据&path=meta/info.json
GET /api/datasets/dataset-14/files?link_name=原始数据&path=data/chunk-000
GET /api/datasets/dataset-14/file?link_name=原始数据&path=videos/observation.images.image/chunk-000/file-000.mp4
Range: bytes=0-1048575
```

视频路径以目录返回值为准。主要 aria-label：`查看原文件`、`选择原文件链接`、`打开目录 meta`、`预览文件 info.json`、`原文件视频`、`原文件上一级`。

执行线仍需验证 1280×900、实际编码播放和拖动，并比对写入扇区。流开始后的故障会断流；永久阻塞的内核读取受四个访问槽限制。

**5 先红后绿**

9 项有红→绿记录，5 项变异全部被检出。[完整证据](/home/shawn/桌面/robot-data-platform.wt/m15-01-file-viewer/tests/file_viewer_tdd_evidence.json)

流程偏差：另外 5 项是前一切片已覆盖行为的补测，初跑即绿，未满足“每个测试先单独见红”的要求；证据中已如实单列。