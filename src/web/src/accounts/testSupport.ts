// 账号测试的独立响应样本；只供注入传输使用，不读取浏览器秘密或网络。
import type { Account } from "../api/accounts";
import type { ProblemResponse } from "../api/problems";

/** 合法安全账号样本，编号使用超过 JS 安全整数的十进制文本以暴露精度损失。 */
export const account: Account = {
  account_id: "9007199254740993",
  login_name: "admin",
  display_name: "管理员",
  role: "administrator",
  status: "enabled",
  must_change_password: false,
  created_at: "2026-10-25T12:30:10.123456Z",
  updated_at: "2026-10-25T12:30:10.123456Z",
  created_by: { account_id: null, name: "运维" },
  updated_by: { account_id: null, name: "运维" },
};

/**
 * 构造独立的合法 problem 样本，状态/类别由已批准的 6.2 表给定。
 * @param status - 样本状态码，400/401/403/404/409/422/429/502。
 * @returns 新 Response，可供单次本地传输读取。
 * @throws 无。
 * @sideEffects 只分配内存响应，不发请求。
 * @timeSemantics 无时钟或等待。
 */
export function problemResponse(status: number): Response {
  const titles: Record<number, string> = {
    400: "Bad Request",
    401: "Unauthorized",
    403: "Forbidden",
    404: "Not Found",
    409: "Conflict",
    422: "Unprocessable Entity",
    429: "Too Many Requests",
    502: "Bad Gateway",
  };
  const problem: ProblemResponse = {
    type: "about:blank",
    title: titles[status] ?? "Bad Request",
    status,
    category: status === 409 ? "conflict" : status === 502 ? "external" : "input",
    detail:
      status === 400
        ? "当前密码不正确"
        : status === 409
          ? "账号状态已变化，请重试"
          : status === 502
            ? "密码核验资源繁忙"
            : "请求被拒绝",
    error_id: "00000000000040008000000000000000",
    diagnostics: [],
  };
  return Response.json(problem, {
    status,
    headers: {
      "Content-Type": "application/problem+json",
      ...(status === 429 ? { "Retry-After": "12" } : {}),
    },
  });
}
