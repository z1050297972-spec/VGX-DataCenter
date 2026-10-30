// M1-07 导航层恢复失败：顶部提示、详情页与管理员确认；请求替身与真实内存 Router 并用，无网络。
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { createMemoryHistory, RouterProvider } from "@tanstack/react-router";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { account } from "../accounts/testSupport";
import type { FetchImplementation } from "../api/client";
import type { RecoveryBlock } from "../api/navigation";
import { onlineWorker } from "../jobs/testSupport";
import { formatDateTime } from "../format";
import { createAppRouter } from "../router";

const BANNER = "导航层写操作已被挡住：上次写入中断后有对不上的项，需管理员处理";
const LONG_PATH = "datasets/" + "very-long-directory-name/".repeat(8) + "meta.json";
const blocked: RecoveryBlock = {
  blocked: true,
  set_at: "2026-10-29T12:00:00Z",
  job_ids: ["3"],
  total_items: 1,
  items: [
    {
      job_id: "3",
      step_index: 0,
      path: LONG_PATH,
      expected_before: "sha256 aaaaaaaaaaaa",
      expected_after: "sha256 bbbbbbbbbbbb",
      actual: "sha256 cccccccccccc",
    },
  ],
};

beforeEach(() => {
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
afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
});

function mount(path: string, role: "administrator" | "member", state: { block: RecoveryBlock }) {
  const posts: string[] = [];
  const fetchImpl: FetchImplementation = (request) => {
    const url = new URL(request.url);
    if (url.pathname === "/api/auth/me")
      return Promise.resolve(Response.json({ ...account, role }));
    if (url.pathname === "/api/worker/status") return Promise.resolve(Response.json(onlineWorker));
    if (url.pathname === "/api/navigation/recovery-block/acknowledge") {
      posts.push(request.method);
      state.block = { blocked: false };
      return Promise.resolve(Response.json({ cleared_job_ids: ["3"] }));
    }
    if (url.pathname === "/api/navigation/recovery-block")
      return Promise.resolve(Response.json(state.block));
    return Promise.resolve(Response.json({ items: [], next_cursor: null }));
  };
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
    posts,
    close: () => {
      view.unmount();
      cache.clear();
      router.history.destroy();
    },
  };
}

it("有标记时所有页面顶部显示提示和跳到详情的链接", async () => {
  const view = mount("/jobs", "member", { block: blocked });
  try {
    expect(await screen.findByText(BANNER)).toBeTruthy();
    expect(screen.getByRole("link", { name: "查看对不上的项" }).getAttribute("href")).toBe(
      "/navigation/recovery",
    );
  } finally {
    view.close();
  }
});

it("没有标记时不显示提示", async () => {
  const view = mount("/jobs", "administrator", { block: { blocked: false } });
  try {
    await screen.findByText("作业列表");
    await new Promise((resolve) => setTimeout(resolve, 50));
    expect(screen.queryByText(BANNER)).toBeNull();
  } finally {
    view.close();
  }
});

it("成员看得到对不上的项但没有放行按钮", async () => {
  const view = mount("/navigation/recovery", "member", { block: blocked });
  try {
    expect(await screen.findByText("sha256 cccccccccccc")).toBeTruthy();
    expect(screen.queryByRole("button", { name: "已处理，放行写操作" })).toBeNull();
    expect(screen.getByText(formatDateTime(blocked.set_at ?? ""))).toBeTruthy();
    const cell = screen.getByText(LONG_PATH);
    expect(cell.getAttribute("title")).toBe(LONG_PATH);
  } finally {
    view.close();
  }
});

it("管理员取消确认不发请求；确认后发一次 POST 且提示消失", async () => {
  const state = { block: blocked };
  const view = mount("/navigation/recovery", "administrator", state);
  try {
    fireEvent.click(await screen.findByRole("button", { name: "已处理，放行写操作" }));
    fireEvent.click(await screen.findByRole("button", { name: /取\s*消/ }));
    await waitFor(() => {
      // jsdom 不触发动画结束事件，关闭中的对话框带 leave 类即视为已关闭。
      const dialog = screen.queryByRole("dialog");
      expect(dialog === null || dialog.className.includes("ant-zoom-leave")).toBe(true);
    });
    expect(view.posts).toHaveLength(0);
    expect(screen.getByText(BANNER)).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "已处理，放行写操作" }));
    fireEvent.click(
      (await screen.findAllByRole("button", { name: "确认放行" })).at(-1) as HTMLElement,
    );
    await waitFor(() => {
      expect(screen.queryByText(BANNER)).toBeNull();
    });
    expect(view.posts).toEqual(["POST"]);
    expect(await screen.findByText("当前没有被挡住的写操作")).toBeTruthy();
  } finally {
    view.close();
  }
});
