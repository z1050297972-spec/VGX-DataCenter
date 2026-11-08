"""机器人和采集词表的公开 HTTP 契约，只使用临时迁移库。"""

from pathlib import Path

import pytest
from account_api_support import api_case


def test_robot_lifecycle(tmp_path: Path) -> None:
    """登记、编辑、停用、恢复、删除各写日志；MAC 规范化且删除编号不复用。"""
    with api_case(tmp_path) as case:
        assert case.login().status_code == 200
        body = {"name": " 一号 ", "robot_model": " R1 ", "macs": [{"mac": "AA-BB-CC-DD-EE-FF"}]}
        response = case.client.post("/api/robots", json=body)
        assert response.status_code == 201, response.text
        robot = response.json()
        assert robot["name"] == "一号" and robot["robot_model"] == "R1"
        assert robot["macs"] == [{"interface": None, "mac": "aa:bb:cc:dd:ee:ff"}]
        assert robot["ssh_port"] == 22 and robot["reference_count"] == 0
        assert robot["created_by"] == {"account_id": "1", "name": "管理员", "deleted": False}
        path = f"/api/robots/{robot['robot_id']}"
        changed = case.client.put(path, json=body | {"name": "二号", "address": "robot.local"})
        assert changed.status_code == 200 and changed.json()["address"] == "robot.local"
        assert case.client.post(path + "/retire").json()["status"] == "retired"
        assert case.client.get("/api/robots").json()["items"][0]["status"] == "retired"
        assert case.client.post(path + "/restore").json()["status"] == "active"
        assert case.client.delete(path).status_code == 204
        assert case.client.get("/api/robots").json() == {"items": []}
        logs = case.client.get("/api/audit/operations").json()["items"]
        operations = [item for item in logs if item["operation"].endswith("_robot")]
        assert {item["operation"] for item in operations} == {
            "create_robot",
            "update_robot",
            "retire_robot",
            "restore_robot",
            "delete_robot",
        }
        assert len(operations) == 5
        assert all(item["target"]["object_id"] == str(robot["robot_id"]) for item in operations)
        again = case.client.post("/api/robots", json=body)
        assert again.status_code == 201 and again.json()["robot_id"] > robot["robot_id"]


def test_vocabulary_seeds_and_lifecycle(tmp_path: Path) -> None:
    """迁移初始词表来源正确；两个词表各自完成新增、改名、启停和删除，记录对象不混淆。"""
    with api_case(tmp_path) as case:
        case.login()
        vocabulary = case.client.get("/api/collection-vocabulary").json()
        assert [(item["name"], item["data_origin"]) for item in vocabulary["methods"]] == [
            ("主从臂遥操作", "真机采集"),
            ("VR 遥操作", "真机采集"),
            ("UMI 手持", "UMI 采集"),
            ("头戴相机", "ego 采集"),
            ("仿真脚本", "仿真生成"),
        ]
        assert [item["name"] for item in vocabulary["purposes"]] == ["训练", "评测", "演示", "试采"]
        for item in vocabulary["methods"] + vocabulary["purposes"]:
            assert item["created_by"] == {"account_id": None, "name": "系统", "deleted": False}
            assert item["reference_count"] == 0 and item["status"] == "active"
        for kind, extra, object_kind in (
            ("methods", {"data_origin": "真机采集"}, "collection_method"),
            ("purposes", {}, "collection_purpose"),
        ):
            base = "/api/collection-vocabulary/" + kind
            created = case.client.post(base, json={"name": " 自定义 "} | extra)
            assert created.status_code == 201, created.text
            item = created.json()
            assert item["name"] == "自定义"
            path = f"{base}/{item['id']}"
            changed = case.client.put(path, json={"name": "已改名"} | extra)
            assert changed.status_code == 200 and changed.json()["id"] == item["id"]
            assert changed.json()["name"] == "已改名"
            assert case.client.post(path + "/retire").json()["status"] == "retired"
            assert (
                case.client.get("/api/collection-vocabulary").json()[kind][-1]["status"]
                == "retired"
            )
            assert case.client.post(path + "/restore").json()["status"] == "active"
            assert case.client.delete(path).status_code == 204
            recreated = case.client.post(base, json={"name": "自定义"} | extra)
            assert recreated.status_code == 201 and recreated.json()["id"] > item["id"]
            logs = case.client.get("/api/audit/operations").json()["items"]
            events = [
                event
                for event in logs
                if event["target"]["kind"] == object_kind
                and event["target"]["object_id"] == str(item["id"])
            ]
            assert len(events) == 5
            assert {event["operation"] for event in events} == {
                "create_collection_term",
                "update_collection_term",
                "retire_collection_term",
                "restore_collection_term",
                "delete_collection_term",
            }
            assert all(event["result"] == "success" for event in events)


