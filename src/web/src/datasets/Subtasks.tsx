// 子任务的按需请求边界；关闭后卸载查询与 Worker，避免跨入口保留大文件（M1-04）。
import { useEffect, useState, type ReactElement } from "react";
import { useQuery } from "@tanstack/react-query";
import { Button } from "antd";
import { useAccountClient, useCurrentAccount } from "../accounts/runtime";
import { DATASET_STALE_TIME_MS, DATASET_GC_TIME_MS, getDatasetSubtasks } from "../api/datasets";
import { DiagnosticCard } from "../DiagnosticCard";
import { toFailureView } from "../api/problems";
import { JsonViewer } from "./JsonViewer";

interface SubtasksProps {
  /** 相对导航入口。 */ entryPath: string;
  /** 本次响应发现过期时通知详情，供其展示单数据集重扫按钮。 */ onStale: () => void;
}

/**
 * 显示一个子任务文件的按需打开入口。
 * @param props - entryPath 是详情响应指定的子任务入口，不推导存储路径。
 * @returns 打开/关闭按钮与独立 JSON 查看器。
 * @throws 无；失败通过统一诊断展示。
 * @sideEffects 只有打开时挂载读取查询；关闭释放大文件缓存、取消请求并终止 Worker。
 * @timeSemantics 打开时读取一次、不轮询或重试，再打开重新读现场文件。
 */
export function SubtasksViewer(props: SubtasksProps): ReactElement {
  const [open, setOpen] = useState(false);
  return (
    <section>
      <Button
        onClick={() => {
          setOpen(!open);
        }}
      >
        {open ? "关闭 子任务.json" : "打开 子任务.json"}
      </Button>
      {open && <SubtasksContent entryPath={props.entryPath} onStale={props.onStale} />}
    </section>
  );
}

function SubtasksContent({ entryPath, onStale }: SubtasksProps): ReactElement {
  const client = useAccountClient();
  const identity = useCurrentAccount();
  const query = useQuery({
    queryKey: ["datasets", identity.data?.account_id, "subtasks", entryPath],
    queryFn: ({ signal }) => getDatasetSubtasks({ client, payload: entryPath, signal }),
    retry: false,
    staleTime: DATASET_STALE_TIME_MS,
    gcTime: DATASET_GC_TIME_MS,
    refetchOnWindowFocus: false,
    refetchOnReconnect: false,
  });
  useEffect(() => {
    if (query.data?.indexStale) onStale();
  }, [query.data?.indexStale, onStale]);
  return (
    <>
      {query.isPending && <p role="status">正在读取子任务…</p>}
      {query.error && <DiagnosticCard failure={toFailureView(query.error)} />}
      {query.data && (
        <>
          <JsonViewer key={query.data.sha256} content={query.data.text} label="子任务.json" />
        </>
      )}
    </>
  );
}
