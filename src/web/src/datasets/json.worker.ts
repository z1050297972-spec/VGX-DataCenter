// 数据集 JSON 的 Worker 入口（M1-04），用标准 JSON 解析器，不访问网络或文件系统。
// 保留原文而不 stringify 解析结果，避免改变未知字段、空白或超过 JS 安全整数的数值表示。
import { JSON_PAGE_CHARS, type JsonPage, type JsonRequest } from "./jsonProtocol";
let text = "";
let valid = false;
self.onmessage = (event: MessageEvent<JsonRequest>) => {
  const request = event.data;
  if (request.type === "load") {
    try {
      JSON.parse(request.text);
      valid = true;
    } catch {
      valid = false;
    }
    text = request.text;
  }
  const totalPages = Math.max(1, Math.ceil(text.length / JSON_PAGE_CHARS));
  const page = request.type === "load" ? 0 : Math.max(0, Math.min(totalPages - 1, request.page));
  const response: JsonPage = {
    text: text.slice(page * JSON_PAGE_CHARS, (page + 1) * JSON_PAGE_CHARS),
    page,
    totalPages,
    valid,
  };
  self.postMessage(response);
};
