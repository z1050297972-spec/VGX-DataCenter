// 工单 02 的契约清单；A2 只收集并跳过，B 用注入依赖逐项实现。
import { it } from "vitest";

it.skip("验证契约：创建客户端不发请求且不修改全局 fetch", () => {
  throw new Error("未实现");
});

it.skip("验证契约：注入 fetch 收到同源 /api/health 请求且不同客户端相互独立", () => {
  throw new Error("未实现");
});
