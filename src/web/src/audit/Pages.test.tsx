// 07 前端契约清单；全部使用注入传输与内存路由，按行为逐条验证。
import { formatDateTime } from "../time";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import {
  act,
  cleanup,
  fireEvent,
  render,
  renderHook,
  screen,
  waitFor,
  within,
} from "@testing-library/react";
import { QueryClient, QueryClientProvider, focusManager } from "@tanstack/react-query";
import { createMemoryHistory, RouterProvider } from "@tanstack/react-router";
import { ConfigProvider } from "antd";
import type { ReactNode } from "react";
import { createAppRouter } from "../router";
import { toFailureView } from "../api/problems";
import { createAccountClient } from "../api/accounts";
import type { FetchImplementation } from "../api/client";
import type { LoginLogPage, OperationLogPage, OperationSearch } from "../api/audit";
import { account, problemResponse } from "../accounts/testSupport";
import { AccountClientProvider } from "../accounts/runtime";
import { useOperationLogs, useLoginLogs, useAuditRetention, useSetAuditRetention } from "./queries";
import { validateLoginSearch, validateOperationSearch } from "./search";

const caches: QueryClient[] = [];
beforeEach(() => {
  // jsdom 不计算伪元素与动画，保留真实 DOM 交互及网络取消行为。
  vi.stubGlobal(
    "ResizeObserver",
    class {
      observe = vi.fn();
      unobserve = vi.fn();
      disconnect = vi.fn();
    },
  );
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
  for (const cache of caches) cache.clear();
  caches.length = 0;
  focusManager.setFocused(undefined);
  vi.useRealTimers();
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
});
function newCache() {
  const cache = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  caches.push(cache);
  return cache;
}
function hooks(fetchImpl: FetchImplementation) {
  const cache = newCache();
  const client = createAccountClient({ fetchImpl, onUnauthorized: vi.fn() });
  const wrapper = ({ children }: { children: ReactNode }) => (
    <QueryClientProvider client={cache}>
      <AccountClientProvider client={client}>{children}</AccountClientProvider>
    </QueryClientProvider>
  );
  return { cache, wrapper };
}
const operation: OperationLogPage["items"][number] = {
  log_id: "101",
  occurred_at: "2026-01-02T03:04:05.000006Z",
  actor: { account_id: "10", name: "原操作人", deleted: false },
  target: { kind: "account", object_id: "20", name: "原对象", deleted: false },
  operation: "set_role",
  result: "success",
  failure_category: null,
  request_id: null,
  source_ip: null,
  details: { version: 1, before: { role: "member" }, after: { role: "administrator" } },
};
const login: LoginLogPage["items"][number] = {
  log_id: "201",
  occurred_at: operation.occurred_at,
  account: { account_id: "10", name: "旧登录者", deleted: false },
  login_name: "old_admin",
  kind: "login",
  result: "success",
  source_ip: null,
  request_id: null,
  failure_category: null,
  attempt_count: 1,
};
function mount(path: string, fetchImpl: FetchImplementation = transport()) {
  const queryClient = newCache();
  const router = createAppRouter({
    queryClient,
    fetchImpl,
    history: createMemoryHistory({ initialEntries: [path] }),
  });
  const view = render(
    <ConfigProvider theme={{ token: { motion: false } }}>
      <QueryClientProvider client={queryClient}>
        <RouterProvider router={router} />
      </QueryClientProvider>
    </ConfigProvider>,
  );
  return { router, queryClient, ...view };
}
function transport(
  operations: OperationLogPage = { items: [operation], next_cursor: null },
  logins: LoginLogPage = { items: [login], next_cursor: null },
) {
  return vi.fn<FetchImplementation>((request) => {
    const path = new URL(request.url).pathname;
    if (path === "/api/auth/me") return Promise.resolve(Response.json(account));
    if (path === "/api/audit/operations") return Promise.resolve(Response.json(operations));
    if (path === "/api/audit/logins") return Promise.resolve(Response.json(logins));
    if (path === "/api/audit/retention") return Promise.resolve(Response.json({ days: 30 }));
    return Promise.resolve(Response.json({ status: "ok" }));
  });
}

it("验收1：操作日志和登录日志表格仅只读，无改单条或删单条按钮", async () => {
  for (const [path, text] of [
    ["operations", "原操作人"],
    ["logins", "旧登录者"],
  ]) {
    const view = mount("/audit/" + (path ?? ""));
    await screen.findByText(text ?? "");
    const table = screen.getByRole("table");
    expect(within(table).queryByRole("button")).toBeNull();
    expect(screen.queryByRole("button", { name: /编辑|删除/ })).toBeNull();
    view.unmount();
  }
});

