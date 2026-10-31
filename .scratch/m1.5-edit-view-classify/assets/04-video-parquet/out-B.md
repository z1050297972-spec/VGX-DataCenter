1. **改动清单**

   扩展既有查看器：新增 fd 视频转码、pyarrow 分页预览、antd 分段控件与表格；同步 OpenAPI、生成类型和测试。仅改 `src/`、`tests/`，保留原有依赖暂存变更，未暂存、未提交。

2. **检查汇总**

   `make check` 退出 0：`2627 passed`；Vitest `39 files / 373 tests passed`；**0 skipped**。Vite 构建通过，主入口 **55,857 bytes**，`dist` 已删除。

3. **契约变更**

   新增三个 GET 接口：`video-info`、`video`、`parquet`。视频默认 60 秒、最多 300 秒、总超时 120 秒，两路并发，超限返回 429。parquet 默认及上限均为 200 行，单元格最多 1024 字符并标记截断，超过 2 GiB 仅返回结构和计数。

4. **演练入口与未验证项**

   已登录后请求，查询值需 URL 编码：

   ```text
   GET /api/datasets/{id}/video-info?link_name={链接}&path={视频相对路径}
   GET /api/datasets/{id}/video?link_name={链接}&path={视频相对路径}&start_s=120&duration_s=60
   GET /api/datasets/{id}/parquet?link_name={链接}&path={parquet相对路径}&offset=0&limit=200
   ```

   60% 跳转取探测总时长 × 0.6。稳定标签包括：`原文件视频`、`视频起点`、`视频上一段`、`视频下一段`、`parquet数据表格`、`parquet上一页`、`parquet下一页`。

   环境无可用浏览器，**1280×900 实际布局尚未验证**；真实数据播放和磁盘扇区比对留给执行线。

5. **先红后绿**

   主要切片均记录实现前失败及最终通过；补充边界用例初跑为绿的原因已注明。删除 `pass_fds`、放宽大文件阈值两项变异均被测试抓住。详见[交付证据](/home/shawn/桌面/robot-data-platform.wt/m15-04-video-parquet/tests/file_preview_tdd_evidence.json)。