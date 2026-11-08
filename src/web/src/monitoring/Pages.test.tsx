// 验证页面消费监控接口并展示镜像、VPN、网速折线与资源，不访问真实网络。
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen } from "@testing-library/react";
import { expect, it, vi } from "vitest";
import { AccountClientProvider } from "../accounts/runtime";
import { createHealthClient, type FetchImplementation } from "../api/client";
import { MonitoringPage } from "./Pages";

it("展示镜像、VPN、网速折线和资源占用", async () => {
  let checkedAt = "2026-11-01T00:00:00Z";
  const transport = vi.fn<FetchImplementation>((request) => {
    if (request.method === "POST") {
      setTimeout(() => (checkedAt = "2026-11-01T00:05:00Z"), 50);
      return Promise.resolve(Response.json({ accepted: true }, { status: 202 }));
    }
    if (request.url.endsWith("/mirror"))
      return Promise.resolve(Response.json({ status: "ineffective", checked_at: checkedAt }));
    if (request.url.endsWith("/vpn"))
      return Promise.resolve(
        Response.json({
          interfaces: "on",
          processes: "off",
          proxy: "on",
          proxy_hosts: ["proxy:8080"],
        }),
      );
    return Promise.resolve(
      Response.json({
        cpu_percent: 80,
        download_speed_bytes_per_s: 4096,
        worker: {
          checked_at: "2026-11-01T00:00:00Z",
          system: { total_bytes: 100000, free_bytes: 40000 },
          storage: [{ name: "nas", total_bytes: 200000, free_bytes: 120000 }],
          gpu: [
            {
              index: 0,
              utilization_percent: 42,
              memory_used_bytes: 1000000,
              memory_total_bytes: 2000000,
            },
          ],
        },
        memory_total_bytes: 1024000,
        memory_available_bytes: 409600,
        swap_total_bytes: 204800,
        swap_free_bytes: 153600,
        history: [
          { timestamp: 1, network: { eth0: { receive_bytes_per_s: 1000, send_bytes_per_s: 500 } } },
          { timestamp: 3, network: { eth0: { receive_bytes_per_s: 2000, send_bytes_per_s: 750 } } },
        ],
      }),
    );
  });
  const cache = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  const view = render(
    <QueryClientProvider client={cache}>
      <AccountClientProvider client={createHealthClient(transport)}>
        <MonitoringPage />
      </AccountClientProvider>
    </QueryClientProvider>,
  );
  expect(await screen.findByText("镜像不生效")).toBeTruthy();
  expect(screen.getByText("VPN/代理可能已开启")).toBeTruthy();
  expect(screen.getByText(/CPU：80/)).toBeTruthy();
  expect(screen.getByText(/内存：/)).toBeTruthy();
  expect(screen.getByText(/下载作业速度：4096/)).toBeTruthy();
  expect(screen.getByText(/系统盘/)).toBeTruthy();
  expect(screen.getByText(/nas/)).toBeTruthy();
  expect(screen.getByText(/GPU 0/)).toBeTruthy();
  expect(screen.getByLabelText("网速折线").querySelectorAll("polyline").length).toBeGreaterThan(0);
  expect(screen.getByText(/proxy:8080/)).toBeTruthy();
  fireEvent.click(screen.getByRole("button", { name: "立即检查" }));
  // 契约：worker 写回新检查时间前显示等待，写回后改为显示结论，不会一直停在等待。
  expect(await screen.findByText("镜像检查已请求，等待 worker 执行")).toBeTruthy();
  expect(await screen.findByText(/检查完成（.*）：镜像不生效/, {}, { timeout: 5000 })).toBeTruthy();
  expect(screen.queryByText("镜像检查已请求，等待 worker 执行")).toBeNull();
  expect(
    transport.mock.calls.some(
      ([request]) =>
        request.method === "POST" && request.url.endsWith("/api/monitoring/mirror/check"),
    ),
  ).toBe(true);
  view.unmount();
  cache.clear();
});