it("验收5：保留期表单只在操作日志页面，两种日志共用同一设置", async () => {
  const fetchImpl = transport();
  const view = mount("/audit/operations", fetchImpl);
  await waitFor(() => {
    expect(screen.getByLabelText<HTMLInputElement>("保留天数").value).toBe("30");
  });
  expect(screen.getByRole("button", { name: "保存保留期" })).toBeTruthy();
  view.unmount();
  fetchImpl.mockClear();
  mount("/audit/logins", fetchImpl);
  await screen.findByText("旧登录者");
  expect(screen.queryByLabelText("保留天数")).toBeNull();
  expect(fetchImpl.mock.calls.some(([request]) => request.url.includes("/retention"))).toBe(false);
});

it("验收5：7和365可提交，6和366以及布尔小数拒绝，失败保留表单和已有列表", async () => {
  const base = transport();
  const writes: Request[] = [];
  mount("/audit/operations", (request) => {
    if (request.method === "PUT") {
      writes.push(request);
      return Promise.resolve(problemResponse(502));
    }
    return base(request);
  });
  await screen.findByText("原操作人");
  await waitFor(() => {
    expect(screen.getByLabelText<HTMLInputElement>("保留天数").value).toBe("30");
  });
  for (const value of ["6", "366", "true", "false", "7.5", ""]) {
    fireEvent.change(screen.getByLabelText("保留天数"), { target: { value } });
    fireEvent.click(screen.getByRole("button", { name: "保存保留期" }));
    expect(await screen.findByText("保留期须为 7–365 天的整数")).toBeTruthy();
    expect(writes).toHaveLength(0);
  }
  for (const days of [7, 365]) {
    fireEvent.change(screen.getByLabelText("保留天数"), { target: { value: String(days) } });
    fireEvent.click(screen.getByRole("button", { name: "保存保留期" }));
    expect(await screen.findByText("口令核验资源繁忙")).toBeTruthy();
    expect(screen.getByLabelText<HTMLInputElement>("保留天数").value).toBe(String(days));
    expect(screen.getByText("原操作人")).toBeTruthy();
  }
  expect(writes).toHaveLength(2);
  expect(await writes[0]?.json()).toEqual({ days: 7 });
  expect(await writes[1]?.json()).toEqual({ days: 365 });
});

it("验收5：保存过程中禁用重复提交，确认成功刷新设置及操作日志并回首页", async () => {
  let resolveSave: ((response: Response) => void) | undefined;
  let saved = false;
  const base = transport({ items: [operation], next_cursor: "next" });
  const fetchImpl = vi.fn<FetchImplementation>((request) => {
    if (request.method === "PUT")
      return new Promise((resolve) => {
        resolveSave = resolve;
      });
    if (saved && new URL(request.url).pathname === "/api/audit/retention")
      return Promise.resolve(Response.json({ days: 7 }));
    return base(request);
  });
  const view = mount("/audit/operations?cursor=old-page", fetchImpl);
  await waitFor(() => {
    expect(screen.getByLabelText<HTMLInputElement>("保留天数").value).toBe("30");
  });
  fireEvent.change(screen.getByLabelText("保留天数"), { target: { value: "7" } });
  const save = screen.getByRole<HTMLButtonElement>("button", { name: "保存保留期" });
  fireEvent.click(save);
  await waitFor(() => {
    expect(resolveSave).toBeDefined();
  });
  expect(save.disabled).toBe(true);
  fireEvent.click(save);
  expect(fetchImpl.mock.calls.filter(([request]) => request.method === "PUT")).toHaveLength(1);
  expect(view.router.state.location.search.cursor).toBe("old-page");
  saved = true;
  act(() => {
    resolveSave?.(Response.json({ days: 7 }));
  });
  await waitFor(() => {
    expect(view.router.state.location.search.cursor).toBeUndefined();
  });
  await waitFor(() => {
    expect(save.disabled).toBe(false);
  });
  expect(
    fetchImpl.mock.calls.filter(
      ([request]) => request.url.includes("/retention") && request.method === "GET",
    ).length,
  ).toBeGreaterThan(1);
  expect(
    fetchImpl.mock.calls.some(
      ([request]) =>
        new URL(request.url).pathname === "/api/audit/operations" &&
        !new URL(request.url).searchParams.has("cursor"),
    ),
  ).toBe(true);
  expect(screen.getByLabelText<HTMLInputElement>("保留天数").value).toBe("7");
});

it("验收6：管理员菜单有操作日志和登录日志，成员菜单两个入口均不显示", async () => {
  for (const role of ["administrator", "member"] as const) {
    const base = transport();
    const view = mount("/", (request) =>
      new URL(request.url).pathname === "/api/auth/me"
        ? Promise.resolve(Response.json({ ...account, role }))
        : base(request),
    );
    await screen.findByText("后端正常");
    for (const name of ["操作日志", "登录日志"])
      expect(Boolean(screen.queryByRole("link", { name }))).toBe(role === "administrator");
    view.unmount();
  }
});

