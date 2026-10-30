// JSON 共享查看器（M1-04）：使用原生 Worker 和 Vite 打包，不自造解析器或在主线程回退解析。
import { useEffect, useRef, useState, type ReactElement } from "react";
import { Alert, Button } from "antd";
import { DiagnosticCard } from "../DiagnosticCard";
import { toFailureView } from "../api/problems";
import { JSON_WORKER_TIMEOUT_MS, type JsonPage, type JsonRequest } from "./jsonProtocol";

interface JsonViewerProps {
  /** API 返回的原始 UTF-8 文本解码结果，最大值受服务端限制。 */ content: string;
  /** 用于无障碍区域名称的文件名。 */ label: string;
}
/**
 * 在独立 Worker 解析 JSON 并按页显示原文。
 * @param props - 原文和区域标签；文件变化时调用方用入口与文件名作为 key。
 * @returns 解析提示、原文分页或统一失败视图；不把无效 JSON 隐藏。
 * @throws 无；Worker 不可用或超时以 DiagnosticCard 呈现。
 * @sideEffects 创建一个 Vite module Worker；只传原文一次，翻页发送页码；卸载终止并清理监听和计时器。
 * @timeSemantics 每次 Worker 响应最多 JSON_WORKER_TIMEOUT_MS；不重试，不在主线程 JSON.parse。
 */
export function JsonViewer(props: JsonViewerProps): ReactElement {
  const [page, setPage] = useState<JsonPage | null>(null);
  const [pending, setPending] = useState(true);
  const [failed, setFailed] = useState(false);
  const send = useRef<((request: JsonRequest) => void) | null>(null);
  useEffect(() => {
    let worker: Worker | undefined;
    let timer: ReturnType<typeof setTimeout> | undefined;
    let active = true;
    // 故障和卸载都走同一个释放入口，避免重复 terminate，也阻止排队消息恢复旧内容。
    const release = () => {
      const current = worker;
      worker = undefined;
      if (current) {
        current.onmessage = null;
        current.onerror = null;
        current.onmessageerror = null;
        current.terminate();
      }
      send.current = null;
      clearTimeout(timer);
    };
    const fail = () => {
      if (!active) return;
      setFailed(true);
      setPending(false);
      active = false;
      release();
    };
    try {
      worker = new Worker(new URL("./json.worker.ts", import.meta.url), { type: "module" });
      worker.onmessage = (event: MessageEvent<JsonPage>) => {
        if (!active) return;
        clearTimeout(timer);
        setPage(event.data);
        setPending(false);
      };
      worker.onerror = fail;
      worker.onmessageerror = fail;
      send.current = (request) => {
        clearTimeout(timer);
        timer = setTimeout(fail, JSON_WORKER_TIMEOUT_MS);
        try {
          worker?.postMessage(request);
        } catch {
          fail();
        }
      };
      send.current({ type: "load", text: props.content });
    } catch {
      fail();
    }
    return () => {
      active = false;
      release();
    };
  }, [props.content]);
  function go(next: number): void {
    setPending(true);
    send.current?.({ type: "page", page: next });
  }
  return (
    <section aria-label={props.label}>
      {pending && <p role="status">正在解析 JSON…</p>}
      {failed ? (
        <DiagnosticCard failure={toFailureView(null)} />
      ) : (
        page && (
          <>
            {!page.valid && <Alert type="warning" title="JSON 无法解析，以下为原文" />}
            <p>
              第 {page.page + 1} / {page.totalPages} 页
            </p>
            <Button
              aria-label="上一页 JSON"
              disabled={pending || page.page === 0}
              onClick={() => {
                go(page.page - 1);
              }}
            >
              上一页
            </Button>
            <Button
              aria-label="下一页 JSON"
              disabled={pending || page.page + 1 >= page.totalPages}
              onClick={() => {
                go(page.page + 1);
              }}
            >
              下一页
            </Button>
            <pre className="dataset-json">{page.text}</pre>
          </>
        )
      )}
    </section>
  );
}
