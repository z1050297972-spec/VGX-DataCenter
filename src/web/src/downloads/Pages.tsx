import "./downloads.css";
// 下载页只管理表单与作业；计划、容量和文件系统操作均由 worker 完成。
import { useCallback, useEffect, useRef, useState, type ReactElement } from "react";
import {
  Alert,
  Breadcrumb,
  Button,
  Card,
  Col,
  Flex,
  Row,
  Checkbox,
  Form,
  Input,
  InputNumber,
  Select,
  Typography,
  type FormInstance,
} from "antd";
import { getRouteApi, useNavigate } from "@tanstack/react-router";
import { useAccountClient } from "../accounts/runtime";
import { submitDownload, type DownloadInput } from "../api/downloads";
import { toFailureView, type RequestFailureView } from "../api/problems";
import { DiagnosticCard } from "../DiagnosticCard";
import { useStorageRoots } from "../storage/queries";
import { Preview } from "./Preview";
import { Staging } from "./Staging";

const route = getRouteApi("/downloads");
const MIB = 1024 * 1024;
interface Values {
  repo_type: "dataset" | "model";
  repo_id: string;
  revision: string;
  storage_root: string;
  target_subdir?: string;
  exclude_video: boolean;
  exclude_cameras: string[];
  include_text: string;
  exclude_text: string;
  max_concurrent_downloads: number;
  max_connection_per_server: number;
  split: number;
  min_split_mib: number;
  max_overall_download_limit_bytes_per_s: number;
  max_tries: number;
  retry_wait_s: number;
}
const defaults: Values = {
  repo_type: "dataset",
  repo_id: "",
  revision: "main",
  storage_root: "",
  target_subdir: "",
  exclude_video: false,
  exclude_cameras: [],
  include_text: "",
  exclude_text: "",
  max_concurrent_downloads: 4,
  max_connection_per_server: 4,
  split: 4,
  min_split_mib: 20,
  max_overall_download_limit_bytes_per_s: 0,
  max_tries: 5,
  retry_wait_s: 10,
};

// glob 模式按行录入，空行不成为匹配规则；空数组保持服务端全部语义。
function patterns(text: string): string[] {
  return text
    .split("\n")
    .map((item) => item.trim())
    .filter(Boolean);
}
function payload(values: Values): DownloadInput {
  return {
    repo_type: values.repo_type,
    repo_id: values.repo_id.trim(),
    revision: values.revision.trim(),
    storage_root: values.storage_root,
    target_subdir: values.repo_type === "model" ? values.target_subdir?.trim() || null : null,
    include: patterns(values.include_text),
    exclude: patterns(values.exclude_text),
    exclude_video: values.exclude_video,
    exclude_cameras: values.exclude_cameras,
    max_concurrent_downloads: values.max_concurrent_downloads,
    max_connection_per_server: values.max_connection_per_server,
    split: values.split,
    min_split_size_bytes: values.min_split_mib * MIB,
    max_overall_download_limit_bytes_per_s: values.max_overall_download_limit_bytes_per_s,
    max_tries: values.max_tries,
    retry_wait_s: values.retry_wait_s,
  };
}

/**
 * 在下载页填写参数、提交 worker 预览并确认下载。
 * @returns 参数表单、预览快照及诊断。
 * @throws Error 缺少路由或客户端提供器。
 * @sideEffects 只提交作业和读取状态；不访问存储根，不持久化表单或凭据。
 * @timeSemantics 预览时才观察容量；修改表单后须重新预览；离页取消请求。
 */
export function DownloadPage(): ReactElement {
  const search = route.useSearch();
  if (search.invalidDownloadSearch) return <Alert type="error" title="下载页面参数不合法" />;
  return (
    <section className="downloads-page">
      <header className="app-page-header">
        <Breadcrumb items={[{ title: "数据" }, { title: "下载" }]} />
        <Typography.Title level={2} className="app-page-title">
          下载
        </Typography.Title>
      </header>
      <DownloadForm previewId={search.preview_job_id} />
      <Card>
        <Staging jobId={search.staging_job_id} />
      </Card>
    </section>
  );
}