it("验收6：成员直接访问两个日志路由时不加载日志和设置，不发对应查询", async () => {
  for (const path of ["operations", "logins"]) {
    const fetchImpl = vi.fn<FetchImplementation>((request) =>
      Promise.resolve(
        Response.json(
          new URL(request.url).pathname === "/api/auth/me"
            ? { ...account, role: "member" }
            : { status: "ok" },
        ),
      ),
    );
    const view = mount("/audit/" + path, fetchImpl);
    await waitFor(() => {
      expect(view.router.state.location.pathname).toBe("/");
    });
    await screen.findByText("后端正常");
    expect(fetchImpl.mock.calls.some(([request]) => request.url.includes("/api/audit/"))).toBe(
      false,
    );
    view.unmount();
  }
});

it("验收6：窗口重新聚焦身份已降级时隐藏日志并取消请求，旧管理员结果不再显示", async () => {
  let member = false;
  const signals: AbortSignal[] = [];
  const base = transport();
  const view = mount("/audit/operations", (request) => {
    if (new URL(request.url).pathname === "/api/auth/me")
      return Promise.resolve(
        Response.json({ ...account, role: member ? "member" : "administrator" }),
      );
    if (member && request.url.includes("/api/audit/")) {
      signals.push(request.signal);
      return new Promise(() => undefined);
    }
    return base(request);
  });
  await screen.findByText("原操作人");
  member = true;
  act(() => {
    focusManager.setFocused(false);
    focusManager.setFocused(true);
  });
  await waitFor(() => {
    expect(view.router.state.location.pathname).toBe("/");
  });
  await screen.findByText("后端正常");
  expect(screen.queryByText("原操作人")).toBeNull();
  expect(screen.queryByRole("link", { name: "操作日志" })).toBeNull();
  expect(signals.length).toBeGreaterThan(0);
  expect(signals.every((signal) => signal.aborted)).toBe(true);
});

it("验收7：操作人和账号对象删除后各显示历史名字加已删除，同名新账号不接管旧记录", async () => {
  mount(
    "/audit/operations",
    transport({
      items: [
        {
          ...operation,
          actor: { ...operation.actor, deleted: true },
          target: { ...operation.target, deleted: true },
        },
        {
          ...operation,
          log_id: "102",
          actor: { account_id: "30", name: "原操作人", deleted: false },
          target: { ...operation.target, object_id: "40" },
        },
      ],
      next_cursor: null,
    }),
  );
  expect(await screen.findByText("原操作人（已删除）")).toBeTruthy();
  expect(screen.getByText("原对象（已删除）")).toBeTruthy();
  expect(screen.getByText("原操作人", { selector: "td" })).toBeTruthy();
});

it("验收3/7：登录日志已删账号保留旧显示名和登录名，未知账号只显示账号不存在", async () => {
  mount(
    "/audit/logins",
    transport(undefined, {
      items: [
        { ...login, account: login.account && { ...login.account, deleted: true } },
        { ...login, log_id: "202", account: null, login_name: null, result: "account_missing" },
      ],
      next_cursor: null,
    }),
  );
  expect(await screen.findByText("旧登录者（已删除）")).toBeTruthy();
  expect(screen.getByText("old_admin")).toBeTruthy();
  expect(screen.getAllByText("账号不存在").length).toBeGreaterThan(0);
});

it("验收3：缺失来源显示未知，IPv4和IPv6作为安全文本呈现", async () => {
  for (const path of ["operations", "logins"]) {
    const ips = [null, "192.0.2.1", "2001:db8::1"];
    const view = mount(
      "/audit/" + path,
      transport(
        {
          items: ips.map((source_ip, i) => ({ ...operation, log_id: String(i + 1), source_ip })),
          next_cursor: null,
        },
        {
          items: ips.map((source_ip, i) => ({ ...login, log_id: String(i + 1), source_ip })),
          next_cursor: null,
        },
      ),
    );
    expect(await screen.findByText("192.0.2.1")).toBeTruthy();
    expect(screen.getByText("2001:db8::1")).toBeTruthy();
    expect(screen.getAllByText("未知").length).toBeGreaterThan(0);
    view.unmount();
  }
});

it("验收4：服务端名字明细按文本渲染，无脚本执行和秘密字段展示", async () => {
  const malicious = "<img src=x onerror=alert(1)>";
  const details = {
    ...operation.details,
    after: { display_name: malicious, password: "secret-password", token: "secret-token" },
  };
  mount(
    "/audit/operations",
    transport({
      items: [{ ...operation, actor: { ...operation.actor, name: malicious }, details }],
      next_cursor: null,
    }),
  );
  await screen.findByText(malicious, { selector: "td" });
  expect(document.querySelector('img[src="x"]')).toBeNull();
  expect(document.body.textContent).toContain(malicious);
  expect(document.body.textContent).not.toMatch(/secret-password|secret-token/);
});

