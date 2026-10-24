// 工单 04 契约测试清单；派工 B 解除跳过并以可观察行为验证，不做整段文本快照。
import { it } from "vitest";

it.skip("验证契约：readProblemResponse 合法四类 problem 保持顺序并使用生成类型，状态与HTTP一致", () => {
  // 契约骨架；待派工 B 先红后绿。
});

it.skip("验证契约：readProblemResponse Content-Type大小写和参数合法；非problem媒体或成功响应返回null", () => {
  // 契约骨架；待派工 B 先红后绿。
});

it.skip("验证契约：readProblemResponse HTML、空体、坏JSON、已消费body及读取失败返回null，不展示原文", () => {
  // 契约骨架；待派工 B 先红后绿。
});

it.skip("验证契约：readProblemResponse 缺必填字段、额外字段、未知枚举、空白文本、非法对象值/重复键返回null", () => {
  // 契约骨架；待派工 B 先红后绿。
});

it.skip("验证契约：readProblemResponse 非法uuid、status与类别或title不符、DEFECT含诊断均返回null", () => {
  // 契约骨架；待派工 B 先红后绿。
});

it.skip("验证契约：readProblemResponse 只读克隆，原Response仍可读取，不发新请求或记录日志", () => {
  // 契约骨架；待派工 B 先红后绿。
});

it.skip("验证契约：createProblemFetch 创建不发送请求、不改全局fetch，不同包装器互不影响", () => {
  // 契约骨架；待派工 B 先红后绿。
});

it.skip("验证契约：createProblemFetch 每次调用传输一次，2xx/3xx返回原Response且保留body/headers", () => {
  // 契约骨架；待派工 B 先红后绿。
});

it.skip("验证契约：createProblemFetch 4xx/5xx合法problem拒绝Error且cause含原载荷，message为固定请求失败", () => {
  // 契约骨架；待派工 B 先红后绿。
});

it.skip("验证契约：createProblemFetch 网络拒绝/超时/取消转为固定不可用提示，不把异常原文放入cause", () => {
  // 契约骨架；待派工 B 先红后绿。
});

it.skip("验证契约：createProblemFetch 代理HTML/坏problem使用不可用提示，只保留合法X-Request-ID，不伪造编号", () => {
  // 契约骨架；待派工 B 先红后绿。
});

it.skip("验证契约：createProblemFetch 透传Request及AbortSignal，不增加重试或计时器", () => {
  // 契约骨架；待派工 B 先红后绿。
});

it.skip("验证契约：toFailureView 合法Error.cause的problem和unavailable保持内容与编号", () => {
  // 契约骨架；待派工 B 先红后绿。
});

it.skip("验证契约：toFailureView null/undefined/原始JSON/任意异常/恶意getter均返回固定无编号兜底", () => {
  // 契约骨架；待派工 B 先红后绿。
});

it.skip("验证契约：toFailureView 不显示error.message或HTML，不改输入或页面URL，不发请求或记日志", () => {
  // 契约骨架；待派工 B 先红后绿。
});

it.skip("验证契约：readProblemResponse 省略type/diagnostics/expected时补齐后端默认值，不把可省略字段误判为必填", () => {
  // 契约骨架；待派工 B 先红后绿。
});
