// 09 契约清单；路由行为通过真实 createAppRouter 与内存 history 验证。
import { formatDateTime } from "../time";
import { it, expect, vi } from "vitest";
import { act, fireEvent, screen, waitFor, within } from "@testing-library/react";
import { mountPage, pageFetch } from "./pageTestSupport";
import { scheduling } from "./testSupport";
import { account, problemResponse } from "../accounts/testSupport";
import { job } from "../jobs/testSupport";
import type { Scheduling } from "../api/scheduling";

it("真实 router 打开 /scheduling：成员与管理员均可见菜单及只读页面，未登录沿用认证跳转", async () => {
  for (const role of ["member", "administrator"] as const) {
    const view = mountPage(
      "/scheduling",
      pageFetch(undefined, undefined, () => ({ ...account, role })),
    );
    try {
      expect(await screen.findByRole("heading", { name: "调度" })).toBeTruthy();
      expect(screen.getByRole("link", { name: "调度" }).getAttribute("href")).toBe("/scheduling");
      expect(screen.queryByRole("tab")).toBeNull();
    } finally {
      view.close();
    }
  }
  const anonymous = mountPage("/scheduling", () => Promise.resolve(problemResponse(401)));
  try {
    await screen.findByLabelText("登录名");
    expect(anonymous.router.state.location.pathname).toBe("/login");
  } finally {
    anonymous.close();
  }
});

it("同一只读页显示每类上限/运行数、每张卡的作业链接及导航写锁持有者，空闲有明确提示", async () => {
  const view = mountPage("/scheduling", pageFetch());
  try {
    const row = await screen.findByRole("row", { name: /示例：占用 GPU/ });
    expect(within(row).getByText("2")).toBeTruthy();
    expect(within(row).getByText("1")).toBeTruthy();
    const gpu = screen.getByRole("region", { name: "GPU 名额" });
    expect(within(gpu).getByRole("link", { name: "#9007199254740993" }).getAttribute("href")).toBe(
      "/jobs/9007199254740993",
    );
    expect(within(gpu).getByText("空闲")).toBeTruthy();
    expect(
      within(screen.getByRole("region", { name: "导航层写锁" }))
        .getByRole("link", { name: "#73" })
        .getAttribute("href"),
    ).toBe("/jobs/73");
    expect(screen.queryByRole("button", { name: /保存|配置|分配/ })).toBeNull();
  } finally {
    view.close();
  }
});

it("同一只读页显示下一次本地时刻、上次作业链接和六种结局，从未提交不伪造结果", async () => {
  const states: Scheduling["schedules"] = [
    ...(["succeeded", "succeeded_with_warnings", "partially_succeeded", "failed"] as const).map(
      (outcome, index) => ({
        name: `计划${String(index)}`,
        next_run_at: "2026-10-27T03:00:00Z",
        last_job_id: String(80 + index),
        last_submitted_at: "2026-10-26T03:00:00Z",
        last_state: "completed" as const,
        last_outcome: outcome,
      }),
    ),
    ...(["cancelled", "interrupted"] as const).map((state, index) => ({
      name: `结束${String(index)}`,
      next_run_at: "2026-10-27T03:00:00Z",
      last_job_id: String(90 + index),
      last_submitted_at: "2026-10-26T03:00:00Z",
      last_state: state,
      last_outcome: null,
    })),
    {
      name: "从未运行",
      next_run_at: "2026-10-27T03:00:00Z",
      last_job_id: null,
      last_submitted_at: null,
      last_state: null,
      last_outcome: null,
    },
  ];
  const view = mountPage(
    "/scheduling",
    pageFetch(() => ({ ...scheduling, schedules: states })),
  );
  try {
    for (const text of ["成功", "带警告成功", "部分成功", "失败", "已取消", "已中断", "从未提交"])
      expect(await screen.findByText(text)).toBeTruthy();
    expect(screen.getByRole("link", { name: "#80" }).getAttribute("href")).toBe("/jobs/80");
    expect(screen.getAllByText(formatDateTime("2026-10-27T03:00:00Z")).length).toBe(7);
    expect(within(screen.getByRole("row", { name: /从未运行/ })).queryByRole("link")).toBeNull();
  } finally {
    view.close();
  }
});

it("worker 离线时注明最后已保存状态；API 查询失败显示 DiagnosticCard，不伪造零占用", async () => {
  const offline = mountPage(
    "/scheduling",
    pageFetch(() => ({ ...scheduling, worker_online: false })),
  );
  try {
    expect(await screen.findByText(/最后已保存状态/)).toBeTruthy();
    expect(screen.getByRole("link", { name: "#73" })).toBeTruthy();
  } finally {
    offline.close();
  }
  const failure = mountPage("/scheduling", (request) =>
    new URL(request.url).pathname === "/api/worker/scheduling"
      ? Promise.resolve(problemResponse(502))
      : pageFetch()(request),
  );
  try {
    expect(await screen.findByRole("alert")).toBeTruthy();
    expect(screen.queryByText("空闲")).toBeNull();
  } finally {
    failure.close();
  }
});