it("规范10.6：两个页面用Router类型化search保存筛选，刷新分享返回相同条件，不解析URLSearchParams", async () => {
  for (const kind of ["operations", "logins"] as const) {
    const view = mount("/audit/" + kind);
    await screen.findByRole("table");
    fireEvent.change(screen.getByLabelText(kind === "operations" ? "操作人编号" : "账号编号"), {
      target: { value: "9007199254740993" },
    });
    fireEvent.change(screen.getByLabelText("开始时间（含）"), {
      target: { value: "2026-01-01T08:00:00+08:00" },
    });
    fireEvent.click(screen.getByRole("button", { name: "筛选" }));
    await waitFor(() => {
      expect(view.router.state.location.search).toMatchObject({
        account_id: "9007199254740993",
        start: "2026-01-01T00:00:00.000000Z",
      });
    });
    const href = view.router.state.location.href;
    view.unmount();
    const restored = mount(href);
    await screen.findByRole("table");
    expect(
      screen.getByLabelText<HTMLInputElement>(kind === "operations" ? "操作人编号" : "账号编号")
        .value,
    ).toBe("9007199254740993");
    expect(screen.getByLabelText<HTMLInputElement>("开始时间（含）").value).toBe(
      "2026-01-01T00:00:00.000000Z",
    );
    restored.unmount();
  }
});

it("筛选契约：改时间账号类型结果时清空cursor，下一页使用next_cursor，不构造offset", async () => {
  const fetchImpl = transport(
    { items: [operation], next_cursor: "opaque-next" },
    { items: [login], next_cursor: "opaque-next" },
  );
  for (const kind of ["operations", "logins"] as const) {
    const view = mount("/audit/" + kind, fetchImpl);
    await screen.findByRole("table");
    for (const [label, value] of [
      ["开始时间（含）", "2026-01-01T00:00:00Z"],
      ["结束时间（不含）", "2026-02-01T00:00:00Z"],
      [kind === "operations" ? "操作人编号" : "账号编号", "12"],
    ]) {
      fireEvent.click(await screen.findByRole("button", { name: "下一页" }));
      await waitFor(() => {
        expect(view.router.state.location.search.cursor).toBe("opaque-next");
      });
      fireEvent.change(screen.getByLabelText(label ?? ""), { target: { value } });
      fireEvent.click(screen.getByRole("button", { name: "筛选" }));
      await waitFor(() => {
        expect(view.router.state.location.search.cursor).toBeUndefined();
      });
    }
    for (const [label, value] of [
      [kind === "operations" ? "操作类型" : "登录类型", kind === "operations" ? "改角色" : "登出"],
      ["筛选结果", "失败"],
    ]) {
      fireEvent.click(await screen.findByRole("button", { name: "下一页" }));
      await waitFor(() => {
        expect(view.router.state.location.search.cursor).toBe("opaque-next");
      });
      fireEvent.mouseDown(screen.getByLabelText(label ?? ""));
      fireEvent.click(
        await screen.findByText(value ?? "", { selector: ".ant-select-item-option-content" }),
      );
      fireEvent.click(screen.getByRole("button", { name: "筛选" }));
      await waitFor(() => {
        expect(view.router.state.location.search.cursor).toBeUndefined();
      });
    }
    expect(
      fetchImpl.mock.calls.some(
        ([request]) => new URL(request.url).searchParams.get("cursor") === "opaque-next",
      ),
    ).toBe(true);
    expect(
      fetchImpl.mock.calls.every(([request]) => !new URL(request.url).searchParams.has("offset")),
    ).toBe(true);
    view.unmount();
  }
});

it("筛选契约：时间要求带偏移且start小于end，start包含end不包含，非法输入不回退查全部", () => {
  for (const validate of [validateOperationSearch, validateLoginSearch]) {
    expect(
      validate({ start: "2026-01-01T08:00:00.000001+08:00", end: "2026-01-01T00:00:00.000002Z" }),
    ).toEqual({ start: "2026-01-01T00:00:00.000001Z", end: "2026-01-01T00:00:00.000002Z" });
    for (const input of [
      { start: "2026-01-01T00:00:00" },
      { start: "2026-02-30T00:00:00Z" },
      { start: "2026-01-01T00:00:00Z", end: "2026-01-01T08:00:00+08:00" },
      { start: "2026-01-02T00:00:00Z", end: "2026-01-01T00:00:00Z" },
    ])
      expect(() => validate(input)).toThrow("日志筛选参数不合法");
  }
});

it("筛选契约：非法数组重复参数未知枚举超长游标非法编号上限和limit拒绝且不回显值", () => {
  for (const validate of [validateOperationSearch, validateLoginSearch]) {
    for (const input of [
      { account_id: ["1", "2"] },
      { account_id: Number.MAX_SAFE_INTEGER + 1 },
      { account_id: "9223372036854775808" },
      { account_id: "0" },
      { result: "private-value" },
      { cursor: "x".repeat(513) },
      { cursor: ["a", "b"] },
      { limit: 0 },
      { limit: 101 },
      { limit: true },
      { limit: 1.5 },
    ])
      expect(() => validate(input)).toThrow(/^日志筛选参数不合法$/);
  }
  expect(() => validateOperationSearch({ operation: "private-value" })).toThrow(
    /^日志筛选参数不合法$/,
  );
  expect(() => validateLoginSearch({ kind: "private-value" })).toThrow(/^日志筛选参数不合法$/);
});

