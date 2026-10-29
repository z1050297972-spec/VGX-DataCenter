// M1-06：重建索引操作在已有日志筛选中有中文展示，并接受可分享的操作码。
import { expect, it } from "vitest";
import { OPERATION_LABELS, validateOperationSearch } from "./search";

it("重建索引操作可筛选且显示中文标签", () => {
  expect(validateOperationSearch({ operation: "rebuild_index" })).toEqual({
    operation: "rebuild_index",
  });
  expect(OPERATION_LABELS).toHaveProperty("rebuild_index", "重建索引");
});
