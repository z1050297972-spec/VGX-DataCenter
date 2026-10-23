// 工单 02 的公开边界测试；传输显式注入，缓存和 DOM 在测试结束时清理。
import { afterEach, expect, it, vi } from "vitest";
import { createHealthClient, type FetchImplementation } from "./client";
import { fetchHealth } from "./health";

afterEach(() => {
  vi.useRealTimers();
});

it("验证契约：200 和 status=ok 返回生成类型的健康响应", async () => {
  const transport = vi.fn<FetchImplementation>().mockResolvedValue(Response.json({ status: "ok" }));
  await expect(fetchHealth(createHealthClient(transport))).resolves.toEqual({ status: "ok" });
  expect(transport).toHaveBeenCalledTimes(1);
});

it("验证契约：非 2xx、缺少响应和非法载荷均拒绝 Promise", async () => {
  const responses = [
    Response.json({ detail: "失败" }, { status: 503 }),
    new Response(null, { status: 204 }),
    Response.json({ status: "failed" }),
    Response.json(null),
    Response.json([]),
    Response.json({}),
    new Response("not json", { headers: { "Content-Type": "application/json" } }),
  ];
  for (const response of responses) {
    const transport = vi.fn<FetchImplementation>().mockResolvedValue(response);
    await expect(fetchHealth(createHealthClient(transport))).rejects.toBeInstanceOf(Error);
    expect(transport).toHaveBeenCalledTimes(1);
  }
});

it("验证契约：传输异常保留失败，不伪装为 ok", async () => {
  const failure = new Error("连接失败");
  const transport = vi.fn<FetchImplementation>().mockRejectedValue(failure);
  await expect(fetchHealth(createHealthClient(transport))).rejects.toBe(failure);
  expect(transport).toHaveBeenCalledTimes(1);
});

it("验证契约：HEALTH_TIMEOUT_MS 到期中止请求且不重试", async () => {
  vi.useFakeTimers();
  const transport = vi.fn<FetchImplementation>(
    (request) =>
      new Promise<Response>((_resolve, reject) => {
        request.signal.addEventListener(
          "abort",
          () => {
            reject(new Error("请求已中止"));
          },
          { once: true },
        );
      }),
  );
  const pending = fetchHealth(createHealthClient(transport));
  const rejected = expect(pending).rejects.toThrow("请求已中止");
  await vi.advanceTimersByTimeAsync(4999);
  expect(transport.mock.calls[0]?.[0].signal.aborted).toBe(false);
  await vi.advanceTimersByTimeAsync(1);
  expect(transport.mock.calls[0]?.[0].signal.aborted).toBe(true);
  await rejected;
  expect(transport).toHaveBeenCalledTimes(1);
});

it("验证契约：已取消信号不发请求，运行中取消传播到注入 fetch", async () => {
  const already = new AbortController();
  already.abort(new Error("预先取消"));
  const unused = vi.fn<FetchImplementation>().mockResolvedValue(Response.json({ status: "ok" }));
  await expect(fetchHealth(createHealthClient(unused), already.signal)).rejects.toThrow("预先取消");
  expect(unused).not.toHaveBeenCalled();

  const controller = new AbortController();
  const transport = vi.fn<FetchImplementation>(
    (request) =>
      new Promise<Response>((_resolve, reject) => {
        request.signal.addEventListener(
          "abort",
          () => {
            reject(new Error("运行中取消"));
          },
          { once: true },
        );
      }),
  );
  const pending = fetchHealth(createHealthClient(transport), controller.signal);
  const rejected = expect(pending).rejects.toThrow("运行中取消");
  controller.abort();
  await rejected;
  expect(transport.mock.calls[0]?.[0].signal.aborted).toBe(true);
  expect(transport).toHaveBeenCalledTimes(1);
});
