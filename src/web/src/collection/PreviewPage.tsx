// M5-04 预览页面只进行浏览器握手并嵌入同源查看器；不启动 relay、不提交连接检查作业。
import { useEffect, useRef, useState, type ReactElement } from "react";
import { useQuery } from "@tanstack/react-query";
import { useParams } from "@tanstack/react-router";
import { Alert, Breadcrumb, Button, Card, Descriptions, Flex, Spin, Typography } from "antd";
import { useAccountClient } from "../accounts/runtime";
import { listRobots, type Robot } from "../api/collection";
import { listPreviewProfiles, PREVIEW_PORT, type ProfileSummary } from "../api/preview";
import { toFailureView } from "../api/problems";
import { DiagnosticCard } from "../DiagnosticCard";
import "./collection.css";

// M5-04 的握手上限为 3 秒；只有可达后才导入布局，规避 Lichtblick #1376。
const PREVIEW_CONNECT_TIMEOUT_MS = 3000;
const RELAY_UNAVAILABLE = "机器人上的预览程序没在运行（第 03 张做好后由平台一键启动）";

/**
 * 显示安全来源限制或已登记机器人的实时预览页面。
 * @returns 非安全来源只显示提示；安全来源显示登记信息及连接操作。
 * @throws 无；HTTP 失败显示 DiagnosticCard，握手失败显示工单指定提示。
 * @sideEffects 安全来源读取机器人与 Profile；用户点击后预检 WebSocket，再挂载 iframe。
 * @timeSemantics HTTP 请求最多 ACCOUNT_TIMEOUT_MS，握手最多 3 秒；离页关闭预检连接和计时器。
 */
export function PreviewPage(): ReactElement {
  if (!window.isSecureContext)
    return <Alert type="warning" title="实时预览只能在工作站本机打开：http://localhost:8600" />;
  return <SecurePreviewPage />;
}

// 事实来自已有列表接口，避免新增仅为页头重复登记数据的接口。
function SecurePreviewPage(): ReactElement {
  const { robotId } = useParams({ from: "/robots/$robotId/preview" });
  const client = useAccountClient();
  const robots = useQuery({
    queryKey: ["robots"],
    queryFn: ({ signal }) => listRobots({ client, signal, payload: undefined }),
    retry: false,
    gcTime: 0,
  });
  const profiles = useQuery({
    queryKey: ["robot-profiles"],
    queryFn: ({ signal }) => listPreviewProfiles({ client, signal, payload: undefined }),
    retry: false,
    gcTime: 0,
  });
  const error = robots.error ?? profiles.error;
  if (error) return <DiagnosticCard failure={toFailureView(error)} />;
  if (!robots.data || !profiles.data) return <Spin />;
  const robot = robots.data.items.find((item) => String(item.robot_id) === robotId);
  if (!robot) return <Alert type="error" title="机器人不存在" />;
  const profile = profiles.data.items.find((item) => item.model === robot.robot_model);
  if (!profile) return <Alert type="warning" title="该型号没有 RobotProfile" />;
  return (
    <PreviewViewer key={`${robotId}:${robot.address ?? ""}`} robot={robot} profile={profile} />
  );
}

// 独立子树以机器人编号为 key，切换机器人时清理旧连接和 iframe，避免沿用上一台的成功状态。
function PreviewViewer({
  robot,
  profile,
}: {
  robot: Robot;
  profile: ProfileSummary;
}): ReactElement {
  const cleanupProbe = useRef<(() => void) | null>(null);
  const [status, setStatus] = useState<"idle" | "connecting" | "connected" | "failed">("idle");
  // 登记契约允许裸 IPv6；URL 的主机部分必须加方括号，不改变登记地址。
  const host = robot.address?.includes(":") ? `[${robot.address}]` : robot.address;
  const url = host ? `ws://${host}:${String(PREVIEW_PORT)}` : null;
  useEffect(
    () => () => {
      cleanupProbe.current?.();
    },
    [],
  );
  function connect(): void {
    if (!url) return;
    cleanupProbe.current?.();
    setStatus("connecting");
    try {
      cleanupProbe.current = probeRelay(url, (connected) => {
        setStatus(connected ? "connected" : "failed");
      });
    } catch {
      setStatus("failed");
    }
  }
  const parameters = new URLSearchParams({
    openIn: "web",
    ds: "foxglove-websocket",
    "ds.url": url ?? "",
    layoutUrl: `${window.location.origin}/api/robots/${String(robot.robot_id)}/preview-layout`,
  });
  return (
    <Flex vertical gap="large">
      <header className="app-page-header">
        <Breadcrumb items={[{ title: "机器人", href: "/robots" }, { title: "实时预览" }]} />
        <Flex justify="space-between" align="center" wrap>
          <Typography.Title level={2} className="app-page-title">
            实时预览 · {robot.name}
          </Typography.Title>
          <Button
            type="primary"
            autoInsertSpace={false}
            loading={status === "connecting"}
            disabled={!url}
            onClick={connect}
          >
            连接
          </Button>
        </Flex>
      </header>
      <Card>
        <Descriptions
          items={[
            { key: "name", label: "机器人", children: robot.name },
            { key: "address", label: "地址", children: robot.address ?? "未填写" },
            {
              key: "version",
              label: "RobotProfile 版本",
              children: `${profile.profile} · v${String(profile.version)}`,
            },
            { key: "url", label: "预览地址", children: url ?? "请先填写机器人地址" },
          ]}
        />
      </Card>
      {status === "failed" && <Alert type="warning" title={RELAY_UNAVAILABLE} />}
      {status === "connected" && (
        <Card>
          <iframe
            title="Lichtblick 实时预览"
            className="collection-preview-frame"
            src={`/lichtblick/?${parameters.toString()}`}
          />
        </Card>
      )}
    </Flex>
  );
}

// 原生浏览器边界：超时、错误和离页都移除事件监听并关闭 socket，不保留待执行回调。
function probeRelay(url: string, onResult: (connected: boolean) => void): () => void {
  const socket = new WebSocket(url, "foxglove.sdk.v1");
  let finished = false;
  const cleanup = (): void => {
    finished = true;
    window.clearTimeout(timer);
    socket.removeEventListener("open", opened);
    socket.removeEventListener("error", failed);
    socket.removeEventListener("close", failed);
    socket.close();
  };
  const finish = (connected: boolean): void => {
    if (finished) return;
    cleanup();
    onResult(connected);
  };
  const opened = (): void => {
    finish(true);
  };
  const failed = (): void => {
    finish(false);
  };
  const timer = window.setTimeout(failed, PREVIEW_CONNECT_TIMEOUT_MS);
  socket.addEventListener("open", opened);
  socket.addEventListener("error", failed);
  socket.addEventListener("close", failed);
  return cleanup;
}
