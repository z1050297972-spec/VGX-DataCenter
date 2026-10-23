// 工单 02 的公开边界测试；传输显式注入，缓存和 DOM 在测试结束时清理。
import { QueryClient, QueryClientProvider, focusManager } from "@tanstack/react-query";
import { act, cleanup, renderHook, waitFor } from "@testing-library/react";
import type { PropsWithChildren } from "react";
import { afterEach, expect, it, vi } from "vitest";
import { createHealthClient, type FetchImplementation } from "./api/client";
import { useHealth } from "./useHealth";

const queryClients: QueryClient[] = [];

// 每个测试单独持有缓存；测试结束释放，避免定时器或上一次结果影响后续断言。
function context() {
  const queryClient = new QueryClient();
  queryClients.push(queryClient);
  function Wrapper({ children }: PropsWithChildren) {
    return <QueryClientProvider client={queryClient}>{children}</QueryClientProvider>;
  }
  return { queryClient, wrapper: Wrapper };
}

afterEach(() => {
  cleanup();
  for (const queryClient of queryClients.splice(0)) queryClient.clear();
  focusManager.setFocused(undefined);
  vi.useRealTimers();
});

it("验证契约：QueryClientProvider 内加载、成功和失败状态正确", async () => {
  let complete: ((response: Response) => void) | undefined;
  const transport = vi.fn<FetchImplementation>(
    () =>
      new Promise<Response>((resolve) => {
        complete = resolve;
      }),
  );
  const client = createHealthClient(transport);
  const query = renderHook(() => useHealth(client), context());
  expect(query.result.current.isPending).toBe(true);
  expect(query.result.current.data).toBeUndefined();
  // 以异步 act 等待 Promise 结果触发的渲染提交。
  await act(() => {
    complete?.(Response.json({ status: "ok" }));
    return Promise.resolve();
  });
  await waitFor(() => {
    expect(query.result.current.isSuccess).toBe(true);
  });
  expect(query.result.current.data).toEqual({ status: "ok" });
  query.unmount();

  const failure = new Error("连接失败");
  const failedClient = createHealthClient(vi.fn<FetchImplementation>().mockRejectedValue(failure));
  const failed = renderHook(() => useHealth(failedClient), context());
  await waitFor(() => {
    expect(failed.result.current.isError).toBe(true);
  });
  expect(failed.result.current.error).toBe(failure);
});

it("验证契约：缓存有效期内不重复请求，过期后重新挂载可获取", async () => {
  // 只控制墙钟以测试 staleTime，保留调度定时器供 React 与 waitFor 正常执行。
  vi.useFakeTimers({ toFake: ["Date"] });
  vi.setSystemTime(10000);
  const transport = vi
    .fn<FetchImplementation>()
    .mockImplementation(() => Promise.resolve(Response.json({ status: "ok" })));
  const client = createHealthClient(transport);
  const environment = context();
  const first = renderHook(() => useHealth(client), environment);
  await waitFor(() => {
    expect(first.result.current.isSuccess).toBe(true);
  });
  first.unmount();
  vi.setSystemTime(10999);
  const fresh = renderHook(() => useHealth(client), environment);
  expect(fresh.result.current.data).toEqual({ status: "ok" });
  expect(transport).toHaveBeenCalledTimes(1);
  fresh.unmount();
  vi.setSystemTime(11001);
  const stale = renderHook(() => useHealth(client), environment);
  await waitFor(() => {
    expect(transport).toHaveBeenCalledTimes(2);
  });
  await waitFor(() => {
    expect(stale.result.current.isFetching).toBe(false);
  });
});

it("验证契约：不同注入客户端不共享健康缓存", async () => {
  const environment = context();
  const firstClient = createHealthClient(
    vi.fn<FetchImplementation>().mockResolvedValue(Response.json({ status: "ok" })),
  );
  const first = renderHook(() => useHealth(firstClient), environment);
  await waitFor(() => {
    expect(first.result.current.isSuccess).toBe(true);
  });
  first.unmount();
  const failure = new Error("第二个后端不可用");
  const secondTransport = vi.fn<FetchImplementation>().mockRejectedValue(failure);
  const secondClient = createHealthClient(secondTransport);
  const second = renderHook(() => useHealth(secondClient), environment);
  expect(second.result.current.data).toBeUndefined();
  await waitFor(() => {
    expect(second.result.current.error).toBe(failure);
  });
  expect(secondTransport).toHaveBeenCalledTimes(1);
});

it("验证契约：失败不自动重试，聚焦和时间推进不触发轮询", async () => {
  const environment = context();
  const transport = vi.fn<FetchImplementation>().mockRejectedValue(new Error("离线"));
  const client = createHealthClient(transport);
  const query = renderHook(() => useHealth(client), environment);
  await waitFor(() => {
    expect(query.result.current.isError).toBe(true);
  });
  vi.useFakeTimers();
  await act(async () => {
    await vi.advanceTimersByTimeAsync(10000);
    focusManager.setFocused(false);
    focusManager.setFocused(true);
    await vi.advanceTimersByTimeAsync(10000);
  });
  expect(transport).toHaveBeenCalledTimes(1);
  expect(query.result.current.isError).toBe(true);
});

it("验证契约：取消查询将 AbortSignal 传递给请求", async () => {
  const environment = context();
  const transport = vi.fn<FetchImplementation>(
    (request) =>
      new Promise<Response>((_resolve, reject) => {
        request.signal.addEventListener(
          "abort",
          () => {
            reject(new Error("查询取消"));
          },
          { once: true },
        );
      }),
  );
  const client = createHealthClient(transport);
  const query = renderHook(() => useHealth(client), environment);
  await waitFor(() => {
    expect(transport).toHaveBeenCalledTimes(1);
  });
  expect(transport.mock.calls[0]?.[0].signal.aborted).toBe(false);
  await act(async () => {
    await environment.queryClient.cancelQueries();
  });
  expect(transport.mock.calls[0]?.[0].signal.aborted).toBe(true);
  await waitFor(() => {
    expect(query.result.current.isFetching).toBe(false);
  });
});