@pytest.mark.parametrize(
    ("fields", "field"),
    [
        ({"serial_number": "S2", "macs": []}, "name"),
        ({"name": "二号", "macs": []}, "serial_number"),
        ({"name": "二号", "serial_number": "S2"}, "macs"),
    ],
)
def test_robot_unique_fields_include_retired(
    tmp_path: Path, fields: dict[str, object], field: str
) -> None:
    """名称、序列号及MAC重复返回409并指明原机器人；停用仍占用唯一值，但允许编辑自身。"""
    with api_case(tmp_path) as case:
        case.login()
        base = {
            "name": "一号",
            "robot_model": "R1",
            "serial_number": "S1",
            "macs": [{"mac": "aa:bb:cc:dd:ee:ff"}],
        }
        created = case.client.post("/api/robots", json=base).json()
        path = f"/api/robots/{created['robot_id']}"
        assert case.client.post(path + "/retire").status_code == 200
        response = case.client.post("/api/robots", json=base | fields)
        assert response.status_code == 409, response.text
        assert "一号" in response.text and str(created["robot_id"]) in response.text
        assert field in response.text
        assert case.client.put(path, json=base).status_code == 200


@pytest.mark.parametrize(
    ("fields", "field"),
    [
        ({"ssh_port": 0}, "ssh_port"),
        ({"ssh_port": 70000}, "ssh_port"),
        ({"name": " "}, "name"),
        ({"macs": [{"mac": "bad"}]}, "macs"),
        ({"address": "bad host"}, "address"),
        ({"address": "robot.."}, "address"),
        ({"ssh_user": "bad user"}, "ssh_user"),
    ],
)
def test_invalid_robot_fields(tmp_path: Path, fields: dict[str, object], field: str) -> None:
    """非法端口、名称、MAC或连接信息返回422并指明字段，不创建机器人。"""
    with api_case(tmp_path) as case:
        case.login()
        response = case.client.post(
            "/api/robots", json={"name": "一号", "robot_model": "R1"} | fields
        )
        assert response.status_code == 422 and field in response.text
        assert case.client.get("/api/robots").json() == {"items": []}


@pytest.mark.parametrize(
    ("kind", "body"),
    [
        ("methods", {"name": "主从臂遥操作", "data_origin": "真机采集"}),
        ("purposes", {"name": "训练"}),
    ],
)
def test_term_duplicate_and_missing(tmp_path: Path, kind: str, body: dict[str, str]) -> None:
    """词表重复名称返回409，更新不存在的词表编号返回404。"""
    with api_case(tmp_path) as case:
        case.login()
        assert case.client.post(f"/api/collection-vocabulary/{kind}", json=body).status_code == 409
        assert (
            case.client.put(f"/api/collection-vocabulary/{kind}/999", json=body).status_code == 404
        )


def test_method_rejects_download_origin(tmp_path: Path) -> None:
    """采集方式来源不允许开源下载，真实HTTP入口返回422。"""
    with api_case(tmp_path) as case:
        case.login()
        response = case.client.post(
            "/api/collection-vocabulary/methods", json={"name": "下载", "data_origin": "开源下载"}
        )
        assert response.status_code == 422 and "data_origin" in response.text


