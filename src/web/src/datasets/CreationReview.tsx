// M1-08 创建预览与确认部件；只展示保存的计划投影，不在前端重算差异或编号。
import { useState, type ReactElement } from "react";
import { Alert, Button, Card, Typography } from "antd";
import { Link } from "@tanstack/react-router";
import { formatDateTime } from "../time";
import { DiagnosticCard } from "../DiagnosticCard";
import type { CreationPreview, QueuedNavigationJob } from "../api/datasetCreation";
import type { RequestFailureView } from "../api/problems";

/** 预览审阅组件输入。 */
export interface CreationReviewProps {
  /** 成功预览，report.creation 必须非空；缺失时不允许确认。 */
  preview: CreationPreview;
  /** 写入提交请求在途时为 true，防止重复点击。 */
  pending: boolean;
  /** 本预览已经成功提交时为 true；仅禁用再次确认，仍可修改参数开始新预览。 */
  submitted: boolean;
  /** 用户看过差异后打开确认流程，先刷新同数据集排队提醒。 */
  onConfirm: () => void;
  /** 返回表单编辑并使本预览确认资格失效。 */
  onEdit: () => void;
}

/**
 * 展示将写文件、链接、数据块、根变化及按格式入口，并请求明确确认。
 * @param props - 保存的预览、pending 和确认/编辑回调。
 * @returns 操作、预计编号、参数、完整差异路径、检查范围及 notices；noop 明确显示已经是这样了。
 * @throws 无；不合约预览禁用确认并由页面给出诊断。
 * @sideEffects 仅发出 onConfirm/onEdit；不把文件正文放入页面，不运行写入作业。
 * @timeSemantics created_at 使用 formatDateTime 显示浏览器本地时区；确认中的按钮禁用。
 */
export function CreationReview(props: CreationReviewProps): ReactElement {
  const details = props.preview.report.creation;
  if (!details) return <Alert type="error" title="预览缺少创建差异，请重新预览" />;
  return (
    <section className="creation-review" aria-label="预览差异">
      <Typography.Title level={3}>预览差异</Typography.Title>
      <p>
        数据集：{props.preview.dataset_name}（{props.preview.dataset_id}）
      </p>
      <p>
        预览时间：
        <time dateTime={props.preview.created_at}>{formatDateTime(props.preview.created_at)}</time>
      </p>
      {details.noop && <Alert type="success" title="已经是这样了，本次不会写入" />}
      <p>
        格式：{details.resolved_format ?? "未重新检查"}；版本：{details.resolved_version ?? "null"}
        ；来源：
        {details.metadata_source === "meta_info"
          ? "meta/info.json"
          : details.metadata_source === "selected_format"
            ? "用户选择（缺少 meta/info.json）"
            : "已有同目标链接，未读取元信息"}
      </p>
      <div className="creation-review-grid">
        <PathList title="新增或更新的文件" items={details.file_paths} />
        <PathList title="新增目录" items={details.directory_paths} />
        <PathList title="生成的格式入口" items={details.format_entry_paths} />
        <PathList title="本次勾选的格式入口" items={details.selected_format_entry_paths} />
        <PathList title="dataset_roots 新增" items={details.dataset_roots_added} />
        <PathList
          title="新增链接"
          items={details.links.map((item) => `${item.path} → ${item.target_path}`)}
        />
      </div>
      <Card title="新增数据块">
        <div className="creation-scroll" aria-label="新增数据块">
          <pre>{JSON.stringify(details.sources_added, null, 2)}</pre>
        </div>
      </Card>
      <Card title="检查范围">
        {props.preview.report.checks.map((item) => (
          <p key={item.name}>
            {item.name}：
            {item.scope === "full" ? "全量" : item.scope === "sampled" ? "抽样" : "执行后检查"}；
            {item.detail}
          </p>
        ))}
      </Card>
      {props.preview.report.notices.map((notice, index) => (
        <Alert key={`${notice.code}:${String(index)}`} type="info" title={notice.message} />
      ))}
      <div className="creation-actions">
        <Button aria-label="修改参数" disabled={props.pending} onClick={props.onEdit}>
          修改参数
        </Button>
        <Button
          type="primary"
          aria-label="确认写入"
          loading={props.pending}
          disabled={props.pending || props.submitted}
          onClick={props.onConfirm}
        >
          确认写入
        </Button>
      </div>
    </section>
  );
}

