// 存储根传输契约清单（10）；请求只经账号客户端与生成OpenAPI类型。
import { describe, it, expect, vi } from "vitest";
import { createAccountClient } from "./accounts";
import { defaultFetch, type FetchImplementation } from "./client";
import { getStorageRoots } from "./storage";
import { storageRoots } from "../storage/testSupport";
import { problemResponse } from "../accounts/testSupport";

describe("存储根传输", () => {
  // 验证稳定相对接口与完整响应类型，不手写重复字段模型。
  it("getStorageRoots经openapi-fetch发送一次GET并返回生成的StorageRoots类型", async () => {
    const transport = vi.fn<FetchImplementation>().mockResolvedValue(Response.json(storageRoots));
    const client = createAccountClient({ fetchImpl: transport, onUnauthorized: vi.fn() });
    const controller = new AbortController();
    expect(
      await getStorageRoots({ client, payload: undefined, signal: controller.signal }),
    ).toEqual(storageRoots);
    expect(transport).toHaveBeenCalledTimes(1);
    const request = transport.mock.calls[0]?.[0];
    expect(request?.method).toBe("GET");
    expect(new URL(request?.url ?? "").pathname).toBe("/api/storage-roots");
    expect(request?.credentials).toBe("same-origin");
  });
  // 验证请求超时独立于worker的可配置访问预算，取消不会重试。
  it("十秒上限、外部取消和网络失败交统一诊断，无自动重试", async () => {
    vi.useFakeTimers();
    try {
      const transport = vi
        .fn<FetchImplementation>()
        .mockImplementation(() => new Promise<Response>(() => undefined));
      const client = createAccountClient({ fetchImpl: transport, onUnauthorized: vi.fn() });
      const controller = new AbortController();
      const pending = getStorageRoots({ client, payload: undefined, signal: controller.signal });
      const failure = expect(pending).rejects.toThrow();
      await vi.advanceTimersByTimeAsync(9999);
      expect(transport.mock.calls[0]?.[0].signal.aborted).toBe(false);
      await vi.advanceTimersByTimeAsync(1);
      await failure;
      expect(transport.mock.calls[0]?.[0].signal.aborted).toBe(true);
      const cancelled = expect(
        getStorageRoots({ client, payload: undefined, signal: controller.signal }),
      ).rejects.toThrow();
      controller.abort();
      await cancelled;
      transport.mockRejectedValueOnce(new TypeError("network"));
      await expect(
        getStorageRoots({ client, payload: undefined, signal: new AbortController().signal }),
      ).rejects.toThrow();
      expect(transport).toHaveBeenCalledTimes(3);
    } finally {
      vi.useRealTimers();
    }
  });
  // 验证缺响应体属于传输失败，禁止制造空根列表。
  it("成功响应缺data仍报错，401/403/502/500保留统一身份和诊断行为", async () => {
    const unauthorized = vi.fn();
    for (const status of [401, 403, 502, 500]) {
      const client = createAccountClient({
        fetchImpl: () =>
          Promise.resolve(
            status === 500
              ? Response.json(
                  {
                    type: "about:blank",
                    title: "Internal Server Error",
                    status: 500,
                    category: "defect",
                    detail: "安全摘要",
                    error_id: "00000000000040008000000000000000",
                    diagnostics: [],
                  },
                  { status, headers: { "Content-Type": "application/problem+json" } },
                )
              : problemResponse(status),
          ),
        onUnauthorized: unauthorized,
      });
      await expect(
        getStorageRoots({ client, payload: undefined, signal: new AbortController().signal }),
      ).rejects.toMatchObject({ cause: { kind: "problem", problem: { status } } });
    }
    expect(unauthorized).toHaveBeenCalledTimes(1);
    for (const response of [Response.json(null), new Response(null, { status: 204 })]) {
      const client = createAccountClient({
        fetchImpl: () => Promise.resolve(response),
        onUnauthorized: unauthorized,
      });
      await expect(
        getStorageRoots({ client, payload: undefined, signal: new AbortController().signal }),
      ).rejects.toThrow();
    }
  });
  // 验证默认传输不被作为对象方法错误绑定this，覆盖已有评审回归。
  it("默认fetch按浏览器this约束调用，响应无UUID、NFS来源或挂载表原文", async () => {
    vi.stubGlobal("fetch", function (this: unknown) {
      if (this !== undefined && this !== globalThis) throw new TypeError("Illegal invocation");
      return Promise.resolve(Response.json(storageRoots));
    });
    try {
      const client = createAccountClient({ fetchImpl: defaultFetch, onUnauthorized: vi.fn() });
      const result = await getStorageRoots({
        client,
        payload: undefined,
        signal: new AbortController().signal,
      });
      expect(result).toEqual(storageRoots);
      expect(Object.keys(result.items[0] ?? {})).toEqual([
        "name",
        "path",
        "writable",
        "online",
        "reason",
        "checked_at",
      ]);
    } finally {
      vi.unstubAllGlobals();
    }
  });
});
