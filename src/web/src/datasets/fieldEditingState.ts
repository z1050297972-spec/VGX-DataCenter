// M1.5-02 编辑会话状态；HTTP查询与草稿基线共用账号生命周期，不维护文件全文缓存。
import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { useAccountClient, useCurrentAccount } from "../accounts/runtime";
import {
  getEditableFields,
  previewFieldEdits,
  confirmFieldEdits,
  type EditableDocument,
  type EditablePage,
  type FieldEdits,
} from "../api/fieldEditing";
import { DATASET_GC_TIME_MS, DATASET_STALE_TIME_MS } from "../api/datasets";
import { useJobAction } from "../jobs/_actions";
import { useRecoveryBlock } from "../navigation/queries";

/** 草稿只含改动项，不保存分页文件全文。 */
export type FieldChange = FieldEdits["changes"][number];
/** 一次已挂载编辑会话；取消或身份切换会卸载并清空。 */
export type FieldEditingState = ReturnType<typeof useFieldEditing>;

/**
 * 维护一个数据集的分页草稿与预览确认生命周期。
 * @param datasetId - 永久数据集编号，非路径。
 * @returns 页面查询、局部草稿、写入门禁和显式操作回调。
 * @throws 无；HTTP故障保留在查询或提交结果中。
 * @sideEffects 分页GET、预览POST和确认POST；成功确认留在原页显示作业卡片，卸载取消。
 * @timeSemantics 表单不轮询或重试；观察到过期基线后锁住本次编辑会话。
 */
export function useFieldEditing(datasetId: string) {
  const client = useAccountClient();
  const account = useCurrentAccount();
  const [offset, setOffset] = useState(0);
  const [expired, setExpired] = useState(false);
  const [changes, setChanges] = useState<Record<string, FieldChange>>({});
  const preview = useJobAction<FieldEdits>(
    (payload, signal) => previewFieldEdits({ client, payload, signal }),
    false,
  );
  const confirm = useJobAction<string>(
    (payload, signal) => confirmFieldEdits({ client, payload, signal }),
    { cardTitle: "修改字段" },
  );
  const block = useRecoveryBlock();
  const busy = preview.isPending || confirm.isPending || confirm.isSuccess;
  const allowed = !block.isError && block.data?.blocked === false;
  // 信息和数据块同时展示，共享草稿；每个文档保留自己的哈希，不能用当前页替代另一份基线。
  const options = (document: EditableDocument, pageOffset: number) => ({
    queryKey: [
      "datasets",
      account.data?.account_id,
      "editable-fields",
      datasetId,
      document,
      pageOffset,
    ],
    queryFn: async ({ signal }: { signal: AbortSignal }) => {
      const data = await getEditableFields({
        client,
        payload: { datasetId, document, offset: pageOffset },
        signal,
      });
      if (outdated(data, changes)) setExpired(true);
      return data;
    },
    retry: false,
    staleTime: DATASET_STALE_TIME_MS,
    gcTime: DATASET_GC_TIME_MS,
    refetchOnWindowFocus: false,
    refetchOnReconnect: false,
  });
  const information = useQuery(options("数据集信息.json", 0));
  const sources = useQuery(options("原始路径.json", offset));
  const stale = expired || outdated(information.data, changes) || outdated(sources.data, changes);
  function resetPreview(): void {
    preview.reset();
    confirm.reset();
  }
  function update(
    data: EditablePage,
    field: EditablePage["fields"][number],
    value: FieldChange["value"],
  ): void {
    if (busy || stale) return;
    const { document, sha256 } = data;
    resetPreview();
    const key = JSON.stringify([document, field.path]);
    setChanges((current) => {
      const remaining = Object.fromEntries(
        Object.entries(current).filter(([name]) => name !== key),
      );
      if (JSON.stringify(value) === JSON.stringify(field.value)) return remaining;
      return {
        ...remaining,
        [key]: { document, expected_sha256: sha256, path: field.path, value },
      };
    });
  }
  function selectOffset(value: number): void {
    setOffset(value);
    resetPreview();
  }
  function submitPreview(): void {
    if (!allowed || busy || stale || !Object.keys(changes).length) return;
    confirm.reset();
    preview.mutate({ dataset_id: datasetId, changes: Object.values(changes) });
  }
  function submitWrite(identifier: string): void {
    if (allowed && !busy && !stale && !confirm.isError) confirm.mutate(identifier);
  }
  return {
    offset,
    changes,
    preview,
    confirm,
    block,
    busy,
    allowed,
    information,
    sources,
    stale,
    update,
    selectOffset,
    submitPreview,
    submitWrite,
  };
}

function outdated(data: EditablePage | undefined, changes: Record<string, FieldChange>): boolean {
  return (
    data !== undefined &&
    Object.values(changes).some(
      (change) => change.document === data.document && change.expected_sha256 !== data.sha256,
    )
  );
}
