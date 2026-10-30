// M1-08 页面验收清单；真实副本浏览器演练由执行线在契约通过后进行。
import { describe, it } from "vitest";

describe("建链与新增数据集的契约行为", () => {
  // 验证契约：建链页按 填参数→预览→明确确认→作业页 完整流转，预览不触发写入。
  it.skip("建链页按 填参数→预览→明确确认→作业页 完整流转，预览不触发写入", () => {
    throw new Error("NotImplementedError");
  });
  // 验证契约：新增页来源必填、首链接必填，预计编号与两个视图完整差异可见。
  it.skip("新增页来源必填、首链接必填，预计编号与两个视图完整差异可见", () => {
    throw new Error("NotImplementedError");
  });
  // 验证契约：预览列文件、链接、sources、dataset_roots、所选与重生成格式入口及检查范围。
  it.skip("预览列文件、链接、sources、dataset_roots、所选与重生成格式入口及检查范围", () => {
    throw new Error("NotImplementedError");
  });
  // 验证契约：同目标已登记的 noop 预览明确显示已经是这样了且计数为零。
  it.skip("同目标已登记的 noop 预览明确显示已经是这样了且计数为零", () => {
    throw new Error("NotImplementedError");
  });
  // 验证契约：没有 meta/info.json 时从登记选项选择格式，版本显示 null；archives 显示原目录名。
  it.skip("没有 meta/info.json 时从登记选项选择格式，版本显示 null；archives 显示原目录名", () => {
    throw new Error("NotImplementedError");
  });
  // 验证契约：任一表单参数修改使旧预览失去确认资格，格式多选拒绝重复和非法版本层。
  it.skip("任一表单参数修改使旧预览失去确认资格，格式多选拒绝重复和非法版本层", () => {
    throw new Error("NotImplementedError");
  });
  // 验证契约：冲突以 DiagnosticCard 展示对象、实际、期望、后果和下一步，并允许重新预览。
  it.skip("冲突以 DiagnosticCard 展示对象、实际、期望、后果和下一步，并允许重新预览", () => {
    throw new Error("NotImplementedError");
  });
  // 验证契约：排队提醒列现有写作业链接，首次取消不提交，明确确认才携带看到的编号。
  it.skip("排队提醒列现有写作业链接，首次取消不提交，明确确认才携带看到的编号", () => {
    throw new Error("NotImplementedError");
  });
  // 验证契约：确认时新增排队作业再次提示，不复用通配确认或盲目跳转。
  it.skip("确认时新增排队作业再次提示，不复用通配确认或盲目跳转", () => {
    throw new Error("NotImplementedError");
  });
  // 验证契约：预览失败、过期、损坏或未完成时禁用确认并保留可修正参数。
  it.skip("预览失败、过期、损坏或未完成时禁用确认并保留可修正参数", () => {
    throw new Error("NotImplementedError");
  });
  // 验证契约：预览作业每 JOB_POLL_INTERVAL_MS 轮询，终态停止，离页取消读取，POST 不重试。
  it.skip("预览作业每 JOB_POLL_INTERVAL_MS 轮询，终态停止，离页取消读取，POST 不重试", () => {
    throw new Error("NotImplementedError");
  });
  // 验证契约：写入提交在途禁用重复点击，成功使用文本编号进入既有作业页。
  it.skip("写入提交在途禁用重复点击，成功使用文本编号进入既有作业页", () => {
    throw new Error("NotImplementedError");
  });
  // 验证契约：真实 Router 支持两个新路由、登录守卫、刷新预览定位及成员访问。
  it.skip("真实 Router 支持两个新路由、登录守卫、刷新预览定位及成员访问", () => {
    throw new Error("NotImplementedError");
  });
  // 验证契约：真实 Router search 的数字、数组或非法编号显示可修正提示，不崩溃不请求。
  it.skip("真实 Router search 的数字、数组或非法编号显示可修正提示，不崩溃不请求", () => {
    throw new Error("NotImplementedError");
  });
  // 验证契约：2^63-1 作业编号保持文本精度，目标路径不写 URL 或浏览器持久存储。
  it.skip("2^63-1 作业编号保持文本精度，目标路径不写 URL 或浏览器持久存储", () => {
    throw new Error("NotImplementedError");
  });
  // 验证契约：恢复失败沿用全局提示与恢复页链接，创建写作业仍可排队。
  it.skip("恢复失败沿用全局提示与恢复页链接，创建写作业仍可排队", () => {
    throw new Error("NotImplementedError");
  });
  // 验证契约：API 默认传输兼容浏览器原生 fetch 的 this 约束，统一认证与 problem 诊断。
  it.skip("API 默认传输兼容浏览器原生 fetch 的 this 约束，统一认证与 problem 诊断", () => {
    throw new Error("NotImplementedError");
  });
  // 验证契约：创建候选与数据集选择支持空索引及多页，不复制来源/格式词表。
  it.skip("创建候选与数据集选择支持空索引及多页，不复制来源/格式词表", () => {
    throw new Error("NotImplementedError");
  });
  // 验证契约：时间沿用服务端预览时刻，使用浏览器本地时区且不伪造新统计时间。
  it.skip("时间沿用服务端预览时刻，使用浏览器本地时区且不伪造新统计时间", () => {
    throw new Error("NotImplementedError");
  });
  // 验证契约：成功后刷新 datasets/jobs 缓存，新数据集和链接可在两棵树及详情页查看。
  it.skip("成功后刷新 datasets/jobs 缓存，新数据集和链接可在两棵树及详情页查看", () => {
    throw new Error("NotImplementedError");
  });
});
