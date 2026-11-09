// 清洗报告页（M4.5-04）：展示持久化事实，选择仅在本次页面内存中存在；不重跑检查算法。
import { useState, type ReactElement } from "react";
import { useQuery } from "@tanstack/react-query";
import { getRouteApi, Link } from "@tanstack/react-router";
import { Alert, Breadcrumb, Card, Checkbox, Collapse, Descriptions, Typography } from "antd";
import type { CleaningPreview, CleaningReport } from "../api/cleaningTemp";
import { getCleaningPreview } from "../api/cleaning";
import { useAccountClient, useCurrentAccount } from "../accounts/runtime";
import { DiagnosticCard, DiagnosticEntries } from "../DiagnosticCard";
import { toFailureView } from "../api/problems";
import { ConvertFromReport } from "./Convert";
import { EpisodeTable, FileTable, episodeKey } from "./Tables";
import "./cleaning.css";

const route = getRouteApi("/cleaning/$jobId");
// 报告是持久化快照；进入时重新读取，离页清理，单位毫秒。不后台刷新以免覆盖用户选择。
const REPORT_STALE_TIME_MS = 0;
const REPORT_GC_TIME_MS = 0;

/**
 * 读取并显示一个清洗预览报告。
 * @returns 报告、规则说明、选择表和底部转换区域；404 明确表示没有报告。
 * @throws 无；接口失败使用统一诊断组件。
 * @sideEffects 按账号和路由编号读取报告；问题筛选写入类型化 URL，选择不持久化。
 * @timeSemantics 生成时间转浏览器本地显示；进入重新请求、离页取消，不轮询、不自动重试。
 */
export function CleaningReportPage(): ReactElement {
  const { jobId } = route.useParams();
  const client = useAccountClient();
  const identity = useCurrentAccount();
  const query = useQuery({
    queryKey: ["cleaning-report", identity.data?.account_id, jobId],
    enabled: !!identity.data && !identity.data.must_change_password,
    queryFn: ({ signal }) => getCleaningPreview({ client, signal, payload: jobId }),
    staleTime: REPORT_STALE_TIME_MS,
    gcTime: REPORT_GC_TIME_MS,
    retry: false,
    refetchOnWindowFocus: false,
    refetchOnReconnect: false,
  });
  if (query.error) {
    const failure = toFailureView(query.error);
    return (
      <>
        {failure.kind === "problem" && failure.problem.status === 404 && (
          <Alert type="info" title="没有清洗报告" />
        )}
        <DiagnosticCard failure={failure} />
      </>
    );
  }
  if (!query.data) return <Typography.Text>正在读取清洗报告…</Typography.Text>;
  return (
    <Report
      key={`${identity.data?.account_id ?? ""}:${jobId}`}
      preview={query.data}
      jobId={jobId}
    />
  );
}

