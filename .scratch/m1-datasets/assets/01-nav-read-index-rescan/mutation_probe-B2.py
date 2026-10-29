import subprocess, pathlib, os
P=pathlib.Path.home()/'.cache/rdp-dispatch/m1-01/probe-B2'
D='src/rdp/jobs/datasets/'
muts=[
 (D+'catalog.py','"解压样本", "已移除"})','"解压样本"})','已移除 不在登记表'),
 (D+'_entry_checks.py','if len(set(str(value) for value in identifiers.values())) > 1:','if False:','dataset_id 不一致不报'),
 (D+'_entry_checks.py','and payload["dataset_name"] != entry.location.dataset_name','and False','名字和目录不符不报'),
 (D+'triggers.py','if self._next_at_s is not None and now_s < self._next_at_s:','if self._next_at_s is not None and now_s <= self._next_at_s:','600 秒边界'),
 ('src/rdp/jobs/service.py','                    SYSTEM_ACTOR,\n','                    OPS_ACTOR,\n','定时提交人不是系统'),
]
for f,old,new,desc in muts:
    p=P/f; orig=p.read_text()
    if orig.count(old)!=1: print(desc,'| NOT-FOUND',orig.count(old)); continue
    q=orig.replace(old,new,1)
    if 'OPS_ACTOR' in new and 'OPS_ACTOR' not in orig.split('\n',40)[0:40].__str__(): q=q.replace('from rdp.infra.actors import SYSTEM_ACTOR','from rdp.infra.actors import OPS_ACTOR, SYSTEM_ACTOR',1)
    p.write_text(q)
    try:
        r=subprocess.run(['.venv/bin/pytest','-q','-p','no:cacheprovider','-n','8','tests/'],cwd=P,env={**os.environ,'PYTHONPATH':str(P/'src')},capture_output=True,text=True,timeout=1200)
        last=[l for l in r.stdout.splitlines() if 'passed' in l or 'failed' in l or 'error' in l][-1:]
        print(desc,'|','KILLED' if r.returncode else 'SURVIVED','|',last)
    finally: p.write_text(orig)
