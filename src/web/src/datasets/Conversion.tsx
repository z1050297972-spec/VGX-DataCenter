// 清洗预览入口（M4.5-04）；只选择有规则的工具、型号与数据块，后台检查由作业系统负责。
import { useState, type ReactElement } from "react";
import { Alert, Button, Checkbox, Drawer, Form, Radio, Select, Space, Typography } from "antd";
import type { DatasetDetail } from "../api/datasets";
import type { CleaningPreviewInput, CleaningPreviewSubmission } from "../api/cleaning";
import type { ToolSummary } from "../api/tools";
import { submitCleaningPreview } from "../api/cleaning";
import { useTools } from "../tools/queries";
import { useAccountClient, useCurrentAccount } from "../accounts/runtime";
import { useJobAction } from "../jobs/_actions";
import { DiagnosticCard } from "../DiagnosticCard";
import { toFailureView } from "../api/problems";

interface Props {
  /** 当前数据集详情；使用数据块格式及规范副本的型号。 */ detail: DatasetDetail;
}

/**
 * 给含受支持格式数据块的数据集提供清洗预览入口。
 * @param props - 本次读取的详情快照。
 * @returns 清洗预览按钮和抽屉；没有受支持的数据块时不渲染。
 * @throws 无；工具请求与提交错误以诊断组件显示。
 * @sideEffects 有受支持的数据块时读取工具清单，提交成功导航到新作业详情。
 * @timeSemantics 工具每次挂载读取一次；提交最多10秒，离页取消请求，无自动重试。
 */
export function ConversionEntry(props: Props): ReactElement | null {
  const identity = useCurrentAccount();
  if (
    identity.data?.role !== "administrator" ||
    !props.detail.entry.dataset_id ||
    !props.detail.sources.some(
      (source) =>
        source.format === "mcap" ||
        source.format === "agibot_native" ||
        (source.format === "archives" && archiveTask(source.direct_path) !== null),
    )
  )
    return null;
  return <ConversionChoice detail={props.detail} />;
}

