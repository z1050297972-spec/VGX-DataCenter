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

it("验证回归：默认 fetch 经账号客户端及对象调用时不绑定错误接收者", async () => {
  const browserFetch = vi.fn<FetchImplementation>(function (this: unknown) {
    if (this !== undefined && this !== globalThis) {
      throw new TypeError("Illegal invocation");
    }
    return Promise.resolve(Response.json({ status: "ok" }));
  });
  // 必须在重新加载模块前替换，旧实现才能捕获此替身，测试全程不触及真实网络。
  vi.resetModules();
  vi.stubGlobal("fetch", browserFetch);
  try {
    const { defaultFetch } = await import("./client");
    const { createAccountClient } = await import("./accounts");
    const onUnauthorized = vi.fn();
    // 默认传输路径与直接注入浏览器函数都不能把 options 作为接收者。
    for (const fetchImpl of [defaultFetch, browserFetch]) {
      const client = createAccountClient({ fetchImpl, onUnauthorized });
      await expect(client.GET("/api/health")).resolves.toMatchObject({ data: { status: "ok" } });
    }
    // 默认传输自身也要隔离外部调用方式，不能只依赖当前客户端的调用点。
    const holder = { send: defaultFetch };
    const response = await holder.send(new Request("/api/health"));
    await expect(response.json()).resolves.toEqual({ status: "ok" });
    expect(browserFetch).toHaveBeenCalledTimes(3);
    expect(onUnauthorized).not.toHaveBeenCalled();
    for (const [request] of browserFetch.mock.calls) {
      expect(request.url).toBe(new URL("/api/health", location.href).href);
      expect(request.method).toBe("GET");
    }
  } finally {
    vi.unstubAllGlobals();
    vi.resetModules();
  }
});
