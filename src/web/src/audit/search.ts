// 日志筛选契约（07，规范 10.6）：由 TanStack Router validateSearch/useSearch/useNavigate 管理。
// 不解析 URLSearchParams；HTTP 字段只用生成类型，保留偏移后转 UTC，不依赖本机时区做测试。
import {
  AUDIT_PAGE_LIMIT,
  AUDIT_CURSOR_MAX_CHARS,
  type LoginSearch,
  type OperationSearch,
} from "../api/audit";

/**
 * 验证操作日志路由的 search，并返回类型化筛选。
 * @param _search - Router 提供的不可信键值，允许未知值类型；不是自行解析的 searchStr。
 * @returns OperationSearch；缺失字段保持缺失，时间要求带偏移的 ISO 8601 并规范化 UTC；start 含、end 不含。account_id 表示操作人，target_account_id 表示对象账号，两者可各自省略或同时按交集查询；编号输出为十进制文本且不超过 2^63-1；输入也接受 Number.isSafeInteger 且为正的 number，超出安全整数范围的 number 因可能丢精度而拒绝，字符串编号规则不变。limit 1-100，cursor 最长 512 字符。未知键忽略，不回显其值。
 * @throws Error 已知字段非法、数组、重复值、naive/倒置时间、未知枚举、越界编号/limit 或超长游标；路由将错误转换为无效筛选状态，保留页面及筛选表单并显示“日志筛选参数不合法”，不发日志请求、不回退查全部，不把输入放异常。
 * @sideEffects 无；不发请求、不直接改地址栏或存储。页面用对应路由的 useSearch 读取，不回退为全部记录；任一账号筛选改变时页面须清 cursor，两个值都参与 Query key。
 * @timeSemantics 同步校验，无时钟/等待；时间比较用绝对 UTC 时刻，回拨不影响筛选。
 */
export function validateOperationSearch(_search: Record<string, unknown>): OperationSearch {
  const result: OperationSearch = common(_search);
  if (_search.target_account_id !== undefined)
    result.target_account_id = identifier(_search.target_account_id);
  if (_search.operation !== undefined)
    result.operation = choice(_search.operation, OPERATION_LABELS);
  if (_search.result !== undefined) result.result = choice(_search.result, OPERATION_RESULTS);
  return result;
}

/**
 * 验证登录日志路由的 search，并返回类型化筛选。
 * @param _search - TanStack Router 提供的未信任键值；不接收或解析 URLSearchParams。
 * @returns LoginSearch；时间 [start,end)、账号编号、kind/result 和游标交集，缺失表示全部；编号接受规范十进制字符串或正的安全整数 number，统一返回字符串，超出安全整数范围的 number 拒绝；未知账号通过 account_missing 结果筛选，不靠输入登录名。
 * @throws Error 已知字段形状/枚举/带偏移时间/编号/limit/游标非法；路由保留页面及筛选表单，显示“日志筛选参数不合法”且不发日志请求，不回显值。
 * @sideEffects 无；筛选提交由页面 useNavigate 更新 typed search，改变任意筛选时清 cursor。
 * @timeSemantics 同步，无墙钟/等待；同一有效 URL 刷新和分享得到同一筛选条件。
 */
export function validateLoginSearch(_search: Record<string, unknown>): LoginSearch {
  const result: LoginSearch = common(_search);
  if (_search.kind !== undefined) result.kind = choice(_search.kind, LOGIN_KINDS);
  if (_search.result !== undefined) result.result = choice(_search.result, LOGIN_RESULTS);
  return result;
}