function DownloadForm({ previewId }: { previewId: string | undefined }): ReactElement {
  const roots = useStorageRoots();
  const [form] = Form.useForm<Values>();
  const repoType = Form.useWatch("repo_type", form);
  const cameras = Form.useWatch("exclude_cameras", form);
  const [advanced, setAdvanced] = useState(false);
  const [fields, setFields] = useState<ServerField[]>([]);
  const reportFields = useCallback((errors: ServerField[]) => {
    if (errors.length) {
      setAdvanced(true);
      setFields(errors);
    }
  }, []);
  // 等高级区域挂载后再设置字段错误，避免收起的字段丢失服务端反馈。
  useEffect(() => {
    if (fields.length) form.setFields(fields);
  }, [form, advanced, fields]);
  const flow = useDownloadFlow(form, reportFields);
  const { markDirty } = flow;
  const setCameras = useCallback(
    (value: string[]) => {
      form.setFieldValue("exclude_cameras", value);
      markDirty();
    },
    [form, markDirty],
  );
  return (
    <section className="downloads-page">
      {roots.isError && <DiagnosticCard failure={toFailureView(roots.error)} />}
      {flow.failure && <DiagnosticCard failure={flow.failure} />}
      <Card>
        <Form
          form={form}
          layout="vertical"
          initialValues={defaults}
          onValuesChange={() => {
            flow.markDirty();
            setFields([]);
          }}
        >
          <Row gutter={16}>
            <Col xs={24} md={12}>
              <Form.Item name="repo_type" label="仓库类型" rules={[{ required: true }]}>
                <Select
                  options={[
                    { value: "dataset", label: "数据集" },
                    { value: "model", label: "模型" },
                  ]}
                />
              </Form.Item>
            </Col>
            <Col xs={24} md={12}>
              <Form.Item
                name="repo_id"
                label="仓库编号"
                rules={[{ required: true, whitespace: true, message: "请输入仓库编号" }]}
              >
                <Input placeholder="命名空间/仓库" />
              </Form.Item>
            </Col>
            <Col xs={24} md={12}>
              <Form.Item
                name="revision"
                label="版本"
                rules={[{ required: true, whitespace: true, message: "请输入版本" }]}
              >
                <Input />
              </Form.Item>
            </Col>
            <Col xs={24} md={12}>
              <Form.Item
                name="storage_root"
                label="目标存储根"
                rules={[{ required: true, message: "请选择可写存储根" }]}
              >
                <Select
                  options={(roots.data?.items ?? [])
                    .filter((root) => root.writable)
                    .map((root) => ({ value: root.name, label: root.name }))}
                />
              </Form.Item>
            </Col>
            {repoType === "model" && (
              <Col xs={24} md={12}>
                <Form.Item
                  name="target_subdir"
                  label="子目录"
                  extra="默认：命名空间/仓库@commit前12位"
                >
                  <Input placeholder="命名空间/仓库@commit前12位" />
                </Form.Item>
              </Col>
            )}
            <Col xs={24} md={12}>
              <Form.Item name="exclude_video" valuePropName="checked">
                <Checkbox>不要视频</Checkbox>
              </Form.Item>
            </Col>
            <Form.Item name="exclude_cameras" hidden>
              <Input />
            </Form.Item>
            <Col xs={24} md={12}>
              <Form.Item
                name="max_overall_download_limit_bytes_per_s"
                label="总限速（B/s）"
                extra="默认不限（0）；范围 0 或 1024–10737418240 B/s"
                rules={[
                  { required: true },
                  {
                    validator: (_, value: number) =>
                      value !== 0 && value < 1024
                        ? Promise.reject(new Error("限速须为 0 或至少 1024 B/s"))
                        : Promise.resolve(),
                  },
                ]}
              >
                <InputNumber min={0} max={10737418240} precision={0} />
              </Form.Item>
            </Col>
          </Row>
          <Button
            className="downloads-advanced-toggle"
            aria-label="高级参数"
            onClick={() => {
              setAdvanced(!advanced);
            }}
          >
            高级参数
          </Button>
          {advanced && <AdvancedFields />}
          <Flex gap="small" wrap="wrap">
            <Button
              aria-label="预览"
              onClick={() => {
                void flow.send(true);
              }}
              loading={flow.busy}
              disabled={flow.busy}
            >
              预览
            </Button>
            <Button
              aria-label="确认下载"
              type="primary"
              onClick={() => {
                void flow.send(false);
              }}
              disabled={!flow.canSubmit}
            >
              确认下载
            </Button>
          </Flex>
        </Form>
      </Card>
      {previewId && (
        <Preview
          key={previewId}
          jobId={previewId}
          excluded={cameras}
          onChange={setCameras}
          onReady={flow.onReady}
        />
      )}
    </section>
  );
}

