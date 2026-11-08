// 08 页面契约清单；请求替身与真实内存Router并用，禁止网络和浏览器持久存储。
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { createMemoryHistory, RouterProvider } from "@tanstack/react-router";
import {
  act,
  cleanup,
  fireEvent,
  render,
  renderHook,
  screen,
  waitFor,
} from "@testing-library/react";
import { expect, it, vi, beforeEach, afterEach } from "vitest";
import { createAppRouter } from "../router";
import { job, onlineWorker, completedJob } from "./testSupport";
import type { OperationLogPage } from "../api/audit";
import type { FetchImplementation } from "../api/client";
import type { Job, JobLog } from "../api/jobs";
import { calculateJobRate, jobStatusLabel, isJobTerminal, useJobTiming } from "./progress";
import { account, problemResponse } from "../accounts/testSupport";

beforeEach(() => {
  // jsdom没有媒体查询和伪元素布局，沿用账号/审计页面的浏览器边界替身。
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

it("验证验收14追加：作业列表没有两个示例入口，旧地址进入前端404且历史示例仍可见", async () => {
  const requests: string[] = [];
  const transport: FetchImplementation = (request) => {
    requests.push(new URL(request.url).pathname);
    return detailFetch(() => completedJob)(request);
  };
  const list = mountPage("/jobs", transport);
  try {
    expect(await screen.findByRole("heading", { name: "作业列表" })).toBeTruthy();
    expect(await screen.findByText(completedJob.display_name)).toBeTruthy();
    expect(screen.queryByText("提交示例作业")).toBeNull();
    expect(screen.queryByText("提交资源示例")).toBeNull();
  } finally {
    list.close();
  }
  for (const path of ["/jobs/new", "/jobs/resources"]) {
    requests.length = 0;
    const view = mountPage(path, transport);
    try {
      expect(await screen.findByText("页面不存在")).toBeTruthy();
      expect(screen.getByText("404")).toBeTruthy();
      expect(requests.some((url) => url.startsWith("/api/jobs"))).toBe(false);
      expect(screen.queryByText("提交示例作业")).toBeNull();
      expect(screen.queryByText("资源示例作业")).toBeNull();
    } finally {
      view.close();
    }
  }
});
afterEach(() => {
  cleanup();
  vi.useRealTimers();
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
});

it("规范7.1/10.6：真实Router打开state和数字limit的URL，成员可见作业入口且请求带相同筛选", async () => {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  const requests: URL[] = [];
  const router = createAppRouter({
    queryClient,
    history: createMemoryHistory({ initialEntries: ["/jobs?state=running&limit=20"] }),
    fetchImpl: (request) => {
      const url = new URL(request.url);
      requests.push(url);
      return Promise.resolve(
        Response.json(
          url.pathname === "/api/auth/me"
            ? { ...account, role: "member" }
            : url.pathname === "/api/worker/status"
              ? {
                  online: true,
                  instance_id: null,
                  pid: null,
                  started_at: null,
                  last_seen_at: null,
                  checked_at: "2026-10-26T00:00:00Z",
                }
              : { items: [], next_cursor: null },
        ),
      );
    },
  });
  try {
    await router.load();
    render(
      <QueryClientProvider client={queryClient}>
        <RouterProvider router={router} />
      </QueryClientProvider>,
    );
    expect(await screen.findByRole("link", { name: "作业" })).toBeTruthy();
    await waitFor(() => {
      expect(
        requests.some(
          (url) =>
            url.pathname === "/api/jobs" &&
            url.searchParams.get("state") === "running" &&
            url.searchParams.get("limit") === "20",
        ),
      ).toBe(true);
    });
    expect(router.state.location.pathname).toBe("/jobs");
  } finally {
    cleanup();
    queryClient.clear();
    router.history.destroy();
  }
});

it("规范7.1/10.6：真实Router遇非法筛选保留表单与提示，不发列表请求、不回退全部、不崩根路由", async () => {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  const requests: string[] = [];
  const router = createAppRouter({
    queryClient,
    history: createMemoryHistory({ initialEntries: ["/jobs?state=unknown&limit=0"] }),
    fetchImpl: (request) => {
      requests.push(new URL(request.url).pathname);
      return Promise.resolve(Response.json(account));
    },
  });
  try {
    await router.load();
    render(
      <QueryClientProvider client={queryClient}>
        <RouterProvider router={router} />
      </QueryClientProvider>,
    );
    expect(await screen.findByText("作业筛选参数不合法")).toBeTruthy();
    expect(requests).not.toContain("/api/jobs");
    expect(router.state.location.pathname).toBe("/jobs");
  } finally {
    cleanup();
    queryClient.clear();
    router.history.destroy();
  }
});

it("验收5：total为null只显示已处理量，不显示百分比或剩余时间；阶段格式为阶段2/4·名称", async () => {
  const progress = job.progress;
  if (!progress) throw new Error("测试样本缺进度");
  const unknown: Job = { ...job, progress: { ...progress, total: null } };
  const view = mountPage(
    `/jobs/${job.job_id}`,
    detailFetch(() => unknown),
  );
  try {
    expect(await screen.findByText("阶段 2/4 · 处理")).toBeTruthy();
    expect(screen.getByText("已处理 2 条")).toBeTruthy();
    expect(screen.queryByRole("progressbar")).toBeNull();
    expect(screen.queryByText(/剩余时间/)).toBeNull();
    expect(screen.queryByText(/%/)).toBeNull();
  } finally {
    view.close();
  }
});

it("M4验收6：详情总进度下显示每项帧数和进度条，无分项时保持原样", async () => {
  const progress = job.progress;
  if (!progress) throw new Error("测试样本缺进度");
  const parts = [
    { name: "head_left", done: 42, total: 100, unit: "帧" },
    { name: "state", done: 60, total: 100, unit: "帧" },
  ];
  for (const includeParts of [true, false]) {
    const record: Job = {
      ...completedJob,
      progress: { ...progress, parts: includeParts ? parts : [] },
    };
    const view = mountPage(
      `/jobs/${job.job_id}`,
      detailFetch(() => record),
    );
    try {
      await screen.findByText("阶段 2/4 · 处理");
      if (includeParts) {
        expect(screen.getByText("head_left")).toBeTruthy();
        expect(screen.getByText("42/100 帧")).toBeTruthy();
        expect(screen.getByText("60/100 帧")).toBeTruthy();
        expect(
          screen.getByRole("progressbar", { name: "head_left进度" }).getAttribute("aria-valuenow"),
        ).toBe("42");
        expect(
          screen.getByRole("progressbar", { name: "state进度" }).getAttribute("aria-valuenow"),
        ).toBe("60");
      } else {
        expect(screen.queryByText("head_left")).toBeNull();
        expect(screen.getAllByRole("progressbar")).toHaveLength(1);
      }
    } finally {
      view.close();
    }
  }
});

it("验收5：最近10秒样本计算速度，少于两份/无时间差/无进展不显示；阶段切换或重跑清空样本", () => {
  const first = { receivedAtMs: 1000, job };
  const later: Job = {
    ...job,
    progress_at: "2026-10-26T12:00:04Z",
    progress: job.progress && { ...job.progress, done: 4 },
  };
  expect(calculateJobRate([])).toEqual({ unitsPerSecond: null, remainingSeconds: null });
  expect(calculateJobRate([first])).toEqual({ unitsPerSecond: null, remainingSeconds: null });
  expect(calculateJobRate([first, { receivedAtMs: 3000, job: later }])).toEqual({
    unitsPerSecond: 1,
    remainingSeconds: 0,
  });
  expect(
    calculateJobRate([
      first,
      {
        receivedAtMs: 3000,
        job: { ...later, progress: later.progress && { ...later.progress, total: null } },
      },
    ]).remainingSeconds,
  ).toBeNull();
  expect(calculateJobRate([first, { receivedAtMs: 1000, job: later }]).unitsPerSecond).toBeNull();
  expect(calculateJobRate([first, { receivedAtMs: 3000, job }]).unitsPerSecond).toBeNull();
  for (const progress of [
    job.progress && { ...job.progress, stage_index: 3, done: 4 },
    job.progress && { ...job.progress, done: 0, total_items: 0 },
  ]) {
    expect(
      calculateJobRate([first, { receivedAtMs: 3000, job: { ...later, progress } }]).unitsPerSecond,
    ).toBeNull();
  }
  expect(calculateJobRate([first, { receivedAtMs: 12000, job: later }]).unitsPerSecond).toBeNull();
  expect(() => calculateJobRate([{ receivedAtMs: NaN, job }])).toThrow();
  expect(() => calculateJobRate([first, { receivedAtMs: 500, job }])).toThrow();
});

it("验收5：已用时间以服务器elapsed加本地单调增量，墙钟回拨不倒退；终态冻结", () => {
  vi.useFakeTimers();
  let monotonic = 1000;
  vi.spyOn(performance, "now").mockImplementation(() => monotonic);
  const props: { value: Job | undefined } = { value: job };
  const view = renderHook(({ value }: typeof props) => useJobTiming(value), {
    initialProps: props,
  });
  try {
    expect(view.result.current.elapsedSeconds).toBe(2);
    monotonic = 4000;
    act(() => {
      vi.advanceTimersByTime(1000);
    });
    expect(view.result.current.elapsedSeconds).toBe(5);
    vi.setSystemTime(new Date("2001-01-01T00:00:00Z"));
    monotonic = 5000;
    act(() => {
      vi.advanceTimersByTime(1000);
    });
    expect(view.result.current.elapsedSeconds).toBe(6);
    view.rerender({ value: { ...job, elapsed_s: 1, progress_at: "2026-10-26T12:00:03Z" } });
    expect(view.result.current.elapsedSeconds).toBeGreaterThanOrEqual(6);
    monotonic = 6000;
    act(() => {
      vi.advanceTimersByTime(1000);
    });
    expect(view.result.current.elapsedSeconds).toBe(7);
    view.rerender({ value: completedJob });
    monotonic = 15000;
    act(() => {
      vi.advanceTimersByTime(5000);
    });
    expect(view.result.current.elapsedSeconds).toBe(4);
    view.rerender({ value: undefined });
    expect(view.result.current.elapsedSeconds).toBeNull();
  } finally {
    view.unmount();
  }
  expect(vi.getTimerCount()).toBe(0);
});

it("验收6：成功、带警告成功、部分成功、失败、已取消、已中断六种结局及三个进行中状态标签正确", () => {
  for (const [state, label] of [
    ["queued", "排队中"],
    ["running", "运行中"],
    ["cancelling", "正在取消"],
  ] as const) {
    const current = { ...job, state };
    expect(jobStatusLabel(current)).toBe(label);
    expect(isJobTerminal(current)).toBe(false);
  }
  const summary = {
    state: "completed" as const,
    outcome: "succeeded" as const,
    progress: job.progress,
    total_items: 2,
    failed_items: 0,
    warning_count: 0,
    aborted: false,
    elapsed_s: 2,
    artifacts: [],
    tool_exit_code: null,
  };
  for (const [outcome, label] of [
    ["succeeded", "成功"],
    ["succeeded_with_warnings", "带警告成功"],
    ["partially_succeeded", "部分成功"],
    ["failed", "失败"],
  ] as const) {
    const current: Job = { ...job, state: "completed", summary: { ...summary, outcome } };
    expect(jobStatusLabel(current)).toBe(label);
    expect(isJobTerminal(current)).toBe(true);
  }
  for (const [state, label] of [
    ["cancelled", "已取消"],
    ["interrupted", "已中断"],
  ] as const) {
    expect(jobStatusLabel({ ...job, state, summary: { ...summary, state, outcome: null } })).toBe(
      label,
    );
  }
  expect(() => jobStatusLabel({ ...job, state: "completed" })).toThrow();
  expect(() => jobStatusLabel({ ...job, summary })).toThrow();
});

it("验收4：成员可以取消他人queued/running作业，cancelling禁用按钮并继续轮询，409刷新详情并呈现诊断", async () => {
  vi.useFakeTimers({ toFake: ["setInterval", "clearInterval"] });
  for (const state of ["queued", "running"] as const) {
    let current: Job =
      state === "queued"
        ? { ...job, state, progress: null, progress_at: null, started_at: null, elapsed_s: 0 }
        : { ...job, state };
    let reads = 0,
      posts = 0;
    const transport: FetchImplementation = (request) => {
      const path = new URL(request.url).pathname;
      if (path.endsWith("/cancel")) {
        posts++;
        current = { ...current, state: "cancelling" };
        return Promise.resolve(problemResponse(409));
      }
      if (path === `/api/jobs/${job.job_id}`) reads++;
      return detailFetch(() => current)(request);
    };
    const view = mountPage(`/jobs/${job.job_id}`, transport);
    try {
      fireEvent.click(await screen.findByRole("button", { name: "取消作业" }));
      expect(await screen.findByText("账号状态已变化，请重试")).toBeTruthy();
      await waitFor(() => {
        expect(screen.getByRole<HTMLButtonElement>("button", { name: "取消作业" }).disabled).toBe(
          true,
        );
      });
      expect(posts).toBe(1);
      const before = reads;
      await act(async () => {
        await vi.advanceTimersByTimeAsync(1000);
      });
      await waitFor(() => {
        expect(reads).toBeGreaterThan(before);
      });
    } finally {
      view.close();
    }
  }
});

it("验收9：终态重提导航到新编号，显示重新提交自，原记录不变，非终态不显示按钮", async () => {
  const original: Job = { ...completedJob };
  const fresh: Job = {
    ...job,
    job_id: "9007199254740994",
    state: "queued",
    started_at: null,
    progress: null,
    progress_at: null,
    elapsed_s: 0,
    resubmitted_from: job.job_id,
  };
  const posts: string[] = [];
  const view = mountPage(`/jobs/${job.job_id}`, (request) => {
    const path = new URL(request.url).pathname;
    if (path.endsWith("/resubmit")) {
      posts.push(path);
      return Promise.resolve(Response.json(fresh, { status: 201 }));
    }
    return detailFetch(() => (path.includes(fresh.job_id) ? fresh : original))(request);
  });
  try {
    fireEvent.click(await screen.findByRole("button", { name: "重新提交" }));
    await waitFor(() => {
      expect(view.router.state.location.pathname).toBe(`/jobs/${fresh.job_id}`);
    });
    expect(await screen.findByRole("link", { name: `重新提交自 #${job.job_id}` })).toBeTruthy();
    expect(screen.queryByRole("button", { name: "重新提交" })).toBeNull();
    expect(posts).toEqual([`/api/jobs/${job.job_id}/resubmit`]);
    expect(original).toEqual(completedJob);
  } finally {
    view.close();
  }
});

it("验收7：日志仅显示最后几十行，cleared提示已清除，not_started提示未开始，工具HTML作为文本", async () => {
  const lines = [
    ...Array.from({ length: 49 }, (_, index) => `行${String(index)}`),
    "<img src=x onerror=alert(1)>",
  ];
  for (const status of ["available", "cleared", "not_started"] as const) {
    const view = mountPage(
      `/jobs/${job.job_id}`,
      detailFetch(
        () => completedJob,
        () => ({ tail: { status, lines: status === "available" ? lines : [], truncated: true } }),
      ),
    );
    try {
      if (status === "available") {
        const log = await screen.findByRole("log");
        expect(log.textContent).toBe(lines.join("\n"));
        expect(log.querySelector("img")).toBeNull();
      } else
        expect(
          await screen.findByText(status === "cleared" ? "作业日志已清除" : "作业未开始"),
        ).toBeTruthy();
    } finally {
      view.close();
    }
  }
});

it("验收7：统一DiagnosticCard展示对象/实际/后果/下一步，程序缺陷不自行拼接内部报错", async () => {
  const diagnostic: Job["diagnostics"][number]["samples"][number] = {
    level: "warning",
    category: "input",
    stage: "处理",
    source: "平台",
    objects: [{ key: "job_id", value: job.job_id }],
    rule: "条目应存在",
    actual: "缺少第2条",
    expected: "条目存在",
    consequence: "跳过这一条",
    next_step: "检查条目来源",
    error_chain: [],
  };
  const record: Job = {
    ...completedJob,
    diagnostics: [
      {
        source: "平台",
        rule: diagnostic.rule,
        total: 12,
        error_count: 0,
        warning_count: 12,
        samples: Array.from({ length: 10 }, (_, index) =>
          index === 0
            ? diagnostic
            : {
                ...diagnostic,
                objects: [...diagnostic.objects, { key: "item", value: String(index) }],
                actual: `其他条目${String(index)}`,
              },
        ),
      },
    ],
  };
  const view = mountPage(
    `/jobs/${job.job_id}`,
    detailFetch(() => record),
  );
  try {
    expect(await screen.findByText(`对象：job_id=${job.job_id}`)).toBeTruthy();
    expect(screen.getByText(/实际：缺少第2条/)).toBeTruthy();
    expect(screen.getAllByText("后果：跳过这一条")).toHaveLength(10);
    expect(screen.getAllByText("检查：检查条目来源")).toHaveLength(10);
    expect(screen.getByText(/共 12 条/)).toBeTruthy();
  } finally {
    view.close();
  }
  const broken: Job = {
    ...completedJob,
    diagnostics: [
      {
        ...record.diagnostics[0],
        source: "平台",
        rule: "缺陷",
        total: 1,
        error_count: 1,
        warning_count: 0,
        samples: [{ ...diagnostic, level: "error", category: "defect", actual: "内部堆栈标记" }],
      },
    ],
  };
  const defect = mountPage(
    `/jobs/${job.job_id}`,
    detailFetch(() => broken),
  );
  try {
    expect(await screen.findByText("作业发生程序缺陷，请按作业编号查看日志。")).toBeTruthy();
    expect(screen.queryByText(/内部堆栈标记/)).toBeNull();
  } finally {
    defect.close();
  }
});

it("验收8：所有登录页面含成员都显示worker离线横幅，超过15秒后出现、重启后消失", async () => {
  let online = false;
  const view = mountPage("/change-password", (request) =>
    Promise.resolve(
      Response.json(
        new URL(request.url).pathname === "/api/auth/me"
          ? { ...account, role: "member" }
          : { ...onlineWorker, online },
      ),
    ),
  );
  try {
    expect(await screen.findByText("worker 没在运行")).toBeTruthy();
    online = true;
    await view.cache.invalidateQueries({ queryKey: ["worker", "status"] });
    await waitFor(() => {
      expect(screen.queryByText("worker 没在运行")).toBeNull();
    });
  } finally {
    view.close();
  }
});

it("验收8：初次加载或查询失败不伪装离线；未登录/强制改密不请求心跳", async () => {
  const paths: string[] = [];
  const view = mountPage("/change-password", (request) => {
    const path = new URL(request.url).pathname;
    paths.push(path);
    return Promise.resolve(path === "/api/auth/me" ? Response.json(account) : problemResponse(502));
  });
  try {
    expect(screen.queryByText("worker 没在运行")).toBeNull();
    expect(await screen.findByRole("alert")).toBeTruthy();
    expect(screen.queryByText("worker 没在运行")).toBeNull();
  } finally {
    view.close();
  }
  paths.length = 0;
  const forced = mountPage("/change-password", (request) => {
    paths.push(new URL(request.url).pathname);
    return Promise.resolve(Response.json({ ...account, must_change_password: true }));
  });
  try {
    expect(await screen.findByLabelText("当前密码")).toBeTruthy();
    expect(paths).not.toContain("/api/worker/status");
  } finally {
    forced.close();
  }
});

it("轮询契约：详情终态读取最后日志后停止，列表继续每秒轮询，全局心跳不随作业停止", async () => {
  vi.useFakeTimers({ toFake: ["setInterval", "clearInterval"] });
  let current = job;
  const counts = { detail: 0, log: 0, worker: 0, list: 0 };
  const view = mountPage(`/jobs/${job.job_id}`, (request) => {
    const path = new URL(request.url).pathname;
    if (path === `/api/jobs/${job.job_id}`) counts.detail++;
    if (path.endsWith("/log")) counts.log++;
    if (path === "/api/worker/status") counts.worker++;
    if (path === "/api/jobs") counts.list++;
    return detailFetch(
      () => current,
      () => ({
        tail: {
          status: "available",
          lines: [current.state === "completed" ? "终态日志" : "运行日志"],
          truncated: false,
        },
      }),
    )(request);
  });
  try {
    expect(await screen.findByText("运行日志")).toBeTruthy();
    const started = { ...counts };
    await act(async () => {
      await vi.advanceTimersByTimeAsync(1000);
    });
    await waitFor(() => {
      expect(counts.detail).toBeGreaterThan(started.detail);
      expect(counts.log).toBeGreaterThan(started.log);
    });
    current = completedJob;
    await act(async () => {
      await vi.advanceTimersByTimeAsync(1000);
    });
    expect(await screen.findByText("成功")).toBeTruthy();
    expect(await screen.findByText("终态日志")).toBeTruthy();
    const stopped = { ...counts };
    await act(async () => {
      await vi.advanceTimersByTimeAsync(3000);
    });
    expect(counts.detail).toBe(stopped.detail);
    expect(counts.log).toBe(stopped.log);
    expect(counts.worker).toBeGreaterThan(stopped.worker);
    await act(async () => {
      await view.router.navigate({ to: "/jobs" });
    });
    await waitFor(() => {
      expect(counts.list).toBeGreaterThan(0);
    });
    const listed = counts.list;
    await act(async () => {
      await vi.advanceTimersByTimeAsync(1000);
    });
    await waitFor(() => {
      expect(counts.list).toBeGreaterThan(listed);
    });
  } finally {
    view.close();
  }
});

it("账号隔离：任意401清缓存回登录，切号和离页取消请求，迟到响应不能污染新账号", async () => {
  let expired = false;
  const first = mountPage(`/jobs/${job.job_id}`, (request) => {
    const path = new URL(request.url).pathname;
    if (path === `/api/jobs/${job.job_id}`) {
      expired = true;
      return Promise.resolve(problemResponse(401));
    }
    if (path === "/api/auth/me" && expired) return Promise.resolve(problemResponse(401));
    return detailFetch(() => job)(request);
  });
  try {
    await screen.findByLabelText("登录名");
    expect(first.router.state.location.pathname).toBe("/login");
    expect(first.cache.getQueryData(["jobs", "detail", job.job_id])).toBeUndefined();
  } finally {
    first.close();
  }
  let loggedIn = true;
  let currentAccount = account;
  let late: ((response: Response) => void) | undefined;
  let mutation: Request | undefined;
  const second = mountPage(`/jobs/${job.job_id}`, (request) => {
    const path = new URL(request.url).pathname;
    if (path.endsWith("/resubmit")) {
      mutation = request;
      return new Promise<Response>((resolve) => {
        late = resolve;
      });
    }
    if (path === "/api/auth/logout") {
      loggedIn = false;
      return Promise.resolve(new Response(null, { status: 204 }));
    }
    if (path === "/api/auth/login") {
      loggedIn = true;
      currentAccount = { ...account, account_id: "9", display_name: "新账号" };
      return Promise.resolve(Response.json(currentAccount));
    }
    if (path === "/api/auth/me")
      return Promise.resolve(loggedIn ? Response.json(currentAccount) : problemResponse(401));
    if (path === "/api/health") return Promise.resolve(Response.json({ status: "ok" }));
    return detailFetch(() => completedJob)(request);
  });
  try {
    fireEvent.click(await screen.findByRole("button", { name: "重新提交" }));
    await waitFor(() => {
      expect(mutation).toBeDefined();
    });
    fireEvent.click(screen.getByRole("button", { name: "登出" }));
    await screen.findByLabelText("登录名");
    expect(mutation?.signal.aborted).toBe(true);
    fireEvent.change(screen.getByLabelText("登录名"), { target: { value: "second" } });
    fireEvent.change(screen.getByLabelText("密码"), { target: { value: "test-credential" } });
    fireEvent.click(screen.getByRole("button", { name: "登录" }));
    expect(await screen.findByText("新账号")).toBeTruthy();
    await act(async () => {
      late?.(Response.json({ ...job, job_id: "9007199254740994" }));
      await Promise.resolve();
    });
    expect(second.router.state.location.pathname).toBe("/");
    expect(second.cache.getQueryData(["jobs", "detail", job.job_id])).toBeUndefined();
    expect(second.cache.getQueryData(["current-account"])).toMatchObject({ account_id: "9" });
  } finally {
    second.close();
  }
});

it("URL契约：真实Router改状态清游标，返回/刷新保留筛选，64位作业编号不经Number", async () => {
  const requests: URL[] = [];
  const transport: FetchImplementation = (request) => {
    const url = new URL(request.url);
    requests.push(url);
    return detailFetch(() => job)(request);
  };
  const view = mountPage("/jobs?state=running&limit=1&cursor=opaque", transport);
  let saved = "";
  try {
    expect(await screen.findByRole("link", { name: `#${job.job_id}` })).toBeTruthy();
    fireEvent.mouseDown(screen.getByRole("combobox", { name: "作业状态" }));
    fireEvent.click(await screen.findByText("已取消"));
    fireEvent.click(screen.getByRole("button", { name: /筛\s*选/ }));
    await waitFor(() => {
      expect(
        requests.some(
          (url) =>
            url.pathname === "/api/jobs" &&
            url.searchParams.get("state") === "cancelled" &&
            !url.searchParams.has("cursor"),
        ),
      ).toBe(true);
    });
    saved = view.router.state.location.href;
    act(() => {
      view.router.history.back();
    });
    await waitFor(() => {
      expect(view.router.state.location.href).toContain("cursor=opaque");
    });
    act(() => {
      view.router.history.forward();
    });
    await waitFor(() => {
      expect(view.router.state.location.href).toBe(saved);
    });
  } finally {
    view.close();
  }
  const refreshed = mountPage(saved, transport);
  try {
    const link = await screen.findByRole("link", { name: `#${job.job_id}` });
    expect(link.getAttribute("href")).toBe(`/jobs/${job.job_id}`);
    fireEvent.click(link);
    await waitFor(() => {
      expect(refreshed.router.state.location.pathname).toBe(`/jobs/${job.job_id}`);
    });
  } finally {
    refreshed.close();
  }
});

it("审计扩展：对象列显示示例：数数#12，不加账号已删除后缀，白名单明细含来源且无参数", async () => {
  const after = {
    job_id: "12",
    job_type: "example_count",
    job_state: "queued",
    resubmitted_from: "11",
    parameters: { marker: "不应进入DOM" },
  };
  const row: OperationLogPage["items"][number] = {
    log_id: "50",
    occurred_at: "2026-10-26T12:00:00Z",
    actor: { account_id: "12", name: "旧账号", deleted: true },
    target: { kind: "job", object_id: "12", name: "示例：数数 #12", deleted: false },
    operation: "submit_job",
    result: "success",
    failure_category: null,
    source_ip: "127.0.0.1",
    request_id: null,
    details: { version: 1, before: {}, after },
  };
  const view = mountPage("/audit/operations", (request) => {
    const path = new URL(request.url).pathname;
    return Promise.resolve(
      Response.json(
        path === "/api/auth/me"
          ? account
          : path === "/api/worker/status"
            ? onlineWorker
            : path === "/api/audit/retention"
              ? { days: 30 }
              : { items: [row], next_cursor: null },
      ),
    );
  });
  try {
    expect(await screen.findByText("示例：数数 #12")).toBeTruthy();
    expect(screen.getByRole("columnheader", { name: "对象" })).toBeTruthy();
    expect(screen.getByText("旧账号（已删除）")).toBeTruthy();
    expect(screen.queryByText("示例：数数 #12（已删除）")).toBeNull();
    const line = screen.getByText(/"resubmitted_from":"11"/);
    expect(line.textContent).toContain('"job_id":"12"');
    expect(line.textContent).not.toContain("parameters");
    expect(screen.queryByText(/不应进入DOM/)).toBeNull();
    expect(screen.getAllByText("提交作业").length).toBeGreaterThan(0);
  } finally {
    view.close();
  }
});

function mountPage(path: string, fetchImpl: FetchImplementation) {
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

function detailFetch(
  record: () => Job,
  log: () => JobLog = () => ({ tail: { status: "available", lines: [], truncated: false } }),
): FetchImplementation {
  return (request) => {
    const path = new URL(request.url).pathname;
    if (path === "/api/auth/me")
      return Promise.resolve(Response.json({ ...account, role: "member" }));
    if (path === "/api/worker/status") return Promise.resolve(Response.json(onlineWorker));
    if (path === "/api/jobs")
      return Promise.resolve(Response.json({ items: [record()], next_cursor: null }));
    if (path.endsWith("/log")) return Promise.resolve(Response.json(log()));
    return Promise.resolve(Response.json(record()));
  };
}

it("评审2：8/30进度显示四舍五入后的整数27%", async () => {
  const progress = job.progress;
  if (!progress) throw new Error("测试样本缺进度");
  const record: Job = { ...job, progress: { ...progress, done: 8, total: 30, total_items: 8 } };
  const view = mountPage(
    `/jobs/${job.job_id}`,
    detailFetch(() => record),
  );
  try {
    expect(await screen.findByText("27%")).toBeTruthy();
    expect(screen.queryByText("26.666666666666668%")).toBeNull();
  } finally {
    view.close();
  }
});

it("评审3：作业日志长行在有界日志框内换行", async () => {
  const line = "x".repeat(10000);
  const view = mountPage(
    `/jobs/${job.job_id}`,
    detailFetch(
      () => completedJob,
      () => ({
        tail: { status: "available", lines: [line], truncated: false },
      }),
    ),
  );
  try {
    const log = await screen.findByRole("log");
    expect(log.textContent).toBe(line);
    // jsdom 不计算外部样式；同时验证类绑定和该规则的声明，守住长行换行及宽度边界。
    expect(log.classList.contains("jobs-log")).toBe(true);
    const fsModule = "node:fs/promises";
    const fs = (await import(fsModule)) as {
      readFile: (path: string, encoding: "utf8") => Promise<string>;
    };
    const css = await fs.readFile("src/jobs/jobs.css", "utf8");
    const rule = css.match(/\.jobs-log\s*\{([^}]*)\}/)?.[1] ?? "";
    expect(rule).toMatch(/(?:^|;)\s*white-space\s*:\s*pre-wrap\s*;/);
    expect(rule).toMatch(/(?:^|;)\s*overflow-wrap\s*:\s*anywhere\s*;/);
    expect(rule).toMatch(/(?:^|;)\s*max-width\s*:\s*100%\s*;/);
    expect(rule).toMatch(/(?:^|;)\s*min-width\s*:\s*0\s*;/);
  } finally {
    view.close();
  }
});

it.each([
  ["/jobs", "member", "作业列表"],
  ["/accounts", "administrator", "账号管理"],
] as const)("评审6：%s 页面显示worker离线横幅", async (path, role, title) => {
  const view = mountPage(path, (request) => {
    const endpoint = new URL(request.url).pathname;
    const response =
      endpoint === "/api/auth/me"
        ? { ...account, role }
        : endpoint === "/api/worker/status"
          ? {
              ...onlineWorker,
              online: false,
              last_seen_at: "2026-10-26T11:59:30Z",
              checked_at: "2026-10-26T12:00:00Z",
            }
          : { items: [], next_cursor: null, next_after_id: null };
    return Promise.resolve(Response.json(response));
  });
  try {
    if (path === "/accounts")
      expect(await screen.findByRole("button", { name: "新建账号" })).toBeTruthy();
    else expect(await screen.findByRole("heading", { name: title })).toBeTruthy();
    expect(await screen.findByText("worker 没在运行")).toBeTruthy();
    expect(view.router.state.location.pathname).toBe(path);
  } finally {
    view.close();
  }
});

it("下载详情展示速度与计数，并提交并发和限速后等待实际生效", async () => {
  // 真实 Router 渲染下载作业；调参响应先排队，再由轮询观察实际值。
  let download: Job = {
    ...job,
    type_name: "download",
    display_name: "下载",
    parameters: {
      max_connection_per_server: 7,
      split: 8,
      min_split_size_bytes: 20971520,
      max_tries: 5,
      retry_wait_s: 10,
    },
  };
  const status = {
    requested_version: 0,
    applied_version: 0,
    requested: { max_concurrent_downloads: 4, max_overall_download_limit_bytes_per_s: 0 },
    effective: { max_concurrent_downloads: 4, max_overall_download_limit_bytes_per_s: 0 },
    speed_bytes_per_s: 2048,
    total_files: 10,
    completed_files: 2,
    failed_files: 1,
    skipped_files: 3,
  };
  let sent: unknown = null;
  const view = mountPage(`/jobs/${job.job_id}`, async (request) => {
    if (new URL(request.url).pathname.endsWith("/download-adjustment")) {
      if (request.method === "POST") {
        sent = await request.json();
        return Response.json({ ...status, requested_version: 1 });
      }
      return Response.json({ ...status, requested_version: sent ? 1 : 0 });
    }
    return detailFetch(() => download)(request);
  });
  try {
    expect(await screen.findByText(/2048 B\/s/)).toBeTruthy();
    expect(screen.getByText(/^文件：2\s*\/\s*10/)).toBeTruthy();
    expect(
      screen.getByText(
        "每服务器连接数：7；每文件分段数：8；最小分段大小：20971520 B；重试次数：5；重试间隔：10 秒",
      ),
    ).toBeTruthy();
    fireEvent.change(screen.getByLabelText("同时下几个文件"), { target: { value: "6" } });
    fireEvent.change(screen.getByLabelText("总限速（B/s）"), { target: { value: "1024" } });
    fireEvent.click(screen.getByRole("button", { name: "调整下载参数" }));
    await waitFor(() => {
      expect(sent).toEqual({
        max_concurrent_downloads: 6,
        max_overall_download_limit_bytes_per_s: 1024,
      });
    });
    expect(await screen.findByText("等待生效")).toBeTruthy();
    // worker 未确认调参就失败时，不把挂起版本误显示成仍在等待。
    download = {
      ...completedJob,
      type_name: "download",
      display_name: "下载",
      summary: completedJob.summary && {
        ...completedJob.summary,
        outcome: "failed",
        aborted: true,
      },
    };
    expect(
      await screen.findByText(
        "调参未生效，作业已结束；原因见下方作业诊断。",
        {},
        { timeout: 4000 },
      ),
    ).toBeTruthy();
  } finally {
    view.close();
  }
});