function ConversionChoice({ detail }: Props): ReactElement {
  const tools = useTools();
  const [open, setOpen] = useState(false);
  const model = datasetModel(detail);
  const candidates =
    tools.data?.items.filter(
      (tool) =>
        tool.cleaning_models.length > 0 &&
        (tool.input_format === "mcap" || tool.preview_by_tool) &&
        detail.sources.some(
          (source) =>
            source.format === tool.input_format &&
            (tool.input_format !== "archives" || archiveTask(source.direct_path) !== null),
        ),
    ) ?? [];
  const matching = candidates.filter(
    (tool) => model !== null && tool.cleaning_models.includes(model),
  );
  const initial =
    matching.find((tool) => tool.status === "可用") ??
    candidates.find((tool) => tool.status === "可用");
  const reason = unavailableReason(tools.isPending, candidates);
  return (
    <>
      <Button
        aria-label="清洗预览"
        disabled={!initial}
        title={initial ? "只读检查数据质量" : reason}
        onClick={() => {
          setOpen(true);
        }}
      >
        清洗预览
      </Button>
      {!initial && <Typography.Text type="secondary">{reason}</Typography.Text>}
      {tools.error && <DiagnosticCard failure={toFailureView(tools.error)} />}
      <Drawer
        title="清洗预览"
        open={open}
        onClose={() => {
          setOpen(false);
        }}
        destroyOnHidden
        size="large"
      >
        {open && initial && (
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
  model: string | null;
}): ReactElement {
  const client = useAccountClient();
  const [tool, setTool] = useState(initial);
  const [form] = Form.useForm<CleaningPreviewInput>();
  const submit = useJobAction(
    (payload: CleaningPreviewSubmission, signal) =>
      submitCleaningPreview({ client, payload, signal }),
    true,
  );
  const sources = detail.sources.filter(
    (source) =>
      source.format === tool.input_format &&
      (tool.input_format !== "archives" || archiveTask(source.direct_path) !== null),
  );
  const native = tool.input_format === "agibot_native";
  const g2 = tool.input_format === "archives";
  const sourceIds = sources.map((source) => source.source_id);
  return (
    <Form
      form={form}
      layout="vertical"
      initialValues={{
        robot_model:
          model && tool.cleaning_models.includes(model) ? model : tool.cleaning_models[0],
        source_ids: tool.input_format === "mcap" ? sourceIds : sourceIds.slice(0, 1),
      }}
      onFinish={(values) => {
        if (detail.entry.dataset_id)
          submit.mutate({
            tool: tool.name,
            parameters: { ...values, dataset_id: detail.entry.dataset_id },
          });
      }}
    >
      <Typography.Paragraph>先只读检查数据质量，生成报告后再决定是否转换。</Typography.Paragraph>
      <Typography.Paragraph>
        预览会把所选数据块里的每个文件完整读一遍，数据越大耗时越长；完成后在报告里看问题、决定保留或剔除，再从报告底部进行转换。
      </Typography.Paragraph>
      <Form.Item label="清洗工具">
        <Select
          aria-label="清洗工具"
          value={tool.name}
          options={tools.map((item) => ({ value: item.name, label: item.name }))}
          onChange={(name: string) => {
            const next = tools.find((item) => item.name === name);
            if (!next) return;
            setTool(next);
            form.setFieldsValue({
              robot_model:
                model && next.cleaning_models.includes(model) ? model : next.cleaning_models[0],
              // 工具切换时重置数据块，避免把上一种格式的选择带入预览。
              source_ids: detail.sources
                .filter(
                  (source) =>
                    source.format === next.input_format &&
                    (next.input_format !== "archives" || archiveTask(source.direct_path) !== null),
                )
                .map((source) => source.source_id)
                .slice(
                  0,
                  next.input_format === "agibot_native" || next.input_format === "archives"
                    ? 1
                    : undefined,
                ),
            });
          }}
        />
      </Form.Item>
      <Alert
        type={tool.status === "可用" ? "info" : "warning"}
        title={`工具状态：${tool.status}`}
        description="预览只读输入，不生成转换产物。"
      />
      <Form.Item
        label="型号配置"
        name="robot_model"
        rules={[{ required: true, message: "请选择型号配置" }]}
      >
        <Select options={tool.cleaning_models.map((value) => ({ value, label: value }))} />
      </Form.Item>
      {g2 && (
        <Alert
          type="info"
          title="同任务 G2 v2.1 归档"
          description="按选择顺序合并；归档名称只用于筛选候选，预览还会验证 g2a、FPS 和特征。视频仅检查成员存在且非空，未执行画面检查。"
        />
      )}
      {native ? (
        <Form.Item
          label="选择一个任务的观测目录"
          name="source_ids"
          rules={[{ type: "array", len: 1, required: true, message: "请选择一个任务的观测目录" }]}
          getValueProps={(value: string[]) => ({ value: value[0] })}
          getValueFromEvent={(event: { target: { value: string } }) => [event.target.value]}
        >
          <Radio.Group>
            <Space orientation="vertical">
              {sources.map((source) => (
                <Radio key={source.source_id} value={source.source_id}>
                  {source.original_path.split("/").filter(Boolean).slice(-2).join("/")}
                </Radio>
              ))}
            </Space>
          </Radio.Group>
        </Form.Item>
      ) : (
        <Form.Item
          label="数据块"
          name="source_ids"
          rules={[
            {
              type: "array",
              min: 1,
              max: 200,
              required: true,
              message: g2 ? "请选择同一任务的1至200个归档" : "请选择1至200个mcap数据块",
            },
            ...(g2
              ? [
                  {
                    validator: (_rule: unknown, value: string[] | undefined) => {
                      const paths = sources
                        .filter((source) => value?.includes(source.source_id))
                        .map((source) => source.direct_path);
                      return new Set(paths.map(archiveTask)).size <= 1 &&
                        new Set(paths).size === paths.length
                        ? Promise.resolve()
                        : Promise.reject(new Error("请选择同一 task 目录下不重复的归档"));
                    },
                  },
                ]
              : []),
          ]}
        >
          <Checkbox.Group>
            <Space orientation="vertical">
              {sources.map((source) => (
                <Checkbox key={source.source_id} value={source.source_id}>
                  {g2 ? source.direct_path.split("/").slice(-2).join("/") : source.source_id}
                </Checkbox>
              ))}
            </Space>
          </Checkbox.Group>
        </Form.Item>
      )}
      {submit.error && <DiagnosticCard failure={toFailureView(submit.error)} />}
      <Button
        type="primary"
        htmlType="submit"
        disabled={tool.status !== "可用"}
        loading={submit.isPending}
      >
        提交清洗预览
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
  if (matching.length === 0) return "没有适用该数据格式的清洗规则";
  return matching.map((tool) => `${tool.name}：${tool.status}`).join("；");
}

// 只按登记的 direct_path 筛候选；服务器与工具继续核对普通文件、任务边界和实际格式。
function archiveTask(path: string): string | null {
  return /^\/(?:[^/]+\/)*task_[0-9]+\/[^/]+\.tar\.gz$/.test(path) && !path.split("/").includes("..")
    ? path.slice(0, path.lastIndexOf("/"))
    : null;
}