it("筛选契约：缺失字段保持缺失，未知键忽略；数字编号始终保留十进制文本", () => {
  for (const validate of [validateOperationSearch, validateLoginSearch]) {
    expect(validate({ unknown: "ignored" })).toEqual({});
    expect(validate({ account_id: 2 })).toEqual({ account_id: "2" });
    expect(validate({ account_id: Number.MAX_SAFE_INTEGER })).toEqual({
      account_id: "9007199254740991",
    });
    expect(validate({ account_id: "9007199254740993", limit: "100" })).toEqual({
      account_id: "9007199254740993",
      limit: 100,
    });
    expect(validate({ limit: 1, cursor: "page", account_id: "9223372036854775807" })).toEqual({
      limit: 1,
      cursor: "page",
      account_id: "9223372036854775807",
    });
  }
});

it("时间契约：显示统一的中文时间并标注时区，带偏移提交转UTC，测试不改全局时区或依赖本机负六时区", async () => {
  mount("/audit/logins");
  expect(await screen.findByText(formatDateTime("2026-01-02T03:04:05.000006Z"))).toBeTruthy();
  expect(validateLoginSearch({ start: "2026-01-01T08:00:00+08:00" }).start).toBe(
    "2026-01-01T00:00:00.000000Z",
  );
});

it("Query契约：key包含全部筛选，操作和登录缓存隔离，缓存staleTime和gcTime均为0", async () => {
  const input: OperationSearch = {
    account_id: "10",
    target_account_id: "20",
    start: "2026-01-01T00:00:00.000000Z",
    end: "2026-02-01T00:00:00.000000Z",
    operation: "set_role",
    result: "success",
    limit: 7,
    cursor: "page",
  };
  const h = hooks(transport());
  const view = renderHook(
    () => ({
      operations: useOperationLogs(input),
      logins: useLoginLogs({
        account_id: "10",
        kind: "login",
        result: "success",
        limit: 7,
        cursor: "page",
      }),
      retention: useAuditRetention(),
    }),
    { wrapper: h.wrapper },
  );
  await waitFor(() => {
    expect(
      view.result.current.operations.isSuccess &&
        view.result.current.logins.isSuccess &&
        view.result.current.retention.isSuccess,
    ).toBe(true);
  });
  expect(view.result.current.operations.isStale).toBe(true);
  expect(view.result.current.logins.isStale).toBe(true);
  expect(view.result.current.retention.isStale).toBe(true);
  const queries = h.cache.getQueryCache().getAll();
  expect(queries).toHaveLength(3);
  expect(queries.map((q) => q.queryKey)).toContainEqual(["audit", "operations", input]);
  expect(queries.map((q) => q.queryKey)).toContainEqual([
    "audit",
    "logins",
    { account_id: "10", kind: "login", result: "success", limit: 7, cursor: "page" },
  ]);
  for (const query of queries) {
    expect(query.options.gcTime).toBe(0);
    expect(query.options.retry).toBe(false);
  }
  view.unmount();
  await waitFor(() => {
    expect(h.cache.getQueryCache().getAll()).toHaveLength(0);
  });
});

it("Query契约：窗口聚焦重查、无轮询无重试；换筛选离页取消旧请求，不让迟到结果覆盖新页", async () => {
  const pending: { request: Request; resolve: (value: Response) => void }[] = [];
  const fetchImpl = vi.fn<FetchImplementation>(
    (request) => new Promise((resolve) => pending.push({ request, resolve })),
  );
  const h = hooks(fetchImpl);
  const view = renderHook(({ id }) => ({ ...useOperationLogs({ account_id: id }) }), {
    wrapper: h.wrapper,
    initialProps: { id: "10" },
  });
  await waitFor(() => {
    expect(pending).toHaveLength(1);
  });
  view.rerender({ id: "20" });
  await waitFor(() => {
    expect(pending).toHaveLength(2);
  });
  expect(pending[0]?.request.signal.aborted).toBe(true);
  act(() => {
    pending[1]?.resolve(
      Response.json({ items: [{ ...operation, log_id: "new" }], next_cursor: null }),
    );
  });
  await waitFor(() => {
    expect(view.result.current.data?.items[0]?.log_id).toBe("new");
  });
  act(() => {
    pending[0]?.resolve(
      Response.json({ items: [{ ...operation, log_id: "old" }], next_cursor: null }),
    );
  });
  expect(view.result.current.data?.items[0]?.log_id).toBe("new");
  act(() => {
    focusManager.setFocused(false);
    focusManager.setFocused(true);
  });
  await waitFor(() => {
    expect(pending).toHaveLength(3);
  });
  act(() => {
    pending[2]?.resolve(problemResponse(502));
  });
  await waitFor(() => {
    expect(view.result.current.isError).toBe(true);
  });
  vi.useFakeTimers();
  await act(async () => {
    await vi.advanceTimersByTimeAsync(60000);
  });
  expect(pending).toHaveLength(3);
  vi.useRealTimers();
  act(() => {
    focusManager.setFocused(false);
    focusManager.setFocused(true);
  });
  await waitFor(() => {
    expect(pending).toHaveLength(4);
  });
  view.unmount();
  expect(pending[3]?.request.signal.aborted).toBe(true);
});

