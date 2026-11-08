// M1.5-16 大小说明验收；直接验证共用大小区域的用户可见内容。
import { expect, it } from "vitest";
import { cleanup, render, screen, within } from "@testing-library/react";
import { DatasetSizeSummary } from "./Sizes";
import { detail } from "./testSupport";

// 契约：统计大小区域说明每天补跑规则、导航写入后的范围和手动入口，不再提到回填。
it("大小区域展示三条统计说明", () => {
  try {
    render(<DatasetSizeSummary size={detail.dataset_size} actions={null} />);
    const items = within(screen.getByRole("list", { name: "大小统计说明" })).getAllByRole(
      "listitem",
    );
    expect(items).toHaveLength(3);
    expect(items[0]?.textContent).toContain("本地时间凌晨 03:00 统计全部数据集");
    expect(items[0]?.textContent).toContain("下次启动时补统计一次，当天只补这一次");
    expect(items[1]?.textContent).toContain("只重新统计这次写入涉及的数据集");
    expect(items[1]?.textContent).toContain("例如编辑字段之后");
    expect(items[1]?.textContent).not.toContain("回填");
    expect(items[2]?.textContent).toContain("点“统计大小”立即统计");
  } finally {
    cleanup();
  }
});