/** 操作类型展示与校验共用表；类型来自生成契约，新增类型须补中文标签。 */
export const OPERATION_LABELS = {
  create_account: "新建账号",
  set_role: "改角色",
  disable_account: "停用",
  enable_account: "启用",
  reset_password: "重置口令（管理员）",
  reset_password_from_ops: "重置口令（运维）",
  delete_account: "删除账号",
  change_password: "改自己的口令",
  create_first_admin: "创建首个管理员",
  set_retention: "修改保留期",
} satisfies Record<NonNullable<OperationSearch["operation"]>, string>;
/** 操作结果筛选和展示使用同一字典。 */
export const OPERATION_RESULTS = { success: "成功", failure: "失败" };
/** 登录事件类型和生成接口保持一致。 */
export const LOGIN_KINDS = {
  login: "登录",
  logout: "登出",
  session_expired: "会话过期",
} satisfies Record<NonNullable<LoginSearch["kind"]>, string>;
/** 未知账号仅通过结果筛选，不收集输入登录名。 */
export const LOGIN_RESULTS = {
  success: "成功",
  wrong_password: "口令错误",
  disabled: "已停用",
  waiting: "等待中",
  account_missing: "账号不存在",
  failure: "失败",
} satisfies Record<NonNullable<LoginSearch["result"]>, string>;

// SQLite 正编号上限，校验不做 Number 精度截断。
const MAX_ACCOUNT_ID = 9223372036854775807n;

// 所有坏参数共用固定提示，避免在路由错误边界暴露输入原文。
function invalid(): never {
  throw new Error("日志筛选参数不合法");
}
// Router 会把未加引号的数字解析成 number；仅安全整数可无损转为编号文本。
function identifier(value: unknown): string {
  if (typeof value === "number") {
    if (!Number.isSafeInteger(value) || value <= 0) return invalid();
    return String(value);
  }
  if (
    typeof value !== "string" ||
    !/^[1-9][0-9]{0,18}$/.test(value) ||
    BigInt(value) > MAX_ACCOUNT_ID
  )
    return invalid();
  return value;
}
// 仅选择字典中声明的枚举，不接受任意输入作为属性名。
function choice<T extends string>(value: unknown, labels: Record<T, string>): T {
  for (const key in labels) if (key === value) return key;
  return invalid();
}
// 路由文本和表单整数均做范围检查，不做布尔或浮点强制转换。
function pageSize(value: unknown): number {
  const parsed =
    typeof value === "string" && /^[1-9][0-9]{0,2}$/.test(value) ? Number(value) : value;
  if (
    typeof parsed !== "number" ||
    !Number.isInteger(parsed) ||
    parsed < 1 ||
    parsed > AUDIT_PAGE_LIMIT
  )
    return invalid();
  return parsed;
}
// 游标只检查非空文本及长度，内容由服务端验证。
function cursor(value: unknown): string {
  if (typeof value !== "string" || !value.length || value.length > AUDIT_CURSOR_MAX_CHARS)
    return invalid();
  return value;
}
// Date 负责偏移换算；小数单独保留六位，防止毫秒舍入改变数据库的包含/不包含边界。
function moment(value: unknown): string {
  if (typeof value !== "string") return invalid();
  const match =
    /^(\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2})(?:\.(\d{1,6}))?(Z|[+-](?:[01]\d|2[0-3]):[0-5]\d)$/.exec(
      value,
    );
  if (!match) return invalid();
  const local = match[1] ?? "";
  validateCalendar(local);
  const utc = new Date(local + (match[3] ?? "")).toISOString();
  if (utc.length !== 24 || utc.startsWith("0000")) return invalid();
  return utc.slice(0, 19) + "." + (match[2] ?? "").padEnd(6, "0") + "Z";
}
// 两类日志复用同一组时间、账号和分页规则，省略字段保持省略。
function common(search: Record<string, unknown>): OperationSearch & LoginSearch {
  const result: OperationSearch & LoginSearch = {};
  if (search.start !== undefined) result.start = moment(search.start);
  if (search.end !== undefined) result.end = moment(search.end);
  if (result.start && result.end && result.start >= result.end) return invalid();
  if (search.account_id !== undefined) result.account_id = identifier(search.account_id);
  if (search.limit !== undefined) result.limit = pageSize(search.limit);
  if (search.cursor !== undefined) result.cursor = cursor(search.cursor);
  return result;
}

// Date 会把 2 月 30 日滚动到 3 月，必须先按原日历分量核对。
function validateCalendar(local: string): void {
  const localDate = new Date(local + "Z");
  if (
    !Number.isFinite(localDate.getTime()) ||
    localDate.toISOString().slice(0, 19) !== local ||
    local.startsWith("0000")
  )
    invalid();
}
