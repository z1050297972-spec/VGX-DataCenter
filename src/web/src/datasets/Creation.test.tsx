// M1-08 页面验收清单；真实副本浏览器演练由执行线在契约通过后进行。
import { describe, it, expect, vi } from "vitest";
import { createAccountClient } from "../api/accounts";
import { defaultFetch } from "../api/client";
import { getCreationOptions } from "../api/datasetCreation";
import * as scenario from "./creationTestSupport";
import { creationOptions, creationFetch } from "./creationTestSupport";
import { mountPage } from "../scheduling/pageTestSupport";
import { screen, fireEvent, waitFor } from "@testing-library/react";

describe("建链与新增数据集的契约行为", () => {
  // 验证契约：建链页按 填参数→预览→明确确认→原页作业卡片 完整流转，预览不触发写入。
  it("建链页按 填参数→预览→明确确认→原页作业卡片 完整流转，预览不触发写入", async () => {
    const requests: Request[] = [];
    const page = await previewPage({}, requests);
    try {
      expect(await screen.findByRole("heading", { name: "预览差异" })).toBeTruthy();
      expect(
        requests.filter(
          (request) => new URL(request.url).pathname === "/api/datasets/creation-writes",
        ),
      ).toHaveLength(0);
      fireEvent.click(screen.getByRole("button", { name: "确认写入" }));
      expect(await screen.findByRole("region", { name: "建链 #102" })).toBeTruthy();
      expect(page.router.state.location.pathname).toBe("/datasets/links/new");
    } finally {
      page.close();
    }
  });
  // 验证契约：新增页来源必填、首链接必填，预计编号与两个视图完整差异可见。
  it("新增页来源必填、首链接必填，预计编号与两个视图完整差异可见", async () => {
    const requests: Request[] = [];
    const page = mountPage("/datasets/new", creationFetch(requests));
    try {
      const name = await screen.findByLabelText("数据集名");
      expect(name.hasAttribute("required")).toBe(true);
      expect(screen.getByLabelText("数据来源").getAttribute("aria-required")).toBe("true");
      expect(document.querySelector("select")).toBeNull();
      expect(screen.getByRole("combobox", { name: "无元信息时的格式" })).toBeTruthy();
      fireEvent.click(screen.getByRole("button", { name: "生成预览" }));
      expect(requests.filter((request) => request.method === "POST")).toHaveLength(0);
      fireEvent.change(name, { target: { value: "接口新数据集" } });
      await choose("数据来源", "开源下载");
      fireEvent.change(screen.getByLabelText("链接名"), { target: { value: "新链接" } });
      fireEvent.change(screen.getByLabelText("目标路径"), { target: { value: "/fake/disk/new" } });
      await choose("无元信息时的格式", "mcap");
      fireEvent.click(screen.getByLabelText("格式入口 mcap"));
      fireEvent.click(screen.getByRole("button", { name: "生成预览" }));
      expect(await screen.findByRole("heading", { name: "预览差异" })).toBeTruthy();
      expect(screen.getByText(/dataset-36/)).toBeTruthy();
      const request = requests.find(
        (request) => new URL(request.url).pathname === "/api/datasets/creation-previews",
      );
      expect(await request?.json()).toMatchObject({
        dataset_name: "接口新数据集",
        data_origin: "开源下载",
        format_entries: [{ format: "mcap", version: null }],
      });
    } finally {
      page.close();
    }
  });
  // M1.5-09 契约：第6项说明与场景独立提交，14项中仅第4项不可填。
  it("新建表单提交可选信息的文字与分类", async () => {
    const requests: Request[] = [];
    const page = mountPage("/datasets/new", creationFetch(requests));
    try {
      fireEvent.change(await screen.findByLabelText("数据集名"), {
        target: { value: "可选信息数据集" },
      });
      await choose("数据来源", "开源下载");
      fireEvent.change(screen.getByLabelText("链接名"), { target: { value: "新链接" } });
      fireEvent.change(screen.getByLabelText("目标路径"), { target: { value: "/fake/disk/new" } });
      const section = screen.getByRole("region", { name: "14 项数据集信息（可选）" });
      expect(section.querySelectorAll("textarea")).toHaveLength(14);
      expect(screen.getByText("第 4 项：数据大小（自动计算）")).toBeTruthy();
      expect(screen.queryByRole("textbox", { name: /第 4 项/ })).toBeNull();
      fireEvent.change(screen.getByRole("textbox", { name: "第 6 项：任务与场景" }), {
        target: { value: "厨房抓取\n保留说明" },
      });
      await choose("场景", "家居-厨房");
      fireEvent.click(screen.getByRole("button", { name: "生成预览" }));
      await screen.findByRole("heading", { name: "预览差异" });
      const request = requests.find(
        (request) => new URL(request.url).pathname === "/api/datasets/creation-previews",
      );
      expect(await request?.json()).toMatchObject({
        information: {
          fields: [{ number: 6, value_markdown: "厨房抓取\n保留说明" }],
          robot_model: "",
          scene: "kitchen",
          tasks: [],
        },
      });
    } finally {
      page.close();
    }
  });
  // 验证契约：预览列文件、链接、sources、dataset_roots、所选与重生成格式入口及检查范围。
  it("预览列文件、链接、sources、dataset_roots、所选与重生成格式入口及检查范围", async () => {
    const page = await previewPage();
    try {
      for (const title of [
        "新增或更新的文件",
        "新增目录",
        "新增链接",
        "生成的格式入口",
        "本次勾选的格式入口",
        "dataset_roots 新增",
        "检查范围",
      ]) {
        expect(screen.getByText(title)).toBeTruthy();
      }
      expect(screen.getByLabelText("新增数据块").textContent).toContain("src_0123456789ab");
      expect(screen.getByText(/全量/)).toBeTruthy();
      expect(document.querySelector(".creation-scroll")).not.toBeNull();
    } finally {
      page.close();
    }
  });
  // 验证契约：同目标已登记的 noop 预览明确显示已经是这样了且计数为零。
  it("同目标已登记的 noop 预览明确显示已经是这样了且计数为零", async () => {
    const details = scenario.creationPreview.report.creation;
    if (!details) throw new Error("样本缺少差异");
    const preview = {
      ...scenario.creationPreview,
      report: {
        ...scenario.creationPreview.report,
        file_count: 0,
        link_count: 0,
        directory_count: 0,
        creation: {
          ...details,
          noop: true,
          file_paths: [],
          directory_paths: [],
          links: [],
          sources_added: [],
          dataset_roots_added: [],
          format_entry_paths: [],
          selected_format_entry_paths: [],
          resolved_format: null,
          resolved_version: null,
          metadata_source: "not_checked" as const,
        },
      },
    };
    const page = await previewPage({
      "/api/datasets/creation-previews/101": () => Response.json(preview),
    });
    try {
      expect(screen.getByText("已经是这样了，本次不会写入")).toBeTruthy();
      expect(screen.getByRole("button", { name: "确认写入" })).toBeTruthy();
    } finally {
      page.close();
    }
  });
  // 验证契约：没有 meta/info.json 时从登记选项选择格式，版本显示 null；archives 显示原目录名。
  it("没有 meta/info.json 时从登记选项选择格式，版本显示 null；archives 显示原目录名", async () => {
    const page = await previewPage();
    try {
      expect(screen.getByText(/用户选择（缺少 meta\/info.json）/)).toBeTruthy();
      expect(screen.getByText(/版本：null/)).toBeTruthy();
      expect(screen.getByLabelText("格式入口 tar、tar.gz（含分卷）")).toBeTruthy();
    } finally {
      page.close();
    }
  });
  // 验证契约：任一表单参数修改使旧预览失去确认资格，格式多选拒绝重复和非法版本层。
  it("任一表单参数修改使旧预览失去确认资格，格式多选拒绝重复和非法版本层", async () => {
    const requests: Request[] = [];
    const page = await previewPage({}, requests);
    try {
      fireEvent.click(screen.getByLabelText("格式入口 mcap"));
      expect(screen.queryByRole("button", { name: "确认写入" })).toBeNull();
      fireEvent.click(screen.getByLabelText("格式入口 mcap"));
      fireEvent.change(screen.getByLabelText("链接名"), { target: { value: "新名字" } });
      fireEvent.click(screen.getByRole("button", { name: "生成预览" }));
      await waitFor(() => {
        expect(requests.filter((request) => request.method === "POST")).toHaveLength(2);
      });
      const posts = requests.filter((request) => request.method === "POST");
      expect(await posts[1]?.json()).toMatchObject({
        link: { name: "新名字" },
        format_entries: [],
      });
    } finally {
      page.close();
    }
  });
  // 验证契约：冲突以 DiagnosticCard 展示对象、实际、期望、后果和下一步，并允许重新预览。
  it("冲突以 DiagnosticCard 展示对象、实际、期望、后果和下一步，并允许重新预览", async () => {
    const page = await previewPage({
      "/api/datasets/creation-writes": () =>
        Response.json(
          {
            type: "about:blank",
            title: "Conflict",
            status: 409,
            category: "conflict",
            detail: "状态已变化",
            error_id: "00000000000040008000000000000000",
            diagnostics: [
              {
                level: "error",
                category: "conflict",
                stage: "写导航层",
                source: "平台",
                rule: "NAV_PREVIEW_STATE",
                objects: [{ key: "file", value: "原始路径.json" }],
                actual: "哈希变化",
                expected: "预览哈希",
                consequence: "一行未写",
                next_step: "重新预览",
                error_chain: [],
              },
            ],
          },
          { status: 409, headers: { "content-type": "application/problem+json" } },
        ),
    });
    try {
      fireEvent.click(screen.getByRole("button", { name: "确认写入" }));
      expect(await screen.findByText(/哈希变化/)).toBeTruthy();
      expect(screen.getByText(/一行未写/)).toBeTruthy();
      fireEvent.click(screen.getByRole("button", { name: "冲突后重新预览" }));
      expect(screen.queryByRole("button", { name: "确认写入" })).toBeNull();
    } finally {
      page.close();
    }
  });
  // 验证契约：排队提醒列现有写作业链接，首次取消不提交，明确确认才携带看到的编号。
  it("排队提醒列现有写作业链接，首次取消不提交，明确确认才携带看到的编号", async () => {
    const requests: Request[] = [];
    const page = await previewPage(
      { "/api/datasets/creation-writes": () => scenario.queueConflict(["60"]) },
      requests,
    );
    try {
      fireEvent.click(screen.getByRole("button", { name: "确认写入" }));
      expect(await screen.findByLabelText("确认排队作业 60")).toBeTruthy();
      expect(screen.getByRole("button", { name: "确认排队并提交" }).hasAttribute("disabled")).toBe(
        true,
      );
      fireEvent.click(screen.getByRole("button", { name: "取消排队确认" }));
      expect(
        requests.filter(
          (request) => new URL(request.url).pathname === "/api/datasets/creation-writes",
        ),
      ).toHaveLength(1);
    } finally {
      page.close();
    }
  });
  // 验证契约：确认时以409诊断提示新排队编号，确认后带acknowledged_queue_job_ids重提，201才显示卡片。
  it("确认时以409诊断提示新排队编号，确认后带acknowledged_queue_job_ids重提，201才显示卡片", async () => {
    let calls = 0;
    const requests: Request[] = [];
    const page = await previewPage(
      {
        "/api/datasets/creation-writes": () => {
          calls++;
          return calls === 1
            ? scenario.queueConflict(["60"])
            : calls === 2
              ? scenario.queueConflict(["61"])
              : Response.json(scenario.creationWrite, { status: 201 });
        },
      },
      requests,
    );
    try {
      fireEvent.click(screen.getByRole("button", { name: "确认写入" }));
      fireEvent.click(await screen.findByLabelText("确认排队作业 60"));
      fireEvent.click(screen.getByRole("button", { name: "确认排队并提交" }));
      fireEvent.click(await screen.findByLabelText("确认排队作业 61"));
      fireEvent.click(screen.getByRole("button", { name: "确认排队并提交" }));
      expect(await screen.findByRole("region", { name: "建链 #102" })).toBeTruthy();
      expect(page.router.state.location.pathname).toBe("/datasets/links/new");
      const posts = requests.filter(
        (request) => new URL(request.url).pathname === "/api/datasets/creation-writes",
      );
      expect(await posts[2]?.json()).toMatchObject({ acknowledged_queue_job_ids: ["60", "61"] });
    } finally {
      page.close();
    }
  });
  // 验证契约：预览失败、过期、损坏或未完成时禁用确认并保留可修正参数。
  it("预览失败、过期、损坏或未完成时禁用确认并保留可修正参数", async () => {
    const response = () =>
      Response.json(
        {
          type: "about:blank",
          title: "Bad Request",
          status: 400,
          category: "input",
          detail: "预览已过期",
          error_id: "00000000000040008000000000000000",
          diagnostics: [],
        },
        { status: 400, headers: { "content-type": "application/problem+json" } },
      );
    const page = mountPage(
      "/datasets/links/new?preview_job_id=%22101%22",
      creationFetch([], { "/api/datasets/creation-previews/101": response }),
    );
    try {
      expect(await screen.findByText("预览已过期")).toBeTruthy();
      expect(screen.queryByRole("button", { name: "确认写入" })).toBeNull();
      expect(screen.getByLabelText("目标路径")).toBeTruthy();
    } finally {
      page.close();
    }
  });
  // 验证契约：预览作业每 JOB_POLL_INTERVAL_MS 轮询，终态停止，离页取消读取，POST 不重试。
  it("预览作业每 JOB_POLL_INTERVAL_MS 轮询，终态停止，离页取消读取，POST 不重试", async () => {
    const { completedJob } = await import("../jobs/testSupport");
    let reads = 0;
    const requests: Request[] = [];
    const page = await previewPage(
      {
        "/api/jobs/101": () => {
          reads++;
          return Response.json(
            reads === 1
              ? scenario.previewJob
              : {
                  ...completedJob,
                  ...scenario.previewJob,
                  state: "completed",
                  summary: completedJob.summary,
                },
          );
        },
      },
      requests,
    );
    try {
      expect(reads).toBe(2);
      await new Promise((resolve) => setTimeout(resolve, 1100));
      expect(reads).toBe(2);
    } finally {
      page.close();
    }
    const waiting: Request[] = [];
    const held = mountPage(
      "/datasets/links/new?preview_job_id=%22101%22",
      creationFetch(waiting, { "/api/jobs/101": () => new Promise<Response>(() => undefined) }),
    );
    try {
      await waitFor(() => {
        expect(waiting.some((request) => new URL(request.url).pathname === "/api/jobs/101")).toBe(
          true,
        );
      });
    } finally {
      held.close();
    }
    await waitFor(() => {
      expect(
        waiting.find((request) => new URL(request.url).pathname === "/api/jobs/101")?.signal
          .aborted,
      ).toBe(true);
    });
  });
  // 验证契约：写入提交在途禁用重复点击，成功使用文本编号展示原页卡片。
  it("写入提交在途禁用重复点击，成功使用文本编号展示原页卡片", async () => {
    let finish: ((response: Response) => void) | undefined;
    const requests: Request[] = [];
    const page = await previewPage(
      {
        "/api/datasets/creation-writes": () =>
          new Promise<Response>((resolve) => {
            finish = resolve;
          }),
      },
      requests,
    );
    try {
      const button = screen.getByRole("button", { name: "确认写入" });
      fireEvent.click(button);
      await waitFor(() => {
        expect(button.hasAttribute("disabled")).toBe(true);
      });
      fireEvent.click(button);
      expect(
        requests.filter(
          (request) => new URL(request.url).pathname === "/api/datasets/creation-writes",
        ),
      ).toHaveLength(1);
      finish?.(Response.json(scenario.creationWrite, { status: 201 }));
      expect(await screen.findByRole("region", { name: "建链 #102" })).toBeTruthy();
      expect(page.router.state.location.pathname).toBe("/datasets/links/new");
    } finally {
      page.close();
    }
  });
  // 验证契约：真实 Router 支持两个新路由、登录守卫、刷新预览定位及成员访问。
  it("真实 Router 支持两个新路由、登录守卫、刷新预览定位及成员访问", async () => {
    const requests: Request[] = [];
    const page = mountPage(
      "/datasets?selected=" + encodeURIComponent("按任务/libero_10"),
      creationFetch(requests),
    );
    try {
      fireEvent.click(await screen.findByRole("button", { name: "建链" }));
      expect(await screen.findByRole("heading", { name: "建链" })).toBeTruthy();
      expect(page.router.state.location.search).toMatchObject({ dataset_id: "dataset-14" });
      fireEvent.click(screen.getByRole("button", { name: "返回数据集" }));
      fireEvent.click(await screen.findByRole("button", { name: "新增数据集" }));
      expect(await screen.findByRole("heading", { name: "新增数据集" })).toBeTruthy();
      await page.router.navigate({
        to: "/datasets/links/new",
        search: { dataset_id: "dataset-14", preview_job_id: "101" },
      });
      expect(await screen.findByRole("heading", { name: "预览差异" })).toBeTruthy();
      expect(requests.filter((request) => request.method === "POST")).toHaveLength(0);
    } finally {
      page.close();
    }
  });
  // 验证契约：真实 Router search 的数字、数组或非法编号显示可修正提示，不崩溃不请求。
  it("真实 Router search 的数字、数组或非法编号显示可修正提示，不崩溃不请求", async () => {
    const requests: Request[] = [];
    const page = mountPage("/datasets/links/new?preview_job_id=101", creationFetch(requests));
    try {
      expect(await screen.findByText("创建页面参数不合法")).toBeTruthy();
      expect(
        requests.filter((request) => new URL(request.url).pathname.startsWith("/api/datasets")),
      ).toHaveLength(0);
      fireEvent.click(screen.getByRole("button", { name: "重置创建参数" }));
      expect(await screen.findByLabelText("链接名")).toBeTruthy();
    } finally {
      page.close();
    }
  });
  // 验证契约：2^63-1 作业编号保持文本精度，目标路径不写 URL 或浏览器持久存储。
  it("2^63-1 作业编号保持文本精度，目标路径不写 URL 或浏览器持久存储", async () => {
    const requests: Request[] = [];
    const maximum = "9223372036854775807";
    const page = await previewPage(
      {
        "/api/datasets/creation-writes": () =>
          Response.json({ ...scenario.creationWrite, job_id: maximum }, { status: 201 }),
        ["/api/jobs/" + maximum]: () =>
          Response.json({ ...scenario.creationWrite, job_id: maximum }),
      },
      requests,
    );
    try {
      fireEvent.click(screen.getByRole("button", { name: "确认写入" }));
      expect(await screen.findByRole("region", { name: `建链 #${maximum}` })).toBeTruthy();
      expect(page.router.state.location.pathname).toBe("/datasets/links/new");
      expect(screen.getByRole("link", { name: "查看详情" }).getAttribute("href")).toBe(
        "/jobs/" + maximum,
      );
      expect(page.router.state.location.href).not.toContain("fake");
      expect(
        requests
          .filter((request) => request.method === "POST")
          .every((request) => request.credentials === "same-origin"),
      ).toBe(true);
    } finally {
      page.close();
    }
  });
  // 验证契约：恢复失败沿用全局提示与恢复页链接，提交按钮禁用。
  it("恢复失败沿用全局提示与恢复页链接，提交按钮禁用", async () => {
    const requests: Request[] = [];
    const page = mountPage(
      "/datasets/links/new?dataset_id=dataset-14",
      creationFetch(requests, {
        "/api/navigation/recovery-block": () =>
          Response.json({
            blocked: true,
            set_at: "2026-10-30T07:00:00Z",
            job_ids: ["5"],
            items: [],
            total_items: 1,
          }),
      }),
    );
    try {
      expect(await screen.findByText("恢复失败：请管理员处理后再提交")).toBeTruthy();
      expect(screen.getByRole("button", { name: "生成预览" }).hasAttribute("disabled")).toBe(true);
      expect(screen.getByRole("link", { name: "查看对不上的项" })).toBeTruthy();
      fireEvent.click(screen.getByRole("button", { name: "生成预览" }));
      expect(requests.filter((request) => request.method === "POST")).toHaveLength(0);
    } finally {
      page.close();
    }
  });
  // 验证契约：API 默认传输兼容浏览器原生 fetch 的 this 约束，统一认证与 problem 诊断。
  it("API 默认传输兼容浏览器原生 fetch 的 this 约束，统一认证与 problem 诊断", async () => {
    vi.stubGlobal("fetch", function (this: unknown) {
      if (this !== undefined && this !== globalThis) throw new TypeError("Illegal invocation");
      return Promise.resolve(Response.json(creationOptions));
    });
    try {
      const client = createAccountClient({ fetchImpl: defaultFetch, onUnauthorized: vi.fn() });
      expect(
        await getCreationOptions({
          client,
          payload: undefined,
          signal: new AbortController().signal,
        }),
      ).toEqual(creationOptions);
    } finally {
      vi.unstubAllGlobals();
    }
  });
  // 验证契约：创建候选与数据集选择支持空索引及多页，不复制来源/格式词表。
  it("创建候选与数据集选择支持空索引及多页，不复制来源/格式词表", async () => {
    const { datasets } = await import("./testSupport");
    const first = datasets.items[0],
      second = datasets.items[1];
    if (!first || !second) throw new Error("样本不足");
    const page = mountPage(
      "/datasets/links/new",
      creationFetch([], {
        "/api/datasets": (request) => {
          const offset = Number(new URL(request.url).searchParams.get("offset") ?? "0");
          return Response.json({
            ...datasets,
            items: [offset ? second : first],
            offset,
            limit: 1,
            total: 2,
          });
        },
      }),
    );
    try {
      fireEvent.mouseDown(await screen.findByLabelText("数据集"));
      expect(await screen.findByRole("option", { name: "libero_10" })).toBeTruthy();
      fireEvent.click(screen.getByRole("button", { name: "下一页数据集" }));
      expect(await screen.findByRole("option", { name: "other" })).toBeTruthy();
      fireEvent.click(screen.getByRole("option", { name: "other" }));
      expect(screen.getByText("other", { selector: ".ant-select-content" })).toBeTruthy();
      fireEvent.mouseDown(screen.getByLabelText("无元信息时的格式"));
      expect(await screen.findByRole("option", { name: "tar、tar.gz（含分卷）" })).toBeTruthy();
    } finally {
      page.close();
    }
  });
  // 验证契约：时间沿用服务端预览时刻，使用浏览器本地时区且不伪造新统计时间。
  it("时间沿用服务端预览时刻，使用浏览器本地时区且不伪造新统计时间", async () => {
    const { formatDateTime } = await import("../time");
    const page = await previewPage();
    try {
      const time = document.querySelector("time[datetime='2026-10-30T07:00:00Z']");
      expect(time?.textContent).toBe(formatDateTime("2026-10-30T07:00:00Z"));
    } finally {
      page.close();
    }
  });
  // 验证契约：成功后刷新 datasets/jobs 缓存，新数据集和链接可在两棵树及详情页查看。
  it("成功后刷新 datasets/jobs 缓存，新数据集和链接可在两棵树及详情页查看", async () => {
    const page = mountPage("/jobs/102", scenario.creationFetch());
    page.cache.setQueryData(["datasets", "probe"], { value: 1 });
    try {
      expect(await screen.findByRole("heading", { name: "写导航层 #102" })).toBeTruthy();
      await waitFor(() => {
        expect(page.cache.getQueryState(["datasets", "probe"])?.isInvalidated).toBe(true);
      });
    } finally {
      page.close();
    }
  });
});

async function previewPage(
  overrides: Record<string, (request: Request) => Response | Promise<Response>> = {},
  requests: Request[] = [],
): Promise<ReturnType<typeof mountPage>> {
  const page = mountPage(
    "/datasets/links/new?dataset_id=dataset-14",
    creationFetch(requests, overrides),
  );
  try {
    fireEvent.change(await screen.findByLabelText("链接名"), { target: { value: "新链接" } });
    fireEvent.change(screen.getByLabelText("目标路径"), { target: { value: "/fake/disk/new" } });
    await choose("无元信息时的格式", "mcap");
    fireEvent.click(screen.getByRole("button", { name: "生成预览" }));
    await screen.findByRole("heading", { name: "预览差异" });
    return page;
  } catch (error) {
    page.close();
    throw error;
  }
}

// 选择真实antd下拉选项，避免把原生change事件发给只读的combobox输入。
async function choose(label: string, option: string): Promise<void> {
  fireEvent.mouseDown(screen.getByLabelText(label));
  fireEvent.click(await screen.findByRole("option", { name: option }));
}
