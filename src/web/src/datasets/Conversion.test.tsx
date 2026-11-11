// M4.5-04：真实详情页只列有清洗规则的型号，提交预览后导航作业详情。
import { fireEvent, screen, waitFor, within } from "@testing-library/react";
import { expect, it } from "vitest";
import { mountPage } from "../scheduling/pageTestSupport";
import { job } from "../jobs/testSupport";
import { account } from "../accounts/testSupport";
import { datasetFetch, detail, taskEntry } from "./testSupport";
import type { DatasetDetail } from "../api/datasets";
import type { ToolList } from "../api/tools";
import { cleaningTools } from "../cleaning/testSupport";

it("只列有清洗规则的型号，提交预览参数后跳到作业详情", async () => {
  const requests: Request[] = [];
  const fallback = datasetFetch(requests);
  const information = {
    ...detail.information,
    content: JSON.stringify({
      dataset_id: "dataset-14",
      robot_model: "Galaxea R1 Lite",
      fields: [],
    }),
  };
  const conversionDetail: DatasetDetail = {
    ...detail,
    information,
    canonical_information: information,
    sources: ["recording-a", "recording-b"].map((id, ordinal) => ({
      ordinal,
      source_id: id,
      original_path: `/tmp/${id}`,
      direct_path: `/tmp/${id}`,
      derived_entry_path: `/tmp/${id}`,
      format: "mcap",
      version: null,
      validation_status: null,
      validation_status_label: "未知",
    })),
  };
  const tools: ToolList = {
    lerobot_environment: cleaningTools.lerobot_environment,
    items: [
      {
        name: "mcap2lerobot",
        version: "0.1.0",
        summary: "MCAP 转 LeRobot",
        input_format: "mcap",
        output_format: "lerobot",
        output_versions: ["v3.0", "v2.1"],
        robot_models: ["Galaxea R1 Lite", "没有规则的型号"],
        cleaning_models: ["Galaxea R1 Lite"],
        needs_gpu: true,
        status: "可用",
        diagnostics: [],
        program_path: "/tmp/library/mcap2lerobot",
        sha256_prefix: "123456789abc",
        readme_available: false,
      },
    ],
  };
  const page = mountPage(
    `/datasets?selected=${encodeURIComponent(taskEntry.entry_path)}`,
    (request) => {
      const path = new URL(request.url).pathname;
      if (path === "/api/auth/me") return Promise.resolve(Response.json(account));
      if (path === "/api/tools") return Promise.resolve(Response.json(tools));
      if (path === "/api/datasets/detail") return Promise.resolve(Response.json(conversionDetail));
      if (path === "/api/jobs/cleaning-preview/mcap2lerobot") {
        requests.push(request.clone());
        return Promise.resolve(Response.json(job, { status: 201 }));
      }
      return fallback(request);
    },
  );
  try {
    const button = await screen.findByRole("button", { name: "清洗预览" });
    await waitFor(() => {
      expect(button.hasAttribute("disabled")).toBe(false);
    });
    fireEvent.click(button);
    const dialog = await screen.findByRole("dialog");
    expect(within(dialog).getByText("清洗预览")).toBeTruthy();
    expect(within(dialog).getByText("Galaxea R1 Lite")).toBeTruthy();
    expect(within(dialog).queryByText("输出格式")).toBeNull();
    expect(within(dialog).queryByText("百分比（%）")).toBeNull();
    fireEvent.mouseDown(within(dialog).getByLabelText("型号配置"));
    expect(await screen.findByRole("option", { name: "Galaxea R1 Lite" })).toBeTruthy();
    expect(screen.queryByRole("option", { name: "没有规则的型号" })).toBeNull();
    fireEvent.click(screen.getByRole("option", { name: "Galaxea R1 Lite" }));
    expect(within(dialog).getByText("工具状态：可用")).toBeTruthy();
    expect(within(dialog).getByLabelText("recording-a")).toHaveProperty("checked", true);
    expect(within(dialog).getByLabelText("recording-b")).toHaveProperty("checked", true);
    fireEvent.click(within(dialog).getByRole("button", { name: "提交清洗预览" }));
    await waitFor(() => {
      expect(page.router.state.location.pathname).toBe(`/jobs/${job.job_id}`);
    });
    const submission = requests.find(
      (request) => new URL(request.url).pathname === "/api/jobs/cleaning-preview/mcap2lerobot",
    );
    expect(await submission?.json()).toEqual({
      dataset_id: "dataset-14",
      source_ids: ["recording-a", "recording-b"],
      robot_model: "Galaxea R1 Lite",
    });
  } finally {
    page.close();
  }
});
