// 清洗事实表：使用报告中的稳定下标，不将最终产物编号当作请求身份。
import type { ReactElement } from "react";
import { Collapse, Space, Switch, Table, Tag, Tooltip, Typography } from "antd";
import type {
  CleaningReport,
  EpisodeIssue,
  EpisodeReport,
  FileReport,
  TopicAlignment,
} from "../api/cleaning";
import { formatNumber } from "./formatNumber";
import { DiagnosticEntries } from "../DiagnosticCard";

interface FileTableProps {
  /** 持久化报告；不在前端重算质量检查。 */ report: CleaningReport;
  /** 当前剔除的文件下标，含所有致命文件。 */ excludedFiles: Set<number>;
  /** 修改非致命文件选择，参数为报告下标。 */ toggleFile: (index: number) => void;
}
/**
 * 展示文件质量与可展开的话题对齐统计。
 * @param props - 报告事实及当前文件选择。
 * @returns 文件表；致命文件固定剔除并直接显示诊断原因。
 * @throws 无。
 * @sideEffects 用户切换调用选择回调，不发请求、不持久化。
 * @timeSemantics 同步展示；对齐时间差单位为毫秒，空统计保持未知。
 */
export function FileTable(props: FileTableProps): ReactElement {
  return (
    <Table<FileReport>
      rowKey="file_index"
      dataSource={props.report.files}
      pagination={false}
      scroll={{ x: "max-content" }}
      expandable={{ expandedRowRender: (file) => <FileDetails file={file} /> }}
      columns={[
        {
          title: "处理",
          fixed: "left",
          render: (_, file) => (
            <Space orientation="vertical">
              <Switch
                aria-label={`文件 ${file.path} 保留`}
                checked={!props.excludedFiles.has(file.file_index)}
                checkedChildren="保留"
                unCheckedChildren="剔除"
                disabled={file.fatal_issues.length > 0}
                onChange={() => {
                  props.toggleFile(file.file_index);
                }}
              />
            </Space>
          ),
        },
        { title: "文件", render: (_, file) => <FileName path={file.path} /> },
        {
          title: "保留帧 / 基准帧",
          render: (_, file) => `${String(file.kept_frames)} / ${String(file.reference_frames)}`,
        },
        {
          title: "episode 数",
          render: (_, file) =>
            props.report.episodes.filter((episode) => episode.file_index === file.file_index)
              .length,
        },
        { title: "坏帧", dataIndex: "bad_frames" },
        { title: "断点", dataIndex: "gaps" },
        {
          title: "过短丢弃",
          render: (_, file) =>
            `${String(file.short_segments)} 段 / ${String(file.short_frames)} 帧`,
        },
        {
          title: "致命问题和警告",
          render: (_, file) => <FileIssues file={file} />,
        },
      ]}
    />
  );
}

// 可见列只放文件名；完整路径通过 antd 悬停提示提供，避免路径决定表格最小宽度。
function FileName({ path }: { path: string | undefined }): ReactElement {
  if (!path) return <>未知文件</>;
  return (
    <Tooltip title={path}>
      <Typography.Text className="cleaning-file-name" ellipsis>
        {path.split("/").at(-1) || path}
      </Typography.Text>
    </Tooltip>
  );
}

function FileIssues({ file }: { file: FileReport }): ReactElement {
  const primary = file.fatal_issues[0] ?? file.warnings[0];
  return (
    <Space orientation="vertical" className="cleaning-issues">
      <Space wrap>
        <Tag color="red">致命 {file.fatal_issues.length}</Tag>
        <Tag color="orange">警告 {file.warnings.length}</Tag>
      </Space>
      {primary && (
        <Typography.Text type={file.fatal_issues.length ? "danger" : undefined}>
          实际：{primary.actual}
        </Typography.Text>
      )}
      {file.fatal_issues.length > 0 && (
        <Typography.Text type="danger" strong>
          该文件已固定剔除
        </Typography.Text>
      )}
    </Space>
  );
}

// 五段诊断保留完整内容，按需展开；与对齐统计一起使用卡片内可收缩的网格。
function FileDetails({ file }: { file: FileReport }): ReactElement {
  return (
    <div className="cleaning-file-details">
      <Typography.Title level={5}>致命问题与警告明细</Typography.Title>
      <DiagnosticEntries diagnostics={file.fatal_issues} />
      <DiagnosticEntries diagnostics={file.warnings} />
      <Typography.Title level={5}>话题对齐统计</Typography.Title>
      <TopicTable topics={file.topics} />
    </div>
  );
}

function TopicTable({ topics }: { topics: TopicAlignment[] }): ReactElement {
  return (
    <Table<TopicAlignment>
      rowKey="topic"
      dataSource={topics}
      pagination={false}
      size="small"
      scroll={{ x: "max-content" }}
      columns={[
        { title: "话题", dataIndex: "topic" },
        { title: "容差", render: (_, topic) => formatNumber(topic.tolerance_ms, "milliseconds") },
        {
          title: "|Δt| 平均",
          render: (_, topic) => formatNumber(topic.mean_abs_dt_ms, "milliseconds"),
        },
        {
          title: "|Δt| 最大",
          render: (_, topic) => formatNumber(topic.max_abs_dt_ms, "milliseconds"),
        },
        { title: "复用帧", dataIndex: "reused_frames" },
        { title: "坏帧", dataIndex: "bad_frames" },
        {
          title: "可选缺失",
          render: (_, topic) => (topic.missing_optional ? "是（使用填充值）" : "否"),
        },
        {
          title: "画面检查",
          render: (_, topic) =>
            topic.image_check === "unchecked_h264"
              ? "H.264 画面未检查"
              : topic.image_check === "sampled"
                ? "已抽样检查"
                : "不适用",
        },
        { title: "说明", render: (_, topic) => topic.image_check_note ?? "—" },
      ]}
    />
  );
}