it("每 JOB_POLL_INTERVAL_MS 轮询，一个查询同时刷新资源和每日计划，离页取消请求，不自动重试", async () => {
  vi.useFakeTimers({ toFake: ["setInterval", "clearInterval"] });
  let current = scheduling;
  let pending = false;
  let request: Request | undefined;
  let finish: ((response: Response) => void) | undefined;
  let calls = 0;
  const view = mountPage("/scheduling", (input) => {
    if (new URL(input.url).pathname === "/api/worker/scheduling") {
      calls++;
      if (pending) {
        request = input;
        return new Promise<Response>((resolve) => {
          finish = resolve;
        });
      }
    }
    return pageFetch(() => current)(input);
  });
  try {
    await screen.findByText("清除过期报错");
    expect(calls).toBe(1);
    current = {
      ...scheduling,
      navigation_job_id: null,
      schedules: scheduling.schedules.map((item) => ({ ...item, name: "更新" + item.name })),
    };
    await act(async () => {
      await vi.advanceTimersByTimeAsync(1000);
    });
    expect(await screen.findByText("更新清除过期报错")).toBeTruthy();
    expect(screen.getByText("无人持有")).toBeTruthy();
    expect(calls).toBe(2);
    pending = true;
    await act(async () => {
      await vi.advanceTimersByTimeAsync(1000);
    });
    await waitFor(() => {
      expect(request).toBeDefined();
    });
    await act(async () => {
      await view.router.navigate({ to: "/" });
    });
    expect(request?.signal.aborted).toBe(true);
    await act(async () => {
      finish?.(Response.json(scheduling));
      await vi.advanceTimersByTimeAsync(3000);
    });
    expect(calls).toBe(3);
    await waitFor(() => {
      expect(view.cache.getQueryData(["scheduling"])).toBeUndefined();
    });
  } finally {
    view.close();
    finish?.(Response.json(scheduling));
  }
});

it("401 按账号感知客户端清缓存并回登录，换账号不闪现上个账号结果或迟到响应", async () => {
  let expired = false;
  const first = mountPage("/scheduling", (request) => {
    const path = new URL(request.url).pathname;
    if (path === "/api/worker/scheduling") {
      expired = true;
      return Promise.resolve(problemResponse(401));
    }
    if (path === "/api/auth/me" && expired) return Promise.resolve(problemResponse(401));
    return pageFetch()(request);
  });
  try {
    await screen.findByLabelText("登录名");
    expect(first.cache.getQueryData(["scheduling"])).toBeUndefined();
  } finally {
    first.close();
  }
  let loggedIn = true;
  let currentAccount = account;
  let late: ((response: Response) => void) | undefined;
  let pending: Request | undefined;
  let old = true;
  const second = mountPage("/scheduling", (request) => {
    const path = new URL(request.url).pathname;
    if (path === "/api/worker/scheduling" && old) {
      pending = request;
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
      old = false;
      currentAccount = { ...account, account_id: "9", display_name: "新账号" };
      return Promise.resolve(Response.json(currentAccount));
    }
    if (path === "/api/auth/me")
      return Promise.resolve(loggedIn ? Response.json(currentAccount) : problemResponse(401));
    return pageFetch(() => ({ ...scheduling, types: [] }))(request);
  });
  try {
    await waitFor(() => {
      expect(pending).toBeDefined();
    });
    fireEvent.click(await screen.findByRole("button", { name: "登出" }));
    await screen.findByLabelText("登录名");
    expect(pending?.signal.aborted).toBe(true);
    fireEvent.change(screen.getByLabelText("登录名"), { target: { value: "new" } });
    fireEvent.change(screen.getByLabelText("口令"), { target: { value: "test-credential" } });
    fireEvent.click(screen.getByRole("button", { name: "登录" }));
    await screen.findByText("新账号");
    await act(async () => {
      await second.router.navigate({ to: "/scheduling" });
    });
    await screen.findByText("清除过期报错");
    await act(async () => {
      late?.(Response.json(scheduling));
      await Promise.resolve();
    });
    expect(screen.queryByText("示例：占用 GPU")).toBeNull();
    expect(second.cache.getQueryData(["current-account"])).toMatchObject({ account_id: "9" });
    old = true;
    pending = undefined;
    await act(async () => {
      second.cache.setQueryData(["current-account"], {
        ...account,
        account_id: "10",
        display_name: "第三账号",
      });
      await Promise.resolve();
    });
    await waitFor(() => {
      expect(pending).toBeDefined();
    });
    expect(screen.queryByText("清除过期报错")).toBeNull();
  } finally {
    second.close();
    late?.(Response.json(scheduling));
  }
});

