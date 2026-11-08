// 转换入口和表单（M4-03）；只选择登记工具与数据块，后台执行和GPU等待由作业系统负责。
import { useState, type ReactElement } from "react";
import { Alert, Button, Checkbox, Drawer, Form, Select, Space, Typography } from "antd";
import type { DatasetDetail } from "../api/datasets";
import type { ToolSummary } from "../api/tools";
import {
  submitConversion,
  type ConversionInput,
  type ConversionSubmission,
} from "../api/conversion";
import { useTools } from "../tools/queries";
import { useAccountClient } from "../accounts/runtime";
import { useJobAction } from "../jobs/_actions";
import { DiagnosticCard } from "../DiagnosticCard";
import { toFailureView } from "../api/problems";

interface Props {
  /** 当前数据集详情；只使用mcap数据块及规范副本的型号。 */ detail: DatasetDetail;
}

/**
 * 给含mcap数据块的数据集提供转换入口。
 * @param props - 本次读取的详情快照。
 * @returns 转换按钮和抽屉；没有mcap数据块时不渲染。
 * @throws 无；工具请求与提交错误以诊断组件显示。
 * @sideEffects 有mcap数据块时读取工具清单，提交成功导航到新作业详情。
 * @timeSemantics 工具每次挂载读取一次；提交最多10秒，离页取消请求，无自动重试。
 */
export function ConversionEntry(props: Props): ReactElement | null {
  if (
    !props.detail.entry.dataset_id ||
    !props.detail.sources.some((source) => source.format === "mcap")
  )
    return null;
  return <ConversionChoice detail={props.detail} />;
}

function ConversionChoice({ detail }: Props): ReactElement {
  const tools = useTools();
  const [open, setOpen] = useState(false);
  const model = datasetModel(detail);
  const candidates = tools.data?.items.filter((tool) => tool.input_format === "mcap") ?? [];
  const matching = candidates.filter((tool) => model !== null && tool.robot_models.includes(model));
  const initial = matching.find((tool) => tool.status === "可用");
  const reason = unavailableReason(tools.isPending, matching);
  return (
    <>
      <Button
        aria-label="转换"
        disabled={!initial}
        title={initial ? "转换为新的数据集" : reason}
        onClick={() => {
          setOpen(true);
        }}
      >
        转换
      </Button>
      {!initial && <Typography.Text type="secondary">{reason}</Typography.Text>}
      {tools.error && <DiagnosticCard failure={toFailureView(tools.error)} />}
      <Drawer
        title="转换数据集"
        open={open}
        onClose={() => {
          setOpen(false);
        }}
        destroyOnHidden
        size="large"
      >
        {open && initial && model && (
          <ConversionForm detail={detail} tools={candidates} initial={initial} model={model} />
        )}
      </Drawer>
    </>
  );
}

function ConversionForm({
  detail,
  tools,
  initial,
  model,
}: {
  detail: DatasetDetail;
  tools: ToolSummary[];
  initial: ToolSummary;
  model: string;
}): ReactElement {
  const client = useAccountClient();
  const [tool, setTool] = useState(initial);
  const [form] = Form.useForm<ConversionInput>();
  const submit = useJobAction(
    (payload: ConversionSubmission, signal) => submitConversion({ client, payload, signal }),
    true,
  );
  const sources = detail.sources.filter((source) => source.format === "mcap");
  return (
    <Form
      form={form}
      layout="vertical"
      initialValues={{
        robot_model: model,
        output_format: initial.output_versions[0],
        source_ids: sources.map((source) => source.source_id),
      }}
      onFinish={(values) => {
        if (detail.entry.dataset_id)
          submit.mutate({
            tool: tool.name,
            parameters: { ...values, dataset_id: detail.entry.dataset_id },
          });
      }}
    >
      <Form.Item label="转换工具">
        <Select
          aria-label="转换工具"
          value={tool.name}
          options={tools.map((item) => ({ value: item.name, label: item.name }))}
          onChange={(name: string) => {
            const next = tools.find((item) => item.name === name);
            if (!next) return;
            setTool(next);
            form.setFieldsValue({
              robot_model: next.robot_models.includes(model) ? model : next.robot_models[0],
              output_format: next.output_versions[0],
            });
          }}
        />
      </Form.Item>
      <Alert
        type={tool.status === "可用" ? "info" : "warning"}
        title={`工具状态：${tool.status}`}
        description={tool.needs_gpu ? "需要 GPU，提交后由作业调度分配。" : "不需要 GPU。"}
      />
      <Form.Item
        label="型号配置"
        name="robot_model"
        rules={[{ required: true, message: "请选择型号配置" }]}
      >
        <Select options={tool.robot_models.map((value) => ({ value, label: value }))} />
      </Form.Item>
      <Form.Item
        label="输出格式"
        name="output_format"
        rules={[{ required: true, message: "请选择输出格式" }]}
      >
        <Select options={tool.output_versions.map((value) => ({ value, label: value }))} />
      </Form.Item>
      <Form.Item
        label="数据块"
        name="source_ids"
        rules={[
          { type: "array", min: 1, max: 200, required: true, message: "请选择1至200个mcap数据块" },
        ]}
      >
        <Checkbox.Group>
          <Space orientation="vertical">
            {sources.map((source) => (
              <Checkbox key={source.source_id} value={source.source_id}>
                {source.source_id}
              </Checkbox>
            ))}
          </Space>
        </Checkbox.Group>
      </Form.Item>
      {submit.error && <DiagnosticCard failure={toFailureView(submit.error)} />}
      <Button
        type="primary"
        htmlType="submit"
        disabled={tool.status !== "可用"}
        loading={submit.isPending}
      >
        提交转换
      </Button>
    </Form>
  );
}

function datasetModel(detail: DatasetDetail): string | null {
  // 型号仅取规范副本顶层字段，不解析第5项Markdown或格式副本。
  const document = detail.canonical_information;
  if (!document?.usable || !document.content) return null;
  try {
    const value: unknown = JSON.parse(document.content);
    if (typeof value !== "object" || value === null || !("robot_model" in value)) return null;
    return typeof value.robot_model === "string" ? value.robot_model.trim() || null : null;
  } catch {
    return null;
  }
}

// 不可用的原因来自当前登记状态，不能把加载失败解释为没有工具。
function unavailableReason(pending: boolean, matching: ToolSummary[]): string {
  if (pending) return "正在检查工具";
  if (matching.length === 0) return "没有适用该数据集型号的转换工具";
  return matching.map((tool) => `${tool.name}：${tool.status}`).join("；");
}
