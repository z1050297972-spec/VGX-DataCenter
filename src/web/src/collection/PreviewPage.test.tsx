// M5-04 页面验收：HTTP 和 WebSocket 都在浏览器边界替换，地址只用回环。
import { expect, it, vi } from "vitest";
import { fireEvent, screen, waitFor } from "@testing-library/react";
import { mountPage, pageFetch } from "../scheduling/pageTestSupport";
import type { FetchImplementation } from "../api/client";

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
        expect(
          screen.getByText("机器人上的预览程序没在运行（第 03 张做好后由平台一键启动）"),
        ).toBeTruthy();
      },
      { timeout: 4000 },
    );
    expect(screen.queryByTitle("Lichtblick 实时预览")).toBeNull();
  } finally {
    page.close();
  }
});