it("Query契约：读取设置失败显示DiagnosticCard并禁用保存，不能用伪默认值提交", async () => {
  const base = transport();
  const fetchImpl = vi.fn<FetchImplementation>((request) =>
    new URL(request.url).pathname === "/api/audit/retention"
      ? Promise.resolve(problemResponse(502))
      : base(request),
  );
  mount("/audit/operations", fetchImpl);
  expect(await screen.findByText("口令核验资源繁忙")).toBeTruthy();
  expect(screen.getByRole<HTMLButtonElement>("button", { name: "保存保留期" }).disabled).toBe(true);
  expect(screen.getByLabelText<HTMLInputElement>("保留天数").value).toBe("");
  fireEvent.click(screen.getByRole("button", { name: "保存保留期" }));
  expect(fetchImpl.mock.calls.every(([request]) => request.method === "GET")).toBe(true);
  expect(screen.getByText("原操作人")).toBeTruthy();
});

it("Query契约：空结果显示空态，末页无下一页按钮，服务端失败不伪装为空结果", async () => {
  for (const path of ["operations", "logins"]) {
    const view = mount(
      "/audit/" + path,
      transport({ items: [], next_cursor: null }, { items: [], next_cursor: null }),
    );
    expect(await screen.findByText("暂无日志")).toBeTruthy();
    expect(screen.queryByRole("button", { name: "下一页" })).toBeNull();
    view.unmount();
    const base = transport();
    const failed = mount("/audit/" + path, (request) =>
      new URL(request.url).pathname.endsWith("/" + path)
        ? Promise.resolve(problemResponse(502))
        : base(request),
    );
    expect(await screen.findByText("口令核验资源繁忙")).toBeTruthy();
    expect(screen.queryByText("暂无日志")).toBeNull();
    failed.unmount();
  }
});

it("装配契约：Provider缺失明确报错，所有请求复用useAccountClient及统一错误视图", async () => {
  const errors = vi.spyOn(console, "error").mockImplementation(() => undefined);
  try {
    for (const hook of [
      () => useOperationLogs({}),
      () => useLoginLogs({}),
      useAuditRetention,
      useSetAuditRetention,
    ])
      expect(() => renderHook<unknown, unknown>(hook)).toThrow("账号客户端未装配");
  } finally {
    errors.mockRestore();
  }
  const h = hooks(() => Promise.resolve(problemResponse(502)));
  const view = renderHook(() => useLoginLogs({}), { wrapper: h.wrapper });
  await waitFor(() => {
    expect(view.result.current.isError).toBe(true);
  });
  expect(toFailureView(view.result.current.error)).toMatchObject({
    kind: "problem",
    problem: { status: 502, detail: "口令核验资源繁忙" },
  });
});

it("修订7：操作人和对象账号是独立筛选项，类型化search可刷新分享，单独清空任何一项保留另一项", async () => {
  const view = mount("/audit/operations");
  await screen.findByRole("table");
  fireEvent.change(screen.getByLabelText("操作人编号"), { target: { value: "10" } });
  fireEvent.change(screen.getByLabelText("对象账号编号"), { target: { value: "20" } });
  fireEvent.click(screen.getByRole("button", { name: "筛选" }));
  await waitFor(() => {
    expect(view.router.state.location.search).toMatchObject({
      account_id: "10",
      target_account_id: "20",
    });
  });
  const href = view.router.state.location.href;
  view.unmount();
  const restored = mount(href);
  await screen.findByRole("table");
  expect(screen.getByLabelText<HTMLInputElement>("对象账号编号").value).toBe("20");
  fireEvent.change(screen.getByLabelText("操作人编号"), { target: { value: "" } });
  fireEvent.click(screen.getByRole("button", { name: "筛选" }));
  await waitFor(() => {
    expect(restored.router.state.location.search).toEqual({ target_account_id: "20" });
  });
  fireEvent.change(screen.getByLabelText("操作人编号"), { target: { value: "10" } });
  fireEvent.change(screen.getByLabelText("对象账号编号"), { target: { value: "" } });
  fireEvent.click(screen.getByRole("button", { name: "筛选" }));
  await waitFor(() => {
    expect(restored.router.state.location.search).toEqual({ account_id: "10" });
  });
});

