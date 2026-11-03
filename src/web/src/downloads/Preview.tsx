// 预览只显示 worker 的快照；作业失败时沿用统一诊断组件。
import { useEffect, type ReactElement } from "react";
import { Card, Alert, Checkbox, Typography } from "antd";
import { useQuery } from "@tanstack/react-query";
import { useAccountClient } from "../accounts/runtime";
import { getDownloadPreview, type DownloadPreview } from "../api/downloads";
import { getJob, JOB_POLL_INTERVAL_MS, type Job } from "../api/jobs";
import { DiagnosticCard, JobDiagnosticCard } from "../DiagnosticCard";
import { toFailureView } from "../api/problems";
import { isJobTerminal } from "../jobs/progress";

/**
 * 轮询预览作业并展示结果或作业诊断。
 * @param props - 预览作业及当前选择。
 * @param props.jobId - 预览编号，十进制文本。
 * @param props.excluded - 当前不下载的相机。
 * @param props.onChange - 更新排除相机的回调。
 * @param props.onReady - 通知父组件预览已成功。
 * @returns 加载状态、诊断或预览内容。
 * @throws Error 缺少页面客户端提供器。
 * @sideEffects 轮询作业并读取结果，不访问存储根。
 * @timeSemantics 作业终态停止轮询；空间信息仅代表生成时快照。
 */
export function Preview({
  jobId,
  excluded,
  onChange,
  onReady,
}: {
  jobId: string;
  excluded: string[];
  onChange: (cameras: string[]) => void;
  onReady: (ready: boolean) => void;
}): ReactElement {
  const client = useAccountClient();
  const job = useQuery({
    queryKey: ["jobs", "download-preview", jobId],
    queryFn: ({ signal }) => getJob({ client, jobId, payload: undefined, signal }),
    refetchInterval: (query) =>
      query.state.data && isJobTerminal(query.state.data) ? false : JOB_POLL_INTERVAL_MS,
    retry: false,
  });
  const succeeded = previewSucceeded(job.data);
  const result = useQuery({
    queryKey: ["downloads", "preview", jobId],
    queryFn: ({ signal }) => getDownloadPreview(client, jobId, signal),
    enabled: succeeded,
    retry: false,
  });
  // 只在已收到 worker 的结果时允许父页面考虑确认，不在渲染期间改变父组件状态。
  const ready = !!result.data;
  usePreviewReady(onReady, ready);
  if (job.isError) return <DiagnosticCard failure={toFailureView(job.error)} />;
  if (result.isError) return <DiagnosticCard failure={toFailureView(result.error)} />;
  if (result.data)
    return <PreviewContent data={result.data} excluded={excluded} onChange={onChange} />;
  if (job.data && isJobTerminal(job.data))
    return (
      <>
        <Alert type="error" title="预览未成功" />
        <JobDiagnosticCard job={job.data} />
      </>
    );
  return <Typography.Text>正在生成预览…</Typography.Text>;
}

// 仅服务端成功结果可读取预览，不从诊断级别推断成功。
function previewSucceeded(job: Job | undefined): boolean {
  return (
    job?.state === "completed" &&
    (job.summary?.outcome === "succeeded" || job.summary?.outcome === "succeeded_with_warnings")
  );
}

// 结果变化和组件卸载必须收回确认资格。
function usePreviewReady(onReady: (ready: boolean) => void, ready: boolean): void {
  useEffect(() => {
    onReady(ready);
    return () => {
      onReady(false);
    };
  }, [onReady, ready]);
}

function PreviewContent({
  data,
  excluded,
  onChange,
}: {
  data: DownloadPreview;
  excluded: string[];
  onChange: (cameras: string[]) => void;
}): ReactElement {
  return (
    <Card>
      <Typography.Title level={3}>预览结果</Typography.Title>
      <div>版本：{data.commit}</div>
      {data.dataset && (
        <>
          <div>episode：{data.dataset.episodes}</div>
          <div>帧数：{data.dataset.frames}</div>
          <div>FPS：{data.dataset.fps}</div>
          <div>robot_type：{data.dataset.robot_type ?? "未知"}</div>
          <div>
            相机：
            {data.dataset.cameras.map((camera) => (
              <Checkbox
                key={camera}
                checked={!excluded.includes(camera)}
                onChange={(event) => {
                  onChange(
                    event.target.checked
                      ? excluded.filter((item) => item !== camera)
                      : [...excluded, camera],
                  );
                }}
              >
                {camera}
              </Checkbox>
            ))}
          </div>
        </>
      )}
      <div>文件数：{data.file_count}</div>
      <div>筛选后大小：{data.capacity.selected_bytes} B</div>
      <div>已完整下载（续传中的不计）：{data.capacity.complete_bytes} B</div>
      <div>剩余空间：{data.capacity.available_bytes} B</div>
      <div>空间：{data.sufficient ? "足够" : "不足"}</div>
    </Card>
  );
}
