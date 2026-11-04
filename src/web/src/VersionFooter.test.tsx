// 第 11 张版本链路契约；全部使用注入传输、内存 router 与假时钟，不访问真实服务。
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { act, cleanup, render, renderHook, screen, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider, focusManager } from "@tanstack/react-query";
import { createMemoryHistory, RouterProvider } from "@tanstack/react-router";
import type { PropsWithChildren } from "react";
import { createAppRouter } from "./router";
import { account, problemResponse } from "./accounts/testSupport";
import { scheduling } from "./scheduling/testSupport";
import { ConfigProvider } from "antd";
import { job, onlineWorker } from "./jobs/testSupport";
import { createHealthClient, type FetchImplementation } from "./api/client";
import { VersionFooter } from "./VersionFooter";
import { usePlatformVersion } from "./usePlatformVersion";
import { fetchPlatformVersion } from "./api/version";

const caches: QueryClient[] = [];
beforeEach(() => {
  // jsdom 无 CSS 布局能力；沿用账号页面测试的浏览器媒体查询适配。
  const computed = window.getComputedStyle.bind(window);
  vi.spyOn(window, "getComputedStyle").mockImplementation((element) => computed(element));
  vi.stubGlobal("matchMedia", () => ({
    matches: false,
    addListener: () => undefined,
    removeListener: () => undefined,
    addEventListener: () => undefined,
    removeEventListener: () => undefined,
  }));
});
function context() {
  const cache = new QueryClient();
  caches.push(cache);
  function Wrapper({ children }: PropsWithChildren) {
    return (
      <ConfigProvider theme={{ token: { motion: false } }}>
        <QueryClientProvider client={cache}>{children}</QueryClientProvider>
      </ConfigProvider>
    );
  }
  return { cache, wrapper: Wrapper };
}
afterEach(() => {
  cleanup();
  for (const cache of caches.splice(0)) cache.clear();
  focusManager.setFocused(undefined);
  vi.useRealTimers();
});
function mountRoute(path: string, transport: FetchImplementation) {
  const environment = context();
  const router = createAppRouter({
    queryClient: environment.cache,
    fetchImpl: transport,
    history: createMemoryHistory({ initialEntries: [path] }),
  });
  return render(<RouterProvider router={router} />, { wrapper: environment.wrapper });
}

// 验证契约：登录后的各业务路由底部显示服务端版本，与命令输出完全一致。
it("所有已登录业务页面显示相同平台版本", async () => {
  const transport = vi.fn<FetchImplementation>((request) => {
    const path = new URL(request.url).pathname;
    if (path === "/api/auth/me") return Promise.resolve(Response.json(account));
    if (path === "/api/version")
      return Promise.resolve(Response.json({ version: "0.1.0 (82907a1)" }));
    if (path === "/api/jobs/scheduling") return Promise.resolve(Response.json(scheduling));
    if (path === "/api/jobs/1") return Promise.resolve(Response.json(job));
    if (path === "/api/worker/status") return Promise.resolve(Response.json(onlineWorker));
    if (path === "/api/health") return Promise.resolve(Response.json({ status: "ok" }));
    if (
      [
        "/api/jobs",
        "/api/accounts",
        "/api/audit/operations",
        "/api/audit/logins",
        "/api/storage-roots",
      ].includes(path)
    )
      return Promise.resolve(Response.json({ items: [], next_after_id: null }));
    return Promise.resolve(problemResponse(404));
  });
  for (const path of [
    "/",
    "/jobs",
    "/jobs/1",
    "/accounts",
    "/audit/operations",
    "/audit/logins",
    "/scheduling",
    "/storage-roots",
  ]) {
    const view = mountRoute(path, transport);
    await screen.findByText("0.1.0 (82907a1)");
    expect(screen.getByRole("contentinfo").textContent).toBe("0.1.0 (82907a1)");
    view.unmount();
  }
});

// 验证契约：提交号缺失的服务端文字原样显示“未知”，不在浏览器发现 git。
it("原样显示未知提交号", async () => {
  const client = createHealthClient(() =>
    Promise.resolve(Response.json({ version: "0.1.0 (未知)" })),
  );
  render(<VersionFooter client={client} />, context());
  expect((await screen.findByText("0.1.0 (未知)")).textContent).toBe("0.1.0 (未知)");
});

// 验证契约：加载和失败分别显示状态，不把 HTTP 失败伪装成未知版本，不影响业务页面。
it("区分加载失败和合法未知版本", async () => {
  let finish: ((response: Response) => void) | undefined;
  const client = createHealthClient(
    () =>
      new Promise<Response>((resolve) => {
        finish = resolve;
      }),
  );
  render(<VersionFooter client={client} />, context());
  expect(screen.getByRole("contentinfo").textContent).toBe("版本加载中");
  await act(() => {
    finish?.(problemResponse(502));
    return Promise.resolve();
  });
  expect((await screen.findByText("版本暂不可用")).textContent).toBe("版本暂不可用");
  expect(screen.queryByText("未知 (未知)")).toBeNull();
});

