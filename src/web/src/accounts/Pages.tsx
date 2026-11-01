// 账号页面（06）：采用 antd 与 TanStack Router/Query；错误统一用 DiagnosticCard，秘密只在表单内存。
import type { HealthClient } from "../api/client";
import { changeToken, getTokenState } from "../api/downloadToken";
import { VersionFooter } from "../VersionFooter";
import { WorkerStatusBanner } from "../jobs/WorkerStatusBanner";
import { RecoveryBlockBanner } from "../navigation/RecoveryBlockBanner";
import type { ReactElement } from "react";
import { useEffect, useRef, useState } from "react";
import { Card, Form, Input, Button, Typography, Alert, Table, Modal, Select, Space } from "antd";
import { useLocation, useNavigate, Link, Outlet } from "@tanstack/react-router";
import { useQueryClient, useQuery } from "@tanstack/react-query";
import {
  login,
  fetchCurrentAccount,
  logout,
  changePassword,
  listAccounts,
  createAccount,
  setAccountRole,
  setAccountStatus,
  resetAccountPassword,
  deleteAccount,
} from "../api/accounts";
import type { Account, LoginInput, PasswordInput, NewAccountInput } from "../api/accounts";
import { toFailureView, type RequestFailureView } from "../api/problems";
import { DiagnosticCard } from "../DiagnosticCard";
import { ADMINISTRATOR_PAGE_PATHS, safeReturnTo } from "./navigation";
import { useAccountClient, useCurrentAccount, ACCOUNT_QUERY_KEY } from "./runtime";
import { formatDateTime } from "../time";
import "../shell.css";

/**
 * 登录名和口令表单；成功后按必须改密标记转改密页，否则回 safeReturnTo；已登录者不重复显示登录表单。401/403/422/429/网络失败均显示 DiagnosticCard，429 展示安全倒计时，不区分未知账号与错口令。
 *
 * @returns 使用 antd 的表单、状态或诊断视图；仅身份明确且权限满足时显示受保护内容。
 * @throws 无。请求错误经 toFailureView/DiagnosticCard 呈现，不展示原始异常或执行服务端 HTML。
 * @sideEffects 仅提交时调用 login；未登录不加载受保护内容；口令在任何结束路径清空，不进入 URL、日志、缓存或浏览器存储。
 * @timeSemantics 请求上限 ACCOUNT_TIMEOUT_MS；切页/卸载取消请求和倒计时，忽略迟到结果，无自动重试。
 */
export function LoginPage(): ReactElement {
  const client = useAccountClient();
  const queryClient = useQueryClient();
  const navigate = useNavigate();
  const search = useLocation({ select: (location) => location.searchStr });
  const target = returnTarget(search);
  const [form] = Form.useForm<LoginInput>();
  const action = useAccountAction();
  const [checking, setChecking] = useState(true);
  const [checkError, setCheckError] = useState<unknown>();
  function complete(account: Account): void {
    queryClient.clear();
    void navigate({
      href: account.must_change_password
        ? "/change-password?returnTo=" + encodeURIComponent(target)
        : target,
      replace: true,
    });
  }
  useEffect(() => {
    const controller = new AbortController();
    void fetchCurrentAccount({ client, payload: undefined, signal: controller.signal })
      .then((account) => {
        if (!controller.signal.aborted) {
          void navigate({
            href: account.must_change_password
              ? "/change-password?returnTo=" + encodeURIComponent(target)
              : target,
            replace: true,
          });
        }
      })
      .catch((error: unknown) => {
        if (controller.signal.aborted) return;
        const failure = toFailureView(error);
        if (!(failure.kind === "problem" && failure.problem.status === 401)) setCheckError(error);
      })
      .finally(() => {
        if (!controller.signal.aborted) setChecking(false);
      });
    return () => {
      controller.abort();
    };
  }, [client, navigate, target]);
  return (
    <Card title="登录">
      {checking ? (
        <Typography.Text>正在确认登录状态…</Typography.Text>
      ) : (
        <>
          {checkError !== undefined && <DiagnosticCard failure={toFailureView(checkError)} />}
          <ActionFailure action={action} />
          <Form
            form={form}
            layout="vertical"
            onFinish={(payload: LoginInput) => {
              void action.run(
                (signal) => login({ client, payload, signal }),
                complete,
                () => {
                  form.resetFields(["password"]);
                },
              );
            }}
          >
            <Form.Item
              name="login_name"
              label="登录名"
              rules={[{ required: true, message: "请输入登录名" }]}
            >
              <Input autoComplete="username" />
            </Form.Item>
            <Form.Item
              name="password"
              label="口令"
              rules={[{ required: true, message: "请输入口令" }]}
            >
              <Input.Password autoComplete="current-password" />
            </Form.Item>
            <Button
              aria-label="登录"
              htmlType="submit"
              type="primary"
              loading={action.busy}
              disabled={action.waiting > 0}
            >
              登录
            </Button>
          </Form>
        </>
      )}
    </Card>
  );
}

