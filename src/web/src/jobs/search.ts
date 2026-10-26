// 作业筛选的 Router 边界（08、规范 10.6），不自行解析 URLSearchParams。
import { JOB_PAGE_LIMIT, JOB_CURSOR_MAX_CHARS } from "../api/jobs";
import type { JobSearch } from "../api/jobs";

/**
 * 校验 TanStack Router 提供的未信任筛选值。
 * @param _search - Router 已解析的键值；数字 limit 可为安全整数 number 或规范十进制字符串。
 * @returns 类型化 JobSearch；缺省 state 查全部，limit 1-100，cursor 非空且最长 512 字符；未知键忽略。
 * @throws Error 已知字段类型、枚举、范围、数组或游标长度非法；固定文案“作业筛选参数不合法”，不包含原值。
 * @sideEffects 无；路由接住错误并保留筛选表单，显示提示且不发列表请求，不回退查全部。筛选改变清空 cursor。
 * @timeSemantics 同步解析，无时钟和等待；带参数 URL 刷新或分享保留相同条件。
 */
export function validateJobSearch(_search: Record<string, unknown>): JobSearch {
  return {
    state: stateField(_search.state),
    limit: limitField(_search.limit),
    cursor: cursorField(_search.cursor),
  };
}

function stateField(value: unknown): JobSearch["state"] {
  if (value === undefined) return undefined;
  switch (value) {
    case "queued":
      return "queued";
    case "running":
      return "running";
    case "cancelling":
      return "cancelling";
    case "completed":
      return "completed";
    case "cancelled":
      return "cancelled";
    case "interrupted":
      return "interrupted";
    default:
      throw new Error("作业筛选参数不合法");
  }
}
function limitField(value: unknown): JobSearch["limit"] {
  if (value === undefined) return undefined;
  const number = typeof value === "string" && /^[1-9][0-9]*$/.test(value) ? Number(value) : value;
  if (
    typeof number !== "number" ||
    !Number.isSafeInteger(number) ||
    number < 1 ||
    number > JOB_PAGE_LIMIT
  )
    throw new Error("作业筛选参数不合法");
  return number;
}
function cursorField(value: unknown): JobSearch["cursor"] {
  if (value === undefined) return undefined;
  if (typeof value !== "string" || !value || value.length > JOB_CURSOR_MAX_CHARS)
    throw new Error("作业筛选参数不合法");
  return value;
}
