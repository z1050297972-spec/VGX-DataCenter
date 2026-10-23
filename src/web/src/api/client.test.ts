// 工单 02 的公开边界测试；传输显式注入，缓存和 DOM 在测试结束时清理。
import { expect, it, vi } from "vitest";
import { createHealthClient, type FetchImplementation } from "./client";

it("验证契约：创建客户端不发请求且不修改全局 fetch", () => {
  const transport = vi.fn<FetchImplementation>();
  const client = createHealthClient(transport);
  expect(typeof client.GET).toBe("function");
  expect(transport).not.toHaveBeenCalled();
});

it("验证契约：注入 fetch 收到同源 /api/health 请求且不同客户端相互独立", async () => {
  const firstTransport = vi
    .fn<FetchImplementation>()
    .mockResolvedValue(Response.json({ status: "ok" }));
  const secondTransport = vi
    .fn<FetchImplementation>()
    .mockResolvedValue(Response.json({ status: "ok" }));
  const first = createHealthClient(firstTransport);
  const second = createHealthClient(secondTransport);
  const result = await first.GET("/api/health");
  expect(result.data).toEqual({ status: "ok" });
  expect(firstTransport).toHaveBeenCalledTimes(1);
  expect(secondTransport).not.toHaveBeenCalled();
  const request = firstTransport.mock.calls[0]?.[0];
  expect(request?.url).toBe(new URL("/api/health", location.href).href);
  expect(request?.method).toBe("GET");
  await second.GET("/api/health");
  expect(secondTransport).toHaveBeenCalledTimes(1);
});