/**
 * 本人当前/新口令与确认表单；强制改密者不能绕过，成功后回安全目的地；旧口令错误400提示“当前口令不正确”并留在本页，第五次429；真实401仍跳登录，错误统一用 DiagnosticCard。
 *
 * @returns 使用 antd 的表单、状态或诊断视图；仅身份明确且权限满足时显示受保护内容。
 * @throws 无。请求错误经 toFailureView/DiagnosticCard 呈现，不展示原始异常或执行服务端 HTML。
 * @sideEffects 提交 changePassword，成功刷新身份；任何结束路径清空秘密；不因超时声称服务端已回滚。
 * @timeSemantics 请求上限 ACCOUNT_TIMEOUT_MS；切页/卸载取消请求和倒计时，忽略迟到结果，无自动重试。
 */
export function PasswordPage(): ReactElement {
  const client = useAccountClient();
  const queryClient = useQueryClient();
  const navigate = useNavigate();
  const search = useLocation({ select: (location) => location.searchStr });
  const [form] = Form.useForm<PasswordInput & { confirmation: string }>();
  const action = useAccountAction();
  return (
    <Card title="修改口令">
      <ActionFailure action={action} />
      <Form
        form={form}
        layout="vertical"
        onFinish={(values: PasswordInput & { confirmation: string }) => {
          const payload: PasswordInput = {
            current_password: values.current_password,
            new_password: values.new_password,
          };
          void action.run(
            (signal) => changePassword({ client, payload, signal }),
            (account) => {
              queryClient.setQueryData(ACCOUNT_QUERY_KEY, account);
              void queryClient.invalidateQueries({
                queryKey: ACCOUNT_QUERY_KEY,
                refetchType: "none",
              });
              void navigate({ href: returnTarget(search), replace: true });
            },
            () => {
              form.resetFields();
            },
          );
        }}
      >
        <Form.Item
          name="current_password"
          label="当前口令"
          rules={[{ required: true, message: "请输入当前口令" }]}
        >
          <Input.Password autoComplete="current-password" />
        </Form.Item>
        <Form.Item
          name="new_password"
          label="新口令"
          rules={[{ required: true, message: "请输入新口令" }]}
        >
          <Input.Password autoComplete="new-password" />
        </Form.Item>
        <Form.Item
          name="confirmation"
          label="确认新口令"
          dependencies={["new_password"]}
          rules={[
            { required: true, message: "请再次输入新口令" },
            ({ getFieldValue }) => ({
              validator: (_rule, value: unknown) =>
                value === getFieldValue("new_password")
                  ? Promise.resolve()
                  : Promise.reject(new Error("两次新口令不一致")),
            }),
          ]}
        >
          <Input.Password autoComplete="new-password" />
        </Form.Item>
        <Button
          aria-label="保存口令"
          htmlType="submit"
          type="primary"
          loading={action.busy}
          disabled={action.waiting > 0}
        >
          保存口令
        </Button>
      </Form>
    </Card>
  );
}

