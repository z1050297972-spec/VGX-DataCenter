// 09 契约清单；路由行为通过真实 createAppRouter 与内存 history 验证。
import { it } from "vitest";

it.skip("真实 router 打开 /scheduling：成员与管理员均可见菜单及只读页面，未登录沿用认证跳转", () => {
  throw new Error("未实现");
});

it.skip("同一只读页显示每类上限/运行数、每张卡的作业链接及导航写锁持有者，空闲有明确提示", () => {
  throw new Error("未实现");
});

it.skip("同一只读页显示下一次本地时刻、上次作业链接和六种结局，从未提交不伪造结果", () => {
  throw new Error("未实现");
});

it.skip("worker 离线时注明最后已保存状态；API 查询失败显示 DiagnosticCard，不伪造零占用", () => {
  throw new Error("未实现");
});

it.skip("每 JOB_POLL_INTERVAL_MS 轮询，一个查询同时刷新资源和每日计划，离页取消请求，不自动重试", () => {
  throw new Error("未实现");
});

it.skip("401 按账号感知客户端清缓存并回登录，换账号不闪现上个账号结果或迟到响应", () => {
  throw new Error("未实现");
});

it.skip("接口中的超 JS 安全整数作业编号保持文本链接，不使用 Number", () => {
  throw new Error("未实现");
});

it.skip("到期但尚未提交显示等待 worker，不把旧到期时间伪造成明天", () => {
  throw new Error("未实现");
});

it.skip("资源示例页面 GPU 时长接受0/600，拒绝bool语义/负数/601，非法表单不发请求", () => {
  throw new Error("未实现");
});

it.skip("写锁期望值允许空、暂停接受0/10秒；超界保留输入并提示，参数不包含路径", () => {
  throw new Error("未实现");
});

it.skip("两个示例成功提交201后进入新详情，提交中禁重复，离页或换号后迟到成功不导航", () => {
  throw new Error("未实现");
});

it.skip("提交失败统一诊断且保留表单，不自动重试不确定写请求", () => {
  throw new Error("未实现");
});

it.skip("被移出池的卡显示移出状态、原因和核对时间，修复后提示重启worker，不假装空闲可分配", () => {
  throw new Error("未实现");
});