it("接口中的超 JS 安全整数作业编号保持文本链接，不使用 Number", async () => {
  const view = mountPage("/scheduling", pageFetch());
  try {
    const link = await screen.findByRole("link", { name: "#9007199254740993" });
    expect(link.getAttribute("href")).toBe("/jobs/9007199254740993");
    fireEvent.click(link);
    await waitFor(() => {
      expect(view.router.state.location.pathname).toBe("/jobs/9007199254740993");
    });
  } finally {
    view.close();
  }
});

it("到期但尚未提交显示等待 worker，不把旧到期时间伪造成明天", async () => {
  const due = "2026-10-26T03:00:00Z";
  const view = mountPage(
    "/scheduling",
    pageFetch(() => ({
      ...scheduling,
      schedules: [
        {
          name: "到期清除",
          next_run_at: due,
          last_job_id: null,
          last_submitted_at: null,
          last_state: null,
          last_outcome: null,
        },
      ],
    })),
  );
  try {
    expect(await screen.findByText("已到点，等待 worker")).toBeTruthy();
    expect(screen.getByText(formatDateTime(due))).toBeTruthy();
  } finally {
    view.close();
  }
});

it("资源示例页面 GPU 时长接受0/600，拒绝bool语义/负数/601，非法表单不发请求", async () => {
  const posts: Request[] = [];
  const view = mountPage("/jobs/resources", (request) => {
    if (request.method === "POST") {
      posts.push(request);
      return Promise.resolve(problemResponse(422));
    }
    return pageFetch()(request);
  });
  try {
    const input = await screen.findByLabelText("占用秒数");
    for (const value of ["true", "-1", "601"]) {
      fireEvent.change(input, { target: { value } });
      fireEvent.click(screen.getByRole("button", { name: "提交占卡作业" }));
      expect(await screen.findByText("占用秒数须为0至600的整数")).toBeTruthy();
    }
    expect(posts).toHaveLength(0);
    for (const value of ["0", "600"]) {
      fireEvent.change(input, { target: { value } });
      fireEvent.click(screen.getByRole("button", { name: "提交占卡作业" }));
      await screen.findByText("请求被拒绝");
      await waitFor(() => {
        expect(posts).toHaveLength(value === "0" ? 1 : 2);
      });
      await waitFor(() => {
        expect(
          screen.getByRole<HTMLButtonElement>("button", { name: "提交占卡作业" }).disabled,
        ).toBe(false);
      });
    }
    expect(await posts[0]?.json()).toEqual({ hold_s: 0 });
    expect(await posts[1]?.json()).toEqual({ hold_s: 600 });
  } finally {
    view.close();
  }
});

it("写锁期望值允许空、暂停接受0/10秒；超界保留输入并提示，参数不包含路径", async () => {
  const posts: Request[] = [];
  const view = mountPage("/jobs/resources", (request) => {
    if (request.method === "POST") {
      posts.push(request);
      return Promise.resolve(problemResponse(422));
    }
    return pageFetch()(request);
  });
  try {
    const expected = await screen.findByLabelText<HTMLInputElement>("期望值");
    const pause = screen.getByLabelText<HTMLInputElement>("写入前暂停（秒）");
    fireEvent.change(expected, { target: { value: "x".repeat(257) } });
    fireEvent.click(screen.getByRole("button", { name: "提交写锁作业" }));
    expect(await screen.findByText("期望值最多256个字符")).toBeTruthy();
    expect(expected.value).toHaveLength(257);
    fireEvent.change(expected, { target: { value: "" } });
    fireEvent.change(pause, { target: { value: "11" } });
    fireEvent.click(screen.getByRole("button", { name: "提交写锁作业" }));
    expect(await screen.findByText("暂停须为0至10的整数秒")).toBeTruthy();
    expect(posts).toHaveLength(0);
    for (const value of ["0", "10"]) {
      fireEvent.change(pause, { target: { value } });
      fireEvent.click(screen.getByRole("button", { name: "提交写锁作业" }));
      await waitFor(() => {
        expect(posts).toHaveLength(value === "0" ? 1 : 2);
      });
      await waitFor(() => {
        expect(
          screen.getByRole<HTMLButtonElement>("button", { name: "提交写锁作业" }).disabled,
        ).toBe(false);
      });
    }
    expect(await posts[0]?.json()).toEqual({ expected_value: "", pause_s: 0 });
    expect(await posts[1]?.json()).toEqual({ expected_value: "", pause_s: 10 });
  } finally {
    view.close();
  }
});

