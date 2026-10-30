// 存储根页面契约清单（10、L3）；路由行为经内存history与真实router验证。
import { formatDateTime } from "../time";
import { describe, it, expect, vi } from "vitest";
import { act, fireEvent, screen, waitFor, within } from "@testing-library/react";
import { focusManager, onlineManager } from "@tanstack/react-query";
import { mountPage } from "../scheduling/pageTestSupport";
import { account, problemResponse } from "../accounts/testSupport";
import type { Account } from "../api/accounts";
import type { StorageRoots } from "../api/storage";
import type { FetchImplementation } from "../api/client";
import { storageRoots } from "./testSupport";
import { ACCOUNT_QUERY_KEY } from "../accounts/runtime";

function transport(
  snapshot: () => StorageRoots = () => storageRoots,
  identity: () => Account = () => account,
): FetchImplementation {
  return (request) =>
    Promise.resolve(
      Response.json(
        new URL(request.url).pathname === "/api/auth/me"
          ? identity()
          : new URL(request.url).pathname === "/api/storage-roots"
            ? snapshot()
            : { status: "ok" },
      ),
    );
}

describe("存储根页面", () => {
  // 验证所有登录账号能通过菜单及直达路由进入，未登录遵循守卫跳转。
  it("成员与管理员均能从菜单打开 /storage-roots，未登录回登录页", async () => {
    for (const role of ["member", "administrator"] as const) {
      const page = mountPage(
        "/",
        transport(undefined, () => ({ ...account, role })),
      );
      try {
        fireEvent.click(await screen.findByRole("link", { name: "存储根" }));
        expect(await screen.findByRole("heading", { name: "存储根" })).toBeTruthy();
        expect(page.router.state.location.pathname).toBe("/storage-roots");
      } finally {
        page.close();
      }
    }
    const page = mountPage("/storage-roots", () => Promise.resolve(problemResponse(401)));
    try {
      await waitFor(() => {
        expect(page.router.state.location.pathname).toBe("/login");
      });
    } finally {
      page.close();
    }
  });
  // 验证展示使用生成模型字段，在线无原因，许可是平台登记值。
  it("按配置顺序显示名字、路径、只读或可写、在线状态和浏览器本地检查时间", async () => {
    const first = storageRoots.items[0];
    if (!first) throw new Error("测试样本缺失");
    const page = mountPage(
      "/storage-roots",
      transport(() => ({
        items: [first, { ...first, name: "writable", path: "/fake/write", writable: true }],
      })),
    );
    try {
      await screen.findByText("disk");
      const rows = screen.getAllByRole("row");
      expect(within(rows[1] as HTMLElement).getByText("只读")).toBeTruthy();
      expect(within(rows[2] as HTMLElement).getByText("可写")).toBeTruthy();
      expect(screen.getByText("/fake/disk")).toBeTruthy();
      expect(screen.getAllByText("在线")).toHaveLength(2);
      expect(screen.getAllByText(formatDateTime(first.checked_at))).toHaveLength(2);
    } finally {
      page.close();
    }
  });
  // 验证三种原因各自展示，不把不响应和没挂载混为一谈。
  it("not_mounted 显示没挂载", async () => {
    const page = mountPage(
      "/storage-roots",
      transport(() => ({
        items: storageRoots.items.map((item) => ({
          ...item,
          online: false,
          reason: "not_mounted",
        })),
      })),
    );
    try {
      expect(await screen.findByText("没挂载")).toBeTruthy();
    } finally {
      page.close();
    }
  });
  it("source_mismatch 显示挂错了盘", async () => {
    const page = mountPage(
      "/storage-roots",
      transport(() => ({
        items: storageRoots.items.map((item) => ({
          ...item,
          online: false,
          reason: "source_mismatch",
        })),
      })),
    );
    try {
      expect(await screen.findByText("挂错了盘")).toBeTruthy();
    } finally {
      page.close();
    }
  });
  it("timeout 显示超时，并说明本页挂载核对不能发现访问超时", async () => {
    const page = mountPage(
      "/storage-roots",
      transport(() => ({
        items: storageRoots.items.map((item) => ({ ...item, online: false, reason: "timeout" })),
      })),
    );
    try {
      expect(await screen.findByText("超时")).toBeTruthy();
      expect(screen.getByText(/访问超时只能由作业检查发现/)).toBeTruthy();
    } finally {
      page.close();
    }
  });
  // 验证查询节奏由显式动作决定，不因聚焦、重连或时间流逝重查。
  it("进入页面检查一次，重新检查按钮只发一次GET，请求中按钮禁用", async () => {
    let calls = 0;
    let finish: ((response: Response) => void) | undefined;
    const fallback = transport();
    const page = mountPage("/storage-roots", (request) => {
      if (new URL(request.url).pathname !== "/api/storage-roots") return fallback(request);
      calls += 1;
      return calls === 1
        ? Promise.resolve(Response.json(storageRoots))
        : new Promise<Response>((resolve) => {
            finish = resolve;
          });
    });
    try {
      await screen.findByText("disk");
      expect(calls).toBe(1);
      const button = screen.getByRole("button", { name: "重新检查" });
      fireEvent.click(button);
      await waitFor(() => {
        expect(calls).toBe(2);
        expect(button).toHaveProperty("disabled", true);
      });
      fireEvent.click(button);
      expect(calls).toBe(2);
      await act(async () => {
        finish?.(Response.json(storageRoots));
        await Promise.resolve();
      });
      await waitFor(() => {
        expect(button).toHaveProperty("disabled", false);
      });
    } finally {
      page.close();
    }
  });
  it("不轮询、不重试、不在聚焦或重连时自动请求，离页重入重新检查", async () => {
    let calls = 0;
    const fallback = transport();
    const page = mountPage("/storage-roots", (request) => {
      if (new URL(request.url).pathname !== "/api/storage-roots") return fallback(request);
      calls += 1;
      return Promise.resolve(calls === 2 ? problemResponse(502) : Response.json(storageRoots));
    });
    try {
      await screen.findByText("disk");
      await waitFor(() => {
        expect(screen.getByRole("button", { name: "重新检查" })).toHaveProperty("disabled", false);
      });
      vi.useFakeTimers();
      await act(async () => {
        focusManager.setFocused(false);
        focusManager.setFocused(true);
        onlineManager.setOnline(false);
        onlineManager.setOnline(true);
        await vi.advanceTimersByTimeAsync(60_000);
      });
      expect(calls).toBe(1);
      await act(async () => {
        fireEvent.click(screen.getByRole("button", { name: "重新检查" }));
        await vi.advanceTimersByTimeAsync(60_000);
      });
      expect(calls).toBe(2);
      vi.useRealTimers();
      await act(() => page.router.navigate({ to: "/" }));
      await act(() => page.router.navigate({ to: "/storage-roots" }));
      await waitFor(() => {
        expect(calls).toBe(3);
      });
    } finally {
      page.close();
      vi.useRealTimers();
      focusManager.setFocused(undefined);
      onlineManager.setOnline(true);
    }
  });
  // 验证失败不能伪装成新的在线结果，旧时刻始终可识别。
  it("失败由DiagnosticCard展示，保留旧数据及原时刻，成功后更新检查时间", async () => {
    let calls = 0;
    const fallback = transport();
    const page = mountPage("/storage-roots", (request) => {
      if (new URL(request.url).pathname !== "/api/storage-roots") return fallback(request);
      calls += 1;
      return Promise.resolve(
        calls === 2
          ? problemResponse(502)
          : Response.json(
              calls === 1
                ? storageRoots
                : {
                    items: storageRoots.items.map((item) => ({
                      ...item,
                      checked_at: "2026-10-27T12:01:00Z",
                    })),
                  },
            ),
      );
    });
    try {
      await screen.findByText("disk");
      const button = screen.getByRole("button", { name: "重新检查" });
      fireEvent.click(button);
      expect(await screen.findByRole("alert")).toBeTruthy();
      expect(screen.getByText("disk")).toBeTruthy();
      expect(screen.getByText(formatDateTime("2026-10-27T12:00:00Z"))).toBeTruthy();
      fireEvent.click(button);
      expect(await screen.findByText(formatDateTime("2026-10-27T12:01:00Z"))).toBeTruthy();
      expect(screen.queryByRole("alert")).toBeNull();
    } finally {
      page.close();
    }
  });
  it("空items显示未登记存储根，初始请求显示加载状态", async () => {
    let finish: ((response: Response) => void) | undefined;
    const fallback = transport();
    const page = mountPage("/storage-roots", (request) =>
      new URL(request.url).pathname === "/api/storage-roots"
        ? new Promise<Response>((resolve) => {
            finish = resolve;
          })
        : fallback(request),
    );
    try {
      expect(await screen.findByRole("status")).toHaveProperty("textContent", "正在检查");
      expect(screen.queryByText("未登记存储根")).toBeNull();
      await act(async () => {
        finish?.(Response.json({ items: [] }));
        await Promise.resolve();
      });
      expect(await screen.findByText("未登记存储根")).toBeTruthy();
      expect(screen.queryByRole("status")).toBeNull();
    } finally {
      page.close();
    }
  });
  // 验证账号隔离与迟到响应，避免上个账号的请求覆盖当前界面。
  it("换号或卸载取消请求并清缓存，迟到响应被忽略，401统一回登录", async () => {
    let identity = account;
    let unauthorized = false;
    let signedOut = false;
    const requests: Request[] = [];
    const finishes: ((response: Response) => void)[] = [];
    const fallback = transport(undefined, () => identity);
    const page = mountPage("/storage-roots", (request) => {
      if (signedOut && new URL(request.url).pathname === "/api/auth/me")
        return Promise.resolve(problemResponse(401));
      if (new URL(request.url).pathname !== "/api/storage-roots") return fallback(request);
      requests.push(request);
      if (unauthorized) {
        signedOut = true;
        return Promise.resolve(problemResponse(401));
      }
      if (requests.length === 2)
        return Promise.resolve(
          Response.json({
            items: storageRoots.items.map((item) => ({ ...item, name: "new-account-root" })),
          }),
        );
      return new Promise<Response>((resolve) => {
        finishes.push(resolve);
      });
    });
    try {
      await waitFor(() => {
        expect(requests).toHaveLength(1);
      });
      identity = { ...account, account_id: "42", display_name: "另一成员", role: "member" };
      await act(() => page.cache.invalidateQueries({ queryKey: ACCOUNT_QUERY_KEY }));
      await screen.findByText("new-account-root");
      expect(requests[0]?.signal.aborted).toBe(true);
      await act(async () => {
        finishes[0]?.(Response.json(storageRoots));
        await Promise.resolve();
      });
      expect(screen.queryByText("disk")).toBeNull();
      await waitFor(() => {
        expect(page.cache.getQueryData(["storage-roots", account.account_id])).toBeUndefined();
      });
      fireEvent.click(screen.getByRole("button", { name: "重新检查" }));
      await waitFor(() => {
        expect(requests).toHaveLength(3);
      });
      await act(() => page.router.navigate({ to: "/" }));
      expect(requests[2]?.signal.aborted).toBe(true);
      await act(async () => {
        finishes[1]?.(Response.json(storageRoots));
        await Promise.resolve();
      });
      unauthorized = true;
      await act(() => page.router.navigate({ to: "/storage-roots" }));
      await waitFor(() => {
        expect(page.router.state.location.pathname).toBe("/login");
      });
      expect(page.cache.getQueryData(["storage-roots", "42"])).toBeUndefined();
    } finally {
      page.close();
      for (const finish of finishes) finish(Response.json(storageRoots));
    }
  });
  // 验证页面不引入search语义；真实router接受直达和刷新，不依赖手工URL解析。
  it("真实router下 /storage-roots 直达与刷新可用，无search参数", async () => {
    for (const label of ["direct", "reloaded"]) {
      const page = mountPage(
        "/storage-roots",
        transport(() => ({ items: storageRoots.items.map((item) => ({ ...item, name: label })) })),
      );
      try {
        expect(await screen.findByText(label)).toBeTruthy();
        expect(page.router.state.location.pathname).toBe("/storage-roots");
        expect(page.router.state.location.search).toEqual({});
      } finally {
        page.close();
      }
    }
  });
});
