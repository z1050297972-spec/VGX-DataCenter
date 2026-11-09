// 机器人登记操作数据库；连接检查提交给 worker，页面只读公钥，不保存凭据。
import { useState, type ReactElement } from "react";
import { Link } from "@tanstack/react-router";
import { listPreviewProfiles } from "../api/preview";
import { useQuery } from "@tanstack/react-query";
import {
  AutoComplete,
  Breadcrumb,
  Button,
  Card,
  Flex,
  Form,
  Input,
  InputNumber,
  Modal,
  Space,
  Table,
  Tag,
  Typography,
} from "antd";
import { useAccountClient } from "../accounts/runtime";
import { listRobots, listRobotModels, saveRobot } from "../api/collection";
import type { HistoricalActor, Robot, RobotInput } from "../api/collection";
import { DiagnosticCard } from "../DiagnosticCard";
import { toFailureView } from "../api/problems";
import { formatDateTime } from "../time";
import { RegistryRowActions, useRegistryAction } from "./shared";
import { RobotConnection } from "./RobotConnection";
import "./collection.css";

// 工单 01：每台最多 8 块网卡；SSH 默认端口为 22。
const MAX_MACS = 8;
const DEFAULT_SSH_PORT = 22;
const EMPTY_ROBOT: RobotInput = {
  name: "",
  robot_model: "",
  serial_number: null,
  macs: [],
  address: null,
  ssh_port: DEFAULT_SSH_PORT,
  ssh_user: null,
};

/**
 * 管理全部机器人登记，展示引用数及最后修改身份。
 * @returns antd 列表、新建和编辑表单及服务端诊断。
 * @throws 无；读取和写入失败用 DiagnosticCard 显示。
 * @sideEffects 读取机器人、型号候选和 Profile 摘要；用户提交后保存或改变状态，成功刷新列表。
 * @timeSemantics 无轮询、无自动重试；查询离页清理，单次请求上限 ACCOUNT_TIMEOUT_MS。
 */
export function RobotsPage(): ReactElement {
  const client = useAccountClient();
  const list = useQuery({
    queryKey: ["robots"],
    queryFn: ({ signal }) => listRobots({ client, signal, payload: undefined }),
    retry: false,
    gcTime: 0,
  });
  const models = useQuery({
    queryKey: ["robots", "models"],
    queryFn: ({ signal }) => listRobotModels({ client, signal, payload: undefined }),
    retry: false,
    gcTime: 0,
  });
  const profiles = useQuery({
    queryKey: ["robot-profiles"],
    queryFn: ({ signal }) => listPreviewProfiles({ client, signal, payload: undefined }),
    retry: false,
    gcTime: 0,
  });
  const action = useRegistryAction("robots");
  const [editor, setEditor] = useState<Robot | "create" | null>(null);
  const [form] = Form.useForm<RobotInput>();
  function edit(row: Robot | "create"): void {
    action.reset();
    setEditor(row);
    form.setFieldsValue(row === "create" ? EMPTY_ROBOT : { ...EMPTY_ROBOT, ...row });
  }
  return (
    <Flex vertical gap="large">
      <header className="app-page-header">
        <Breadcrumb items={[{ title: "机器人" }]} />
        <Flex justify="space-between" align="center" wrap>
          <Typography.Title level={2} className="app-page-title">
            机器人
          </Typography.Title>
          <Button
            type="primary"
            disabled={action.isPending}
            onClick={() => {
              edit("create");
            }}
          >
            新建机器人
          </Button>
        </Flex>
      </header>
      {[list.error, models.error, profiles.error, editor === null ? action.error : null].map(
        (error, index) =>
          error ? <DiagnosticCard key={index} failure={toFailureView(error)} /> : null,
      )}
      <Card>
        <Table<Robot>
          rowKey="robot_id"
          scroll={{ x: "max-content" }}
          loading={list.isFetching}
          dataSource={list.data?.items ?? []}
          rowClassName={(row) => (row.status === "retired" ? "collection-retired" : "")}
          columns={[
            { title: "编号", dataIndex: "robot_id" },
            { title: "名称", dataIndex: "name" },
            { title: "型号", dataIndex: "robot_model" },
            {
              title: "序列号",
              dataIndex: "serial_number",
              render: (value: Robot["serial_number"]) => value ?? "—",
            },
            {
              title: "MAC",
              render: (_, row) => (
                <Space vertical>
                  {row.macs.map((item) => (
                    <Typography.Text
                      key={item.mac}
                      type={row.status === "retired" ? "secondary" : undefined}
                    >
                      {item.interface ? `${item.interface}：` : ""}
                      {item.mac}
                    </Typography.Text>
                  ))}
                </Space>
              ),
            },
            {
              title: "地址",
              dataIndex: "address",
              render: (value: Robot["address"]) => value ?? "—",
            },
            {
              title: "SSH",
              render: (_, row) => `${row.ssh_user ?? "—"} / ${String(row.ssh_port)}`,
            },
            {
              title: "状态",
              render: (_, row) => <Tag>{row.status === "active" ? "使用中" : "停用"}</Tag>,
            },
            { title: "被引用数", dataIndex: "reference_count" },
            {
              title: "最后修改",
              render: (_, row) => (
                <Space vertical>
                  <span>{actorLabel(row.updated_by)}</span>
                  <span>{formatDateTime(row.updated_at)}</span>
                </Space>
              ),
            },
            {
              title: "连接检查",
              render: (_, row) => <RobotConnection robot={row} />,
            },
            {
              title: "实时预览",
              render: (_, row) =>
                profiles.data?.items.some((profile) => profile.model === row.robot_model) ? (
                  <Link to="/robots/$robotId/preview" params={{ robotId: String(row.robot_id) }}>
                    实时预览
                  </Link>
                ) : (
                  <Space vertical>
                    <Button disabled>实时预览</Button>
                    <Typography.Text type="secondary">
                      {profiles.isFetching ? "正在读取 RobotProfile" : "该型号没有 RobotProfile"}
                    </Typography.Text>
                  </Space>
                ),
            },
            {
              title: "操作",
              render: (_, row) => (
                <RegistryRowActions
                  kind="robots"
                  id={row.robot_id}
                  name={row.name}
                  status={row.status}
                  referenceCount={row.reference_count}
                  action={action}
                  onEdit={() => {
                    edit(row);
                  }}
                />
              ),
            },
          ]}
        />
      </Card>
      <Modal
        open={editor !== null}
        title={editor === "create" ? "新建机器人" : "编辑机器人"}
        footer={null}
        destroyOnHidden
        onCancel={() => {
          if (!action.isPending) setEditor(null);
        }}
      >
        {action.error && <DiagnosticCard failure={toFailureView(action.error)} />}
        <Form
          form={form}
          layout="vertical"
          disabled={action.isPending}
          onFinish={(values: RobotInput) => {
            if (editor === null) return;
            action.mutate(
              (signal) =>
                saveRobot({
                  client,
                  signal,
                  id: editor === "create" ? null : editor.robot_id,
                  payload: robotPayload(values),
                }),
              {
                onSuccess: () => {
                  setEditor(null);
                },
              },
            );
          }}
        >
          <RobotFields models={models.data?.items ?? []} />
          <Button type="primary" htmlType="submit" loading={action.isPending}>
            保存机器人
          </Button>
        </Form>
      </Modal>
    </Flex>
  );
}

