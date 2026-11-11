// M4-01 验收 5：真实页面和路由只替换 HTTP 传输，验证不可用工具的可见状态和诊断。
import { fireEvent, screen } from "@testing-library/react";
import { expect, it } from "vitest";
import type { ToolList, LeRobotEnvironment } from "../api/tools";
import { cleaningTools } from "../cleaning/testSupport";
import { mountPage, pageFetch } from "../scheduling/pageTestSupport";

it("工具库中的指纹不符显示红色状态，展开后显示五段诊断", async () => {
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
        robot_models: ["Galaxea R1 Lite"],
        cleaning_models: ["Galaxea R1 Lite"],
        needs_gpu: true,
        status: "指纹不符",
        program_path: "/tmp/tools/mcap2lerobot",
        sha256_prefix: "f09daa6af5d4",
        diagnostics: [
          {
            level: "error",
            category: "input",
            stage: "工具登记",
            source: "平台",
            objects: [{ key: "tool", value: "mcap2lerobot" }],
            rule: "tools.fingerprint",
            actual: "sha256 0123456789ab，16 字节",
            expected: "sha256 f09daa6af5d4，16 字节",
            consequence: "不能用于转换",
            next_step: "工具程序已变化，需要执行线重新登记",
            error_chain: [],
          },
        ],
      },
    ],
  };
  const fallback = pageFetch();
  const page = mountPage("/", (request) =>
    new URL(request.url).pathname === "/api/tools"
      ? Promise.resolve(Response.json(tools))
      : fallback(request),
  );
  try {
    fireEvent.click(await screen.findByRole("link", { name: "工具库" }));
    const status = await screen.findByText("指纹不符");
    // jsdom 保留 CSS 变量表达式；核对实际 color 使用红色令牌，不检查组件 props 或类名。
    expect(window.getComputedStyle(status).color).toBe("var(--ant-red-7)");
    fireEvent.click(screen.getByRole("button", { name: "查看诊断" }));
    expect(await screen.findByText(/工具程序已变化，需要执行线重新登记/)).toBeTruthy();
    expect(screen.getByText(/对象：tool=mcap2lerobot/)).toBeTruthy();
    expect(screen.getByText(/规则：tools.fingerprint/)).toBeTruthy();
    expect(
      screen.getByText(/实际：sha256 0123456789ab，16 字节；期望：sha256 f09daa6af5d4/),
    ).toBeTruthy();
    expect(screen.getByText(/后果：不能用于转换/)).toBeTruthy();
  } finally {
    page.close();
  }
});

// 环境三种业务状态及探测失败均保留状态、版本和说明，卡片不显示指纹标签或值。
it.each<{ status: LeRobotEnvironment["status"]; label: string }>([
  { status: "unconfigured", label: "未配置" },
  { status: "available", label: "可用" },
  { status: "mismatch", label: "不符" },
  { status: "error", label: "检查失败" },
])("LeRobot 环境 $label 卡片保留版本和说明，不显示指纹", async ({ status, label }) => {
  const fallback = pageFetch();
  const page = mountPage("/tools", (request) =>
    new URL(request.url).pathname === "/api/tools"
      ? Promise.resolve(
          Response.json({
            ...cleaningTools,
            lerobot_environment: {
              ...cleaningTools.lerobot_environment,
              status,
              expected_version: "0.6.2",
              actual_version: "0.6.1",
              expected_fingerprint: "expected-hash",
              actual_fingerprint: "actual-hash",
              message: "环境探测说明",
            },
          }),
        )
      : fallback(request),
  );
  try {
    const card = (await screen.findByText("LeRobot 环境")).closest(".ant-card");
    expect(card).not.toBeNull();
    const cardText = card?.textContent;
    expect(cardText).toContain("状态");
    expect(cardText).toContain(label);
    expect(cardText).toContain("期望版本");
    expect(cardText).toContain("0.6.2");
    expect(cardText).toContain("实际版本");
    expect(cardText).toContain("0.6.1");
    expect(cardText).toContain("环境探测说明");
    expect(cardText).not.toContain("指纹");
    expect(cardText).not.toContain("expected-hash");
    expect(cardText).not.toContain("actual-hash");
    expect(
      screen.getAllByRole("columnheader", { name: "有清洗规则的型号" }).length,
    ).toBeGreaterThan(0);
  } finally {
    page.close();
  }
});