/**
 * 管理员分页账号列表、新建、改角色、启停、重置口令、删除。停用和删除均用 antd Modal 二次确认，取消不发请求；403、404、409、422、429/网络错误用 DiagnosticCard，失败保留原列表。
 *
 * @returns 使用 antd 的表单、状态或诊断视图；仅身份明确且权限满足时显示受保护内容。
 * @throws 无。请求错误经 toFailureView/DiagnosticCard 呈现，不展示原始异常或执行服务端 HTML。
 * @sideEffects 通过生成类型的 accounts API 操作；写成功才刷新列表，不乐观删除；新建/重置口令只在表单内存，结束后清除。
 * @timeSemantics 请求上限 ACCOUNT_TIMEOUT_MS；切页/卸载取消请求和倒计时，忽略迟到结果，无自动重试。
 */
export function AccountsPage(): ReactElement {
  const client = useAccountClient();
  const cache = useQueryClient();
  const [afterId, setAfterId] = useState("0");
  const [previous, setPrevious] = useState<string[]>([]);
  const list = useQuery({
    queryKey: ["accounts", afterId],
    queryFn: ({ signal }) => listAccounts({ client, signal, payload: undefined, afterId }),
    retry: false,
    gcTime: 0,
    refetchOnWindowFocus: false,
  });
  const action = useAccountAction();
  const [modal, holder] = Modal.useModal();
  const [editor, setEditor] = useState<"create" | Account | null>(null);
  const [form] = Form.useForm<NewAccountInput>();
  function refresh(): void {
    void cache.invalidateQueries({ queryKey: ["accounts"] });
    void cache.invalidateQueries({ queryKey: ACCOUNT_QUERY_KEY });
  }
  function confirm(target: Account, operation: "disable" | "delete"): void {
    modal.confirm({
      title: operation === "disable" ? "确认停用账号" : "确认删除账号",
      content: target.display_name,
      okText: operation === "disable" ? "确认停用" : "确认删除",
      cancelText: "取消",
      onOk: () =>
        action.run<unknown>(
          (signal) =>
            operation === "disable"
              ? setAccountStatus({
                  client,
                  signal,
                  accountId: target.account_id,
                  payload: { status: "disabled" },
                })
              : deleteAccount({ client, signal, accountId: target.account_id, payload: undefined }),
          refresh,
        ),
    });
  }
  const columns = [
    { title: "编号", dataIndex: "account_id" },
    { title: "登录名", dataIndex: "login_name" },
    { title: "显示名", dataIndex: "display_name" },
    {
      title: "角色",
      render: (_value: unknown, row: Account) => (row.role === "administrator" ? "管理员" : "成员"),
    },
    {
      title: "状态",
      render: (_value: unknown, row: Account) => (row.status === "enabled" ? "启用" : "停用"),
    },
    {
      title: "必须改口令",
      render: (_value: unknown, row: Account) => (row.must_change_password ? "是" : "否"),
    },
    { title: "创建人", render: (_value: unknown, row: Account) => row.created_by.name },
    {
      title: "修改时间",
      render: (_value: unknown, row: Account) => formatDateTime(row.updated_at),
    },
    {
      title: "操作",
      render: (_value: unknown, row: Account) => (
        <Space wrap>
          <Button
            disabled={action.busy}
            onClick={() => {
              void action.run(
                (signal) =>
                  setAccountRole({
                    client,
                    signal,
                    accountId: row.account_id,
                    payload: { role: row.role === "administrator" ? "member" : "administrator" },
                  }),
                refresh,
              );
            }}
          >
            {row.role === "administrator" ? "改为成员" : "改为管理员"}
          </Button>
          <Button
            aria-label={row.status === "enabled" ? "停用" : "启用"}
            disabled={action.busy}
            onClick={() => {
              if (row.status === "enabled") confirm(row, "disable");
              else
                void action.run(
                  (signal) =>
                    setAccountStatus({
                      client,
                      signal,
                      accountId: row.account_id,
                      payload: { status: "enabled" },
                    }),
                  refresh,
                );
            }}
          >
            {row.status === "enabled" ? "停用" : "启用"}
          </Button>
          <Button
            disabled={action.busy}
            onClick={() => {
              form.resetFields();
              setEditor(row);
            }}
          >
            重置口令
          </Button>
          <Button
            aria-label="删除"
            danger
            disabled={action.busy}
            onClick={() => {
              confirm(row, "delete");
            }}
          >
            删除
          </Button>
        </Space>
      ),
    },
  ];
  return (
    <Card title="账号管理">
      <DownloadTokenSection />
      {holder}
      <ActionFailure action={action} />
      {list.isError && <DiagnosticCard failure={toFailureView(list.error)} />}
      <Button
        onClick={() => {
          form.resetFields();
          setEditor("create");
        }}
      >
        新建账号
      </Button>
      <Table<Account>
        scroll={{ x: "max-content" }}
        rowKey="account_id"
        columns={columns}
        dataSource={list.data?.items ?? []}
        pagination={false}
        loading={list.isFetching}
      />
      <Space>
        <Button
          disabled={previous.length === 0 || list.isFetching}
          onClick={() => {
            const copy = [...previous];
            setAfterId(copy.pop() ?? "0");
            setPrevious(copy);
          }}
        >
          上一页
        </Button>
        <Button
          disabled={!list.data?.next_after_id || list.isFetching}
          onClick={() => {
            if (list.data?.next_after_id) {
              setPrevious([...previous, afterId]);
              setAfterId(list.data.next_after_id);
            }
          }}
        >
          下一页
        </Button>
      </Space>
      <Modal
        open={editor !== null}
        title={editor === "create" ? "新建账号" : "重置口令"}
        footer={null}
        onCancel={() => {
          if (!action.busy) {
            form.resetFields();
            setEditor(null);
          }
        }}
        destroyOnHidden
      >
        <Form
          form={form}
          layout="vertical"
          initialValues={{ role: "member" }}
          onFinish={(values: NewAccountInput) => {
            const selected = editor;
            if (selected === null) return;
            void action.run(
              (signal) =>
                selected === "create"
                  ? createAccount({ client, signal, payload: values })
                  : resetAccountPassword({
                      client,
                      signal,
                      accountId: selected.account_id,
                      payload: { password: values.password },
                    }),
              () => {
                setEditor(null);
                refresh();
              },
              () => {
                form.resetFields(["password"]);
              },
            );
          }}
        >
          {editor === "create" && (
            <>
              <Form.Item
                name="login_name"
                label="登录名"
                rules={[{ required: true, message: "请输入登录名" }]}
              >
                <Input autoComplete="off" />
              </Form.Item>
              <Form.Item
                name="display_name"
                label="显示名"
                rules={[{ required: true, message: "请输入显示名" }]}
              >
                <Input />
              </Form.Item>
              <Form.Item name="role" label="角色">
                <Select
                  options={[
                    { value: "member", label: "成员" },
                    { value: "administrator", label: "管理员" },
                  ]}
                />
              </Form.Item>
            </>
          )}
          <Form.Item
            name="password"
            label="初始口令"
            rules={[{ required: true, message: "请输入口令" }]}
          >
            <Input.Password autoComplete="new-password" />
          </Form.Item>
          <Button aria-label="保存账号" htmlType="submit" type="primary" loading={action.busy}>
            保存账号
          </Button>
        </Form>
      </Modal>
    </Card>
  );
}