interface EpisodeTableProps extends FileTableProps {
  /** 当前剔除段的稳定键，形式为文件下标:段下标。 */ excludedEpisodes: Set<string>;
  /** 最终产物编号，从零开始；已剔除项没有编号。 */ numbers: Map<string, number>;
  /** 只显示存在质量问题的段，不影响选择和编号。 */ onlyIssues: boolean;
  /** 切换段的稳定身份。 */ toggleEpisode: (key: string) => void;
}
/**
 * 展示随选择变化的 episode 编号、时间及问题明细。
 * @param props - 报告、选择、当前连续编号及筛选状态。
 * @returns 段表；被剔除文件的段灰显且不能切换。
 * @throws 无。
 * @sideEffects 用户修改段选择时调用回调，不改变原始报告。
 * @timeSemantics 时长取恒定帧率 duration_s；原始 stamp 跨度单独标明，问题时间相对段首。
 */
export function EpisodeTable(props: EpisodeTableProps): ReactElement {
  const files = new Map(props.report.files.map((file) => [file.file_index, file]));
  return (
    <Table<EpisodeReport>
      rowKey={(episode) => episodeKey(episode)}
      dataSource={props.report.episodes.filter(
        (episode) => !props.onlyIssues || episode.issues.length > 0,
      )}
      pagination={false}
      scroll={{ x: "max-content" }}
      rowClassName={(episode) =>
        props.excludedFiles.has(episode.file_index) ? "cleaning-excluded-file" : ""
      }
      columns={[
        {
          title: "处理",
          fixed: "left",
          render: (_, episode) => (
            <Space orientation="vertical">
              <Switch
                aria-label={`文件 ${String(episode.file_index)} 段 ${String(episode.segment_index)} 保留`}
                checked={
                  !props.excludedFiles.has(episode.file_index) &&
                  !props.excludedEpisodes.has(episodeKey(episode))
                }
                disabled={props.excludedFiles.has(episode.file_index)}
                checkedChildren="保留"
                unCheckedChildren="剔除"
                onChange={() => {
                  props.toggleEpisode(episodeKey(episode));
                }}
              />
              {props.excludedFiles.has(episode.file_index) && (
                <Typography.Text type="secondary">所属文件已剔除</Typography.Text>
              )}
            </Space>
          ),
        },
        {
          title: "产物编号（从 0 开始）",
          render: (_, episode) => props.numbers.get(episodeKey(episode)) ?? "—（剔除）",
        },
        {
          title: "文件",
          render: (_, episode) => <FileName path={files.get(episode.file_index)?.path} />,
        },
        { title: "段下标", dataIndex: "segment_index" },
        { title: "帧数", dataIndex: "frame_count" },
        { title: "时长", render: (_, episode) => formatNumber(episode.duration_s, "seconds") },
        {
          title: "原始时间跨度",
          render: (_, episode) => formatNumber(episode.stamp_span_s, "span"),
        },
        {
          title: "开始时间（原始 stamp）",
          render: (_, episode) => formatNumber(episode.start_time_s, "seconds"),
        },
        {
          title: "问题",
          render: (_, episode) => (
            <Space orientation="vertical" className="cleaning-issues">
              {episode.issues.map((issue, index) => (
                <Issue key={index} issue={issue} />
              ))}
              {files
                .get(episode.file_index)
                ?.topics.filter((topic) => topic.image_check === "unchecked_h264")
                .map((topic) => (
                  <Tag className="cleaning-topic-note" key={topic.topic}>
                    {topic.topic}：H.264 画面未检查
                  </Tag>
                ))}
            </Space>
          ),
        },
      ]}
    />
  );
}

function Issue({ issue }: { issue: EpisodeIssue }): ReactElement {
  const details = issue.details;
  return (
    <div>
      <Tag color={issue.severity === "severe" ? "red" : "orange"}>
        {issue.severity === "severe" ? "严重" : "提示"} · {issue.check}
      </Tag>
      <Typography.Paragraph>{issue.message}</Typography.Paragraph>
      <Collapse
        items={[
          {
            key: "details",
            label: "问题明细",
            children: (
              <>
                <div>次数：{details.count}</div>
                <div>首次时间（相对段首秒）：{formatNumber(details.first_time_s, "seconds")}</div>
                <div>
                  特征：{details.feature ?? "—"}；话题：{details.topic ?? "—"}
                </div>
                <div>
                  区间（相对段首秒，含端点）：
                  {details.ranges
                    .map(
                      (range) =>
                        `${formatNumber(range.start_s, "seconds")}–${formatNumber(range.end_s, "seconds")}`,
                    )
                    .join("、") || "无"}
                </div>
                <DiagnosticEntries diagnostics={[issue.diagnostic]} />
              </>
            ),
          },
        ]}
      />
    </div>
  );
}

/**
 * 为段生成与显示编号无关的选择键。
 * @param episode - 报告中的文件和段下标，均为从零开始的整数。
 * @returns 无碰撞的文件下标:段下标文本。
 * @throws 无。
 * @sideEffects 无。
 * @timeSemantics 同步；剔除其他文件或段不会改变身份。
 */
export function episodeKey(episode: EpisodeReport): string {
  return `${String(episode.file_index)}:${String(episode.segment_index)}`;
}