function Report({ preview, jobId }: { preview: CleaningPreview; jobId: string }): ReactElement {
  const report = preview.report;
  const [excludedFiles, setExcludedFiles] = useState(
    () =>
      new Set(
        report.files
          .filter((file) => file.default_excluded || file.fatal_issues.length > 0)
          .map((file) => file.file_index),
      ),
  );
  const [excludedEpisodes, setExcludedEpisodes] = useState(
    () =>
      new Set(
        report.episodes.filter((episode) => episode.default_action === "exclude").map(episodeKey),
      ),
  );
  const search = route.useSearch();
  const navigate = route.useNavigate();
  // 始终按报告顺序计算最终产物编号；过滤表格不能影响编号或请求身份。
  const activeEpisodes = report.episodes.filter(
    (episode) => !excludedFiles.has(episode.file_index),
  );
  const keptEpisodes = activeEpisodes.filter(
    (episode) => !excludedEpisodes.has(episodeKey(episode)),
  );
  const numbers = new Map(keptEpisodes.map((episode, index) => [episodeKey(episode), index]));
  const fileCount = report.files.filter((file) => !excludedFiles.has(file.file_index)).length;
  const toggleFile = (index: number) => {
    if (report.files.find((file) => file.file_index === index)?.fatal_issues.length) return;
    setExcludedFiles((previous) => toggled(previous, index));
  };
  return (
    <section className="cleaning-page">
      <header className="app-page-header">
        <Breadcrumb
          items={[
            { title: "数据" },
            {
              title: (
                <Link to="/jobs/$jobId" params={{ jobId }}>
                  预览作业 #{jobId}
                </Link>
              ),
            },
            { title: "清洗报告" },
          ]}
        />
        <Typography.Title level={2} className="app-page-title">
          清洗报告 #{jobId}
        </Typography.Title>
      </header>
      <Card title="报告概要">
        <Descriptions
          items={[
            { key: "dataset", label: "数据集", children: preview.dataset_id },
            { key: "tool", label: "工具", children: preview.tool_name },
            { key: "model", label: "型号", children: preview.robot_model },
            {
              key: "time",
              label: "生成时间",
              children: new Date(preview.created_at).toLocaleString(),
            },
            {
              key: "files",
              label: "文件数 / 默认剔除",
              children: `${String(report.summary.files)} / ${String(report.summary.excluded_files)}`,
            },
            {
              key: "episodes",
              label: "episode 数 / 默认剔除",
              children: `${String(report.summary.episodes)} / ${String(report.summary.excluded_episodes)}`,
            },
            {
              key: "frames",
              label: "对齐保留帧 / 基准帧",
              children: `${String(report.summary.kept_frames)} / ${String(report.summary.reference_frames)}`,
            },
          ]}
        />
        <DiagnosticEntries diagnostics={report.warnings} />
      </Card>
      <Collapse
        items={[{ key: "rules", label: "规则说明", children: <Rules report={report} /> }]}
      />
      <Card title="文件">
        <FileTable report={report} excludedFiles={excludedFiles} toggleFile={toggleFile} />
      </Card>
      <Card title="episode">
        <Checkbox
          checked={search.onlyIssues}
          onChange={(event) => {
            void navigate({ search: { onlyIssues: event.target.checked }, replace: true });
          }}
        >
          只看有问题的 episode
        </Checkbox>
        <Typography.Paragraph>
          当前保留：{fileCount} 个文件，{keptEpisodes.length} 个 episode，
          {keptEpisodes.reduce((sum, episode) => sum + episode.frame_count, 0)} 帧
        </Typography.Paragraph>
        <EpisodeTable
          report={report}
          excludedFiles={excludedFiles}
          toggleFile={toggleFile}
          excludedEpisodes={excludedEpisodes}
          numbers={numbers}
          onlyIssues={search.onlyIssues}
          toggleEpisode={(key) => {
            setExcludedEpisodes((previous) => toggled(previous, key));
          }}
        />
      </Card>
      <Card title="进行转换">
        <ConvertFromReport
          preview={preview}
          jobId={jobId}
          excludedFiles={report.files
            .filter((file) => excludedFiles.has(file.file_index))
            .map((file) => file.file_index)}
          excludedEpisodes={activeEpisodes
            .filter((episode) => excludedEpisodes.has(episodeKey(episode)))
            .map(({ file_index, segment_index }) => ({ file_index, segment_index }))}
          fileCount={fileCount}
          episodeCount={keptEpisodes.length}
        />
      </Card>
    </section>
  );
}

function toggled<T>(previous: Set<T>, key: T): Set<T> {
  const next = new Set(previous);
  if (next.has(key)) next.delete(key);
  else next.add(key);
  return next;
}

function Rules({ report }: { report: CleaningReport }): ReactElement {
  return (
    <>
      <Descriptions
        items={[
          { key: "reference", label: "基准话题", children: report.reference_topic },
          { key: "fps", label: "帧率", children: `${String(report.fps)} 帧/秒` },
          { key: "config", label: "配置指纹", children: report.tool_config_sha256 },
          { key: "rules", label: "规则指纹", children: report.rules_sha256 },
        ]}
      />
      <Typography.Paragraph>
        逐话题容差见文件展开项。默认容差、断点阈值、最短段和数值检查阈值：报告未提供。
      </Typography.Paragraph>
      <Typography.Paragraph>
        数值检查以 episode
        中的检查项、说明和明细为准：严重问题默认剔除，提示默认保留；可以逐段修改。H.264
        话题画面未检查。
      </Typography.Paragraph>
    </>
  );
}