/**
 * 在右上角显示当前显示名、角色、改口令入口和登出；管理员额外显示账号管理、操作日志和登录日志入口，成员不显示。
 *
 * @returns 含所有登录账号可见的“调度”入口；使用 antd 的表单、状态或诊断视图；仅身份明确且权限满足时显示受保护内容。
 * @throws 无。请求错误经 toFailureView/DiagnosticCard 呈现，不展示原始异常或执行服务端 HTML。
 * @sideEffects 订阅共享的内存身份查询，设置 refetchOnWindowFocus: true、staleTime: 0；切回窗口重新查 /api/auth/me，401 统一清缓存并跳登录；登出成功或 401 才清缓存去登录页，网络失败显示 DiagnosticCard，不假装退出。
 * @timeSemantics 请求上限 ACCOUNT_TIMEOUT_MS；切页/卸载取消请求和倒计时，忽略迟到结果，无自动重试。
 */
export function AccountMenu(): ReactElement {
  const identity = useCurrentAccount();
  const client = useAccountClient();
  const queryClient = useQueryClient();
  const navigate = useNavigate();
  const action = useAccountAction();
  if (!identity.data) return <></>;
  return (
    <div
      style={{
        display: "flex",
        justifyContent: "flex-end",
        gap: 16,
        alignItems: "center",
        flexWrap: "wrap",
      }}
    >
      <Typography.Text>{identity.data.display_name}</Typography.Text>
      <Typography.Text>
        角色：{identity.data.role === "administrator" ? "管理员" : "成员"}
      </Typography.Text>
      <nav aria-label="主菜单" className="app-menu">
        <Link to="/change-password">修改口令</Link>
        <Link to="/jobs">作业</Link>
        <Link to="/downloads">下载</Link>
        <Link to="/scheduling">调度</Link>
        <Link to="/datasets">数据集</Link>
        <Link to="/storage-roots">存储根</Link>
        {identity.data.role === "administrator" && <Link to="/accounts">账号管理</Link>}
        {identity.data.role === "administrator" && (
          <>
            <Link to="/audit/operations">操作日志</Link>
            <Link to="/audit/logins">登录日志</Link>
          </>
        )}
      </nav>
      <Button
        aria-label="登出"
        loading={action.busy}
        onClick={() => {
          void action.run(
            (signal) => logout({ client, signal, payload: undefined }),
            () => {
              queryClient.clear();
              void navigate({ href: "/login", replace: true });
            },
          );
        }}
      >
        登出
      </Button>
      <ActionFailure action={action} />
    </div>
  );
}