it("修订7：修改任一账号筛选清cursor，两个账号都进入Query key，交换操作人和对象不复用旧页", async () => {
  const fetchImpl = transport({ items: [operation], next_cursor: "next" });
  const view = mount("/audit/operations", fetchImpl);
  await screen.findByRole("table");
  for (const [actor, target] of [
    ["10", "20"],
    ["20", "10"],
  ]) {
    fireEvent.click(await screen.findByRole("button", { name: "下一页" }));
    await waitFor(() => {
      expect(view.router.state.location.search.cursor).toBe("next");
    });
    fireEvent.change(screen.getByLabelText("操作人编号"), { target: { value: actor } });
    fireEvent.change(screen.getByLabelText("对象账号编号"), { target: { value: target } });
    fireEvent.click(screen.getByRole("button", { name: "筛选" }));
    await waitFor(() => {
      expect(view.router.state.location.search).toEqual({
        account_id: actor,
        target_account_id: target,
      });
    });
    await waitFor(() => {
      expect(
        view.queryClient.getQueryCache().find({
          queryKey: ["audit", "operations", { account_id: actor, target_account_id: target }],
        })?.state.status,
      ).toBe("success");
    });
    expect(
      fetchImpl.mock.calls.some(([request]) => {
        const url = new URL(request.url);
        return (
          url.searchParams.get("account_id") === actor &&
          url.searchParams.get("target_account_id") === target &&
          !url.searchParams.has("cursor")
        );
      }),
    ).toBe(true);
  }
});

it("修订7：对象账号为1至2^63-1十进制文本，非法前导零或溢出安全拒绝且不回退查全部", () => {
  for (const target_account_id of ["1", "9007199254740993", "9223372036854775807"])
    expect(validateOperationSearch({ target_account_id })).toEqual({ target_account_id });
  for (const target_account_id of [
    "01",
    "0",
    "-1",
    "1.0",
    "9223372036854775808",
    Number.MAX_SAFE_INTEGER + 1,
    0,
    -1,
    1.5,
    true,
    ["1"],
  ])
    expect(() => validateOperationSearch({ target_account_id })).toThrow(/^日志筛选参数不合法$/);
});

it("修订7：已删除目标仍按原编号查询，同名新账号不会接管历史对象记录", async () => {
  const base = transport();
  const fetchImpl = vi.fn<FetchImplementation>((request) => {
    const url = new URL(request.url);
    if (url.pathname === "/api/audit/operations")
      return Promise.resolve(
        Response.json({
          items:
            url.searchParams.get("target_account_id") === "20"
              ? [{ ...operation, target: { ...operation.target, deleted: true } }]
              : [],
          next_cursor: null,
        }),
      );
    return base(request);
  });
  const view = mount("/audit/operations?target_account_id=%2220%22", fetchImpl);
  expect(await screen.findByText("原对象（已删除）")).toBeTruthy();
  fireEvent.change(screen.getByLabelText("对象账号编号"), { target: { value: "30" } });
  fireEvent.click(screen.getByRole("button", { name: "筛选" }));
  await waitFor(() => {
    expect(view.router.state.location.search.target_account_id).toBe("30");
  });
  expect(await screen.findByText("暂无日志")).toBeTruthy();
  expect(screen.queryByText("原对象（已删除）")).toBeNull();
});

it("路由回归：非法或重复筛选阻止日志请求，诊断不回显输入，也不退回全量查询", async () => {
  for (const suffix of [
    "account_id=1&account_id=2",
    "result=private-invalid-result",
    "start=2026-01-01T00%3A00%3A00",
  ]) {
    const fetchImpl = transport();
    const view = mount("/audit/operations?" + suffix, fetchImpl);
    expect(await screen.findByText("日志筛选参数不合法")).toBeTruthy();
    expect(screen.getByRole("heading", { name: "操作日志" })).toBeTruthy();
    expect(document.body.textContent).not.toContain("private-invalid-result");
    expect(fetchImpl.mock.calls.some(([request]) => request.url.includes("/api/audit/"))).toBe(
      false,
    );
    view.unmount();
  }
});

it("保存取消契约：离页取消保留期写请求，忽略迟到成功，不导航回来或刷新旧页", async () => {
  let resolveSave: ((response: Response) => void) | undefined;
  let signal: AbortSignal | undefined;
  const base = transport();
  const fetchImpl = vi.fn<FetchImplementation>((request) => {
    if (request.method === "PUT") {
      signal = request.signal;
      return new Promise((resolve) => {
        resolveSave = resolve;
      });
    }
    return base(request);
  });
  const view = mount("/audit/operations", fetchImpl);
  await waitFor(() => {
    expect(screen.getByLabelText<HTMLInputElement>("保留天数").value).toBe("30");
  });
  fireEvent.change(screen.getByLabelText("保留天数"), { target: { value: "7" } });
  fireEvent.click(screen.getByRole("button", { name: "保存保留期" }));
  await waitFor(() => {
    expect(resolveSave).toBeDefined();
  });
  await act(async () => {
    await view.router.navigate({ to: "/" });
  });
  expect(await screen.findByText("后端正常")).toBeTruthy();
  expect(signal?.aborted).toBe(true);
  const count = fetchImpl.mock.calls.length;
  act(() => {
    resolveSave?.(Response.json({ days: 7 }));
  });
  // 推进有界请求上限之外，证明迟到成功不会恢复已经取消的 mutation。
  vi.useFakeTimers();
  await act(async () => {
    await vi.advanceTimersByTimeAsync(11000);
  });
  expect(fetchImpl.mock.calls).toHaveLength(count);
  expect(view.router.state.location.pathname).toBe("/");
});

