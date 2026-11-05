// M1-04 后半段验收：真实 Router 和 HTTP 边界替身验证用户可见行为，不访问真实数据。
import { formatDateTime } from "../time";
import { describe, it, expect, vi } from "vitest";
import { screen, within, fireEvent, waitFor, act } from "@testing-library/react";
import { mountPage } from "../scheduling/pageTestSupport";
import { problemResponse, account } from "../accounts/testSupport";
import { ACCOUNT_QUERY_KEY } from "../accounts/runtime";
import { completedJob } from "../jobs/testSupport";
import {
  datasetFetch,
  detail,
  panel,
  taskEntry,
  formatEntry,
  filters,
  datasets,
} from "./testSupport";
import type { FetchImplementation } from "../api/client";
import type { DatasetDetail } from "../api/datasets";

const selectedUrl = `/datasets?selected=${encodeURIComponent(taskEntry.entry_path)}`;
const offlineLink: DatasetDetail["links"][number] = {
  name: "data",
  ordinal: 0,
  derived_entry_path: "按任务/libero_10/data",
  source_path: "/fake/disk/data",
  source_type: "directory",
  observed_target: "/fake/disk/data",
  storage_root_name: "disk",
  status: "offline",
  checked_at: "2026-10-29T12:00:00Z",
  size_bytes: 4096,
  size_checked_at: "2026-10-28T12:00:00Z",
};

// 仅替换 HTTP 响应；客户端、查询生命周期和真实路由照常执行。
function transport(
  overrides: Record<string, (request: Request) => Response | Promise<Response>>,
  requests: Request[] = [],
): FetchImplementation {
  const fallback = datasetFetch(requests);
  return (request) => {
    const handler = overrides[new URL(request.url).pathname];
    if (!handler) return fallback(request);
    requests.push(request);
    return Promise.resolve(handler(request));
  };
}

