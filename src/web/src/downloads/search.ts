// URL 仅允许不丢精度的预览作业编号，不存放仓库凭据和表单。
/** 下载页可分享的预览定位参数。 */
export interface DownloadSearch {
  /** 规范十进制作业编号，以字符串保留。 */
  preview_job_id?: string;
  /** 已生成的暂存扫描作业编号。 */
  staging_job_id?: string;
  /** 非法输入时显示提示而不回显。 */
  invalidDownloadSearch?: true;
}

/**
 * 验证 Router 已解码的下载页搜索参数。
 * @param input - 搜索参数原始对象。
 * @returns 规范编号或无回显的错误标记。
 * @throws 无。
 * @sideEffects 无。
 * @timeSemantics 同步纯校验。
 */
export function validateDownloadSearch(input: Record<string, unknown>): DownloadSearch {
  const preview = input.preview_job_id;
  const staging = input.staging_job_id;
  if (!validId(preview) || !validId(staging)) return { invalidDownloadSearch: true };
  return {
    preview_job_id: typeof preview === "string" ? preview : undefined,
    staging_job_id: typeof staging === "string" ? staging : undefined,
  };
}

// TanStack Router 可能把未引用的数字解析为 number；不能转换以免损失 64 位精度。
function validId(value: unknown): boolean {
  if (value === undefined) return true;
  return (
    typeof value === "string" &&
    /^[1-9][0-9]{0,18}$/.test(value) &&
    (value.length < 19 || value <= "9223372036854775807")
  );
}
