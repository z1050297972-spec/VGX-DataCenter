// M1-04 Worker 内部消息协议；原文留在 Worker，主线程每次最多接收一页，避免海量 DOM。
/** 每页最多 20,000 个 UTF-16 码元，用于限制跨线程消息与单次 DOM 更新；不截断文件内容。 */
export const JSON_PAGE_CHARS = 20_000;
/** JSON 解析及每页响应的等待上限 60 秒，超过后终止 Worker，不回退主线程解析。 */
export const JSON_WORKER_TIMEOUT_MS = 60_000;
export type JsonRequest =
  { type: "load"; text: string; format?: boolean } | { type: "page"; page: number };
export interface JsonPage {
  /** 当前页的原始文本，保留未知字段及原始数值表示。 */ text: string;
  /** 从零开始的页码。 */ page: number;
  /** 总页数，空文件也有一页。 */ totalPages: number;
  /** Worker 是否成功解析 JSON；false 时仍可查看原文。 */ valid: boolean;
}
