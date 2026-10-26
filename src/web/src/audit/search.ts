// 日志筛选契约（07，规范 10.6）：由 TanStack Router validateSearch/useSearch/useNavigate 管理。
// 不解析 URLSearchParams；HTTP 字段只用生成类型，保留偏移后转 UTC，不依赖本机时区做测试。
import type { LoginSearch, OperationSearch } from "../api/audit";

/**
 * 验证操作日志路由的 search，并返回类型化筛选。
 * @param _search - Router 提供的不可信键值，允许未知值类型；不是自行解析的 searchStr。
 * @returns OperationSearch；缺失字段保持缺失，时间要求带偏移的 ISO 8601 并规范化 UTC；start 含、end 不含。account_id 表示操作人，target_account_id 表示对象账号，两者可各自省略或同时按交集查询；编号保留十进制文本且不超过 2^63-1，limit 1-100，cursor 最长 512 字符。未知键忽略，不回显其值。
 * @throws Error 已知字段非法、数组、重复值、naive/倒置时间、未知枚举、越界编号/limit 或超长游标；由路由诊断边界显示安全输入提示，不把输入放异常。
 * @sideEffects 无；不发请求、不直接改地址栏或存储。页面用对应路由的 useSearch 读取，不回退为全部记录；任一账号筛选改变时页面须清 cursor，两个值都参与 Query key。
 * @timeSemantics 同步校验，无时钟/等待；时间比较用绝对 UTC 时刻，回拨不影响筛选。
 */
// eslint-disable-next-line @typescript-eslint/no-unused-vars -- 参数由调用契约要求，函数当前只抛错；开始使用该参数后删除此豁免。
export function validateOperationSearch(_search: Record<string, unknown>): OperationSearch {
  throw new Error("未实现");
}

/**
 * 验证登录日志路由的 search，并返回类型化筛选。
 * @param _search - TanStack Router 提供的未信任键值；不接收或解析 URLSearchParams。
 * @returns LoginSearch；时间 [start,end)、账号编号、kind/result 和游标交集，缺失表示全部；未知账号通过 account_missing 结果筛选，不靠输入登录名。
 * @throws Error 已知字段形状/枚举/带偏移时间/编号/limit/游标非法，使用安全诊断，不回显值。
 * @sideEffects 无；筛选提交由页面 useNavigate 更新 typed search，改变任意筛选时清 cursor。
 * @timeSemantics 同步，无墙钟/等待；同一有效 URL 刷新和分享得到同一筛选条件。
 */
// eslint-disable-next-line @typescript-eslint/no-unused-vars -- 参数由调用契约要求，函数当前只抛错；开始使用该参数后删除此豁免。
export function validateLoginSearch(_search: Record<string, unknown>): LoginSearch {
  throw new Error("未实现");
}