/**
 * 提供右上角 AccountMenu 和受保护页面 Outlet；身份未知时显示加载状态，不闪现受保护内容。
 *
 * @returns 使用 antd 的表单、状态或诊断视图；仅身份明确且权限满足时显示受保护内容。
 * @throws 无。请求错误经 toFailureView/DiagnosticCard 呈现，不展示原始异常或执行服务端 HTML。
 * @sideEffects 由 guardAccountRoute 完成进入前鉴权，并保持一份活跃身份 Query（refetchOnWindowFocus: true、staleTime: 0）；
 * 成员被停用后，切回窗口立即重新查 /api/auth/me，收到 401 就清缓存并跳登录；任何其他 API 的 401 同样统一 handleUnauthorized。
 * 身份查询不使用定时轮询；worker 状态通过顶部横幅每秒查询，任意接口401均触发既有身份清理。根布局统一保护页面内容。
 * @timeSemantics 请求上限 ACCOUNT_TIMEOUT_MS；切页/卸载取消请求和倒计时，忽略迟到结果，无自动重试。
 */
export function AccountLayout(): ReactElement {
  const client = useAccountClient();
  const identity = useCurrentAccount();
  const navigate = useNavigate();
  const location = useLocation();
  const force = identity.data?.must_change_password && location.pathname !== "/change-password";
  const denied =
    identity.data?.role === "member" && ADMINISTRATOR_PAGE_PATHS.has(location.pathname);
  useEffect(() => {
    if (force)
      void navigate({
        href: "/change-password?returnTo=" + encodeURIComponent(safeReturnTo(location.href)),
        replace: true,
      });
    else if (denied) void navigate({ href: "/?permission=denied", replace: true });
  }, [force, denied, navigate, location.href]);
  if (identity.isPending) return <Typography.Text>正在确认身份…</Typography.Text>;
  if (identity.isError) return <DiagnosticCard failure={toFailureView(identity.error)} />;
  if (force || denied) return <Typography.Text>正在跳转…</Typography.Text>;
  return (
    <div className="app-shell">
      <AccountMenu />
      <WorkerStatusBanner />
      <RecoveryBlockBanner />
      {new URLSearchParams(location.searchStr).get("permission") === "denied" && (
        <Alert type="warning" title="需要管理员权限" />
      )}
      <main style={{ marginTop: 24 }}>
        <Outlet />
      </main>
      {renderVersionFooter(identity.data, location.pathname, client)}
    </div>
  );
}

