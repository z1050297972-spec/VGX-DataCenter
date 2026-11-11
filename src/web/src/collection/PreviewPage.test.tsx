// M5-04 页面验收：HTTP 和 WebSocket 都在浏览器边界替换，地址只用回环。
import { expect, it, vi } from "vitest";
import { fireEvent, screen, waitFor } from "@testing-library/react";
import { mountPage, pageFetch } from "../scheduling/pageTestSupport";
import type { FetchImplementation } from "../api/client";
import { completedJob } from "../jobs/testSupport";

function previewFetch(): FetchImplementation {
  const fallback = pageFetch();
  return (request) => {
    const path = new URL(request.url).pathname;
    if (path === "/api/robots")
      return Promise.resolve(
        Response.json({
          items: [
            {
              robot_id: 7,
              name: "预览机器人",
              robot_model: "Galaxea R1 Lite",
              address: "127.0.0.1",
            },
          ],
        }),
      );
    if (path === "/api/robot-profiles")
      return Promise.resolve(
        Response.json({
          items: [
            {
              profile: "r1lite",
              version: 1,
              model: "Galaxea R1 Lite",
              unknown_count: 1,
            },
          ],
        }),
      );
    return fallback(request);
  };
}

// 契约：不安全来源只显示本机打开提示，即使机器人存在也不嵌查看器。
it("非安全来源不提供实时预览连接", async () => {
  vi.stubGlobal("isSecureContext", false);
  const page = mountPage("/robots/7/preview", previewFetch());
  try {
    expect(
      await screen.findByText("实时预览只能在工作站本机打开：http://localhost:8600"),
    ).toBeTruthy();
    expect(screen.queryByTitle("Lichtblick 实时预览")).toBeNull();
    expect(screen.queryByRole("button", { name: "连接" })).toBeNull();
    expect(screen.queryByRole("button", { name: "开启预览" })).toBeNull();
    expect(screen.queryByRole("button", { name: "停止预览" })).toBeNull();
  } finally {
    page.close();
  }
});

// 契约：预检用 sdk 子协议，成功后才设置包含绝对布局 URL 的同源 iframe。
it("安全来源先握手再嵌入正确的查看器地址", async () => {
  vi.stubGlobal("isSecureContext", true);
  vi.stubGlobal(
    "WebSocket",
    class extends EventTarget {
      constructor(url: string, protocol: string) {
        super();
        expect(url).toBe("ws://127.0.0.1:8765");
        expect(protocol).toBe("foxglove.sdk.v1");
        queueMicrotask(() => this.dispatchEvent(new Event("open")));
      }
      close(): void {
        /* 假网络无需释放真实 socket。 */
      }
    },
  );
  const page = mountPage("/robots/7/preview", previewFetch());
  try {
    const button = await screen.findByRole("button", { name: "连接" });
    expect(screen.queryByTitle("Lichtblick 实时预览")).toBeNull();
    expect(screen.getByText("RobotProfile 版本")).toBeTruthy();
    fireEvent.click(button);
    const frame = await screen.findByTitle("Lichtblick 实时预览");
    expect(frame.getAttribute("src")).toBe(
      "/lichtblick/?openIn=web&ds=foxglove-websocket&ds.url=ws%3A%2F%2F127.0.0.1%3A8765&layoutUrl=" +
        encodeURIComponent(`${window.location.origin}/api/robots/7/preview-layout`),
    );
  } finally {
    page.close();
  }
});

// 契约：握手错误或三秒内没有结果均显示未运行提示，不创建 iframe。
it.each(["error", "timeout"])("预检 %s 时不嵌入查看器", async (result) => {
  vi.stubGlobal("isSecureContext", true);
  vi.stubGlobal(
    "WebSocket",
    class extends EventTarget {
      constructor() {
        super();
        if (result === "error") queueMicrotask(() => this.dispatchEvent(new Event("error")));
      }
      close(): void {
        /* 不创建网络资源。 */
      }
    },
  );
  const page = mountPage("/robots/7/preview", previewFetch());
  try {
    fireEvent.click(await screen.findByRole("button", { name: "连接" }));
    await waitFor(
      () => {
        expect(screen.getByText("机器人上的预览程序没在运行，先点开启预览")).toBeTruthy();
      },
      { timeout: 4000 },
    );
    expect(screen.queryByTitle("Lichtblick 实时预览")).toBeNull();
  } finally {
    page.close();
  }
});

// M5-09 验收：加载不启动；人工开启成功才握手，人工停止先撤下 iframe 再提交作业。
it("人工启停预览并在启动成功后自动连接", async () => {
  vi.stubGlobal("isSecureContext", true);
  const sockets = vi.fn();
  vi.stubGlobal(
    "WebSocket",
    class extends EventTarget {
      constructor() {
        super();
        sockets();
        queueMicrotask(() => this.dispatchEvent(new Event("open")));
      }
      close(): void {
        /* 没有真实网络资源。 */
      }
    },
  );
  const requests: unknown[] = [];
  const fallback = previewFetch();
  const fetcher: FetchImplementation = async (request) => {
    const path = new URL(request.url).pathname;
    if (path === "/api/jobs" && request.method === "POST") {
      const body: unknown = await request.json();
      requests.push(body);
      if (requests.length === 2) expect(screen.queryByTitle("Lichtblick 实时预览")).toBeNull();
      return Response.json(
        { ...completedJob, job_id: String(requests.length), state: "queued", summary: null },
        { status: 201 },
      );
    }
    if (path === "/api/jobs/1" || path === "/api/jobs/2")
      return Response.json({
        ...completedJob,
        job_id: path.endsWith("1") ? "1" : "2",
        type_name: path.endsWith("1") ? "robot_preview_start" : "robot_preview_stop",
      });
    return fallback(request);
  };
  const page = mountPage("/robots/7/preview", fetcher);
  try {
    const start = await screen.findByRole("button", { name: "开启预览" });
    expect(requests).toEqual([]);
    expect(sockets).not.toHaveBeenCalled();
    expect(
      screen.getByText("预览要手动开启和停止，平台不会自动开启。正式采集前请先停止预览。"),
    ).toBeTruthy();
    fireEvent.click(start);
    await screen.findByTitle("Lichtblick 实时预览");
    expect(requests).toEqual([{ type_name: "robot_preview_start", parameters: { robot_id: 7 } }]);
    fireEvent.click(screen.getByRole("button", { name: "停止预览" }));
    await waitFor(() => {
      expect(requests).toHaveLength(2);
    });
    expect(requests[1]).toEqual({ type_name: "robot_preview_stop", parameters: { robot_id: 7 } });
    expect(screen.queryByTitle("Lichtblick 实时预览")).toBeNull();
  } finally {
    page.close();
  }
});
