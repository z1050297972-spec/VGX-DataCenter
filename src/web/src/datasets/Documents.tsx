// 详情中已读取的两份 JSON 按需展开；始终使用当前入口原文，不用规范副本冒充当前文件（M1-03/04）。
import { useState, type ReactElement } from "react";
import { Button } from "antd";
import type { DatasetDetail } from "../api/datasets";
import { DiagnosticEntries } from "../DiagnosticCard";
import { JsonViewer } from "./JsonViewer";

/**
 * 展开一份当前入口的原始 JSON 文档。
 * @param props - document 来自详情接口，content 为 null 表示不可读取。
 * @param props.document - 所选入口的现场原文与读取诊断。
 * @returns 打开入口、文档诊断及有界分页原文。
 * @throws 无；Worker 错误由查看器显示。
 * @sideEffects 展开才创建 Worker，关闭即终止；不重复请求详情。
 * @timeSemantics 原文属于 detail.observed_at，关闭重开解析同次读取内容。
 */
export function NavigationDocumentViewer(props: {
  /** 现场 JSON 原文，不是索引投影。 */ document: DatasetDetail["information"];
}): ReactElement {
  const [open, setOpen] = useState(false);
  const document = props.document;
  return (
    <section>
      <Button
        onClick={() => {
          setOpen(!open);
        }}
      >
        {open ? "关闭" : "打开"} {document.name}
      </Button>
      {open && (
        <>
          <DiagnosticEntries diagnostics={document.diagnostics} />
          {document.content === null ? (
            <p>文件不可读取</p>
          ) : (
            <JsonViewer
              key={`${document.entry_path}:${document.sha256 ?? "unknown"}`}
              content={document.content}
              label={document.name}
            />
          )}
        </>
      )}
    </section>
  );
}
