// M1-10 来源标注 HTTP 边界；类型只取生成契约，所有请求沿用账号客户端与有界等待。
import type { components } from "./schema";
import type { AccountCall } from "./accounts";
import { boundedRequest } from "./_request";
import { JOB_REQUEST_TIMEOUT_MS, type Job } from "./jobs";

/** 六选一中文来源及永久数据集编号，不接收路径或操作者。 */
export type DataOriginInput = components["schemas"]["DataOriginParameters"];
/** 服务端生成的同一份计划报告；页面不重新计算旧值或改动文件。 */
export type NavigationPreview = components["schemas"]["NavigationPreviewResponse"];

/**
 * 提交只读的数据来源预览作业。
 * @param input - 账号客户端、生成的参数和生命周期取消信号。
 * @returns 新 queued 作业，预览结果在该作业完成后读取。
 * @throws Error 请求、权限或参数失败经统一诊断返回。
 * @sideEffects 一次 POST，不写导航层，不自动确认。
 * @timeSemantics 最多 JOB_REQUEST_TIMEOUT_MS，无重试；卸载取消等待。
 */
export function previewDataOrigin(input: AccountCall<DataOriginInput>): Promise<Job> {
  return boundedRequest(input.signal, JOB_REQUEST_TIMEOUT_MS, async (signal) => {
    const response = await input.client.POST("/api/navigation/data-origin/preview", {
      body: input.payload,
      signal,
    });
    if (!response.data) throw new Error("预览提交未返回作业");
    return response.data;
  });
}

/**
 * 读取一个已成功完成的预览报告。
 * @param input - 账号客户端、十进制文本预览编号和取消信号。
 * @returns 包含文件路径、新旧来源及 UTC 生成时间的报告。
 * @throws Error 作业未成功、预览过期、权限或传输失败经统一诊断返回。
 * @sideEffects 一次 GET，只读状态目录；不获取计划中的文件正文。
 * @timeSemantics 最多 JOB_REQUEST_TIMEOUT_MS，无重试；报告不会在页面上重新计算。
 */
export function getNavigationPreview(input: AccountCall<string>): Promise<NavigationPreview> {
  return boundedRequest(input.signal, JOB_REQUEST_TIMEOUT_MS, async (signal) => {
    const response = await input.client.GET("/api/navigation/previews/{job_id}", {
      params: { path: { job_id: input.payload } },
      signal,
    });
    if (!response.data) throw new Error("预览报告不可用");
    const data = response.data;
    return {
      ...data,
      report: {
        ...data.report,
        // openapi-fetch 把嵌套元组拓宽成数组；按生成契约恢复二元组，不用断言掩盖长度错误。
        notices: data.report.notices.map((notice) => ({
          ...notice,
          objects: notice.objects.map<
            NavigationPreview["report"]["notices"][number]["objects"][number]
          >((object) => {
            const [key, value] = object;
            if (object.length !== 2 || key === undefined || value === undefined)
              throw new Error("预览提示对象不符合二元组契约");
            return [key, value];
          }),
        })),
      },
    };
  });
}

/**
 * 确认已查看的预览，提交第 07 张的通用写入作业。
 * @param input - 账号客户端、预览编号文本和取消信号；编号必须能无损表示为 JSON 整数。
 * @returns 新 nav_write_apply 作业，调用方进入作业详情。
 * @throws Error 编号超出 JavaScript 安全整数范围，或请求/权限/冲突失败；不静默舍入编号。
 * @sideEffects 一次 POST /api/jobs；不重新生成计划，不自动重试。
 * @timeSemantics 请求预算 JOB_REQUEST_TIMEOUT_MS；返回不代表 worker 已完成写入。
 */
export function applyNavigationPreview(input: AccountCall<string>): Promise<Job> {
  const identifier = Number(input.payload);
  // 后端通用参数是 JSON 整数；超过安全范围就拒绝，避免把另一份预览的编号提交出去。
  if (!/^[1-9][0-9]*$/.test(input.payload) || !Number.isSafeInteger(identifier))
    return Promise.reject(new Error("预览编号超出浏览器安全整数范围，请联系管理员处理。"));
  return boundedRequest(input.signal, JOB_REQUEST_TIMEOUT_MS, async (signal) => {
    const response = await input.client.POST("/api/jobs", {
      body: { type_name: "nav_write_apply", parameters: { preview_job_id: identifier } },
      signal,
    });
    if (!response.data) throw new Error("确认写入未返回作业");
    return response.data;
  });
}