def test_missing_robot(tmp_path: Path) -> None:
    """更新、删除未知机器人编号返回404，不冒充成功。"""
    with api_case(tmp_path) as case:
        case.login()
        assert (
            case.client.put(
                "/api/robots/999", json={"name": "一号", "robot_model": "R1"}
            ).status_code
            == 404
        )
        assert case.client.delete("/api/robots/999").status_code == 404


def test_model_options_merge_index_and_registry(tmp_path: Path) -> None:
    """型号候选合并索引和登记值，包含停用机器人并去重排序，不依赖扫描真实路径。"""
    from sqlalchemy import text

    from rdp.infra.db.connection import session_scope

    with api_case(tmp_path) as case:
        case.login()
        robot = case.client.post("/api/robots", json={"name": "一号", "robot_model": "R1"}).json()
        case.client.post(f"/api/robots/{robot['robot_id']}/retire")
        with session_scope(case.engine) as session:
            session.execute(
                text("""INSERT INTO dataset_scans
                (scan_id,scope,started_at,navigation_finished_at,committed_at,navigation_elapsed_s,lock_held_s,storage_stage,is_current)
                VALUES (1,'all','2026-10-25T12:30:10.123456Z','2026-10-25T12:30:10.123456Z','2026-10-25T12:30:10.123456Z',0,0,'not_run',1)""")
            )
            for index, model in enumerate(("R1", "R2", None), start=1):
                session.execute(
                    text("""INSERT INTO datasets
                    (dataset_id,name,scan_id,fingerprint,data_origin,robot_model)
                    VALUES (:id,'索引测试',1,'{}','unknown',:model)"""),
                    {"id": str(index), "model": model},
                )
        response = case.client.get("/api/robots/model-options")
        assert response.status_code == 200 and response.json() == {"items": ["R1", "R2"]}


def test_member_writes_and_historical_identity(tmp_path: Path) -> None:
    """成员可以维护登记；删除创建账号后仍保留当时身份与时间，后续修改只更新修改人。"""
    from datetime import timedelta

    from account_api_support import add_actor
    from pydantic import SecretStr

    with api_case(tmp_path) as case:
        assert case.client.get("/api/robots").status_code == 401
        grant = add_actor(case)
        assert case.login("member", SecretStr("member-updated-value")).status_code == 200
        robot_body = {"name": "成员的机器人", "robot_model": "R1"}
        robot = case.client.post("/api/robots", json=robot_body).json()
        term = case.client.post(
            "/api/collection-vocabulary/purposes", json={"name": "成员的用途"}
        ).json()
        original_time = robot["created_at"]
        assert robot["created_by"]["name"] == "成员" and not robot["created_by"]["deleted"]
        assert case.login().status_code == 200
        assert (
            case.client.delete(f"/api/accounts/{grant.identity.account.account_id}").status_code
            == 204
        )
        listed = case.client.get("/api/robots").json()["items"][0]
        assert listed["created_by"] == {
            "account_id": str(grant.identity.account.account_id),
            "name": "成员",
            "deleted": True,
        }
        assert listed["updated_by"] == listed["created_by"]
        terms = case.client.get("/api/collection-vocabulary").json()["purposes"]
        assert next(item for item in terms if item["id"] == term["id"])["created_by"]["deleted"]
        case.clock.value += timedelta(seconds=1)
        changed = case.client.put(f"/api/robots/{robot['robot_id']}", json=robot_body).json()
        assert (
            changed["created_by"] == listed["created_by"] and changed["created_at"] == original_time
        )
        assert changed["updated_by"] == {"account_id": "1", "name": "管理员", "deleted": False}
        assert changed["updated_at"] > changed["created_at"]


def test_collection_origins_match_dataset_policy() -> None:
    """Collection 的独立来源集合恰为上层 DATA_ORIGINS 去掉开源下载和未知。"""
    from rdp.collection.types import COLLECTION_DATA_ORIGINS
    from rdp.jobs.navwrite.policy import DATA_ORIGINS

    assert set(DATA_ORIGINS) - {"开源下载", "未知"} == COLLECTION_DATA_ORIGINS
