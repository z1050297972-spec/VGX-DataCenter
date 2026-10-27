// 09 契约清单；路由行为通过真实 createAppRouter 与内存 history 验证。
import { it, expect, vi } from "vitest";
import { createAccountClient } from "./accounts";
import { defaultFetch, type FetchImplementation } from "./client";
import { getScheduling, submitGpuJob, submitNavigationJob } from "./scheduling";
import { scheduling } from "../scheduling/testSupport";
import { job } from "../jobs/testSupport";
import { problemResponse } from "../accounts/testSupport";

it("getScheduling 使用账号客户端的相对GET路径、生成类型和AbortSignal，单次十秒上限", async () => {
  const transport = vi.fn<FetchImplementation>().mockResolvedValue(Response.json(scheduling));
  const client = createAccountClient({ fetchImpl: transport, onUnauthorized: vi.fn() });
  const controller = new AbortController();
  const result = await getScheduling({ client, payload: undefined, signal: controller.signal });
  expect(result).toEqual(scheduling);
  const request = transport.mock.calls[0]?.[0];
  expect(request?.method).toBe("GET");
  expect(new URL(request?.url ?? "").pathname).toBe("/api/worker/scheduling");
  expect(request?.credentials).toBe("same-origin");
  expect(transport).toHaveBeenCalledTimes(1);
  controller.abort();
  expect(request?.signal.aborted).toBe(true);
});

it("401、403、409、502走统一问题处理，不返回伪造空资源", async () => {
  const unauthorized = vi.fn();
  for (const status of [401, 403, 409, 502]) {
    const transport = vi.fn<FetchImplementation>().mockResolvedValue(problemResponse(status));
    const client = createAccountClient({ fetchImpl: transport, onUnauthorized: unauthorized });
    await expect(
      getScheduling({ client, payload: undefined, signal: new AbortController().signal }),
    ).rejects.toMatchObject({ cause: { kind: "problem", problem: { status } } });
    expect(transport).toHaveBeenCalledTimes(1);
  }
  expect(unauthorized).toHaveBeenCalledTimes(1);
  const client = createAccountClient({
    fetchImpl: () => Promise.resolve(Response.json(null)),
    onUnauthorized: unauthorized,
  });
  await expect(
    getScheduling({ client, payload: undefined, signal: new AbortController().signal }),
  ).rejects.toThrow();
});

it("GPU/写锁示例POST使用各自生成载荷，成功返回新记录，无操作者或命令路径", async () => {
  const transport = vi
    .fn<FetchImplementation>()
    .mockImplementation(() => Promise.resolve(Response.json(job, { status: 201 })));
  const client = createAccountClient({ fetchImpl: transport, onUnauthorized: vi.fn() });
  const signal = new AbortController().signal;
  expect(await submitGpuJob({ client, payload: { hold_s: 600 }, signal })).toEqual(job);
  expect(
    await submitNavigationJob({ client, payload: { expected_value: "", pause_s: 10 }, signal }),
  ).toEqual(job);
  expect(
    transport.mock.calls.map(([request]) => [request.method, new URL(request.url).pathname]),
  ).toEqual([
    ["POST", "/api/jobs/example/gpu"],
    ["POST", "/api/jobs/example/navigation"],
  ]);
  expect(await transport.mock.calls[0]?.[0].json()).toEqual({ hold_s: 600 });
  expect(await transport.mock.calls[1]?.[0].json()).toEqual({ expected_value: "", pause_s: 10 });
});

it("请求超时/取消不重试，默认传输保持浏览器原生fetch的this调用语义", async () => {
  vi.useFakeTimers();
  try {
    const transport = vi
      .fn<FetchImplementation>()
      .mockImplementation(() => new Promise<Response>(() => undefined));
    const client = createAccountClient({ fetchImpl: transport, onUnauthorized: vi.fn() });
    const controller = new AbortController();
    const pending = getScheduling({ client, payload: undefined, signal: controller.signal });
    const rejected = expect(pending).rejects.toThrow();
    await vi.advanceTimersByTimeAsync(9999);
    expect(transport.mock.calls[0]?.[0].signal.aborted).toBe(false);
    await vi.advanceTimersByTimeAsync(1);
    await rejected;
    expect(transport.mock.calls[0]?.[0].signal.aborted).toBe(true);
    const cancelled = getScheduling({ client, payload: undefined, signal: controller.signal });
    const cancellation = expect(cancelled).rejects.toThrow();
    controller.abort();
    await cancellation;
    expect(transport).toHaveBeenCalledTimes(2);
    vi.stubGlobal("fetch", function (this: unknown) {
      if (this !== undefined && this !== globalThis) throw new TypeError("Illegal invocation");
      return Promise.resolve(Response.json(scheduling));
    });
    const browser = createAccountClient({ fetchImpl: defaultFetch, onUnauthorized: vi.fn() });
    expect(
      await getScheduling({
        client: browser,
        payload: undefined,
        signal: new AbortController().signal,
      }),
    ).toEqual(scheduling);
  } finally {
    vi.useRealTimers();
    vi.unstubAllGlobals();
  }
});
