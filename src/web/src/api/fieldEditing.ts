// M1.5-02 字段编辑的HTTP边界；仅使用OpenAPI生成类型与已有有界请求。
import type { components } from "./schema";
import type { AccountCall } from "./accounts";
import { boundedRequest } from "./_request";
import { JOB_REQUEST_TIMEOUT_MS, type Job } from "./jobs";

/** 一页规范副本表单及原字节摘要。 */
export type EditablePage = components["schemas"]["EditableFieldsPage"];
/** 只含修改项的预览输入。 */
export type FieldEdits = components["schemas"]["FieldEditParameters"];
/** 受限文档名，不能传任意文件路径。 */
export type EditableDocument = EditablePage["document"];
interface PageInput {
  /** 永久编号，非导航路径。 */ datasetId: string;
  /** 受限三份JSON文件名。 */ document: EditableDocument;
  /** 非负条目偏移，页大小由服务端默认值限定。 */ offset: number;
}

/**
 * 读取规范副本的分页编辑值。
 * @param input - 账号客户端、编号、文档、偏移及生命周期信号。
 * @returns 一页字段与该文件的原字节哈希。
 * @throws Error 认证、文件不可用或请求失败，由统一诊断展示。
 * @sideEffects 一次GET，不读取存储根，不写导航。
 * @timeSemantics 请求最多JOB_REQUEST_TIMEOUT_MS，取消即停止等待，不重试。
 */
export function getEditableFields(input: AccountCall<PageInput>): Promise<EditablePage> {
  return boundedRequest(input.signal, JOB_REQUEST_TIMEOUT_MS, async (signal) => {
    const result = await input.client.GET("/api/datasets/{dataset_id}/editable-fields", {
      params: {
        path: { dataset_id: input.payload.datasetId },
        query: { document: input.payload.document, offset: input.payload.offset },
      },
      signal,
    });
    if (!result.data) throw new Error("编辑字段不可用");
    return result.data;
  });
}

/**
 * 为已修改字段提交只读预览。
 * @param input - 生成契约的局部改动及取消信号。
 * @returns queued的预览作业，完成后读取统一报告。
 * @throws Error 参数、权限或传输失败。
 * @sideEffects 一次POST，只新增预览作业，不直接修改导航。
 * @timeSemantics 最多JOB_REQUEST_TIMEOUT_MS，不重试；未确认不提交写入。
 */
export function previewFieldEdits(input: AccountCall<FieldEdits>): Promise<Job> {
  return boundedRequest(input.signal, JOB_REQUEST_TIMEOUT_MS, async (signal) => {
    const result = await input.client.POST("/api/navigation/fields/preview", {
      body: input.payload,
      signal,
    });
    if (!result.data) throw new Error("字段预览未返回作业");
    return result.data;
  });
}

/**
 * 确认已审阅的字段预览。
 * @param input - 预览编号文本和取消信号，不发送新的字段内容。
 * @returns nav_write_apply排队作业，冲突由409诊断返回。
 * @throws Error 过期预览、并发变化、权限或传输失败。
 * @sideEffects 一次POST，服务端只读核对后提交统一写作业。
 * @timeSemantics 最多JOB_REQUEST_TIMEOUT_MS，不自动重试或重算预览。
 */
export function confirmFieldEdits(input: AccountCall<string>): Promise<Job> {
  return boundedRequest(input.signal, JOB_REQUEST_TIMEOUT_MS, async (signal) => {
    const result = await input.client.POST("/api/navigation/fields/previews/{job_id}/apply", {
      params: { path: { job_id: input.payload } },
      signal,
    });
    if (!result.data) throw new Error("确认字段写入未返回作业");
    return result.data;
  });
}
