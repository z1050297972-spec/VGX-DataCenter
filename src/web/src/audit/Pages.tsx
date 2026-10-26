// 管理员日志页面契约（07）：antd 只读表格、TanStack Router 类型化 search 和 Query 数据状态。
// 历史名字和明细只做安全文本展示，页面不提供修改单条记录的入口。
import { useRef, useState, type ReactElement } from "react";
import { Alert, Button, Form, Input, Select, Table, Typography } from "antd";
import { getRouteApi } from "@tanstack/react-router";
import type { TableColumnsType } from "antd";
import type { OperationLogPage, LoginLogPage, OperationSearch, LoginSearch } from "../api/audit";
import { AUDIT_MIN_RETENTION_DAYS, AUDIT_MAX_RETENTION_DAYS, AUDIT_PAGE_LIMIT } from "../api/audit";
import { toFailureView } from "../api/problems";
import { DiagnosticCard } from "../DiagnosticCard";
import { useOperationLogs, useLoginLogs, useAuditRetention, useSetAuditRetention } from "./queries";
import {
  OPERATION_LABELS,
  OPERATION_RESULTS,
  LOGIN_KINDS,
  LOGIN_RESULTS,
  validateOperationSearch,
  validateLoginSearch,
} from "./search";

const operationRoute = getRouteApi("/audit/operations");
const loginRoute = getRouteApi("/audit/logins");

/**
 * 显示管理员操作日志、筛选和共同保留期设置。
 * @returns antd 的倒序只读表格、类型化时间/操作人账号/对象账号/操作/结果筛选、游标翻页和 7-365 天设置表单；无单条编辑/删除入口。actor/target.deleted 显示“名字（已删除）”，不按同名新账号改写旧记录；空来源显示“未知”，运维显示“运维”。
 * @throws 无；查询/保存失败用 DiagnosticCard，服务端文字作为文本渲染。
 * @sideEffects 通过 getRouteApi("/audit/operations").useSearch 与 useNavigate 的 typed search 管理筛选；“操作人”绑定 account_id，“对象账号”绑定 target_account_id，可独立清空并同时取交集；改任一筛选清 cursor，翻页用 next_cursor。用 useOperationLogs/useAuditRetention/useSetAuditRetention，来源为既有账号感知客户端；成员不加载日志或设置，管理员菜单才有入口。
 * @timeSemantics 显示时转浏览器本地时间，提交时带偏移并转 UTC；缓存立即过期、离页释放、窗口聚焦重查；请求上限 10 秒、无轮询或自动重试，迟到结果不覆盖新筛选。
 */
export function OperationLogsPage(): ReactElement {
  const search = operationRoute.useSearch();
  const navigate = operationRoute.useNavigate();
  if (search.invalidAuditSearch)
    return (
      <InvalidFilters
        operation
        onApply={(raw) => {
          void navigate({ search: validateOperationSearch(raw) });
        }}
      />
    );
  return <OperationContent search={search} />;
}

// 仅在路由筛选有效时挂载查询，避免把无效输入当成空条件查全部日志。
function OperationContent({ search }: { search: OperationSearch }): ReactElement {
  const logs = useOperationLogs(search);
  const navigate = operationRoute.useNavigate();
  return (
    <section>
      <Typography.Title level={2}>操作日志</Typography.Title>
      <Retention />
      <Filters
        key={JSON.stringify(search)}
        search={search}
        operation
        onApply={(raw) => {
          void navigate({ search: validateOperationSearch(raw) });
        }}
      />
      {!logs.isError && logs.data?.next_cursor && (
        <Button
          onClick={() => {
            void navigate({ search: { ...search, cursor: logs.data.next_cursor ?? undefined } });
          }}
        >
          下一页
        </Button>
      )}
      {logs.isError ? (
        <DiagnosticCard failure={toFailureView(logs.error)} />
      ) : (
        <Table
          rowKey="log_id"
          columns={operationColumns}
          dataSource={logs.data?.items}
          loading={logs.isPending}
          pagination={false}
          locale={{ emptyText: "暂无日志" }}
        />
      )}
    </section>
  );
}

/**
 * 显示管理员登录日志和来源 IP。
 * @returns antd 只读表格和时间/账号/kind/result 筛选、游标翻页；未知账号只显示“账号不存在”，空 IP 显示“未知”；已删账号以历史显示名加“（已删除）”，可显示已知账号当时的登录名。
 * @throws 无；失败用统一 DiagnosticCard，不回显未知登录名或凭据。
 * @sideEffects 用 getRouteApi("/audit/logins").useSearch 读取已校验的 typed search，useNavigate 更新筛选或游标，变更筛选回首页；用 useLoginLogs，不解析 URLSearchParams、不单独创建 fetch 客户端。成员看不到菜单、无法加载页面内容或发日志查询。
 * @timeSemantics UTC 事件时间只在显示转浏览器本地；固定时间测试不修改全局时区。缓存 staleTime/gcTime=0、聚焦重查，无轮询/retry，离页取消 10 秒上限请求并忽略迟到结果。
 */