it("两个示例成功提交201后进入新详情，提交中禁重复，离页或换号后迟到成功不导航", async () => {
  for (const name of ["提交占卡作业", "提交写锁作业"]) {
    let finish: ((response: Response) => void) | undefined;
    const posts: Request[] = [];
    const fresh = { ...job, job_id: "9007199254740994" };
    const view = mountPage("/jobs/resources", (request) => {
      if (request.method === "POST") {
        posts.push(request);
        return new Promise<Response>((resolve) => {
          finish = resolve;
        });
      }
      return pageFetch(undefined, () => fresh)(request);
    });
    try {
      fireEvent.click(await screen.findByRole("button", { name }));
      await waitFor(() => {
        expect(posts).toHaveLength(1);
      });
      const button = screen.getByRole<HTMLButtonElement>("button", { name });
      expect(button.disabled).toBe(true);
      fireEvent.click(button);
      expect(posts).toHaveLength(1);
      await act(async () => {
        finish?.(Response.json(fresh, { status: 201 }));
        await Promise.resolve();
      });
      await waitFor(() => {
        expect(view.router.state.location.pathname).toBe("/jobs/9007199254740994");
      });
    } finally {
      view.close();
      finish?.(Response.json(fresh));
    }
  }
  let finish: ((response: Response) => void) | undefined;
  let sent: Request | undefined;
  const late = mountPage("/jobs/resources", (request) => {
    if (request.method === "POST") {
      sent = request;
      return new Promise<Response>((resolve) => {
        finish = resolve;
      });
    }
    return pageFetch()(request);
  });
  try {
    fireEvent.click(await screen.findByRole("button", { name: "提交占卡作业" }));
    await waitFor(() => {
      expect(sent).toBeDefined();
    });
    await act(async () => {
      late.cache.setQueryData(["current-account"], {
        ...account,
        account_id: "9",
        display_name: "切换账号",
      });
      await Promise.resolve();
    });
    await screen.findByText("切换账号");
    expect(sent?.signal.aborted).toBe(true);
    await act(async () => {
      await late.router.navigate({ to: "/" });
      finish?.(Response.json({ ...job, job_id: "99" }, { status: 201 }));
      await Promise.resolve();
    });
    expect(late.router.state.location.pathname).toBe("/");
  } finally {
    late.close();
    finish?.(Response.json(job));
  }
});

it("提交失败统一诊断且保留表单，不自动重试不确定写请求", async () => {
  vi.useFakeTimers({ toFake: ["setInterval", "clearInterval"] });
  let calls = 0;
  const view = mountPage("/jobs/resources", (request) => {
    if (request.method === "POST") {
      calls++;
      return Promise.resolve(problemResponse(409));
    }
    return pageFetch()(request);
  });
  try {
    const input = await screen.findByLabelText<HTMLInputElement>("期望值");
    fireEvent.change(input, { target: { value: "上次预览" } });
    fireEvent.click(screen.getByRole("button", { name: "提交写锁作业" }));
    expect(await screen.findByText("账号状态已变化，请重试")).toBeTruthy();
    expect(input.value).toBe("上次预览");
    await act(async () => {
      await vi.advanceTimersByTimeAsync(3000);
    });
    expect(calls).toBe(1);
    expect(view.router.state.location.pathname).toBe("/jobs/resources");
  } finally {
    view.close();
  }
});

it("被移出池的卡显示移出状态、原因和核对时间，修复后提示重启worker，不假装空闲可分配", async () => {
  const data: Scheduling = {
    ...scheduling,
    gpus: [
      {
        gpu_index: 1,
        job_id: null,
        availability: "excluded",
        checked_at: "2026-10-26T12:00:00Z",
        diagnostics: [
          {
            level: "error",
            category: "external",
            stage: "核卡",
            source: "nvidia-smi",
            objects: [{ key: "gpu_index", value: "1" }],
            rule: "卡必须存在",
            actual: "找不到物理卡",
            expected: "卡1可用",
            consequence: "移出本次名额池",
            next_step: "检查驱动",
            error_chain: [],
          },
        ],
      },
    ],
  };
  const view = mountPage(
    "/scheduling",
    pageFetch(() => data),
  );
  try {
    expect(await screen.findByText("已移出名额池")).toBeTruthy();
    expect(screen.getByText(/找不到物理卡/)).toBeTruthy();
    expect(screen.getByText("修复后需重启 worker 重新核对")).toBeTruthy();
    expect(screen.getByText(formatDateTime("2026-10-26T12:00:00Z"))).toBeTruthy();
    expect(screen.queryByText("空闲")).toBeNull();
  } finally {
    view.close();
  }
});
