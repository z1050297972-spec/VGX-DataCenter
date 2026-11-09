// 报告规则说明只展示生成时的规则快照；不读取工具当前配置，不在前端维护默认阈值或严重检查列表。
import type { ReactElement } from "react";
import { Descriptions, Table, Tag, Typography } from "antd";
import type { CleaningReport, CleaningSourceRules } from "../api/cleaning";

interface Props {
  /** 持久化报告；规则数值、单位和严重检查项以生成类型描述为准。 */
  report: CleaningReport;
}

/**
 * 展示清洗预览实际使用的对齐和质量检查规则。
 * @param props - 含 sync、checks 及来源阈值的报告快照。
 * @returns 对齐参数、质量检查阈值、严重检查列表和逐来源阈值表。
 * @throws 无。
 * @sideEffects 只渲染文本，不改报告、选择或 URL，不发请求。
 * @timeSemantics 时间阈值按字段单位显示；断点毫秒值直接使用报告，避免前端重新计算漂移。
 */
export function ReportRules(props: Props): ReactElement {
  const { report } = props;
  const { sync, checks } = report.rules;
  return (
    <>
      <Typography.Title level={4}>对齐规则</Typography.Title>
      <Descriptions
        items={[
          { key: "reference", label: "基准话题", children: report.reference_topic },
          { key: "fps", label: "帧率", children: <>{report.fps} 帧/秒</> },
          { key: "tolerance", label: "默认容差", children: <>{sync.default_tolerance_ms} 毫秒</> },
          {
            key: "gap",
            label: "断点（相邻基准帧间隔超过）",
            children: (
              <>
                {sync.max_frame_gap} 倍 / {sync.max_frame_gap_ms} 毫秒
              </>
            ),
          },
          { key: "minimum", label: "最短段", children: <>{sync.min_episode_frames} 帧</> },
          { key: "config", label: "配置指纹", children: report.tool_config_sha256 },
          { key: "rules", label: "规则指纹", children: report.rules_sha256 },
        ]}
      />
      <Typography.Paragraph>各话题实际使用的容差见文件展开项。</Typography.Paragraph>
      <Typography.Title level={4}>数值和画面检查规则</Typography.Title>
      <Descriptions
        items={[
          { key: "static-feature", label: "静止检查特征", children: checks.static_feature },
          {
            key: "static-duration",
            label: "连续静止最短时长",
            children: <>{checks.long_static_s} 秒</>,
          },
          { key: "jump-feature", label: "跳变检查特征", children: checks.jump_feature },
          { key: "frozen", label: "相机冻结最短时长", children: <>{checks.frozen_s} 秒</> },
          { key: "sample", label: "亮度抽样间隔", children: <>{checks.sample_interval_s} 秒</> },
          { key: "dark", label: "黑屏阈值", children: <>平均亮度 &lt; {checks.dark_below}</> },
          { key: "bright", label: "过曝阈值", children: <>平均亮度 &gt; {checks.bright_above}</> },
          {
            key: "severe",
            label: "严重检查（默认剔除）",
            children: checks.severe_checks.length
              ? checks.severe_checks.map((check) => (
                  <Tag key={check} color="red">
                    {check}
                  </Tag>
                ))
              : "无",
          },
        ]}
      />
      <Typography.Paragraph>
        严重检查项取自本报告；其他检查作为提示。段的初始处理以报告默认选择为准，可以手动修改。H.264
        话题画面未检查。
      </Typography.Paragraph>
      <Typography.Title level={4}>每个来源的阈值</Typography.Title>
      <Typography.Paragraph>
        静止、跳变阈值及限位的单位与来源数值一致；未配置的阈值不参与相应检查。
      </Typography.Paragraph>
      <Table<CleaningSourceRules>
        rowKey="topic"
        dataSource={checks.sources}
        pagination={false}
        size="small"
        scroll={{ x: "max-content" }}
        locale={{ emptyText: "没有配置来源阈值" }}
        columns={[
          { title: "来源话题", dataIndex: "topic" },
          { title: "静止阈值", render: (_, source) => source.static_threshold ?? "不检查" },
          { title: "跳变阈值", render: (_, source) => source.jump_threshold ?? "不检查" },
          {
            title: "逐维限位（下限，上限）",
            render: (_, source) =>
              source.limits
                ?.map(
                  ([lower, upper], index) =>
                    `第 ${String(index + 1)} 维：[${String(lower)}, ${String(upper)}]`,
                )
                .join("；") || "未配置",
          },
        ]}
      />
    </>
  );
}
