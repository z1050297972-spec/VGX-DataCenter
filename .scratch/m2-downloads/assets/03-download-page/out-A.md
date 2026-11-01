**工单尚未完成。**目前只实现了下载作业提交接口；预览、调参、token、暂存管理、前端页面及相应测试均未完成。没有达到你指定的停止条件，也没有运行到约 80 分钟，因此这不是可验收的检查点。

### 1. 改动清单

- `src/rdp/api/jobs.py`：新增提交下载作业接口，复用现有作业服务。
- `src/web/src/api/openapi.json`：通过 `make api-types` 重新生成。
- `src/web/src/api/schema.d.ts`：通过 `make api-types` 重新生成。
- `tests/test_download_page_api.py`：新增真实应用提交下载作业测试。

改动留在工作区，未执行 `git add` 或提交。

### 2. `make check`

最后一次运行命令：`make check`，退出码为 0。末尾输出原样如下：

```text
 Test Files  39 passed (39)
      Tests  373 passed (373)
   Start at  01:19:54
   Duration  10.58s (tests 56%, import 23%, environment 20%, transform 1%)
```

这只能证明**当前部分改动**通过检查，不能证明整张工单验收通过。

### 3. 依赖申请

无。

### 4. 自己定的设计选择和拿不准的地方

- 下载提交接口复用已有作业服务的提交事务和操作日志；Web 不执行下载，也不访问存储根。
- token 尚未实现，因此尚未决定写入路径的具体实现。
- worker 预览、暂存列表及安全删除的协调方式尚未实现和验证。

### 5. 先红后绿

- `test_submit_download`：首次运行失败，接口返回 `405 Method Not Allowed`；实现接口后通过。