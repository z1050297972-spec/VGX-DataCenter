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
    text = request.format && valid ? pretty(request.text) : request.text;
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

// JSON.stringify会舍入超过JS安全整数范围的数字；只重排已通过JSON.parse验证的原始词法，
// 保留数值、转义和键顺序。这里不解析业务内容，也不代替JSON.parse验证。
const opening = new Set<string | undefined>(["{", "["]);
const closing = new Set<string | undefined>(["}", "]"]);
function pretty(raw: string): string {
  const tokens = raw.match(/"(?:\\.|[^"\\])*"|[{}\[\],:]|[^\s{}\[\],:"]+/g) ?? [];
  let depth = 0;
  let result = "";
  for (const [index, token] of tokens.entries()) {
    const previous = tokens[index - 1];
    const next = tokens[index + 1];
    if (opening.has(token)) {
      result += token;
      depth++;
      if (!closing.has(next)) result += "\n" + "  ".repeat(depth);
    } else if (closing.has(token)) {
      depth--;
      if (!opening.has(previous)) result += "\n" + "  ".repeat(depth);
      result += token;
    } else if (token === ",") result += ",\n" + "  ".repeat(depth);
    else if (token === ":") result += ": ";
    else result += token;
  }
  return result;
}
