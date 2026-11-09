// 清洗事实表：使用报告中的稳定下标，不将最终产物编号当作请求身份。
import type { ReactElement } from "react";
import { Collapse, Space, Switch, Table, Tag, Typography } from "antd";
import type {
  CleaningReport,
  EpisodeIssue,
  EpisodeReport,
  FileReport,
  TopicAlignment,
} from "../api/cleaningTemp";
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
      expandable={{ expandedRowRender: (file) => <TopicTable topics={file.topics} /> }}
      columns={[
        { title: "文件", dataIndex: "path" },
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
          render: (_, file) => (
            <Space orientation="vertical">
              <DiagnosticEntries diagnostics={file.fatal_issues} />
              <DiagnosticEntries diagnostics={file.warnings} />
              {file.topics
                .filter((topic) => topic.image_check === "unchecked_h264")
                .map((topic) => (
                  <Tag key={topic.topic}>{topic.topic}：H.264 画面未检查</Tag>
                ))}
            </Space>
          ),
        },
        {
          title: "处理",
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
              {file.fatal_issues.length > 0 && (
                <Typography.Text type="danger">致命问题，固定剔除</Typography.Text>
              )}
            </Space>
          ),
        },
      ]}
    />
  );
}

function TopicTable({ topics }: { topics: TopicAlignment[] }): ReactElement {
  return (
    <Table<TopicAlignment>
      rowKey="topic"
      dataSource={topics}
      pagination={false}
      size="small"
      columns={[
        { title: "话题", dataIndex: "topic" },
        { title: "容差（ms）", dataIndex: "tolerance_ms" },
        { title: "|Δt| 平均（ms）", render: (_, topic) => topic.mean_abs_dt_ms ?? "未知" },
        { title: "|Δt| 最大（ms）", render: (_, topic) => topic.max_abs_dt_ms ?? "未知" },
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
          title: "产物编号（从 0 开始）",
          render: (_, episode) => props.numbers.get(episodeKey(episode)) ?? "—（剔除）",
        },
        {
          title: "文件",
          render: (_, episode) => files.get(episode.file_index)?.path ?? "未知文件",
        },
        { title: "段下标", dataIndex: "segment_index" },
        { title: "帧数", dataIndex: "frame_count" },
        { title: "时长（秒）", dataIndex: "duration_s" },
        { title: "原始时间跨度（秒）", dataIndex: "stamp_span_s" },
        { title: "开始时间（原始 stamp 秒）", dataIndex: "start_time_s" },
        {
          title: "问题",
          render: (_, episode) => (
            <Space orientation="vertical">
              {episode.issues.map((issue, index) => (
                <Issue key={index} issue={issue} />
              ))}
              {files
                .get(episode.file_index)
                ?.topics.filter((topic) => topic.image_check === "unchecked_h264")
                .map((topic) => (
                  <Tag key={topic.topic}>{topic.topic}：H.264 画面未检查</Tag>
                ))}
            </Space>
          ),
        },
        {
          title: "处理",
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
                <div>首次时间（相对段首秒）：{details.first_time_s ?? "未知"}</div>
                <div>
                  特征：{details.feature ?? "—"}；话题：{details.topic ?? "—"}
                </div>
                <div>
                  区间（相对段首秒，含端点）：
                  {details.ranges
                    .map((range) => `${String(range.start_s)}–${String(range.end_s)}`)
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