describe("数据集后半段验收", () => {
  // 验收3：离线状态由索引明确提供；旧统计值及原统计时间保留，不能误报断链。
  it("存储根离线时顶部提示、链接标存储根离线并保留旧大小", async () => {
    const page = mountPage(
      selectedUrl,
      transport({
        "/api/datasets/panel": () =>
          Response.json({
            ...panel,
            storage_roots: [
              {
                name: "disk",
                path: "/fake/disk",
                online: false,
                reason: "timeout",
                checked_at: "2026-10-29T12:00:00Z",
              },
            ],
          }),
        "/api/datasets/detail": () =>
          Response.json({
            ...detail,
            links: [offlineLink],
            dataset_size: {
              ...detail.dataset_size,
              size_bytes: 4096,
              size_checked_at: "2026-10-28T12:00:00Z",
              display_bytes: 4096,
              display_source: "measured",
            },
          }),
      }),
    );
    try {
      expect(
        await screen.findByText("存储根 disk 离线：访问超时；其下磁盘检查已跳过"),
      ).toBeTruthy();
      const links = await screen.findByRole("region", { name: "链接状态" });
      expect(within(links).getByText("存储根离线")).toBeTruthy();
      expect(within(links).queryByText("断链")).toBeNull();
      expect(
        screen.getByText(/统计大小：4.0 KiB · LeRobot 只计 parquet、mp4 和 meta/),
      ).toBeTruthy();
      expect(screen.getByText(`统计时间：${formatDateTime("2026-10-28T12:00:00Z")}`)).toBeTruthy();
    } finally {
      page.close();
    }
  });
  // 验收4：详情指纹或随后读取的子任务响应头都能使页面过期；重扫只用永久编号。
  it("详情或子任务发现索引过期时显示重新扫描并提交单数据集作业", async () => {
    vi.stubGlobal(
      "Worker",
      class {
        postMessage() {}
        terminate() {}
      },
    );
    for (const fromSubtasks of [false, true]) {
      const requests: Request[] = [];
      const page = mountPage(
        selectedUrl,
        transport(
          {
            "/api/datasets/detail": () => Response.json({ ...detail, index_stale: !fromSubtasks }),
            "/api/datasets/subtasks": () =>
              new Response('{"dataset_id":"dataset-14"}', { headers: { "X-Index-Stale": "true" } }),
            "/api/datasets/dataset-14/rescan": () => Response.json(completedJob, { status: 201 }),
          },
          requests,
        ),
      );
      try {
        await screen.findByRole("heading", { name: "libero_10" });
        if (fromSubtasks) fireEvent.click(screen.getByRole("button", { name: "打开 子任务.json" }));
        expect(await screen.findByText("索引过期")).toBeTruthy();
        fireEvent.click(screen.getByRole("button", { name: "重新扫描" }));
        expect(
          await screen.findByRole("region", { name: `重新检查 #${completedJob.job_id}` }),
        ).toBeTruthy();
        expect(page.router.state.location.pathname).toBe("/datasets");
        expect(
          requests
            .filter((request) => request.method === "POST")
            .map((request) => new URL(request.url).pathname),
        ).toEqual(["/api/datasets/dataset-14/rescan"]);
      } finally {
        page.close();
      }
    }
  });
  // 验收5：型号表出现后使用后端提供的默认方式；编号传给接口，不把标签冒充型号。
  it("有型号映射时默认按机器人型号，更多筛选保留标签", async () => {
    const requests: Request[] = [];
    const page = mountPage(
      "/datasets",
      transport(
        {
          "/api/datasets/filters": () =>
            Response.json({
              ...filters,
              default_robot_filter: "robot_model",
              robot_models_registered: true,
              robot_models: [{ model_id: "model-7", name: "R1 Lite", robot_types: ["franka"] }],
              robot_model_options: [
                { value: "model-7", label: "R1 Lite", count: 1 },
                { value: "unknown", label: "未知", count: 1 },
              ],
            }),
        },
        requests,
      ),
    );
    try {
      fireEvent.mouseDown(await screen.findByRole("combobox", { name: "机器人型号" }));
      fireEvent.click(await screen.findByRole("option", { name: "R1 Lite（1）" }));
      await waitFor(() => {
        expect(page.router.state.location.search).toMatchObject({ robot_model_id: "model-7" });
      });
      await waitFor(() => {
        expect(
          requests.some(
            (request) =>
              new URL(request.url).pathname === "/api/datasets" &&
              new URL(request.url).searchParams.get("robot_model_id") === "model-7",
          ),
        ).toBe(true);
      });
      expect(screen.queryByRole("combobox", { name: "型号标签" })).toBeNull();
      fireEvent.click(screen.getByRole("button", { name: "更多筛选" }));
      expect(screen.getByRole("combobox", { name: "型号标签" })).toBeTruthy();
    } finally {
      page.close();
    }
  });
  // 范围筛选：来源和未知值同时进入 URL/API；翻页和目录选择不得丢失条件。
  it("数据来源与未知值筛选可分享，分页和目录定位保持筛选", async () => {
    const first = datasets.items[0];
    if (!first) throw new Error("缺少测试样本");
    const rows = Array.from({ length: 21 }, (_, index) => ({
      ...first,
      dataset_id: `item-${String(index)}`,
      name: `item-${String(index)}`,
      robot_types: [null],
      fps: [null],
    }));
    const requests: Request[] = [];
    const page = mountPage(
      "/datasets?fps=unknown&robot_type=unknown",
      transport(
        {
          "/api/datasets": (request) => {
            const offset = Number(new URL(request.url).searchParams.get("offset") ?? 0);
            return Response.json({
              ...datasets,
              offset,
              total: 21,
              items: rows.slice(offset, offset + 20),
            });
          },
        },
        requests,
      ),
    );
    try {
      fireEvent.mouseDown(await screen.findByRole("combobox", { name: "数据来源" }));
      fireEvent.click(await screen.findByRole("option", { name: "未知（2）" }));
      await screen.findByText("共 21 个数据集");
      fireEvent.click(await screen.findByTitle("Next Page"));
      expect(await screen.findByRole("button", { name: "打开 item-20" })).toBeTruthy();
      await waitFor(() => {
        expect(page.router.state.location.search).toMatchObject({
          data_origin: "unknown",
          fps: "unknown",
          robot_type: "unknown",
          offset: 20,
        });
      });
      fireEvent.click(screen.getByRole("tab", { name: "按任务" }));
      await waitFor(() => {
        expect(document.querySelector('.dataset-tree-name[title="按任务"]')).not.toBeNull();
      });
      fireEvent.click(document.querySelector('.dataset-tree-name[title="按任务"]') as Element);
      await waitFor(() => {
        expect(
          requests.some((request) => {
            const url = new URL(request.url);
            return (
              url.pathname === "/api/datasets" &&
              url.searchParams.get("entry_path") === "按任务" &&
              url.searchParams.get("data_origin") === "unknown" &&
              url.searchParams.get("fps") === "unknown" &&
              url.searchParams.get("robot_type") === "unknown"
            );
          }),
        ).toBe(true);
      });
      expect(page.router.state.location.search.offset).toBeUndefined();
    } finally {
      page.close();
    }
  });
  // 11 Q12：业务信息来自规范副本，Markdown只渲染；未知HTML作为文字，不解析其中的业务值。
  it("规范副本的14项按Markdown渲染，缺失规范副本明确提示", async () => {
    const fields = Array.from({ length: 14 }, (_, index) => ({
      number: index + 1,
      name: `字段${String(index + 1)}`,
      value_markdown:
        index === 0
          ? "**规范副本**、`robot_type`\n\n[资料](https://example.invalid/data) 与 [数据路径](</fake/data>)\n\n<img src=x onerror=alert(1)>"
          : `原文${String(index + 1)}`,
    }));
    const page = mountPage(
      selectedUrl,
      transport({
        "/api/datasets/detail": () =>
          Response.json({
            ...detail,
            canonical_information: {
              ...detail.information,
              content: JSON.stringify({
                dataset_id: "dataset-14",
                snapshot_date: "2026-10-12",
                fields,
              }),
            },
          }),
      }),
    );
    try {
      const info = await screen.findByRole("region", { name: "14 项数据集信息" });
      expect(within(info).getAllByRole("row")).toHaveLength(15);
      expect(within(info).getByText("规范副本").tagName).toBe("STRONG");
      expect(within(info).getByText("robot_type").tagName).toBe("CODE");
      expect(within(info).getByRole("link", { name: "资料" }).getAttribute("href")).toBe(
        "https://example.invalid/data",
      );
      expect(within(info).queryByRole("link", { name: "数据路径" })).toBeNull();
      expect(within(info).getByText("/fake/data")).toBeTruthy();
      expect(within(info).queryByRole("img")).toBeNull();
      expect(within(info).getByText("原文14")).toBeTruthy();
    } finally {
      page.close();
    }
    const missing = mountPage(selectedUrl, datasetFetch());
    try {
      expect(await screen.findByText("规范副本不可用，无法展示14项数据集信息")).toBeTruthy();
    } finally {
      missing.close();
    }
  });
  // 契约：详情保留链接状态和检查时间，移除数据块、观察指向及两处原文按钮，保留子任务入口。
  it("详情隐藏数据块和原文按钮，保留链接状态与子任务", async () => {
    const page = mountPage(
      selectedUrl,
      transport({
        "/api/datasets/detail": () =>
          Response.json({
            ...detail,
            links: [{ ...offlineLink, status: "broken" }],
            sources: [
              {
                ordinal: 0,
                source_id: "source-17",
                original_path: "/fake/old",
                direct_path: "/fake/current",
                derived_entry_path: "按任务/libero_10/data",
                format: "lerobot",
                version: "3.0",
                validation_status: "legacy_custom",
                validation_status_label: "未识别（保留原值）",
              },
            ],
          }),
      }),
    );
    try {
      const links = await screen.findByRole("region", { name: "链接状态" });
      expect(within(links).getByText("断链")).toBeTruthy();
      expect(within(links).getByText(formatDateTime("2026-10-29T12:00:00Z"))).toBeTruthy();
      expect(screen.queryByRole("region", { name: "数据块" })).toBeNull();
      expect(within(links).queryByRole("columnheader", { name: "观察到的指向" })).toBeNull();
      for (const name of ["名称", "登记指向", "存储根", "状态", "检查时间"])
        expect(within(links).getByRole("columnheader", { name })).toBeTruthy();
      expect(screen.queryByRole("button", { name: "打开 数据集信息.json" })).toBeNull();
      expect(screen.queryByRole("button", { name: "打开 原始路径.json" })).toBeNull();
      expect(screen.getByRole("button", { name: "打开 子任务.json" })).toBeTruthy();
    } finally {
      page.close();
    }
  });
  // 手动统计只发送当前数据集编号；等待响应期间重复点击不能生成第二个作业。
  it("统计大小按钮提交单数据集作业且不重复提交", async () => {
    let finish: ((response: Response) => void) | undefined;
    const requests: Request[] = [];
    const page = mountPage(
      selectedUrl,
      transport(
        {
          "/api/datasets/sizing": () =>
            new Promise<Response>((resolve) => {
              finish = resolve;
            }),
        },
        requests,
      ),
    );
    try {
      const button = await screen.findByRole("button", { name: "统计大小" });
      fireEvent.click(button);
      await waitFor(() => {
        expect(button).toHaveProperty("disabled", true);
      });
      fireEvent.click(button);
      const sent = requests.filter((request) => request.method === "POST");
      expect(sent).toHaveLength(1);
      expect(await sent[0]?.clone().json()).toEqual({ dataset_id: "dataset-14" });
      await act(async () => {
        finish?.(Response.json(completedJob, { status: 201 }));
        await Promise.resolve();
      });
      expect(
        await screen.findByRole("region", { name: `统计大小 #${completedJob.job_id}` }),
      ).toBeTruthy();
      expect(page.router.state.location.pathname).toBe("/datasets");
    } finally {
      page.close();
      finish?.(Response.json(completedJob));
    }
  });
  // 生命周期：Worker错误和超时后结束等待、只释放一次，迟到响应不能复活查看器。
  it("Worker故障或超时后显示诊断、释放一次并忽略迟到响应", async () => {
    for (const mode of ["error", "timeout"]) {
      const workers: {
        onerror: (() => void) | null;
        onmessage: ((event: MessageEvent) => void) | null;
        terminate: ReturnType<typeof vi.fn>;
      }[] = [];
      vi.stubGlobal(
        "Worker",
        class {
          onerror: (() => void) | null = null;
          onmessage: ((event: MessageEvent) => void) | null = null;
          terminate = vi.fn();
          postMessage() {}
          constructor() {
            workers.push(this);
          }
        },
      );
      const page = mountPage(
        selectedUrl,
        transport({ "/api/datasets/subtasks": () => new Response("{}") }),
      );
      try {
        fireEvent.click(await screen.findByRole("button", { name: "打开 子任务.json" }));
        await waitFor(() => {
          expect(workers).toHaveLength(1);
        });
        const worker = workers[0];
        if (!worker) throw new Error("缺少Worker");
        const late = worker.onmessage;
        if (mode === "error")
          act(() => {
            worker.onerror?.();
          });
        else {
          vi.useFakeTimers();
          // 计时器必须在Worker创建之前替换；这里改为重新打开，确保使用测试时钟。
          fireEvent.click(screen.getByRole("button", { name: "关闭 子任务.json" }));
          fireEvent.click(screen.getByRole("button", { name: "打开 子任务.json" }));
          await act(async () => {
            await vi.advanceTimersByTimeAsync(60_100);
          });
          vi.useRealTimers();
        }
        expect(await screen.findByText("请求失败，请检查网络或稍后重试。")).toBeTruthy();
        act(() => {
          late?.(
            new MessageEvent("message", {
              data: { text: "迟到旧内容", page: 0, totalPages: 1, valid: true },
            }),
          );
        });
        expect(screen.queryByText("迟到旧内容")).toBeNull();
        page.close();
        for (const instance of workers) expect(instance.terminate).toHaveBeenCalledTimes(1);
      } finally {
        page.close();
        vi.useRealTimers();
      }
    }
  });
  // 请求故障沿用统一诊断；失败正文不送进Worker，失败请求不自动重试。
  it("子任务请求失败显示统一诊断且不启动Worker或自动重试", async () => {
    const worker = vi.fn();
    vi.stubGlobal("Worker", worker);
    const requests: Request[] = [];
    const page = mountPage(
      selectedUrl,
      transport({ "/api/datasets/subtasks": () => problemResponse(404) }, requests),
    );
    try {
      fireEvent.click(await screen.findByRole("button", { name: "打开 子任务.json" }));
      expect(await screen.findByText("请求被拒绝")).toBeTruthy();
      expect(worker).not.toHaveBeenCalled();
      vi.useFakeTimers();
      await act(async () => {
        await vi.advanceTimersByTimeAsync(3000);
      });
      expect(
        requests.filter((request) => new URL(request.url).pathname === "/api/datasets/subtasks"),
      ).toHaveLength(1);
      expect(page.router.state.location.pathname).toBe("/datasets");
    } finally {
      page.close();
      vi.useRealTimers();
    }
  });

  // 路由离开所选入口必须取消尚未完成的大文件请求，迟到响应不能出现在新入口。
  it("切换入口取消子任务请求并忽略迟到正文", async () => {
    let pending: Request | undefined;
    let finish: ((response: Response) => void) | undefined;
    const worker = vi.fn();
    vi.stubGlobal("Worker", worker);
    const page = mountPage(
      selectedUrl,
      transport({
        "/api/datasets/subtasks": (request) => {
          pending = request;
          return new Promise<Response>((resolve) => {
            finish = resolve;
          });
        },
      }),
    );
    try {
      fireEvent.click(await screen.findByRole("button", { name: "打开 子任务.json" }));
      await waitFor(() => {
        expect(pending).toBeDefined();
      });
      fireEvent.click(screen.getByRole("button", { name: `跳转到 ${formatEntry.entry_path}` }));
      await waitFor(() => {
        expect(pending?.signal.aborted).toBe(true);
      });
      await act(async () => {
        finish?.(new Response('{"old":"迟到正文"}'));
        await Promise.resolve();
      });
      expect(await screen.findByRole("button", { name: "打开 子任务.json" })).toBeTruthy();
      expect(worker).not.toHaveBeenCalled();
      expect(screen.queryByText(/迟到正文/)).toBeNull();
    } finally {
      page.close();
      finish?.(new Response("{}"));
    }
  });

  // 同一路由换号后关闭旧文件并释放Worker，不能把前一个账号的解析内容保留给新账号。
  it("换号释放旧Worker并关闭旧账号的子任务内容", async () => {
    let identity = account;
    const workers: { terminate: ReturnType<typeof vi.fn> }[] = [];
    vi.stubGlobal(
      "Worker",
      class {
        onmessage: ((event: MessageEvent) => void) | null = null;
        terminate = vi.fn();
        constructor() {
          workers.push(this);
        }
        postMessage() {
          queueMicrotask(() => {
            this.onmessage?.(
              new MessageEvent("message", {
                data: { text: "旧账号内容", page: 0, totalPages: 1, valid: true },
              }),
            );
          });
        }
      },
    );
    const page = mountPage(
      selectedUrl,
      transport({
        "/api/auth/me": () => Response.json(identity),
        "/api/datasets/subtasks": () => new Response("{}"),
      }),
    );
    try {
      fireEvent.click(await screen.findByRole("button", { name: "打开 子任务.json" }));
      await screen.findByText("旧账号内容");
      identity = { ...account, account_id: "42", display_name: "新账号" };
      await act(async () => {
        await page.cache.invalidateQueries({ queryKey: ACCOUNT_QUERY_KEY });
      });
      await screen.findByText("新账号");
      expect(await screen.findByRole("button", { name: "打开 子任务.json" })).toBeTruthy();
      expect(screen.queryByText("旧账号内容")).toBeNull();
      expect(workers[0]?.terminate).toHaveBeenCalledTimes(1);
      await waitFor(() => {
        expect(
          page.cache.getQueryData([
            "datasets",
            account.account_id,
            "subtasks",
            taskEntry.entry_path,
          ]),
        ).toBeUndefined();
      });
    } finally {
      page.close();
    }
  });
});