// 型号候选只辅助输入，允许新型号；复杂合法性及重复检测交服务端字段诊断。
function RobotFields({ models }: { models: string[] }): ReactElement {
  return (
    <>
      <Form.Item name="name" label="名称" rules={[{ required: true, whitespace: true, max: 64 }]}>
        <Input maxLength={64} />
      </Form.Item>
      <Form.Item
        name="robot_model"
        label="型号"
        rules={[{ required: true, whitespace: true, max: 64 }]}
      >
        <AutoComplete options={models.map((value) => ({ value }))} />
      </Form.Item>
      <Form.Item name="serial_number" label="序列号">
        <Input maxLength={64} />
      </Form.Item>
      <Form.List name="macs">
        {(fields, { add, remove }) => (
          <>
            {fields.map((field) => (
              <Space key={field.key} align="baseline">
                <Form.Item name={[field.name, "interface"]} label="网卡名">
                  <Input maxLength={32} />
                </Form.Item>
                <Form.Item
                  name={[field.name, "mac"]}
                  label="MAC"
                  rules={[{ required: true, message: "请输入 MAC" }]}
                >
                  <Input placeholder="aa:bb:cc:dd:ee:ff" />
                </Form.Item>
                <Button
                  onClick={() => {
                    remove(field.name);
                  }}
                >
                  删除网卡
                </Button>
              </Space>
            ))}
            <Form.Item>
              <Button
                disabled={fields.length >= MAX_MACS}
                onClick={() => {
                  add({ interface: null, mac: "" });
                }}
              >
                添加网卡
              </Button>
            </Form.Item>
          </>
        )}
      </Form.List>
      <Form.Item name="address" label="地址">
        <Input maxLength={253} />
      </Form.Item>
      <Form.Item
        name="ssh_port"
        label="SSH 端口"
        rules={[{ required: true, type: "integer", min: 1, max: 65535 }]}
      >
        <InputNumber min={1} max={65535} precision={0} />
      </Form.Item>
      <Form.Item name="ssh_user" label="SSH 用户">
        <Input maxLength={32} />
      </Form.Item>
    </>
  );
}

// 空可选输入按契约传 null；MAC 规范化和全局唯一性由后端负责。
function robotPayload(values: RobotInput): RobotInput {
  return {
    ...values,
    serial_number: values.serial_number?.trim() || null,
    address: values.address?.trim() || null,
    ssh_user: values.ssh_user?.trim() || null,
    macs: values.macs.map((item) => ({ ...item, interface: item.interface?.trim() || null })),
  };
}

// 和作业提交人一致：空编号代表系统，同名账号保留编号，已删账号保留历史姓名。
function actorLabel(actor: HistoricalActor): string {
  if (actor.account_id === null) return "系统";
  return (
    actor.name +
    (actor.name === "系统" ? `（账号 #${actor.account_id}）` : "") +
    (actor.deleted ? "（已删除）" : "")
  );
}
