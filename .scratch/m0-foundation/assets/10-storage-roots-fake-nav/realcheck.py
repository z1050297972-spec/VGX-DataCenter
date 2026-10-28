"""验收 2：本机两块盘的真实在线判断（只读挂载表、by-uuid 和根目录 stat）。"""
from datetime import UTC, datetime
from pathlib import Path
from rdp.infra.config import StorageConfig, StorageRootConfig
from rdp.infra.storage import LinuxMountSource, MountInspector, StorageAccessChecker, read_storage_root

def run(label, roots):
    src = LinuxMountSource()
    mounts = MountInspector(roots, src.read_mountinfo, src.resolve_uuid_device, lambda: datetime.now(UTC))
    print(f"== {label}")
    for s in mounts.inspect():
        print(f"  web   {s.name:9} {s.path} online={s.online} reason={s.reason} writable={s.writable}")
    checker = StorageAccessChecker(mounts, StorageConfig(), read_storage_root)
    for r in roots:
        s = checker.check(r.name, checkpoint=lambda: None)
        print(f"  job   {s.name:9} online={s.online} reason={s.reason}")

base = "/" + "mnt"
ok = (StorageRootConfig(name="dataset1", path=Path(base, "dataset1"), uuid="2d3a48d6-3785-47fe-8c8f-a20857fdc41a"),
      StorageRootConfig(name="dataset2", path=Path(base, "dataset2"), uuid="35445b14-9e83-4f74-ac73-1551e3db6d63"))
run("登记正确", ok)
bad = (ok[0], StorageRootConfig(name="dataset2", path=Path(base, "dataset2"), uuid="35445b14-9e83-4f74-ac73-1551e3db6d64"))
run("dataset2 的 UUID 改错一位", bad)
swap = (StorageRootConfig(name="dataset1", path=Path(base, "dataset1"), uuid=ok[1].uuid),)
run("dataset1 登记成 dataset2 的 UUID（挂的是别的盘）", swap)
nm = (StorageRootConfig(name="nas", path=Path(base, "nas_not_here"), nfs_export="server:/export"),)
run("没挂载的路径", nm)
