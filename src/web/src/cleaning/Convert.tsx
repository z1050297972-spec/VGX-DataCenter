// 报告底部转换表单：先确认当前选择，再经已有作业 action 提交；不直接提交工具转换。
import { useState, type ReactElement } from "react";
import { Alert, Button, Form, InputNumber, Modal, Select, Typography } from "antd";
import type { CleaningConversionInput, ExcludedEpisode } from "../api/conversion";
import type { CleaningPreview } from "../api/cleaning";
import type { ToolSummary } from "../api/tools";
import { convertFromCleaningPreview } from "../api/conversion";
import { useAccountClient, useCurrentAccount } from "../accounts/runtime";
import { useJobAction } from "../jobs/_actions";
import { useConversionDestinations } from "../storage/queries";
import { useTools } from "../tools/queries";
import { DiagnosticCard } from "../DiagnosticCard";
import { toFailureView } from "../api/problems";

interface Props {
  /** 当前报告快照；编号由路由原文传递，避免数值转换丢精度。 */ preview: CleaningPreview;
  /** 预览作业编号文本。 */ jobId: string;
  /** 当前文件剔除列表，含固定剔除文件。 */ excludedFiles: number[];
  /** 仅包含未剔除文件内的段选择；AgiBot 提交时固定为空数组。 */ excludedEpisodes: ExcludedEpisode[];
  /** 交给工具的文件数，非负整数。 */ fileCount: number;
  /** 最终保留的 episode 数，非负整数。 */ episodeCount: number;
}
// 预留偏置沿用 M4.5 的 1 GiB，百分比由当前工具清单提供。
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
 * @sideEffects 读取工具版本与挂载快照，确认后保存输出根选择并导航作业详情。
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
  const destinations = useConversionDestinations(props.jobId);
  if (tools.error) return <DiagnosticCard failure={toFailureView(tools.error)} />;
  if (!tools.data) return <Typography.Text>正在读取工具版本…</Typography.Text>;
  const tool = tools.data.items.find((item) => item.name === props.preview.tool_name);
  if (!tool) return <Alert type="warning" title="报告使用的工具尚未登记，无法转换。" />;
  if (!destinations.data)
    return destinations.error ? (
      <DiagnosticCard failure={toFailureView(destinations.error)} />
    ) : (
      <Typography.Text>正在核对输出存储根…</Typography.Text>
    );
  return <ReadyConversionForm {...props} tool={tool} destinations={destinations} />;
}

function ReadyConversionForm(
  props: Props & {
    /** 当前登记工具，提供输出版本和默认空间百分比。 */ tool: ToolSummary;
    /** 挂载检查快照，刷新失败也保留已选根，不自动替换。 */ destinations: ReturnType<
      typeof useConversionDestinations
    >;
  },
): ReactElement {
  const client = useAccountClient();
  const tool = props.tool;
  const destinations = props.destinations;
  const destination = useDestination(destinations);
  const { outputRoot, selected, storageReason } = destination;
  const native = props.preview.report.source_format === "agibot_native";
  const remux = props.preview.report.source_format !== "mcap";
  const [form] = Form.useForm<FormValues>();
  const [pending, setPending] = useState<CleaningConversionInput | null>(null);
  const submit = useJobAction(
    (parameters: CleaningConversionInput, signal) =>
      convertFromCleaningPreview({ client, signal, payload: { jobId: props.jobId, parameters } }),
    true,
  );
  const reason =
    storageReason ??
    (props.fileCount === 0
      ? "没有保留的文件，无法转换。"
      : props.episodeCount === 0
        ? "没有保留的 episode，无法转换。"
        : null);
  const hasExclusions = props.excludedFiles.length > 0 || props.excludedEpisodes.length > 0;
  const confirmation = remux
    ? `将只转换保留的 ${String(props.episodeCount)} 个 Episode，视频不重新编码，产出清洗后的 LeRobot 数据集`
    : `将把 ${String(props.fileCount)} 个文件交给工具，转换后剔除 ${String(props.excludedEpisodes.length)} 个 episode，产出清洗后的 LeRobot 数据集`;
  return (
    <>
      <Typography.Paragraph>
        空间检查按输入大小的百分比加偏置估算，不保证转换途中空间足够。
      </Typography.Paragraph>
      {!remux && hasExclusions && <Alert type="info" title="产物按两倍估算" />}
      <Typography.Paragraph>{confirmation}</Typography.Paragraph>
      {reason && <Alert type="warning" title={reason} />}
      <Form
        form={form}
        layout="vertical"
        initialValues={{
          output_format: tool.output_versions[0],
          space_ratio_percent: tool.default_space_ratio_percent,
          space_reserve_gib: DEFAULT_SPACE_RESERVE_GIB,
        }}
        onFinish={(values) => {
          if (reason) return;
          setPending({
            ...values,
            output_root: outputRoot,
            output_format: values.output_format,
            excluded_files: props.excludedFiles,
            // AgiBot 一集一文件，绝不能走转换后删段、重新编码的视频流程。
            excluded_episodes: native ? [] : props.excludedEpisodes,
          });
        }}
      >
        <DestinationFields
          query={destinations}
          destination={destination}
          onChange={(value) => {
            destination.setOutputRoot(value);
            setPending(null);
          }}
        />
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
        okButtonProps={{ disabled: !!reason }}
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
        <Typography.Paragraph>{confirmation}。</Typography.Paragraph>
        <SelectedDestination selected={selected} />
      </Modal>
    </>
  );
}