// 回跳值每次使用前都校验，重复参数不能被 URLSearchParams.get 静默忽略。
function returnTarget(search: string): string {
  const values = new URLSearchParams(search).getAll("returnTo");
  return safeReturnTo(values.length === 1 ? values[0] : values);
}

// 复用账号页短期写请求生命周期；token 不放入 Query mutation 缓存。
function DownloadTokenSection(): ReactElement {
  const client = useAccountClient();
  const cache = useQueryClient();
  const action = useAccountAction();
  const [form] = Form.useForm<{ token: string }>();
  const state = useQuery({
    queryKey: ["downloads", "token-state"],
    queryFn: ({ signal }) => getTokenState(client, signal),
    retry: false,
    gcTime: 0,
  });
  function apply(token: string | null): void {
    void action.run(
      (signal) => changeToken(client, token, signal),
      (result) => {
        cache.setQueryData(["downloads", "token-state"], result);
      },
      () => {
        form.resetFields();
      },
    );
  }
  return (
    <section>
      <Typography.Title level={3}>Hugging Face token</Typography.Title>
      {state.data && (
        <Typography.Text>{state.data.configured ? "已设置" : "未设置"}</Typography.Text>
      )}
      {state.isError && <DiagnosticCard failure={toFailureView(state.error)} />}
      <ActionFailure action={action} />
      <Form
        form={form}
        onFinish={(values: { token: string }) => {
          apply(values.token);
        }}
      >
        <Form.Item name="token" label="token" rules={[{ required: true, message: "请输入 token" }]}>
          <Input.Password autoComplete="off" />
        </Form.Item>
        <Button htmlType="submit" loading={action.busy} disabled={action.busy}>
          设置 token
        </Button>
        <Button
          disabled={action.busy || !state.data?.configured}
          onClick={() => {
            apply(null);
          }}
        >
          清除 token
        </Button>
      </Form>
    </section>
  );
}

// 写操作不进 Query mutation 缓存，口令只由提交闭包短暂持有，退出必须取消并清理。
function useAccountAction() {
  const active = useRef<AbortController | null>(null);
  const [busy, setBusy] = useState(false);
  const [failure, setFailure] = useState<RequestFailureView | null>(null);
  const [waiting, setWaiting] = useState(0);
  useEffect(
    () => () => {
      active.current?.abort();
    },
    [],
  );
  useEffect(() => {
    if (waiting <= 0) return;
    const timer = setTimeout(() => {
      setWaiting((value) => Math.max(0, value - 1));
    }, 1000);
    return () => {
      clearTimeout(timer);
    };
  }, [waiting]);
  async function run<T>(
    work: (signal: AbortSignal) => Promise<T>,
    success: (value: T) => void,
    clear: () => void = () => undefined,
  ): Promise<void> {
    if (active.current || waiting > 0) return;
    const controller = new AbortController();
    active.current = controller;
    setBusy(true);
    setFailure(null);
    try {
      const result = await work(controller.signal);
      if (!controller.signal.aborted) success(result);
    } catch (error) {
      if (!controller.signal.aborted) {
        const view = toFailureView(error);
        setFailure(view);
        if (view.kind === "problem") setWaiting(view.retryAfterSeconds ?? 0);
      }
    } finally {
      clear();
      active.current = null;
      if (!controller.signal.aborted) setBusy(false);
    }
  }
  return { busy, failure, waiting, run };
}

function ActionFailure({ action }: { action: ReturnType<typeof useAccountAction> }): ReactElement {
  return (
    <>
      {action.failure && <DiagnosticCard failure={action.failure} />}
      {action.waiting > 0 && (
        <Alert type="warning" title={`请等待 ${String(action.waiting)} 秒后重试`} />
      )}
    </>
  );
}

// 只有完成改密的业务页面请求受保护版本；身份守卫仍由布局统一处理。
function renderVersionFooter(
  account: Account,
  pathname: string,
  client: HealthClient,
): ReactElement | null {
  if (account.must_change_password || pathname === "/change-password") return null;
  return <VersionFooter client={client} />;
}
