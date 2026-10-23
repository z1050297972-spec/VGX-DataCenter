// 工单 02 的契约清单；A2 只收集并跳过，B 用注入依赖逐项实现。
import { it } from "vitest";

it.skip("验证契约：200 和 status=ok 返回生成类型的健康响应", () => {
  throw new Error("未实现");
});

it.skip("验证契约：非 2xx、缺少响应和非法载荷均拒绝 Promise", () => {
  throw new Error("未实现");
});

it.skip("验证契约：传输异常保留失败，不伪装为 ok", () => {
  throw new Error("未实现");
});

it.skip("验证契约：HEALTH_TIMEOUT_MS 到期中止请求且不重试", () => {
  throw new Error("未实现");
});

it.skip("验证契约：已取消信号不发请求，运行中取消传播到注入 fetch", () => {
  throw new Error("未实现");
});