// 验证契约：登录与强制改密路由不请求受保护版本接口。
it("未完成登录或改密时不请求版本", async () => {
  for (const forced of [false, true]) {
    const transport = vi.fn<FetchImplementation>((request) => {
      const path = new URL(request.url).pathname;
      if (path === "/api/auth/me")
        return Promise.resolve(
          forced ? Response.json({ ...account, must_change_password: true }) : problemResponse(401),
        );
      return Promise.resolve(Response.json({ version: "不应显示" }));
    });
    const view = mountRoute(forced ? "/change-password" : "/login", transport);
    await screen.findByLabelText(forced ? "新密码" : "登录名");
    expect(
      transport.mock.calls.filter(([request]) => new URL(request.url).pathname === "/api/version"),
    ).toHaveLength(0);
    expect(screen.queryByRole("contentinfo")).toBeNull();
    view.unmount();
  }
});

// 验证契约：60000 毫秒边界后聚焦刷新，同客户端复用缓存，不同客户端完全隔离。
it("缓存过期聚焦刷新且不同应用隔离", async () => {
  vi.useFakeTimers({ toFake: ["Date"] });
  vi.setSystemTime(10000);
  const transport = vi.fn<FetchImplementation>(() =>
    Promise.resolve(Response.json({ version: "v1" })),
  );
  const client = createHealthClient(transport);
  const environment = context();
  const first = renderHook(() => usePlatformVersion(client), environment);
  await waitFor(() => {
    expect(first.result.current.data).toBe("v1");
  });
  first.unmount();
  vi.setSystemTime(69999);
  const second = renderHook(() => usePlatformVersion(client), environment);
  expect(second.result.current.data).toBe("v1");
  expect(transport).toHaveBeenCalledTimes(1);
  await act(() => {
    focusManager.setFocused(false);
    focusManager.setFocused(true);
    return Promise.resolve();
  });
  expect(transport).toHaveBeenCalledTimes(1);
  vi.setSystemTime(70000);
  await act(() => {
    focusManager.setFocused(false);
    focusManager.setFocused(true);
    return Promise.resolve();
  });
  await waitFor(() => {
    expect(transport).toHaveBeenCalledTimes(2);
  });
  const other = createHealthClient(() => Promise.resolve(Response.json({ version: "v2" })));
  const third = renderHook(() => usePlatformVersion(other), environment);
  expect(third.result.current.data).toBeUndefined();
  await waitFor(() => {
    expect(third.result.current.data).toBe("v2");
  });
});

// 验证契约：5 秒超时、卸载取消与取消前无请求；请求结束清定时器，不重试。
it("版本请求超时取消与计时器清理", async () => {
  vi.useFakeTimers();
  const transport = vi.fn<FetchImplementation>(() => new Promise<Response>(() => undefined));
  const client = createHealthClient(transport);
  const cancelled = new AbortController();
  cancelled.abort();
  await expect(fetchPlatformVersion(client, cancelled.signal)).rejects.toThrow();
  expect(transport).toHaveBeenCalledTimes(0);
  const pending = fetchPlatformVersion(client);
  const rejected = expect(pending).rejects.toThrow();
  await vi.advanceTimersByTimeAsync(4999);
  expect(transport.mock.calls[0]?.[0].signal.aborted).toBe(false);
  await vi.advanceTimersByTimeAsync(1);
  await rejected;
  expect(transport.mock.calls[0]?.[0].signal.aborted).toBe(true);
  expect(vi.getTimerCount()).toBe(0);
  const controller = new AbortController();
  const second = fetchPlatformVersion(client, controller.signal);
  const rejection = expect(second).rejects.toThrow();
  controller.abort();
  await rejection;
  expect(vi.getTimerCount()).toBe(0);
  const fast = createHealthClient(() => Promise.resolve(Response.json({ version: "v" })));
  expect(await fetchPlatformVersion(fast)).toBe("v");
  expect(vi.getTimerCount()).toBe(0);
  vi.useRealTimers();
  const hook = renderHook(() => usePlatformVersion(client), context());
  await waitFor(() => {
    expect(transport).toHaveBeenCalledTimes(3);
  });
  hook.unmount();
  expect(transport.mock.calls[2]?.[0].signal.aborted).toBe(true);
});

// 验证契约：空版本、过长版本、控制字符、错误 JSON 和非 2xx 不能作为正常版本展示。
it("拒绝不合法版本载荷并沿用统一错误边界", async () => {
  for (const payload of [
    {},
    { version: "" },
    { version: "x".repeat(129) },
    { version: 7 },
    { version: "x\n" },
    { version: "x\u0085" },
    { version: "x\u2028" },
  ]) {
    const client = createHealthClient(() => Promise.resolve(Response.json(payload)));
    await expect(fetchPlatformVersion(client)).rejects.toThrow();
  }
  const malformed = createHealthClient(() =>
    Promise.resolve(new Response("{", { headers: { "Content-Type": "application/json" } })),
  );
  await expect(fetchPlatformVersion(malformed)).rejects.toThrow();
  const failed = createHealthClient(() => Promise.resolve(problemResponse(502)));
  await expect(fetchPlatformVersion(failed)).rejects.toMatchObject({ cause: { kind: "problem" } });
});
