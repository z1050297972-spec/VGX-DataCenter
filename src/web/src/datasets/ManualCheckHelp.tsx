// 第14张的只读排查说明：复用 antd 折叠与表格，内容不参与扫描或诊断判定。
import type { ReactElement } from "react";
import { Collapse, Table, Typography } from "antd";

const situations = [
  {
    situation: "数据块不存在（SOURCE_MISSING，需处理）",
    meaning: "登记的数据块在盘上找不到了",
    action: "数据还在别处：改成新路径；确实删了：从 原始路径.json 删掉这个数据块",
  },
  {
    situation: "链接断开 / 指向错误（LINK_*，需处理）",
    meaning: "导航层的链接打不开或指错地方",
    action: '在数据集页面"改指向"修正',
  },
  {
    situation: "两份副本不一致（*_MISMATCH）",
    meaning: "按任务和按格式的同一份信息内容不同",
    action: "在编辑里重新保存一次，平台会同步两份副本",
  },
  {
    situation: "JSON 读不了 / 缺字段（JSON_*，需处理）",
    meaning: "导航文件损坏或格式不对",
    action: "从备份恢复，或手工修正后排查",
  },
  {
    situation: "顶层未登记（TOP_LEVEL_UNREGISTERED）",
    meaning: "/mnt/datasets 下有平台不认识的目录",
    action: "不是数据集就删掉或移走",
  },
  {
    situation: "引用文件不存在（*_REFERENCE_MISSING、SUMMARY_PATH_MISSING）",
    meaning: "文字或字段里提到的文件不在了",
    action: "删掉这条引用，或者把文件放回去；不影响数据本身",
  },
  {
    situation: "排除目录不存在（EXCLUDED_PATH_MISSING）",
    meaning: '登记为"排除"的目录已经没了',
    action: "从排除列表里删掉",
  },
  {
    situation: "目录下有未登记内容（ROOT_CONTENT_UNLINKED）",
    meaning: "数据集目录里有东西既没链接也没排除，比如脚本、环境",
    action: "是数据：补链接；不是数据：登记为排除，或不管",
  },
  {
    situation: "下载残留（DOWNLOAD_INCOMPLETE）",
    meaning: "有 .aria2/.incomplete 文件，下载可能没完成",
    action: "核对文件是否完整，必要时重新下载，再删掉残留文件",
  },
  {
    situation: "数据盘离线（STORAGE_OFFLINE，需处理）",
    meaning: "数据盘没挂载或读不到",
    action: "检查硬盘和挂载，恢复后排查",
  },
];

/**
 * 显示默认折叠的排查原理、检查范围和处理说明。
 * @returns 可折叠说明卡片，标明需优先处理的问题。
 * @throws 无。
 * @sideEffects 无；展开只改变本地展示状态。
 * @timeSemantics 静态说明，不请求或轮询。
 */
export function ManualCheckHelp(): ReactElement {
  return (
    <Collapse
      items={[
        {
          key: "help",
          label: "排查说明",
          children: (
            <>
              <Typography.Title level={4}>原理</Typography.Title>
              <ul>
                <li>
                  导航层（/mnt/datasets 下的三份 JSON
                  和链接）是平台的事实来源。"排查"会把导航层和两块数据盘重新读一遍，核对它们是否对得上，结果显示在这里。
                </li>
                <li>
                  排查只读不写：不改导航层，也不改数据盘。每次结果覆盖上一次，不会越积越多。修好一个问题后再点一次"排查"，对应的消息就会消失。
                </li>
                <li>
                  什么时候会自动检查：保存导航层字段、新建数据集、改链接之后，平台会自动刷新相关数据集；平台重启后会做一次全量检查。其他时候都要手动点"排查"。
                </li>
              </ul>
              <Typography.Title level={4}>检查什么</Typography.Title>
              <ul>
                <li>
                  导航文件：JSON
                  能不能读、必填字段、编号和名称是否一致、按任务和按格式两份副本是否一致、顶层有没有不认识的目录。
                </li>
                <li>
                  链接：链接是否断开、是否指向登记的数据盘和数据集目录、和 原始路径.json
                  的声明是否一致。
                </li>
                <li>
                  数据块和引用：原始路径.json 里的数据块路径在不在、排除目录在不在、14
                  项文字和子任务里引用的文件在不在、数据集目录下有没有既没链接也没排除的内容。
                </li>
                <li>存储：数据盘是否在线，有没有没下载完的残留文件（.aria2、.incomplete）。</li>
              </ul>
              <Typography.Title level={4}>常见状况和处理</Typography.Title>
              <Typography.Paragraph>优先处理标为“需处理”的问题。</Typography.Paragraph>
              <Table
                rowKey="situation"
                pagination={false}
                scroll={{ x: "max-content" }}
                dataSource={situations}
                columns={[
                  { title: "状况", dataIndex: "situation" },
                  { title: "意思", dataIndex: "meaning" },
                  { title: "怎么处理", dataIndex: "action" },
                ]}
              />
            </>
          ),
        },
      ]}
    />
  );
}