// 无副作用地核对表单与本页上次提交的预览，避免确认过期结果。
function confirmed(
  preview: boolean,
  ready: boolean,
  dirty: boolean,
  submitted: string | null,
  input: DownloadInput,
): boolean {
  return preview || (ready && !dirty && submitted === JSON.stringify(input));
}

function useDownloadFlow(
  form: FormInstance<Values>,
  reportFields: (fields: ServerField[]) => void,
) {
  const client = useAccountClient();
  const navigate = useNavigate();
  const [ready, setReady] = useState(false);
  const [dirty, setDirty] = useState(true);
  const [busy, setBusy] = useState(false);
  const [failure, setFailure] = useState<RequestFailureView | null>(null);
  const [submitted, setSubmitted] = useState<string | null>(null);
  const active = useRef<AbortController | null>(null);
  useEffect(
    () => () => {
      active.current?.abort();
    },
    [],
  );
  const onReady = useCallback((value: boolean) => {
    setReady(value);
  }, []);
  const markDirty = useCallback(() => {
    setDirty(true);
  }, []);
  async function send(preview: boolean): Promise<void> {
    if (active.current) return;
    try {
      await form.validateFields();
    } catch {
      return;
    }
    // getFieldsValue(true) 保留收起的高级字段及其默认值。
    const input = payload(form.getFieldsValue(true) as Values);
    if (!confirmed(preview, ready, dirty, submitted, input)) return;
    const controller = new AbortController();
    active.current = controller;
    setBusy(true);
    setFailure(null);
    try {
      const job = await submitDownload(client, input, preview, controller.signal);
      if (controller.signal.aborted) return;
      if (preview) {
        setSubmitted(JSON.stringify(input));
        setDirty(
          JSON.stringify(payload(form.getFieldsValue(true) as Values)) !== JSON.stringify(input),
        );
        setReady(false);
        await navigate({
          to: "/downloads",
          search: (previous) => ({ ...previous, preview_job_id: job.job_id }),
        });
      } else await navigate({ to: "/jobs/$jobId", params: { jobId: job.job_id } });
    } catch (error) {
      if (!controller.signal.aborted) {
        const view = toFailureView(error);
        setFailure(view);
        reportFields(serverFields(view));
      }
    } finally {
      active.current = null;
      if (!controller.signal.aborted) setBusy(false);
    }
  }
  return {
    send,
    busy,
    failure,
    onReady,
    markDirty,
    canSubmit: !busy && ready && !dirty && submitted !== null,
  };
}