export function LoginLogsPage(): ReactElement {
  const search = loginRoute.useSearch();
  const navigate = loginRoute.useNavigate();
  if (search.invalidAuditSearch)
    return (
      <InvalidFilters
        operation={false}
        onApply={(raw) => {
          void navigate({ search: validateLoginSearch(raw) });
        }}
      />
    );
  return <LoginContent search={search} />;
}

// 登录列表和设置查询都不能在无效筛选页面启动；用户修正后由路由重新挂载。
function LoginContent({ search }: { search: LoginSearch }): ReactElement {
  const logs = useLoginLogs(search);
  const navigate = loginRoute.useNavigate();
  return (
    <section>
      <Typography.Title level={2}>登录日志</Typography.Title>
      <Filters
        key={JSON.stringify(search)}
        search={search}
        operation={false}
        onApply={(raw) => {
          void navigate({ search: validateLoginSearch(raw) });
        }}
      />
      {!logs.isError && logs.data?.next_cursor && (
        <Button
          onClick={() => {
            void navigate({ search: { ...search, cursor: logs.data.next_cursor ?? undefined } });
          }}
        >
          下一页
        </Button>
      )}
      {logs.isError ? (
        <DiagnosticCard failure={toFailureView(logs.error)} />
      ) : (
        <Table
          rowKey="log_id"
          columns={loginColumns}
          dataSource={logs.data?.items}
          loading={logs.isPending}
          pagination={false}
          locale={{ emptyText: "暂无日志" }}
        />
      )}
    </section>
  );
}

// 历史名字只取响应快照，不查询当前账号；React 文本节点自动转义 HTML。
function historical(value: { name: string; deleted: boolean }): string {
  return value.name + (value.deleted ? "（已删除）" : "");
}
// 仅展示层使用浏览器本地时区，筛选和传输仍用 UTC。
function localTime(value: string): string {
  return new Date(value).toLocaleString();
}
// 即使响应额外夹带字段也只展示契约白名单，绝不把凭据序列化到 DOM。
function details(value: OperationLogPage["items"][number]["details"]): string {
  const safe = (input: typeof value.before) => ({
    display_name: input.display_name,
    login_name: input.login_name,
    role: input.role,
    status: input.status,
    must_change_password: input.must_change_password,
    retention_days: input.retention_days,
  });
  return JSON.stringify({
    version: value.version,
    before: safe(value.before),
    after: safe(value.after),
  });
}
const operationColumns: TableColumnsType<OperationLogPage["items"][number]> = [
  { title: "时间", key: "time", render: (_, row) => localTime(row.occurred_at) },
  { title: "操作人", key: "actor", render: (_, row) => historical(row.actor) },
  { title: "对象账号", key: "target", render: (_, row) => historical(row.target) },
  { title: "操作类型", key: "operation", render: (_, row) => OPERATION_LABELS[row.operation] },
  { title: "结果", key: "result", render: (_, row) => OPERATION_RESULTS[row.result] },
  { title: "失败类别", dataIndex: "failure_category" },
  { title: "来源 IP", key: "ip", render: (_, row) => row.source_ip ?? "未知" },
  { title: "请求编号", dataIndex: "request_id" },
  { title: "明细", key: "details", render: (_, row) => details(row.details) },
];
const loginColumns: TableColumnsType<LoginLogPage["items"][number]> = [
  { title: "时间", key: "time", render: (_, row) => localTime(row.occurred_at) },
  {
    title: "账号",
    key: "account",
    render: (_, row) => (row.account ? historical(row.account) : "账号不存在"),
  },
  { title: "登录名", dataIndex: "login_name" },
  { title: "类型", key: "kind", render: (_, row) => LOGIN_KINDS[row.kind] },
  { title: "结果", key: "result", render: (_, row) => LOGIN_RESULTS[row.result] },
  { title: "失败类别", dataIndex: "failure_category" },
  { title: "来源 IP", key: "ip", render: (_, row) => row.source_ip ?? "未知" },
  { title: "请求编号", dataIndex: "request_id" },
];

