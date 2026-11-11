// M5-04/09 预览页面：仅人工提交启停，启动成功后握手并嵌入同源查看器。
import { useCallback, useEffect, useRef, useState, type ReactElement } from "react";
import { useQuery } from "@tanstack/react-query";
import { useParams } from "@tanstack/react-router";
import { Alert, Breadcrumb, Button, Card, Descriptions, Flex, Spin, Typography } from "antd";
import { useAccountClient } from "../accounts/runtime";
import { listRobots, type Robot } from "../api/collection";
import {
  listPreviewProfiles,
  submitPreviewJob,
  PREVIEW_PORT,
  type ProfileSummary,
} from "../api/preview";
import { toFailureView } from "../api/problems";
import { DiagnosticCard, JobDiagnosticCard } from "../DiagnosticCard";
import { getJob, JOB_POLL_INTERVAL_MS, type Job } from "../api/jobs";
import { isJobTerminal, jobStatusLabel } from "../jobs/progress";
import { useRegistryAction } from "./shared";
import "./collection.css";

// M5-04 的握手上限为 3 秒；只有可达后才导入布局，规避 Lichtblick #1376。
const PREVIEW_CONNECT_TIMEOUT_MS = 3000;
const RELAY_UNAVAILABLE = "机器人上的预览程序没在运行，先点开启预览";