type DestinationQuery = ReturnType<typeof useConversionDestinations>;
type Destination = NonNullable<DestinationQuery["data"]>["items"][number];

// 仅首次装载选默认；后续刷新失效仍保留原名称，要求用户主动重选。
function useDestination(query: DestinationQuery) {
  const [outputRoot, setOutputRoot] = useState<string | undefined>(
    () => query.data?.items.find((item) => item.writable && item.online)?.name,
  );
  const selected = query.data?.items.find((item) => item.name === outputRoot);
  return { outputRoot, setOutputRoot, selected, storageReason: storageReason(query, selected) };
}

function storageReason(query: DestinationQuery, selected: Destination | undefined): string | null {
  if (query.isFetching) return "正在重新核对挂载，暂不能提交。";
  if (query.error) return "输出存储根获取失败，请重新检查。";
  if (!query.data?.items.some((item) => item.online && item.writable))
    return "没有在线且可写的输出存储根，无法转换。";
  if (!selected?.online || !selected.writable) return "已选存储根不可用，请重新选择输出存储根。";
  return null;
}

function DestinationFields({
  query: destinations,
  destination,
  onChange,
}: {
  /** 当前请求，刷新失败不允许使用旧快照提交。 */ query: DestinationQuery;
  /** 当前选择与对应快照。 */ destination: ReturnType<typeof useDestination>;
  /** 用户主动选择时清除旧确认状态。 */ onChange: (value: string) => void;
}): ReactElement {
  const { outputRoot, selected } = destination;
  return (
    <>
      <Form.Item label="输出存储根" required>
        <Select
          aria-label="输出存储根"
          value={outputRoot}
          onChange={onChange}
          options={destinations.data?.items.map((item) => ({
            value: item.name,
            label: `${item.name} · ${item.path}${!item.writable ? "（只读）" : ""}${!item.online ? `（离线：${item.reason ?? "未知"}）` : ""}`,
            disabled: !item.online || !item.writable,
          }))}
        />
      </Form.Item>
      <Button
        onClick={() => {
          void destinations.refetch();
        }}
        loading={destinations.isFetching}
      >
        重新检查挂载
      </Button>
      {destinations.error && <DiagnosticCard failure={toFailureView(destinations.error)} />}
      {selected && (
        <>
          <Typography.Paragraph>
            预计入库位置，重名或入库确认时可能调整，未预留：{selected.expected_output_path}
          </Typography.Paragraph>
          <Typography.Paragraph>
            暂存目录规则，作业编号提交后产生：{selected.staging_template}
          </Typography.Paragraph>
          <Typography.Paragraph>
            挂载核对时刻：{new Date(selected.checked_at).toLocaleString()}
          </Typography.Paragraph>
        </>
      )}
      <Typography.Paragraph>
        挂载已核对，容量/实际访问在执行前检查。正式入库位置以实际入库结果/导航入口为准。
      </Typography.Paragraph>
    </>
  );
}

function SelectedDestination({
  selected,
}: {
  /** 待确认输出根快照。 */ selected: Destination | undefined;
}): ReactElement {
  return (
    <Typography.Paragraph>
      输出存储根：{selected?.name} · {selected?.path}
    </Typography.Paragraph>
  );
}