// 接口诊断中的字段位置只匹配已声明的安全白名单，永不把任意键当作表单路径。
const SERVER_FIELD_NAMES = new Map<string, keyof Values>([
  ["repo_type", "repo_type"],
  ["repo_id", "repo_id"],
  ["revision", "revision"],
  ["storage_root", "storage_root"],
  ["target_subdir", "target_subdir"],
  ["exclude_video", "exclude_video"],
  ["exclude_cameras", "exclude_cameras"],
  ["include", "include_text"],
  ["exclude", "exclude_text"],
  ["max_concurrent_downloads", "max_concurrent_downloads"],
  ["max_connection_per_server", "max_connection_per_server"],
  ["split", "split"],
  ["min_split_size_bytes", "min_split_mib"],
  ["max_overall_download_limit_bytes_per_s", "max_overall_download_limit_bytes_per_s"],
  ["max_tries", "max_tries"],
  ["retry_wait_s", "retry_wait_s"],
]);
type ServerField = { name: keyof Values; errors: string[] };
function serverFields(failure: RequestFailureView): ServerField[] {
  if (failure.kind !== "problem" || failure.problem.status !== 422) return [];
  const fields = new Set<keyof Values>();
  for (const diagnostic of failure.problem.diagnostics) {
    for (const object of diagnostic.objects) {
      if (object.key !== "field") continue;
      const match = /^body\.([a-z0-9_]+)(?:[.\[]|$)/.exec(object.value);
      const field = match?.[1] ? SERVER_FIELD_NAMES.get(match[1]) : undefined;
      if (field) fields.add(field);
    }
  }
  return Array.from(fields, (name) => ({ name, errors: ["服务器校验未通过，请检查范围。"] }));
}

// 数字上限与后端 DownloadParameters 一致；说明明确单位和不可动态修改的原因。
function AdvancedFields(): ReactElement {
  return (
    <section>
      <Typography.Text>除并发和总限速外，修改须取消后重新提交；续传不受影响。</Typography.Text>
      <Row gutter={16}>
        <Col xs={24} md={12}>
          <Form.Item
            name="max_concurrent_downloads"
            label="同时下几个文件"
            extra="默认 4，范围 1–16，可运行中调整"
            rules={[{ required: true }]}
          >
            <InputNumber min={1} max={16} precision={0} />
          </Form.Item>
        </Col>
        <Col xs={24} md={12}>
          <Form.Item
            name="max_connection_per_server"
            label="每服务器连接数"
            extra="默认 4，范围 1–16"
            rules={[{ required: true }]}
          >
            <InputNumber min={1} max={16} precision={0} />
          </Form.Item>
        </Col>
        <Col xs={24} md={12}>
          <Form.Item
            name="split"
            label="每文件分段数"
            extra="默认 4，范围 1–16"
            rules={[{ required: true }]}
          >
            <InputNumber min={1} max={16} precision={0} />
          </Form.Item>
        </Col>
        <Col xs={24} md={12}>
          <Form.Item
            name="min_split_mib"
            label="最小分段大小（MiB）"
            extra="默认 20 MiB，范围 1–1024 MiB"
            rules={[{ required: true }]}
          >
            <InputNumber min={1} max={1024} precision={0} />
          </Form.Item>
        </Col>
        <Col xs={24} md={12}>
          <Form.Item
            name="max_tries"
            label="重试次数"
            extra="默认 5，范围 1–20"
            rules={[{ required: true }]}
          >
            <InputNumber min={1} max={20} precision={0} />
          </Form.Item>
        </Col>
        <Col xs={24} md={12}>
          <Form.Item
            name="retry_wait_s"
            label="重试间隔（秒）"
            extra="默认 10 秒，范围 0–600 秒"
            rules={[{ required: true }]}
          >
            <InputNumber min={0} max={600} precision={0} />
          </Form.Item>
        </Col>
        <Col xs={24} md={12}>
          <Form.Item name="include_text" label="包含模式" extra="每行一个 glob，留空包含全部">
            <Input.TextArea />
          </Form.Item>
        </Col>
        <Col xs={24} md={12}>
          <Form.Item name="exclude_text" label="排除模式" extra="每行一个 glob，排除优先">
            <Input.TextArea />
          </Form.Item>
        </Col>
      </Row>
    </section>
  );
}
