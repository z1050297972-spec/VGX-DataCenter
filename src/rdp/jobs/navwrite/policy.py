"""写导航层底座的具名常量（M1-07、ADR 0009）；不读配置、时钟或文件。"""

from typing import Final

# 状态目录下三个子目录名；ADR 0009 与运维手册 4.4 的固定名字，不可由配置改写。
NAV_JOURNAL_DIRNAME: Final = "nav-journal"
NAV_CHANGES_DIRNAME: Final = "nav-changes"
# 预览结果的存放位置：预览是只读 worker 作业，结果太大不放进作业记录（M1-07 工单）。
NAV_PREVIEWS_DIRNAME: Final = "nav-previews"

# 写入日志、预览、变更记录三种磁盘格式各自的版本号；读到更大的版本一律拒绝解析。
JOURNAL_FORMAT_VERSION: Final = 1
PREVIEW_FORMAT_VERSION: Final = 1
CHANGE_FORMAT_VERSION: Final = 1
PROVENANCE_FORMAT_VERSION: Final = 1

# 写入日志的文件名。journal.json 先写成 journal.json.tmp、fsync，再 rename，所以它出现就是完整的；
# 只有 .tmp 或目录为空，说明日志没落完整，导航层一处都还没动（ADR 0009）。
JOURNAL_FILENAME: Final = "journal.json"
JOURNAL_IMAGES_DIRNAME: Final = "images"
# 临时文件命名：同目录、点号开头，再带作业编号和步骤序号，恢复时能按名字找到并清理。
TEMP_NAME_TEMPLATE: Final = ".{name}.rdp-{job_id}-{index}.tmp"

# 变更记录里"全文存进 JSON"的单文件上限，单位字节。M1-07 工单：1 MiB 以下存修改前后的全文。
CHANGE_INLINE_MAX_BYTES: Final = 1024 * 1024
# 恢复失败标记里最多保存的对不上的项，防止一次大批量改写把数据库行撑大；总数另存。
MARKER_ITEM_SAMPLE_LIMIT: Final = 200
# 预览报告里"每一处单独列出"的 Markdown/notes 替换项上限；总数始终完整（规范 6.6）。
PREVIEW_LISTED_CHANGE_LIMIT: Final = 500
# 操作日志明细里最多列出的数据集编号（AuditValues 限长）；更多的只记个数。
AUDIT_DATASET_ID_LIMIT: Final = 20

# 新增数据集编号的最小位数，L6："至少两位"。
DATASET_NUMBER_MIN_DIGITS: Final = 2
DATASET_ID_PREFIX: Final = "dataset-"
# 被移除的入口所在的顶层目录；分配编号时要扫描它（L6、L7）。
REMOVED_DIRNAME: Final = "已移除"
TASK_VIEW_DIRNAME: Final = "按任务"

# 来源.json 的数据来源取值，GLOSSARY "Data Origin 数据来源"；缺文件等同"未知"。
DATA_ORIGINS: Final = ("真机采集", "UMI 采集", "ego 采集", "仿真生成", "开源下载", "未知")
