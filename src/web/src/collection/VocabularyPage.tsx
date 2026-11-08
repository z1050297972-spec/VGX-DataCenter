// 采集方式和用途共用管理页；页签由类型化 URL 保存，场景和任务仍归数据中心。
import { useState, type ReactElement } from "react";
import { useQuery } from "@tanstack/react-query";
import { useNavigate, useSearch } from "@tanstack/react-router";
import {
  Breadcrumb,
  Button,
  Card,
  Flex,
  Form,
  Input,
  Modal,
  Select,
  Table,
  Tabs,
  Tag,
  Typography,
} from "antd";
import { useAccountClient } from "../accounts/runtime";
import { listVocabulary, saveTerm } from "../api/collection";
import type { DataOrigin, MethodInput, Term, VocabularyKind } from "../api/collection";
import { DiagnosticCard } from "../DiagnosticCard";
import { toFailureView } from "../api/problems";
import { RegistryRowActions, useRegistryAction } from "./shared";
import "./collection.css";

// 工单 02 允许的四种采集来源；不包含开源下载和未知。
const DATA_ORIGINS: DataOrigin[] = ["真机采集", "UMI 采集", "ego 采集", "仿真生成"];

/**
 * 管理采集方式与用途，名称变化不改变编号。
 * @returns 两个 URL 页签、登记表格和新增或改名表单。
 * @throws 无；请求错误统一呈现诊断。
 * @sideEffects 读取词表，提交即时数据库写操作；切换页签更新 tab 查询参数。
 * @timeSemantics 无轮询和自动重试；离页释放查询，单请求上限 ACCOUNT_TIMEOUT_MS。
 */
export function VocabularyPage(): ReactElement {
  const search = useSearch({ from: "/collection-vocabulary" });
  const navigate = useNavigate({ from: "/collection-vocabulary" });
  return (
    <Flex vertical gap="large">
      <header className="app-page-header">
        <Breadcrumb items={[{ title: "采集词表" }]} />
        <Typography.Title level={2} className="app-page-title">
          采集词表
        </Typography.Title>
      </header>
      <Card>
        <Tabs
          activeKey={search.tab}
          onChange={(key) => {
            void navigate({ search: { tab: key === "purposes" ? "purposes" : "methods" } });
          }}
          items={[
            { key: "methods", label: "采集方式" },
            { key: "purposes", label: "用途" },
          ]}
        />
      </Card>
      <VocabularyTable key={search.tab} kind={search.tab} />
    </Flex>
  );
}

// 切页签卸载本页草稿与请求，避免把采集方式草稿提交到用途接口。
function VocabularyTable({ kind }: { kind: VocabularyKind }): ReactElement {
  const client = useAccountClient();
  const list = useQuery({
    queryKey: ["collection-vocabulary"],
    queryFn: ({ signal }) => listVocabulary({ client, signal, payload: undefined }),
    retry: false,
    gcTime: 0,
  });
  const action = useRegistryAction("collection-vocabulary");
  const [editor, setEditor] = useState<Term | "create" | null>(null);
  const [form] = Form.useForm<MethodInput>();
  const label = kind === "methods" ? "采集方式" : "用途";
  function edit(row: Term | "create"): void {
    action.reset();
    setEditor(row);
    form.setFieldsValue({
      name: row === "create" ? "" : row.name,
      data_origin: row !== "create" && "data_origin" in row ? row.data_origin : undefined,
    });
  }
  return (
    <>
      {[list.error, editor === null ? action.error : null].map((error, index) =>
        error ? <DiagnosticCard key={index} failure={toFailureView(error)} /> : null,
      )}
      <Card
        title={label}
        extra={
          <Button
            type="primary"
            disabled={action.isPending}
            onClick={() => {
              edit("create");
            }}
          >
            新增{label}
          </Button>
        }
      >
        <Table<Term>
          rowKey="id"
          scroll={{ x: "max-content" }}
          loading={list.isFetching}
          dataSource={list.data?.[kind] ?? []}
          rowClassName={(row) => (row.status === "retired" ? "collection-retired" : "")}
          columns={[
            { title: "编号", dataIndex: "id" },
            { title: "名称", dataIndex: "name" },
            ...(kind === "methods" ? [{ title: "对应数据来源", dataIndex: "data_origin" }] : []),
            {
              title: "状态",
              render: (_, row) => <Tag>{row.status === "active" ? "使用中" : "停用"}</Tag>,
            },
            { title: "被引用数", dataIndex: "reference_count" },
            {
              title: "操作",
              render: (_, row) => (
                <RegistryRowActions
                  kind={kind}
                  id={row.id}
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
        title={`${editor === "create" ? "新增" : "修改"}${label}`}
        open={editor !== null}
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
          onFinish={(values: MethodInput) => {
            if (editor === null) return;
            const id = editor === "create" ? null : editor.id;
            action.mutate(
              (signal) =>
                saveTerm({
                  client,
                  signal,
                  payload: undefined,
                  id,
                  ...(kind === "methods"
                    ? { kind, values }
                    : { kind, values: { name: values.name } }),
                }),
              {
                onSuccess: () => {
                  setEditor(null);
                },
              },
            );
          }}
        >
          <Form.Item
            name="name"
            label="名称"
            rules={[{ required: true, whitespace: true, max: 32 }]}
          >
            <Input maxLength={32} />
          </Form.Item>
          {kind === "methods" && (
            <Form.Item
              name="data_origin"
              label="对应数据来源"
              rules={[{ required: true, message: "请选择对应数据来源" }]}
            >
              <Select options={DATA_ORIGINS.map((value) => ({ value, label: value }))} />
            </Form.Item>
          )}
          <Button type="primary" htmlType="submit" loading={action.isPending}>
            保存{label}
          </Button>
        </Form>
      </Modal>
    </>
  );
}