/** 排队提醒的显式确认输入。 */
export interface CreationQueueWarningProps {
  /** 当前同数据集排队写作业，按编号升序；展示对应 /jobs/$jobId 链接。 */
  jobs: QueuedNavigationJob[];
  /** POST 进行中为 true，禁用继续提交。 */
  pending: boolean;
  /** 明确确认当前看到的编号；新排队编号出现时必须再次提示。 */
  onAcknowledge: (jobIds: string[]) => void;
  /** 取消确认，保留可编辑表单。 */
  onCancel: () => void;
}

/**
 * 提醒已有排队作业将修改相同数据集。
 * @param props - 当前排队列表、请求状态及明确确认/取消回调。
 * @returns 提醒与作业链接；说明可能冲突，提供继续提交和返回编辑。
 * @throws 无。
 * @sideEffects 只发出用户实际看到的编号，不用通配确认跳过后续新提醒。
 * @timeSemantics 反映提交前队列快照，不保证随后无新作业；最终冲突由 worker L12 校验。
 */
export function CreationQueueWarning(props: CreationQueueWarningProps): ReactElement {
  const [selected, setSelected] = useState<string[]>([]);
  const all = props.jobs.length > 0 && props.jobs.every((item) => selected.includes(item.job_id));
  return (
    <section aria-label="排队作业确认" className="creation-queue">
      <Alert
        type="warning"
        title="已有排队写作业，请逐项勾选确认"
        description="这些作业可能先修改同一数据集；实际写入仍会重新核对预览状态。"
      />
      {props.jobs.map((item) => (
        <label key={item.job_id} className="creation-check">
          <input
            type="checkbox"
            aria-label={`确认排队作业 ${item.job_id}`}
            disabled={props.pending}
            checked={selected.includes(item.job_id)}
            onChange={(event) => {
              setSelected((values) =>
                event.target.checked
                  ? [...values, item.job_id]
                  : values.filter((id) => id !== item.job_id),
              );
            }}
          />
          <Link to="/jobs/$jobId" params={{ jobId: item.job_id }}>
            作业 #{item.job_id}
          </Link>
        </label>
      ))}
      <div className="creation-actions">
        <Button aria-label="取消排队确认" disabled={props.pending} onClick={props.onCancel}>
          返回修改
        </Button>
        <Button
          type="primary"
          aria-label="确认排队并提交"
          disabled={!all || props.pending}
          loading={props.pending}
          onClick={() => {
            props.onAcknowledge(props.jobs.map((item) => item.job_id));
          }}
        >
          确认排队并提交
        </Button>
      </div>
    </section>
  );
}

/** 冲突反馈不复制服务端诊断协议。 */
export interface CreationConflictProps {
  /** HTTP 或写作业中的统一冲突诊断，包含对象、实际、期望及下一步。 */
  failure: RequestFailureView;
  /** 丢弃旧预览确认资格，回到当前参数重新预览。 */
  onPreviewAgain: () => void;
}

/**
 * 显示预览后导航状态变化的差异与重新预览入口。
 * @param props - 服务端冲突诊断和回到预览的回调。
 * @returns 复用 DiagnosticCard 的差异展示，提示本次冲突一行未写。
 * @throws 无。
 * @sideEffects 点击后触发 onPreviewAgain，不自动重提旧计划。
 * @timeSemantics 冲突是写锁内复核结果；重新预览生成新的状态与编号观察。
 */
export function CreationConflict(props: CreationConflictProps): ReactElement {
  return (
    <section aria-label="创建冲突">
      <DiagnosticCard failure={props.failure} />
      <Button aria-label="冲突后重新预览" onClick={props.onPreviewAgain}>
        重新预览
      </Button>
    </section>
  );
}

function PathList({ title, items }: { title: string; items: string[] }): ReactElement {
  return (
    <Card title={title}>
      {items.length ? (
        <ul className="creation-paths">
          {items.map((item, index) => (
            <li key={`${item}:${String(index)}`}>{item}</li>
          ))}
        </ul>
      ) : (
        <p>无</p>
      )}
    </Card>
  );
}
