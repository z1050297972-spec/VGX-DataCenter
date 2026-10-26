// 08传输契约：真实defaultFetch的浏览器this绑定回归，其他请求用账号感知客户端。
import { expect, it, vi } from "vitest";
import { createAccountClient } from "./accounts";
import { defaultFetch } from "./client";
import {
  listJobs,
  getJob,
  submitCountJob,
  cancelJob,
  resubmitJob,
  getJobLog,
  getWorkerStatus,
} from "./jobs";
import type { FetchImplementation } from "./client";
import { job, onlineWorker } from "../jobs/testSupport";
import { problemResponse } from "../accounts/testSupport";

it("规范7.1：默认传输保持浏览器原生fetch的this，成员通过账号感知客户端GET作业", async () => {
  vi.stubGlobal("fetch", function (this: unknown) {
    if (this !== undefined && this !== globalThis) throw new TypeError("Illegal invocation");
    return Promise.resolve(Response.json({ items: [], next_cursor: null }));
  });
  try {
    const client = createAccountClient({ fetchImpl: defaultFetch, onUnauthorized: vi.fn() });
    const page = await listJobs({ client, payload: {}, signal: new AbortController().signal });
    expect(page).toEqual({ items: [], next_cursor: null });
  } finally {
    vi.unstubAllGlobals();
  }
});

it("HTTP契约：提交/取消/重提使用生成路径与同源Origin，201/200后才显示成功，不重试POST", async () => {
  const transport = vi
    .fn<FetchImplementation>()
    .mockImplementation(() => Promise.resolve(Response.json(job)));
  const client = createAccountClient({ fetchImpl: transport, onUnauthorized: vi.fn() });
  const signal = new AbortController().signal;
  expect(
    await submitCountJob({
      client,
      signal,
      payload: { steps: 4, interval_ms: 0, failed_steps: [], warning_steps: [] },
    }),
  ).toEqual(job);
  expect(await cancelJob({ client, signal, payload: undefined, jobId: job.job_id })).toEqual(job);
  expect(await resubmitJob({ client, signal, payload: undefined, jobId: job.job_id })).toEqual(job);
  const requests = transport.mock.calls.map(([request]) => request);
  expect(
    requests.map((request) => [request.method, new URL(request.url).pathname, request.credentials]),
  ).toEqual([
    ["POST", "/api/jobs/example", "same-origin"],
    ["POST", `/api/jobs/${job.job_id}/cancel`, "same-origin"],
    ["POST", `/api/jobs/${job.job_id}/resubmit`, "same-origin"],
  ]);
  expect(await requests[0]?.json()).toEqual({
    steps: 4,
    interval_ms: 0,
    failed_steps: [],
    warning_steps: [],
  });
});
it("HTTP契约：401清缓存，409保留诊断，422不回显载荷，超时或取消不声称数据库已回滚", async () => {
  const unauthorized = vi.fn();
  for (const status of [401, 409, 422]) {
    const transport = vi.fn<FetchImplementation>().mockResolvedValue(problemResponse(status));
    const client = createAccountClient({ fetchImpl: transport, onUnauthorized: unauthorized });
    await expect(
      cancelJob({
        client,
        payload: undefined,
        jobId: job.job_id,
        signal: new AbortController().signal,
      }),
    ).rejects.toMatchObject({ cause: { kind: "problem", problem: { status } } });
    expect(transport).toHaveBeenCalledTimes(1);
  }
  expect(unauthorized).toHaveBeenCalledTimes(1);
});
it("分页契约：state/limit/cursor传输不改原值，文本编号超过JS安全整数仍无损", async () => {
  const transport = vi
    .fn<FetchImplementation>()
    .mockResolvedValueOnce(Response.json({ items: [job], next_cursor: "next" }))
    .mockResolvedValueOnce(Response.json(job))
    .mockResolvedValueOnce(
      Response.json({ tail: { status: "cleared", lines: [], truncated: false } }),
    )
    .mockResolvedValueOnce(Response.json(onlineWorker));
  const client = createAccountClient({ fetchImpl: transport, onUnauthorized: vi.fn() });
  const signal = new AbortController().signal;
  expect(
    (
      await listJobs({
        client,
        signal,
        payload: { state: "running", limit: 20, cursor: "opaque_cursor" },
      })
    ).items[0]?.job_id,
  ).toBe("9007199254740993");
  const url = new URL(transport.mock.calls[0]?.[0].url ?? "");
  expect(Object.fromEntries(url.searchParams)).toEqual({
    state: "running",
    limit: "20",
    cursor: "opaque_cursor",
  });
  expect((await getJob({ client, signal, payload: undefined, jobId: job.job_id })).job_id).toBe(
    job.job_id,
  );
  expect(
    (await getJobLog({ client, signal, payload: undefined, jobId: job.job_id })).tail.status,
  ).toBe("cleared");
  expect((await getWorkerStatus({ client, signal, payload: undefined })).online).toBe(true);
});
it("资源契约：卸载取消AbortSignal并忽略迟到响应，不持久化参数或身份", async () => {
  let resolve: ((response: Response) => void) | undefined;
  const stored = vi.spyOn(Storage.prototype, "setItem");
  const transport = vi.fn<FetchImplementation>().mockImplementation(
    () =>
      new Promise<Response>((done) => {
        resolve = done;
      }),
  );
  const client = createAccountClient({ fetchImpl: transport, onUnauthorized: vi.fn() });
  const controller = new AbortController();
  try {
    const pending = listJobs({ client, payload: {}, signal: controller.signal });
    const rejected = expect(pending).rejects.toThrow();
    controller.abort();
    await rejected;
    expect(transport.mock.calls[0]?.[0].signal.aborted).toBe(true);
    resolve?.(Response.json({ items: [job], next_cursor: null }));
    expect(stored).not.toHaveBeenCalled();
  } finally {
    stored.mockRestore();
  }
});
