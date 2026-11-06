// 第14张通过页面与 HTTP 边界验证手动全量排查，不替换内部 hook。
import { expect, it } from "vitest";
import { fireEvent, screen, waitFor } from "@testing-library/react";
import { mountPage } from "../scheduling/pageTestSupport";
import { completedJob, job } from "../jobs/testSupport";
import { datasetFetch, panel } from "./testSupport";
import { formatDateTime } from "../time";

// 契约：全量提交、原页进度、完成刷新，以及默认折叠的三段说明。
it("手动排查提交全量扫描并刷新面板，说明默认折叠", async () => {
  const requests: Request[] = [];
  const fallback = datasetFetch(requests);
  let finished = false;
  const updatedAt = "2026-11-06T12:00:00Z";
  const scan = { ...job, type_name: "dataset_rescan", parameters: { dataset_id: null } };
  const page = mountPage("/datasets?panel=true", (request) => {
    const path = new URL(request.url).pathname;
    if (path === "/api/jobs" && request.method === "POST") {
      requests.push(request.clone());
      return Promise.resolve(Response.json(scan, { status: 201 }));
    }
    if (path === `/api/jobs/${job.job_id}`)
      return Promise.resolve(
        Response.json(finished ? { ...completedJob, type_name: "dataset_rescan" } : scan),
      );
    if (path === "/api/datasets/panel" && finished) {
      requests.push(request);
      return Promise.resolve(Response.json({ ...panel, findings: [], indexed_at: updatedAt }));
    }
    return fallback(request);
  });
  try {
    const button = await screen.findByRole("button", { name: "排查" });
    const help = screen.getByRole("button", { name: "排查说明" });
    expect(help.getAttribute("aria-expanded")).toBe("false");
    expect(screen.queryByRole("heading", { name: "原理" })).toBeNull();
    fireEvent.click(help);
    for (const name of ["原理", "检查什么", "常见状况和处理"])
      expect(await screen.findByRole("heading", { name })).toBeTruthy();
    expect(screen.getByText(/上次排查时间/).textContent).toContain(
      formatDateTime("2026-10-29T12:00:00Z"),
    );
    fireEvent.click(button);
    expect(await screen.findByRole("region", { name: `排查 #${job.job_id}` })).toBeTruthy();
    expect(page.router.state.location.pathname).toBe("/datasets");
    const submissions = requests.filter((request) => request.method === "POST");
    expect(submissions).toHaveLength(1);
    expect(await submissions[0]?.json()).toEqual({
      type_name: "dataset_rescan",
      parameters: { dataset_id: null },
    });
    expect(await screen.findByRole("progressbar", { name: "作业卡片进度" })).toBeTruthy();
    finished = true;
    await waitFor(
      () => {
        expect(screen.getByText(/上次排查时间/).textContent).toContain(formatDateTime(updatedAt));
      },
      { timeout: 4000 },
    );
    expect(screen.queryByText("TOP_LEVEL_UNREGISTERED · 共 7 条（展示 1 条）")).toBeNull();
  } finally {
    page.close();
  }
});