/**
 * 显示安全来源限制或已登记机器人的实时预览页面。
 * @returns 非安全来源只显示提示；安全来源显示登记信息及连接操作。
 * @throws 无；HTTP 失败显示 DiagnosticCard，握手失败显示工单指定提示。
 * @sideEffects 安全来源读取机器人与 Profile；用户点击后提交启停作业；开启成功或点击连接后预检 WebSocket，再挂载 iframe。
 * @timeSemantics HTTP 请求最多 ACCOUNT_TIMEOUT_MS，作业每秒轮询至终态，握手最多 3 秒；离页关闭预检连接和计时器。
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
  const control = usePreviewJob(robot.robot_id);
  const url = robotPreviewUrl(robot.address);
  const { status, connect, disconnect } = useRelayProbe(url, control.startedJobId);
  function submit(operation: "start" | "stop"): void {
    // 停止先撤下查看器和握手，提交失败也不会继续展示仍连接的 iframe。
    if (operation === "stop") disconnect();
    control.submit(operation);
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
          <Flex gap="small">
            <Button
              type="primary"
              disabled={!url || control.busy}
              loading={control.action.isPending}
              onClick={() => {
                submit("start");
              }}
            >
              开启预览
            </Button>
            <Button
              disabled={control.busy}
              onClick={() => {
                submit("stop");
              }}
            >
              停止预览
            </Button>
            <Button
              autoInsertSpace={false}
              loading={status === "connecting"}
              disabled={!url || control.busy}
              onClick={connect}
            >
              连接
            </Button>
          </Flex>
        </Flex>
      </header>
      <Alert type="info" title="预览要手动开启和停止，平台不会自动开启。正式采集前请先停止预览。" />
      <PreviewJobFeedback control={control} />
      <PreviewFacts robot={robot} profile={profile} url={url} />
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

// 作业查询只在点击后启用，轮询结果与浏览器连接状态分别管理。
function usePreviewJob(robotId: Robot["robot_id"]) {
  const client = useAccountClient();
  const action = useRegistryAction("jobs");
  const [activeJob, setActiveJob] = useState<{ id: string; action: "start" | "stop" } | null>(null);
  const job = useQuery({
    queryKey: ["preview-job", activeJob?.id],
    enabled: activeJob !== null,
    queryFn: ({ signal }) =>
      getJob({ client, signal, payload: undefined, jobId: activeJob?.id ?? "" }),
    retry: false,
    gcTime: 0,
    refetchInterval: (query) =>
      query.state.data && isJobTerminal(query.state.data) ? false : JOB_POLL_INTERVAL_MS,
    refetchOnWindowFocus: (query) => !query.state.data || !isJobTerminal(query.state.data),
  });
  const busy =
    action.isPending ||
    (activeJob !== null && (!job.data || !isJobTerminal(job.data)) && !job.error);
  function submit(operation: "start" | "stop"): void {
    action.mutate(async (signal) => {
      const submitted = await submitPreviewJob({ client, signal, payload: robotId }, operation);
      if (!signal.aborted) setActiveJob({ id: submitted.job_id, action: operation });
    });
  }
  return { job, action, busy, submit, startedJobId: successfulStart(job.data) };
}

function successfulStart(job: Job | undefined): string | null {
  if (job?.type_name !== "robot_preview_start") return null;
  return job.summary?.outcome === "succeeded" || job.summary?.outcome === "succeeded_with_warnings"
    ? job.job_id
    : null;
}

// effect 只建立外部 WebSocket 订阅，状态由异步握手结果更新；同一成功作业只触发一次。
function useRelayProbe(url: string | null, startedJobId: string | null) {
  const cleanupProbe = useRef<(() => void) | null>(null);
  const handledJob = useRef<string | null>(null);
  const [status, setStatus] = useState<"idle" | "connecting" | "connected" | "failed">("idle");
  const open = useCallback((): void => {
    if (!url) return;
    cleanupProbe.current?.();
    cleanupProbe.current = probeRelay(url, (connected) => {
      setStatus(connected ? "connected" : "failed");
    });
  }, [url]);
  useEffect(
    () => () => {
      cleanupProbe.current?.();
    },
    [],
  );
  useEffect(() => {
    if (startedJobId === null || handledJob.current === startedJobId) return;
    handledJob.current = startedJobId;
    open();
  }, [startedJobId, open]);
  function connect(): void {
    setStatus("connecting");
    open();
  }
  function disconnect(): void {
    cleanupProbe.current?.();
    setStatus("idle");
  }
  return { status, connect, disconnect };
}

function PreviewJobFeedback({
  control,
}: {
  control: ReturnType<typeof usePreviewJob>;
}): ReactElement {
  const { action, job } = control;
  return (
    <>
      {action.error && <DiagnosticCard failure={toFailureView(action.error)} />}
      {job.error && <DiagnosticCard failure={toFailureView(job.error)} />}
      {job.data && (
        <Card title={`预览作业 · ${jobStatusLabel(job.data)}`}>
          <Typography.Paragraph>{job.data.progress?.stage_name ?? "排队中"}</Typography.Paragraph>
          <Typography.Link href={`/jobs/${job.data.job_id}`}>
            作业 #{job.data.job_id}
          </Typography.Link>
          <JobDiagnosticCard job={job.data} />
        </Card>
      )}
    </>
  );
}

function PreviewFacts({
  robot,
  profile,
  url,
}: {
  robot: Robot;
  profile: ProfileSummary;
  url: string | null;
}): ReactElement {
  return (
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
  );
}

function robotPreviewUrl(address: Robot["address"]): string | null {
  // 登记契约允许裸 IPv6；URL 的主机部分必须加方括号，不改变登记地址。
  if (!address) return null;
  const host = address.includes(":") ? `[${address}]` : address;
  return `ws://${host}:${String(PREVIEW_PORT)}`;
}

// 构造失败也经异步结果回调报告，生命周期和握手错误一致，离页可取消迟到通知。
function probeRelay(url: string, onResult: (connected: boolean) => void): () => void {
  try {
    return openRelayProbe(url, onResult);
  } catch {
    const timer = window.setTimeout(() => {
      onResult(false);
    }, 0);
    return () => {
      window.clearTimeout(timer);
    };
  }
}

// 原生浏览器边界：超时、错误和离页都移除事件监听并关闭 socket，不保留待执行回调。
function openRelayProbe(url: string, onResult: (connected: boolean) => void): () => void {
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
