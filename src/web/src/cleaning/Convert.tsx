// 报告底部转换表单：先确认当前选择，再经已有作业 action 提交；不直接提交工具转换。
import { useState, type ReactElement } from "react";
import { Alert, Button, Form, InputNumber, Modal, Select, Typography } from "antd";
import type { CleaningConversionInput, ExcludedEpisode } from "../api/cleaningTemp";
import type { CleaningPreview } from "../api/cleaning";
import type { ToolSummary } from "../api/tools";
import { convertFromCleaningPreview } from "../api/conversion";
import { useAccountClient, useCurrentAccount } from "../accounts/runtime";
import { useJobAction } from "../jobs/_actions";
import { useTools } from "../tools/queries";
import { DiagnosticCard } from "../DiagnosticCard";
import { toFailureView } from "../api/problems";

interface Props {
  /** 当前报告快照；编号由路由原文传递，避免数值转换丢精度。 */ preview: CleaningPreview;
  /** 预览作业编号文本。 */ jobId: string;
  /** 当前文件剔除列表，含固定剔除文件。 */ excludedFiles: number[];
  /** 仅包含未剔除文件内的段选择。 */ excludedEpisodes: ExcludedEpisode[];
  /** 交给工具的文件数，非负整数。 */ fileCount: number;
  /** 最终保留的 episode 数，非负整数。 */ episodeCount: number;
}
// 工单约定空间默认值；百分比、GiB 单位与已有转换参数保持一致。
const DEFAULT_SPACE_RATIO_PERCENT = 25;
const DEFAULT_SPACE_RESERVE_GIB = 1;
type FormValues = Pick<
  CleaningConversionInput,
  "output_format" | "space_ratio_percent" | "space_reserve_gib"
>;

/**
 * 为管理员提供报告转换表单和确认框。
 * @param props - 当前报告、剔除身份和保留计数。
 * @returns 转换表单；成员只看到权限说明，空产物禁用提交。
 * @throws 无；请求错误交 DiagnosticCard。
 * @sideEffects 读取工具版本，确认后提交转换并导航作业详情；不保存选择。
 * @timeSemantics 请求至多 10 秒，无自动重试；离页取消提交。
 */
export function ConvertFromReport(props: Props): ReactElement {
  const identity = useCurrentAccount();
  return identity.data?.role === "administrator" ? (
    <ConversionForm {...props} />
  ) : (
    <Typography.Text type="secondary">只有管理员可以进行转换。</Typography.Text>
  );
}

function ConversionForm(props: Props): ReactElement {
  const tools = useTools();
  if (tools.error) return <DiagnosticCard failure={toFailureView(tools.error)} />;
  if (!tools.data) return <Typography.Text>正在读取工具版本…</Typography.Text>;
  const tool = tools.data.items.find((item) => item.name === props.preview.tool_name);
  if (!tool) return <Alert type="warning" title="报告使用的工具尚未登记，无法转换。" />;
  return <ReadyConversionForm {...props} tool={tool} />;
}

function ReadyConversionForm(
  props: Props & { /** 当前登记工具，只取输出版本及可用状态。 */ tool: ToolSummary },
): ReactElement {
  const client = useAccountClient();
  const tool = props.tool;
  const [form] = Form.useForm<FormValues>();
  const [pending, setPending] = useState<CleaningConversionInput | null>(null);
  const submit = useJobAction(
    (parameters: CleaningConversionInput, signal) =>
      convertFromCleaningPreview({ client, signal, payload: { jobId: props.jobId, parameters } }),
    true,
  );
  const reason =
    props.fileCount === 0
      ? "没有保留的文件，无法转换。"
      : props.episodeCount === 0
        ? "没有保留的 episode，无法转换。"
        : null;
  const hasExclusions = props.excludedFiles.length > 0 || props.excludedEpisodes.length > 0;
  return (
    <>
      <Typography.Paragraph>空间检查按输入大小的百分比加偏置估算。</Typography.Paragraph>
      {hasExclusions && <Alert type="info" title="产物按两倍估算" />}
      <Typography.Paragraph>
        将把 {props.fileCount} 个文件交给工具，转换后剔除 {props.excludedEpisodes.length} 个
        episode，产出清洗后的 LeRobot 数据集
      </Typography.Paragraph>
      {reason && <Alert type="warning" title={reason} />}
      <Form
        form={form}
        layout="vertical"
        initialValues={{
          output_format: tool.output_versions[0],
          space_ratio_percent: DEFAULT_SPACE_RATIO_PERCENT,
          space_reserve_gib: DEFAULT_SPACE_RESERVE_GIB,
        }}
        onFinish={(values) => {
          if (reason) return;
          setPending({
            ...values,
            output_format: values.output_format,
            excluded_files: props.excludedFiles,
            excluded_episodes: props.excludedEpisodes,
          });
        }}
      >
        <Form.Item label="输出版本" name="output_format">
          <Select
            aria-label="输出版本"
            placeholder="请选择输出版本"
            options={tool.output_versions.map((value) => ({ value, label: value }))}
          />
        </Form.Item>
        {/* 空间参数范围沿用现有转换契约，偏置允许小数 GiB。 */}
        <Form.Item
          label="百分比（%）"
          name="space_ratio_percent"
          rules={[{ required: true, type: "integer", min: 0, max: 1000 }]}
        >
          <InputNumber min={0} max={1000} precision={0} />
        </Form.Item>
        <Form.Item
          label="偏置（GiB）"
          name="space_reserve_gib"
          rules={[{ required: true, type: "number", min: 0, max: 1024 }]}
        >
          <InputNumber min={0} max={1024} />
        </Form.Item>
        {submit.error && <DiagnosticCard failure={toFailureView(submit.error)} />}
        <Button type="primary" htmlType="submit" disabled={!!reason} loading={submit.isPending}>
          进行转换
        </Button>
      </Form>
      <Modal
        title="确认进行转换"
        open={pending !== null}
        okText="确认转换"
        cancelText="取消"
        confirmLoading={submit.isPending}
        onCancel={() => {
          if (!submit.isPending) setPending(null);
        }}
        onOk={() => {
          if (pending && !reason) {
            submit.mutate(pending);
            setPending(null);
          }
        }}
      >
        <Typography.Paragraph>
          将把 {props.fileCount} 个文件交给工具，转换后剔除 {props.excludedEpisodes.length} 个
          episode，产出清洗后的 LeRobot 数据集。
        </Typography.Paragraph>
      </Modal>
    </>
  );
}
