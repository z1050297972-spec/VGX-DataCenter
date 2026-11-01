收尾两处，改完就交，第一行写 `状态：全部完成`：
1. `src/web/src/downloads/Preview.tsx` 里把 `capacity.complete_bytes` 的标签从"已在暂存区"改成"已完整下载（续传中的不计）"，或等价的准确说法；对应测试的断言一起改。
2. `src/web/src/jobs/DownloadDetail.tsx`：作业详情把 spec 第 6 条全部 7 个 aria2 参数的实际生效值都显示出来（数据取自作业参数；能运行中改的那两个显示调参后的生效值），现有测试补一条断言即可，不新增测试文件。

`make check` 一次全绿后交，最终回复只写改了什么和 `make check` 末尾输出。边界不变。