// 提交统一走路由校验；表单空项代表移除条件，已验证的游标从不继承到新筛选。
function Filters(props: {
  search: OperationSearch | LoginSearch;
  operation: boolean;
  onApply: (raw: Record<string, unknown>) => void;
}): ReactElement {
  const [invalid, setInvalid] = useState(false);
  return (
    <Form<Record<string, unknown>>
      layout="inline"
      initialValues={props.search}
      onFinish={(values) => {
        const raw = Object.fromEntries(
          Object.entries(values).filter(
            ([key, value]) => key !== "cursor" && value !== "" && value !== undefined,
          ),
        );
        try {
          props.onApply(raw);
          setInvalid(false);
        } catch {
          setInvalid(true);
        }
      }}
    >
      <Form.Item name="start" label="开始时间（含）">
        <Input placeholder="带偏移的 ISO 时间" />
      </Form.Item>
      <Form.Item name="end" label="结束时间（不含）">
        <Input placeholder="带偏移的 ISO 时间" />
      </Form.Item>
      <Form.Item name="account_id" label={props.operation ? "操作人编号" : "账号编号"}>
        <Input />
      </Form.Item>
      {props.operation && (
        <Form.Item name="target_account_id" label="对象账号编号">
          <Input />
        </Form.Item>
      )}
      <Form.Item
        name={props.operation ? "operation" : "kind"}
        label={props.operation ? "操作类型" : "登录类型"}
      >
        <Select
          allowClear
          style={{ minWidth: 160 }}
          options={options(props.operation ? OPERATION_LABELS : LOGIN_KINDS)}
        />
      </Form.Item>
      <Form.Item name="result" label="筛选结果">
        <Select
          allowClear
          style={{ minWidth: 120 }}
          options={options(props.operation ? OPERATION_RESULTS : LOGIN_RESULTS)}
        />
      </Form.Item>
      <Form.Item name="limit" label="每页条数">
        <Input placeholder={`1–${String(AUDIT_PAGE_LIMIT)}`} />
      </Form.Item>
      <Button htmlType="submit" autoInsertSpace={false}>
        筛选
      </Button>
      {invalid && <Alert type="error" title="日志筛选参数不合法" />}
    </Form>
  );
}
// 选项复用路由枚举字典，防止页面与校验接受不同值。
function options(labels: Record<string, string>) {
  return Object.entries(labels).map(([value, label]) => ({ value, label }));
}

// 读设置失败时不构造默认值；草稿只在该表单内保留，保存失败不动表格或 URL。
function Retention(): ReactElement {
  const setting = useAuditRetention();
  const mutation = useSetAuditRetention();
  const [draft, setDraft] = useState<string | undefined>(undefined);
  const [invalid, setInvalid] = useState(false);
  const pending = useRef(false);
  const value = draft ?? (setting.data ? String(setting.data.days) : "");
  const submit = () => {
    if (!setting.isSuccess || pending.current) return;
    const days = /^[0-9]+$/.test(value) ? Number(value) : NaN;
    if (
      !Number.isInteger(days) ||
      days < AUDIT_MIN_RETENTION_DAYS ||
      days > AUDIT_MAX_RETENTION_DAYS
    ) {
      setInvalid(true);
      return;
    }
    setInvalid(false);
    pending.current = true;
    mutation.mutate(
      { days },
      {
        onSettled: () => {
          pending.current = false;
        },
      },
    );
  };
  return (
    <section aria-label="日志保留期">
      {setting.isError && <DiagnosticCard failure={toFailureView(setting.error)} />}
      {mutation.isError && <DiagnosticCard failure={toFailureView(mutation.error)} />}
      <Form layout="inline" onFinish={submit}>
        <Form.Item label="保留天数" htmlFor="audit-retention-days">
          <Input
            id="audit-retention-days"
            value={value}
            disabled={!setting.isSuccess || mutation.isPending}
            onChange={(event) => {
              setDraft(event.target.value);
            }}
          />
        </Form.Item>
        <Button
          htmlType="submit"
          loading={mutation.isPending}
          disabled={!setting.isSuccess || mutation.isPending}
        >
          保存保留期
        </Button>
      </Form>
      {invalid && (
        <Alert
          type="error"
          title={`保留期须为 ${String(AUDIT_MIN_RETENTION_DAYS)}–${String(AUDIT_MAX_RETENTION_DAYS)} 天的整数`}
        />
      )}
    </section>
  );
}

// 无效链接保留页面和可提交的空表单，不回显坏值；提交后仍经同一套路由校验。
function InvalidFilters(props: {
  operation: boolean;
  onApply: (raw: Record<string, unknown>) => void;
}): ReactElement {
  return (
    <section>
      <Typography.Title level={2}>{props.operation ? "操作日志" : "登录日志"}</Typography.Title>
      <Alert role="alert" type="error" title="日志筛选参数不合法" />
      <Filters search={{}} operation={props.operation} onApply={props.onApply} />
    </section>
  );
}
