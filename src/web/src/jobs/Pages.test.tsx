// 08 页面契约清单；请求替身与真实内存Router并用，禁止网络和浏览器持久存储。
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { createMemoryHistory, RouterProvider } from "@tanstack/react-router";
import { cleanup, render, screen } from "@testing-library/react";
import { expect, it } from "vitest";
import { createAppRouter } from "../router";
import { account } from "../accounts/testSupport";

it.skip("规范7.1/10.6：真实Router打开state和数字limit的URL，成员可见作业入口且请求带相同筛选", async () => {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  const requests: URL[] = [];
  const router = createAppRouter({
    queryClient,
    history: createMemoryHistory({ initialEntries: ["/jobs?state=running&limit=20"] }),
    fetchImpl: (request) => {
      const url = new URL(request.url);
      requests.push(url);
      return Promise.resolve(
        Response.json(
          url.pathname === "/api/auth/me"
            ? { ...account, role: "member" }
            : url.pathname === "/api/worker/status"
              ? {
                  online: true,
                  instance_id: null,
                  pid: null,
                  started_at: null,
                  last_seen_at: null,
                  checked_at: "2026-10-26T00:00:00Z",
                }
              : { items: [], next_cursor: null },
        ),
      );
    },
  });
  try {
    await router.load();
    render(
      <QueryClientProvider client={queryClient}>
        <RouterProvider router={router} />
      </QueryClientProvider>,
    );
    expect(await screen.findByRole("link", { name: "作业" })).toBeTruthy();
    expect(
      requests.some(
        (url) =>
          url.pathname === "/api/jobs" &&
          url.searchParams.get("state") === "running" &&
          url.searchParams.get("limit") === "20",
      ),
    ).toBe(true);
    expect(router.state.location.pathname).toBe("/jobs");
  } finally {
    cleanup();
    queryClient.clear();
    router.history.destroy();
  }
});

it.skip("规范7.1/10.6：真实Router遇非法筛选保留表单与提示，不发列表请求、不回退全部、不崩根路由", async () => {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  const requests: string[] = [];
  const router = createAppRouter({
    queryClient,
    history: createMemoryHistory({ initialEntries: ["/jobs?state=unknown&limit=0"] }),
    fetchImpl: (request) => {
      requests.push(new URL(request.url).pathname);
      return Promise.resolve(Response.json(account));
    },
  });
  try {
    await router.load();
    render(
      <QueryClientProvider client={queryClient}>
        <RouterProvider router={router} />
      </QueryClientProvider>,
    );
    expect(await screen.findByText("作业筛选参数不合法")).toBeTruthy();
    expect(requests).not.toContain("/api/jobs");
    expect(router.state.location.pathname).toBe("/jobs");
  } finally {
    cleanup();
    queryClient.clear();
    router.history.destroy();
  }
});

it.skip("验收5：total为null只显示已处理量，不显示百分比或剩余时间；阶段格式为阶段2/4·名称", () => {
  throw new Error("未实现");
});

it.skip("验收5：最近10秒样本计算速度，少于两份/无时间差/无进展不显示；阶段切换或重跑清空样本", () => {
  throw new Error("未实现");
});

it.skip("验收5：已用时间以服务器elapsed加本地单调增量，墙钟回拨不倒退；终态冻结", () => {
  throw new Error("未实现");
});

it.skip("验收6：成功、带警告成功、部分成功、失败、已取消、已中断六种结局及三个进行中状态标签正确", () => {
  throw new Error("未实现");
});

it.skip("验收4：成员可以取消他人queued/running作业，cancelling禁用按钮并继续轮询，409刷新详情并呈现诊断", () => {
  throw new Error("未实现");
});

it.skip("验收9：终态重提导航到新编号，显示重新提交自，原记录不变，非终态不显示按钮", () => {
  throw new Error("未实现");
});

it.skip("验收7：日志仅显示最后几十行，cleared提示已清除，not_started提示未开始，工具HTML作为文本", () => {
  throw new Error("未实现");
});

it.skip("验收7：统一DiagnosticCard展示对象/实际/后果/下一步，程序缺陷不自行拼接内部报错", () => {
  throw new Error("未实现");
});

it.skip("验收8：所有登录页面含成员都显示worker离线横幅，超过15秒后出现、重启后消失", () => {
  throw new Error("未实现");
});

it.skip("验收8：初次加载或查询失败不伪装离线；未登录/强制改密不请求心跳", () => {
  throw new Error("未实现");
});

it.skip("轮询契约：详情终态读取最后日志后停止，列表继续每秒轮询，全局心跳不随作业停止", () => {
  throw new Error("未实现");
});

it.skip("账号隔离：任意401清缓存回登录，切号和离页取消请求，迟到响应不能污染新账号", () => {
  throw new Error("未实现");
});

it.skip("表单契约：步数、毫秒间隔、失败/警告序号、中止步范围正确，提交期间禁重复，422保留输入", () => {
  throw new Error("未实现");
});

it.skip("URL契约：真实Router改状态清游标，返回/刷新保留筛选，64位作业编号不经Number", () => {
  throw new Error("未实现");
});

it.skip("审计扩展：对象列显示示例：数数#12，不加账号已删除后缀，白名单明细含来源且无参数", () => {
  throw new Error("未实现");
});
