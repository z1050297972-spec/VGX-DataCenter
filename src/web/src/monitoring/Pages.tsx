import "./monitoring.css";
// 网络与资源页只读取监控快照；镜像探测与存储根检查由 worker 负责。
import { useMutation, useQuery } from "@tanstack/react-query";
import { Alert, Breadcrumb, Button, Card, Typography } from "antd";
import { useEffect, useRef, type ReactElement } from "react";
import { useAccountClient } from "../accounts/runtime";
import { boundedRequest } from "../api/_request";
import type { HealthClient } from "../api/client";
import type { components } from "../api/schema";
import { toFailureView } from "../api/problems";
import { DiagnosticCard } from "../DiagnosticCard";

// 与后端采样间隔一致；历史保存在 Web 进程内而不是浏览器数据库。
const REFRESH_INTERVAL_MS = 2_000;
const REQUEST_TIMEOUT_MS = 10_000;
const MIB = 1024 * 1024;
type Vpn = components["schemas"]["VpnResponse"];
type Resources = components["schemas"]["ResourceResponse"];

type Snapshot = {
  mirror: components["schemas"]["MirrorResponse"];
  vpn: Vpn;
  resources: Resources;
};

async function getSnapshot(client: HealthClient, signal: AbortSignal): Promise<Snapshot> {
  return boundedRequest(signal, REQUEST_TIMEOUT_MS, async (requestSignal) => {
    const [mirror, vpn, resources] = await Promise.all([
      client.GET("/api/monitoring/mirror", { signal: requestSignal }),
      client.GET("/api/monitoring/vpn", { signal: requestSignal }),
      client.GET("/api/monitoring/resources", { signal: requestSignal }),
    ]);
    if (!mirror.data || !vpn.data || !resources.data) throw new Error("监控数据不可用");
    return { mirror: mirror.data, vpn: vpn.data, resources: resources.data };
  });
}

function vpnConclusion(vpn: Vpn): string {
  const signals = [vpn.interfaces, vpn.processes, vpn.proxy];
  if (signals.includes("on")) return "VPN/代理可能已开启";
  if (signals.includes("unknown")) return "VPN/代理状态未知";
  return "未发现 VPN/代理迹象";
}

function mirrorLabel(status: Snapshot["mirror"]["status"]): string {
  if (status === "effective") return "镜像生效";
  if (status === "ineffective") return "镜像不生效";
  return "镜像状态未知";
}

function MirrorCheckButton(): ReactElement {
  const client = useAccountClient();
  const active = useRef<AbortController | null>(null);
  useEffect(() => () => active.current?.abort(), []);
  const mutation = useMutation({
    mutationFn: async () => {
      const controller = new AbortController();
      active.current = controller;
      return boundedRequest(controller.signal, REQUEST_TIMEOUT_MS, async (signal) => {
        const result = await client.POST("/api/monitoring/mirror/check", { signal });
        if (!result.data) throw new Error("提交失败");
        return result.data;
      });
    },
    retry: false,
  });
  return (
    <div>
      <Button
        loading={mutation.isPending}
        onClick={() => {
          mutation.mutate();
        }}
      >
        立即检查
      </Button>
      {mutation.isSuccess && <p>镜像检查已请求，等待 worker 执行</p>}
      {mutation.isError && <DiagnosticCard failure={toFailureView(mutation.error)} />}
    </div>
  );
}

function diskDescription(space: components["schemas"]["DiskSpace"]): string {
  if (space.total_bytes === null || space.free_bytes === null) return "未知";
  return `可用 ${(space.free_bytes / MIB).toFixed(1)} / ${(space.total_bytes / MIB).toFixed(1)} MiB`;
}

function WorkerResources({ worker }: { worker: Resources["worker"] }): ReactElement {
  if (!worker) return <p>磁盘与 GPU：等待 worker 采集</p>;
  return (
    <div>
      <p>系统盘：{diskDescription(worker.system)}</p>
      {worker.storage.map((disk) => (
        <p key={disk.name}>
          存储根 {disk.name}：{diskDescription(disk)}
        </p>
      ))}
      {worker.gpu === null ? (
        <p>GPU：未知或不可用</p>
      ) : worker.gpu.length === 0 ? (
        <p>GPU：无</p>
      ) : (
        worker.gpu.map((gpu) => (
          <p key={gpu.index}>
            GPU {gpu.index}：{gpu.utilization_percent}%；显存{" "}
            {(gpu.memory_used_bytes / MIB).toFixed(1)} / {(gpu.memory_total_bytes / MIB).toFixed(1)}{" "}
            MiB
          </p>
        ))
      )}
      <p>磁盘及 GPU 检查时间：{worker.checked_at}</p>
    </div>
  );
}

