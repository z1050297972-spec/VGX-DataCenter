// M1-04 大文件验收：只替换浏览器 Worker 边界，页面、客户端和 Query 使用真实实现。
import { it, expect, vi } from "vitest";
import { act, fireEvent, screen, waitFor } from "@testing-library/react";
import { mountPage } from "../scheduling/pageTestSupport";
import { datasetFetch, taskEntry } from "./testSupport";

// 验证约 14 MB 原文按需请求并走 Vite Worker 路径，主线程仅接收一页文本；卸载必须 terminate。
it("14 MB 子任务点击才请求并交给 Worker，分页且离页释放", async () => {
  const raw = '{"dataset_id":"dataset-14","padding":"' + "x".repeat(14 * 1024 * 1024) + '"}';
  const requests: Request[] = [];
  const fallback = datasetFetch(requests);
  const workers: {
    url: URL;
    options: WorkerOptions;
    postMessage: ReturnType<typeof vi.fn>;
    terminate: ReturnType<typeof vi.fn>;
    onmessage: ((event: MessageEvent) => void) | null;
  }[] = [];
  vi.stubGlobal(
    "Worker",
    class {
      onmessage: ((event: MessageEvent) => void) | null = null;
      postMessage = vi.fn();
      terminate = vi.fn();
      constructor(
        public url: URL,
        public options: WorkerOptions,
      ) {
        workers.push(this);
      }
    },
  );
  const page = mountPage(
    `/datasets?selected=${encodeURIComponent(taskEntry.entry_path)}`,
    (request) => {
      if (new URL(request.url).pathname === "/api/datasets/subtasks") {
        requests.push(request);
        return Promise.resolve(
          new Response(raw, {
            headers: {
              "Content-Type": "text/plain; charset=utf-8",
              "X-Index-Stale": "false",
              "X-Document-Sha256": "abc",
            },
          }),
        );
      }
      return fallback(request);
    },
  );
  try {
    await screen.findByRole("heading", { name: "libero_10" });
    expect(
      requests.filter((request) => new URL(request.url).pathname === "/api/datasets/subtasks"),
    ).toHaveLength(0);
    expect(workers).toHaveLength(0);
    fireEvent.click(screen.getByRole("button", { name: "打开 子任务.json" }));
    await waitFor(() => {
      expect(workers).toHaveLength(1);
    });
    const worker = workers[0];
    if (!worker) throw new Error("缺少 Worker");
    expect(worker.url.pathname).toMatch(/json\.worker\.ts$/);
    expect(worker.options).toEqual({ type: "module" });
    expect(worker.postMessage).toHaveBeenCalledWith({ type: "load", text: raw });
    expect(screen.getByText("正在解析 JSON…")).toBeTruthy();
    act(() => {
      worker.onmessage?.(
        new MessageEvent("message", {
          data: { text: "第一页内容", page: 0, totalPages: 2, valid: true },
        }),
      );
    });
    expect(await screen.findByText("第一页内容")).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "下一页 JSON" }));
    expect(worker.postMessage).toHaveBeenLastCalledWith({ type: "page", page: 1 });
    expect(
      requests.filter((request) => new URL(request.url).pathname === "/api/datasets/subtasks"),
    ).toHaveLength(1);
    page.close();
    expect(worker.terminate).toHaveBeenCalledTimes(1);
  } finally {
    page.close();
  }
});

// 契约：另外两份 JSON 展示详情接口现场原文，未知字段保留，不从索引重建正文。
it("两份现场 JSON 原文均可独立打开", async () => {
  const messages: unknown[] = [];
  vi.stubGlobal(
    "Worker",
    class {
      onmessage: ((event: MessageEvent) => void) | null = null;
      terminate = vi.fn();
      postMessage(message: { type: string; text: string }) {
        messages.push(message);
        queueMicrotask(() =>
          this.onmessage?.(
            new MessageEvent("message", {
              data: { text: message.text, page: 0, totalPages: 1, valid: true },
            }),
          ),
        );
      }
    },
  );
  const page = mountPage(
    `/datasets?selected=${encodeURIComponent(taskEntry.entry_path)}`,
    datasetFetch(),
  );
  try {
    await screen.findByRole("heading", { name: "libero_10" });
    fireEvent.click(screen.getByRole("button", { name: "打开 数据集信息.json" }));
    expect(await screen.findByText(/"value_markdown":"libero_10"/)).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "打开 原始路径.json" }));
    expect(await screen.findByText('{"dataset_id":"dataset-14","sources":[]}')).toBeTruthy();
    expect(messages).toHaveLength(2);
  } finally {
    page.close();
  }
});
