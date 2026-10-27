// 页面测试只替换浏览器能力及HTTP传输，使用真实路由、查询缓存和组件。
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { createMemoryHistory, RouterProvider } from "@tanstack/react-router";
import { cleanup, render } from "@testing-library/react";
import { beforeEach, afterEach, vi } from "vitest";
import { createAppRouter } from "../router";
import { account } from "../accounts/testSupport";
import { job, onlineWorker } from "../jobs/testSupport";
import { scheduling } from "./testSupport";
import type { Account } from "../api/accounts";
import type { Job } from "../api/jobs";
import type { Scheduling } from "../api/scheduling";
import type { FetchImplementation } from "../api/client";

beforeEach(() => {
  const computed = window.getComputedStyle.bind(window);
  vi.spyOn(window, "getComputedStyle").mockImplementation((element) => computed(element));
  vi.stubGlobal(
    "ResizeObserver",
    class {
      observe = vi.fn();
      unobserve = vi.fn();
      disconnect = vi.fn();
    },
  );
  vi.stubGlobal("matchMedia", () => ({
    matches: false,
    addListener: () => undefined,
    removeListener: () => undefined,
    addEventListener: () => undefined,
    removeEventListener: () => undefined,
  }));
});
afterEach(() => {
  cleanup();
  vi.useRealTimers();
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
});

/**
 * 在隔离缓存和真实内存Router中挂载页面。
 * @param path - 初始相对URL，包含测试需要的search参数。
 * @param fetchImpl - HTTP边界替身，不访问网络。
 * @returns 路由、缓存及必须在finally调用的close函数。
 * @throws Error 测试组件或路由装配错误。
 * @sideEffects 挂载React树；close取消请求并释放缓存/history。
 * @timeSemantics 生产轮询与超时保持原值，测试可通过Vitest推进计时器。
 */
export function mountPage(path: string, fetchImpl: FetchImplementation) {
  const cache = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  const router = createAppRouter({
    queryClient: cache,
    history: createMemoryHistory({ initialEntries: [path] }),
    fetchImpl,
  });
  const view = render(
    <QueryClientProvider client={cache}>
      <RouterProvider router={router} />
    </QueryClientProvider>,
  );
  return {
    cache,
    router,
    close: () => {
      view.unmount();
      cache.clear();
      router.history.destroy();
    },
  };
}

/**
 * 提供页面常用的独立响应样本。
 * @param snapshot - 当前调度快照，测试可推进。
 * @param record - 当前作业，默认独立运行样本。
 * @param identity - 当前账号，默认成员。
 * @returns 不联网的FetchImplementation。
 * @throws 无。
 * @sideEffects 无；仅生成Response。
 * @timeSemantics 同步读取本次样本，异步返回响应，不等待真实时间。
 */
export function pageFetch(
  snapshot: () => Scheduling = () => scheduling,
  record: () => Job = () => job,
  identity: () => Account = () => ({ ...account, role: "member" }),
): FetchImplementation {
  return (request) => {
    const path = new URL(request.url).pathname;
    if (path === "/api/auth/me") return Promise.resolve(Response.json(identity()));
    if (path === "/api/worker/status") return Promise.resolve(Response.json(onlineWorker));
    if (path === "/api/worker/scheduling") return Promise.resolve(Response.json(snapshot()));
    if (path === "/api/health") return Promise.resolve(Response.json({ status: "ok" }));
    if (path === "/api/jobs")
      return Promise.resolve(Response.json({ items: [record()], next_cursor: null }));
    if (path.endsWith("/log"))
      return Promise.resolve(
        Response.json({ tail: { status: "available", lines: [], truncated: false } }),
      );
    return Promise.resolve(Response.json(record()));
  };
}
