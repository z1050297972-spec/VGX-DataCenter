// 版本查询适配（11 M2）：接口结构由 OpenAPI 生成，只向页面返回版本文字，不在浏览器拼版本。
import { toFailureView } from "./problems";
import { boundedRequest } from "./_request";
import type { HealthClient } from "./client";

/** 版本查询上限 5000 毫秒，与健康查询预算一致，避免页脚无限等待。 */
export const VERSION_TIMEOUT_MS = 5000;

/**
 * 获取当前服务实例的版本文字。
 * @param _client - 同源类型化客户端；复用现有认证和统一错误适配。
 * @param _signal - 调用方取消信号，可省略；已取消时不发送请求。
 * @returns GET /api/version 的 version 字段，逐字保留服务端版本；不自行拼提交号或猜版本。
 * @throws Error HTTP、超时、取消或载荷校验失败时拒绝 Promise，不将失败伪装为“未知”版本。
 * @sideEffects 仅一次只读请求；响应结构使用生成类型，不写缓存、URL 或本地存储。
 * @timeSemantics 最长 VERSION_TIMEOUT_MS 毫秒，复用 boundedRequest；结束清理计时器，无重试。
 */
export function fetchPlatformVersion(
  _client: HealthClient,
  _signal?: AbortSignal,
): Promise<string> {
  return boundedRequest(
    _signal ?? new AbortController().signal,
    VERSION_TIMEOUT_MS,
    async (signal) => {
      const { data, response } = await _client.GET("/api/version", { signal });
      const payload: unknown = data;
      if (
        !response.ok ||
        typeof payload !== "object" ||
        payload === null ||
        !("version" in payload) ||
        typeof payload.version !== "string"
      )
        throw new Error("请求失败", { cause: toFailureView(null) });
      const version = payload.version;
      // Python 按 Unicode 码点限制长度，JS 的 UTF-16 length 不能直接充当同一约束。
      if (
        Array.from(version).length < 1 ||
        Array.from(version).length > 128 ||
        Array.from(version).some((char) => {
          const point = char.codePointAt(0) ?? 0;
          return (
            point < 32 || (point >= 127 && point <= 159) || point === 0x2028 || point === 0x2029
          );
        })
      )
        throw new Error("请求失败", { cause: toFailureView(null) });
      return version;
    },
  );
}
