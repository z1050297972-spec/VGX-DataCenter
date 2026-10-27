// 09 契约清单；路由行为通过真实 createAppRouter 与内存 history 验证。
import { it, expect, vi } from "vitest";
import { act, fireEvent, screen, waitFor } from "@testing-library/react";
import { mountPage, pageFetch } from "../scheduling/pageTestSupport";
import { job, completedJob } from "./testSupport";
import type { Job } from "../api/jobs";

it("验收2：queued 显示等待 GPU，卡归还后轮询转运行；等待原因不改作业状态标签", async () => {
  vi.useFakeTimers({ toFake: ["setInterval", "clearInterval"] });
  let current: Job = {
    ...job,
    state: "queued",
    wait_reason: "gpu",
    gpu_index: null,
    progress: null,
  };
  const view = mountPage(
    "/jobs",
    pageFetch(undefined, () => current),
  );
  try {
    expect(await screen.findByText("等待 GPU")).toBeTruthy();
    expect(screen.getByText("排队中")).toBeTruthy();
    current = { ...job, gpu_index: 0 };
    await act(async () => {
      await vi.advanceTimersByTimeAsync(1000);
    });
    expect(await screen.findByText("运行中")).toBeTruthy();
    expect(screen.queryByText("等待 GPU")).toBeNull();
  } finally {
    view.close();
  }
});

it("验收4：running 显示等待导航层写锁，获得锁后等待原因消失", async () => {
  vi.useFakeTimers({ toFake: ["setInterval", "clearInterval"] });
  let current: Job = { ...job, wait_reason: "navigation_lock" };
  const view = mountPage(
    `/jobs/${job.job_id}`,
    pageFetch(undefined, () => current),
  );
  try {
    expect(await screen.findByText("等待导航层写锁")).toBeTruthy();
    expect(screen.getByText("运行中")).toBeTruthy();
    current = { ...job, holds_navigation_lock: true };
    await act(async () => {
      await vi.advanceTimersByTimeAsync(1000);
    });
    await waitFor(() => {
      expect(screen.queryByText("等待导航层写锁")).toBeNull();
    });
    expect(screen.getByText("运行中")).toBeTruthy();
  } finally {
    view.close();
  }
});

it("作业详情显示分到的物理 GPU 编号，终态仍显示历史卡号，None 明确未分配", async () => {
  for (const record of [{ ...job, gpu_index: 0 }, { ...completedJob, gpu_index: 1 }, job]) {
    const view = mountPage(
      `/jobs/${record.job_id}`,
      pageFetch(undefined, () => record),
    );
    try {
      expect(
        await screen.findByText(
          record.gpu_index === null ? "GPU：未分配" : `GPU：${String(record.gpu_index)}`,
        ),
      ).toBeTruthy();
    } finally {
      view.close();
    }
  }
});

it("空编号系统身份不加已删除标记，有编号且同名系统的账号保留账号标记；重新提交显示当前点击账号", async () => {
  for (const submitter of [
    { account_id: null, name: "系统", deleted: false },
    { account_id: "2", name: "系统", deleted: true },
  ]) {
    const record: Job = { ...completedJob, submitted_by: submitter };
    const view = mountPage(
      `/jobs/${record.job_id}`,
      pageFetch(undefined, () => record),
    );
    try {
      expect(
        await screen.findByText(
          submitter.account_id === null ? "提交人：系统" : "提交人：系统（账号 #2）（已删除）",
        ),
      ).toBeTruthy();
    } finally {
      view.close();
    }
  }
  let current: Job = {
    ...completedJob,
    submitted_by: { account_id: null, name: "系统", deleted: false },
  };
  const view = mountPage(`/jobs/${current.job_id}`, (request) => {
    if (new URL(request.url).pathname.endsWith("/resubmit")) {
      current = {
        ...job,
        job_id: "99",
        submitted_by: { account_id: "9", name: "点击账号", deleted: false },
      };
      return Promise.resolve(Response.json(current, { status: 201 }));
    }
    return pageFetch(undefined, () => current)(request);
  });
  try {
    fireEvent.click(await screen.findByRole("button", { name: "重新提交" }));
    expect(await screen.findByText("提交人：点击账号")).toBeTruthy();
    expect(view.router.state.location.pathname).toBe("/jobs/99");
  } finally {
    view.close();
  }
});

it("真实 router 保留既有 /jobs?state=queued&limit=2 搜索行为，新资源显示不破坏筛选", async () => {
  const urls: URL[] = [];
  const view = mountPage("/jobs?state=queued&limit=2", (request) => {
    urls.push(new URL(request.url));
    return pageFetch(undefined, () => ({ ...job, state: "queued", wait_reason: "gpu" }))(request);
  });
  try {
    expect(await screen.findByText("等待 GPU")).toBeTruthy();
    const request = urls.find((url) => url.pathname === "/api/jobs");
    expect(request?.searchParams.get("state")).toBe("queued");
    expect(request?.searchParams.get("limit")).toBe("2");
    expect(view.router.state.location.href).toContain("state=queued");
  } finally {
    view.close();
  }
});

it("取消/中断无 outcome 时保持原有六种结局和进度，不将等待映射为新终态", async () => {
  const summary = completedJob.summary;
  if (!summary) throw new Error("样本缺摘要");
  const records: ReadonlyArray<readonly [Job, string]> = [
    ...(["succeeded", "succeeded_with_warnings", "partially_succeeded", "failed"] as const).map(
      (outcome, index): readonly [Job, string] => [
        { ...completedJob, summary: { ...summary, outcome } },
        ["成功", "带警告成功", "部分成功", "失败"][index] ?? "",
      ],
    ),
    [
      {
        ...completedJob,
        state: "cancelled",
        summary: { ...summary, state: "cancelled", outcome: null },
      },
      "已取消",
    ],
    [
      {
        ...completedJob,
        state: "interrupted",
        summary: { ...summary, state: "interrupted", outcome: null },
      },
      "已中断",
    ],
  ];
  for (const [record, label] of records) {
    const view = mountPage(
      `/jobs/${record.job_id}`,
      pageFetch(undefined, () => record),
    );
    try {
      expect(await screen.findByText(label)).toBeTruthy();
      expect(screen.getByText(/阶段 2\/4/)).toBeTruthy();
      expect(screen.queryByText("等待 GPU")).toBeNull();
      expect(screen.queryByText("等待导航层写锁")).toBeNull();
    } finally {
      view.close();
    }
  }
});
