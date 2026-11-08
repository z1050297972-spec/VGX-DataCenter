// M4-03转换提交边界；字段取生成类型，复用作业请求预算和账号传输。
import type { components } from "./schema";
import type { AccountCall } from "./accounts";
import { boundedRequest } from "./_request";
import { JOB_REQUEST_TIMEOUT_MS, type Job } from "./jobs";
import { toFailureView } from "./problems";

/** 数据块1至200个，型号与输出版本由服务端按工具清单校验。 */
export type ConversionInput = components["schemas"]["ConversionParameters"];
/** 工具身份只选登记名称，不接收可执行文件或配置路径。 */
export interface ConversionSubmission {
  /** 工具登记包名称。 */ tool: string;
  /** 表单选择，默认值来自数据集和工具清单。 */ parameters: ConversionInput;
}

/**
 * 提交一次转换并返回新作业。
 * @param input - 账号客户端、工具和转换参数以及取消信号。
 * @returns 服务端已提交的排队作业，默认版本已经补齐。
 * @throws Error 参数、权限、网络或请求超时，通过统一诊断呈现。
 * @sideEffects 发出同源POST /api/jobs/convert/{tool_name}；不在浏览器访问数据路径。
 * @timeSemantics 请求最多10秒，不等待GPU或转换完成，不自动重试。
 */
export function submitConversion(input: AccountCall<ConversionSubmission>): Promise<Job> {
  return boundedRequest(input.signal, JOB_REQUEST_TIMEOUT_MS, async (signal) => {
    const response = await input.client.POST("/api/jobs/convert/{tool_name}", {
      params: { path: { tool_name: input.payload.tool } },
      body: input.payload.parameters,
      signal,
    });
    if (!response.data) throw new Error("请求失败", { cause: toFailureView(null) });
    return response.data;
  });
}
