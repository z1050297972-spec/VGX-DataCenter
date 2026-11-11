import struct, sys
from mcap.reader import make_reader
topics = ["/motion_target/target_joint_state_arm_left", "/motion_target/target_joint_state_arm_right", "/hdas/camera_wrist_right/color/image_raw/compressed", "/hdas/camera_head/left_raw/image_raw_color/compressed"]
st = {t: [] for t in topics}
with open(sys.argv[1], "rb") as f:
    for schema, ch, msg in make_reader(f).iter_messages(topics=topics):
        d = msg.data
        sec, nsec = struct.unpack_from("<iI", d, 4)
        st[ch.topic].append(sec * 1_000_000_000 + nsec)
for t, v in st.items():
    v = sorted(x for x in v if x)
    iv = sorted((b - a) / 1e6 for a, b in zip(v, v[1:]))
    n = len(iv)
    print(t.split("/")[-1] if "camera" not in t else t, f"条数 {len(v)} 中位间隔 {iv[n//2]:.2f} ms p99 {iv[int(n*0.99)]:.2f} 最大 {iv[-1]:.2f} 超过20ms的间隔 {sum(x>20 for x in iv)} 超过60ms {sum(x>60 for x in iv)}")