it("保存刷新契约：首页修改保留期成功也重新查询操作日志，保留现有筛选", async () => {
  const fetchImpl = transport();
  const view = mount("/audit/operations?account_id=%2210%22", fetchImpl);
  await screen.findByText("原操作人");
  await waitFor(() => {
    expect(screen.getByLabelText<HTMLInputElement>("保留天数").value).toBe("30");
  });
  const before = fetchImpl.mock.calls.filter(
    ([request]) => new URL(request.url).pathname === "/api/audit/operations",
  ).length;
  fireEvent.change(screen.getByLabelText("保留天数"), { target: { value: "7" } });
  fireEvent.click(screen.getByRole("button", { name: "保存保留期" }));
  await waitFor(() => {
    expect(
      fetchImpl.mock.calls.filter(
        ([request]) => new URL(request.url).pathname === "/api/audit/operations",
      ).length,
    ).toBeGreaterThan(before);
  });
  expect(view.router.state.location.search).toEqual({ account_id: "10" });
});

it.each(["登录", "设置"])("Query补充：%s聚焦重查、无轮询重试，离页取消", async (kind) => {
  const pending: { signal: AbortSignal; resolve: (value: Response) => void }[] = [];
  const h = hooks(
    (request) =>
      new Promise((resolve) => {
        pending.push({ signal: request.signal, resolve });
      }),
  );
  const useLogs = kind === "登录" ? () => useLoginLogs({}) : useAuditRetention;
  const view = renderHook(() => ({ ...useLogs() }), { wrapper: h.wrapper });
  await waitFor(() => {
    expect(pending).toHaveLength(1);
  });
  act(() => {
    pending[0]?.resolve(problemResponse(502));
  });
  await waitFor(() => {
    expect(view.result.current.isError).toBe(true);
  });
  vi.useFakeTimers();
  await act(async () => {
    await vi.advanceTimersByTimeAsync(60000);
  });
  expect(pending).toHaveLength(1);
  vi.useRealTimers();
  act(() => {
    focusManager.setFocused(false);
    focusManager.setFocused(true);
  });
  await waitFor(() => {
    expect(pending).toHaveLength(2);
  });
  view.unmount();
  expect(pending[1]?.signal.aborted).toBe(true);
});

it.each([
  ["operations", "account_id"],
  ["operations", "target_account_id"],
  ["logins", "account_id"],
])("路由数字编号：%s?%s=2 正常渲染并按字符串编号查询", async (kind, field) => {
  const fetchImpl = transport();
  mount(`/audit/${kind}?${field}=2`, fetchImpl);
  await screen.findByText(kind === "operations" ? "原操作人" : "旧登录者");
  const requests = fetchImpl.mock.calls.filter(
    ([request]) => new URL(request.url).pathname === `/api/audit/${kind}`,
  );
  expect(requests.length).toBeGreaterThan(0);
  expect(requests.every(([request]) => new URL(request.url).searchParams.get(field) === "2")).toBe(
    true,
  );
  expect(screen.queryByText("日志筛选参数不合法")).toBeNull();
});

it.each([
  ["operations", "abc"],
  ["logins", "abc"],
  ["operations", "9007199254740993"],
  ["logins", "9007199254740993"],
])(
  "路由非法编号：%s?account_id=%s 保留页面和筛选表单，不发日志请求且可修正",
  async (kind, value) => {
    const fetchImpl = transport();
    mount(`/audit/${kind}?account_id=${value}`, fetchImpl);
    expect(await screen.findByText("日志筛选参数不合法")).toBeTruthy();
    expect(
      screen.getByRole("heading", { name: kind === "operations" ? "操作日志" : "登录日志" }),
    ).toBeTruthy();
    expect(screen.getByRole("link", { name: "账号管理" })).toBeTruthy();
    expect(screen.queryByText("请求失败，请检查网络或稍后重试。")).toBeNull();
    expect(fetchImpl.mock.calls.some(([request]) => request.url.includes("/api/audit/"))).toBe(
      false,
    );
    fireEvent.change(screen.getByLabelText(kind === "operations" ? "操作人编号" : "账号编号"), {
      target: { value: "2" },
    });
    fireEvent.click(screen.getByRole("button", { name: "筛选" }));
    await screen.findByText(kind === "operations" ? "原操作人" : "旧登录者");
    expect(screen.queryByText("日志筛选参数不合法")).toBeNull();
    expect(
      fetchImpl.mock.calls.some(
        ([request]) => new URL(request.url).searchParams.get("account_id") === "2",
      ),
    ).toBe(true);
  },
);