function NetworkChart({ history }: { history: Resources["history"] }): ReactElement {
  const points = history.map((point) => ({
    receive: Object.values(point.network).reduce((sum, rate) => sum + rate.receive_bytes_per_s, 0),
    send: Object.values(point.network).reduce((sum, rate) => sum + rate.send_bytes_per_s, 0),
  }));
  const max = Math.max(1, ...points.flatMap((point) => [point.receive, point.send]));
  const width = 600;
  const height = 120;
  const coordinates = (key: "receive" | "send") =>
    points
      .map(
        (point, index) =>
          `${String((index * width) / Math.max(1, points.length - 1))},${String(height - (point[key] * height) / max)}`,
      )
      .join(" ");
  const last = history.at(-1);
  return (
    <div>
      {last ? (
        Object.entries(last.network).map(([name, rate]) => (
          <p className="monitoring-rate" key={name}>
            <span>{name}：</span>
            <span>
              接收 {rate.receive_bytes_per_s.toFixed(0)} B/s；发送{" "}
              {rate.send_bytes_per_s.toFixed(0)} B/s
            </span>
          </p>
        ))
      ) : (
        <p>等待下一次采样</p>
      )}
      <p>曲线：蓝色为接收，橙色为发送</p>
      <svg role="img" aria-label="网速折线" viewBox="0 0 600 120" width="100%" height={120}>
        <polyline points={coordinates("receive")} fill="none" stroke="#1677ff" strokeWidth="2" />
        <polyline points={coordinates("send")} fill="none" stroke="#d46b08" strokeWidth="2" />
      </svg>
    </div>
  );
}

/**
 * 展示最近镜像、VPN 和内核资源快照。
 * @returns 网络和资源状态页面。
 * @throws Error 缺少账号客户端提供器。
 * @sideEffects 可取消地读取监控接口，手动检查请求 worker 周期线程，不在 Web 直接探测镜像或访问存储根。
 * @timeSemantics 页面可见期间每两秒刷新，失败不重试，离页取消请求。
 */
export function MonitoringPage(): ReactElement {
  const client = useAccountClient();
  const query = useQuery({
    queryKey: ["network-resources"],
    queryFn: ({ signal }) => getSnapshot(client, signal),
    retry: false,
    gcTime: 0,
    refetchInterval: REFRESH_INTERVAL_MS,
  });
  if (query.isPending) return <p>正在读取网络与资源状态…</p>;
  if (query.isError) return <DiagnosticCard failure={toFailureView(query.error)} />;
  const { mirror, vpn, resources } = query.data;
  const mirrorText = mirrorLabel(mirror.status);
  const usedMemory = resources.memory_total_bytes - resources.memory_available_bytes;
  return (
    <section className="monitoring-page">
      <header className="app-page-header">
        <Breadcrumb items={[{ title: "系统" }, { title: "网络与资源" }]} />
        <Typography.Title level={2} className="app-page-title">
          网络与资源
        </Typography.Title>
      </header>
      <div className="monitoring-grid">
        <Card title="镜像状态" className="monitoring-card">
          <p>{mirrorText}</p>
          <p>检查时间：{mirror.checked_at ?? "尚未检查"}</p>
          <MirrorCheckButton />
        </Card>

        <Card title="VPN 与代理" className="monitoring-card">
          <Alert
            title={vpnConclusion(vpn)}
            type={
              vpn.interfaces === "on" || vpn.processes === "on" || vpn.proxy === "on"
                ? "warning"
                : "info"
            }
          />
          <p>
            隧道网卡：{vpn.interfaces}；代理进程：{vpn.processes}；代理变量：{vpn.proxy}
          </p>
          <p>代理地址：{vpn.proxy_hosts.join("、") || "无"}</p>
        </Card>

        <Card title="网速" className="monitoring-card">
          <p>下载作业速度：{resources.download_speed_bytes_per_s} B/s</p>
          <NetworkChart history={resources.history} />
        </Card>

        <Card title="资源占用" className="monitoring-card">
          <WorkerResources worker={resources.worker} />
          <p>
            CPU：
            {resources.cpu_percent === null ? "等待采样" : `${resources.cpu_percent.toFixed(1)}%`}
          </p>
          <p>
            内存：{(usedMemory / MIB).toFixed(1)} /{" "}
            {(resources.memory_total_bytes / MIB).toFixed(1)} MiB
          </p>
          <p>
            交换区：{((resources.swap_total_bytes - resources.swap_free_bytes) / MIB).toFixed(1)} /{" "}
            {(resources.swap_total_bytes / MIB).toFixed(1)} MiB
          </p>
        </Card>
      </div>
    </section>
  );
}
