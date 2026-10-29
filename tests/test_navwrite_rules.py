"""写入规则的契约测试清单（M1-07：JSON 写出 L10/L11、按格式入口生成 L8/L9、编号分配 L6、来源.json）。

骨架阶段全部跳过；实现时每个测试先红后绿。样本取 tests/fixtures/nav 的假导航层（EgoProDemo、agibot_world_alpha），
不碰真实路径。真实导航层副本的对拍由 Claude 在验收 1 里做，不在这里。
"""

import pytest


def test_load_keeps_key_order_and_unknown_keys() -> None:
    """契约 load_navigation_json：键顺序与文件一致，不认识的键原样保留。"""
    pytest.skip("M1-07：该契约尚未实现")


def test_load_rejects_invalid_documents() -> None:
    """契约 load_navigation_json：非 UTF-8、非 JSON、顶层不是对象、超过 MAX_DOCUMENT_BYTES 都报 InputError，诊断不回显正文。"""
    pytest.skip("M1-07：该契约尚未实现")


def test_dump_format_l11() -> None:
    """L11：dump_navigation_json 写 2 空格缩进、ensure_ascii=False、结尾恰好一个换行；新键追加在末尾。"""
    pytest.skip("M1-07：该契约尚未实现")


def test_roundtrip_is_byte_identical_except_derived() -> None:
    """L11 验收：对假导航层每份 JSON，load 再 dump 与原字节相同，只允许 L10 推导字段带来的差异。"""
    pytest.skip("M1-07：该契约尚未实现")


def test_regenerate_derived_fields_writes_version_null() -> None:
    """L10：按格式入口省略 version 时，regenerate_derived_fields 显式写出 version: null，键已存在则留在原位。"""
    pytest.skip("M1-07：该契约尚未实现")


def test_regenerate_derived_fields_does_not_add_schema_version() -> None:
    """L10：数据集信息.json 不补 schema_version；原始路径.json 缺 schema_version 时同样不补。"""
    pytest.skip("M1-07：该契约尚未实现")


def test_regenerate_rederives_entry_paths() -> None:
    """L8：regenerate_derived_fields 重新推导 links[].entry_path 和 sources[].entry_path，与 reading.derive_source_entry_path 一致。"""
    pytest.skip("M1-07：该契约尚未实现")


def test_select_reachable_sources_boundary() -> None:
    """L8：direct_path 等于链接目标或位于其下（紧跟 /）才算够得着；/a/b 不覆盖 /a/bc。"""
    pytest.skip("M1-07：该契约尚未实现")


def test_select_reachable_sources_keeps_order_and_partitions() -> None:
    """L8、L9：两组各自保持输入顺序，不重叠，合起来等于输入。"""
    pytest.skip("M1-07：该契约尚未实现")


def test_filter_subtasks_drops_unreferenced_tasks() -> None:
    """L8：filter_subtasks 只保留引用到入选数据块的任务，任务内部 sources[] 同样筛，task_count 重算，未知键保留。"""
    pytest.skip("M1-07：该契约尚未实现")


def test_filter_subtasks_reports_counts() -> None:
    """L8：返回被筛掉的引用条数和整体去掉的 task_key；入选集合为空时所有任务都去掉。"""
    pytest.skip("M1-07：该契约尚未实现")


def test_generate_egopro_demo_format_entry() -> None:
    """L8 样本一：EgoProDemo 的 lerobot/3.0 入口只链接 EgoProStandard-body/lerobot，生成的 sources[] 只含该目录下的数据块，子任务数与规范副本筛选结果一致。"""
    pytest.skip("M1-07：该契约尚未实现")


def test_generate_alpha_omits_unreachable_blocks() -> None:
    """L9 样本二：agibot_world_alpha 的按格式入口生成后少 3 个链接够不着的数据块，omitted_source_ids 恰好列出它们，规范副本里它们的 entry_path 仍是绝对路径。"""
    pytest.skip("M1-07：该契约尚未实现")


def test_generate_copies_dataset_info_verbatim() -> None:
    """L8：数据集信息.json 整份复制，生成的字节与规范副本相同。"""
    pytest.skip("M1-07：该契约尚未实现")


def test_generate_uses_current_entry_links() -> None:
    """L8：链接以该按格式入口自己的 links[] 为准，不用规范副本的链接。"""
    pytest.skip("M1-07：该契约尚未实现")


def test_generate_rejects_wrong_dataset_or_view() -> None:
    """契约 generate_format_entry：canonical 与 current 的 dataset_id 不同、current 不是按格式入口时报 InputError。"""
    pytest.skip("M1-07：该契约尚未实现")


def test_allocate_dataset_id_scans_removed() -> None:
    """L6 验收：已移除/ 下有 dataset-40_x/ 时，分配到 dataset-41。"""
    pytest.skip("M1-07：该契约尚未实现")


def test_allocate_dataset_id_takes_max_not_count() -> None:
    """L6：按任务/ 里编号有空洞时取最大加 1，不取个数加 1。"""
    pytest.skip("M1-07：该契约尚未实现")


def test_allocate_dataset_id_min_two_digits() -> None:
    """L6：没有任何数据集时分配 dataset-01，至少两位。"""
    pytest.skip("M1-07：该契约尚未实现")


def test_allocate_dataset_id_refuses_unreadable_entry() -> None:
    """契约 scan_max_dataset_number：有入口读不出 dataset_id 时报 InputError，不分配可能重复的编号。"""
    pytest.skip("M1-07：该契约尚未实现")


def test_allocate_dataset_id_refuses_unnumbered_removed_dir() -> None:
    """契约 scan_max_dataset_number：已移除/ 下有不带编号前缀的目录名时报 InputError。"""
    pytest.skip("M1-07：该契约尚未实现")


def test_read_provenance_absent() -> None:
    """契约 read_provenance：文件不存在为 ABSENT，不当作错误。"""
    pytest.skip("M1-07：该契约尚未实现")


def test_read_provenance_invalid_never_becomes_empty() -> None:
    """契约 read_provenance：软链接、非普通文件、坏 JSON、未知 schema_version 为 INVALID 且给出原因，不替换成空文档。"""
    pytest.skip("M1-07：该契约尚未实现")


def test_read_provenance_valid_draft_sample() -> None:
    """来源.json 第 1 版：15 号票草样去掉 _example_platform_record 后可读，lineage 一条，字段对得上。"""
    pytest.skip("M1-07：该契约尚未实现")


def test_new_provenance_has_empty_lineage() -> None:
    """契约 new_provenance：新文件 lineage 为空表示来历未知；origin 不是未知却没有 set_by 时报 InputError。"""
    pytest.skip("M1-07：该契约尚未实现")


def test_with_data_origin_records_who_and_when() -> None:
    """契约 with_data_origin：替换 data_origin 与 data_origin_set_by，lineage 原样；kind 不是人工类时报 InputError。"""
    pytest.skip("M1-07：该契约尚未实现")


def test_with_lineage_record_is_append_only() -> None:
    """契约 with_lineage_record：只在末尾追加，已有记录一条不改；record_id 不是下一个编号时报 InputError。"""
    pytest.skip("M1-07：该契约尚未实现")


def test_dump_provenance_key_order() -> None:
    """契约 dump_provenance：键顺序固定为 schema_version、dataset_id、dataset_name、data_origin、data_origin_set_by、collection_task_id、lineage，空值写 null。"""
    pytest.skip("M1-07：该契约尚未实现")
