// 工单 02 的契约清单；A2 只收集并跳过，B 用注入依赖逐项实现。
import { it } from "vitest";

it.skip("验证契约：QueryClientProvider 内加载、成功和失败状态正确", () => {
  throw new Error("未实现");
});

it.skip("验证契约：缓存有效期内不重复请求，过期后重新挂载可获取", () => {
  throw new Error("未实现");
});

it.skip("验证契约：不同注入客户端不共享健康缓存", () => {
  throw new Error("未实现");
});

it.skip("验证契约：失败不自动重试，聚焦和时间推进不触发轮询", () => {
  throw new Error("未实现");
});

it.skip("验证契约：取消查询将 AbortSignal 传递给请求", () => {
  throw new Error("未实现");
});
