import subprocess, pathlib, os
P=pathlib.Path.home()/'.cache/rdp-dispatch/m1-01/probe-B1'
D='src/rdp/jobs/datasets/'
muts=[
 (D+'reading.py','version = payload.get("schema_version", 1)','version = payload.get("schema_version", 2)','缺 schema_version 不当 1'),
 (D+'reading.py',r'match = re.search(r"（([0-9]+(?:,[0-9]{3})*) B；"',r'match = re.search(r"（([0-9]+) B；"','记录值不认千分位'),
 (D+'_fingerprints.py','LinkFingerprint(name=name, target=os.readlink(name, dir_fd=descriptor))','LinkFingerprint(name=name, target="")','指纹不含链接目标'),
 (D+'_fingerprints.py','sha256=hashlib.sha256(content).hexdigest() if content is not None else None,','sha256=None,','指纹不含 JSON 摘要'),
 (D+'_plan.py','if item.fingerprint.verifiable and fresh.verifiable and item.fingerprint == fresh:','if True:','提交复核不比较指纹'),
]
tests=['tests/test_datasets_reading.py','tests/test_datasets_fingerprint.py','tests/test_datasets_index.py','tests/test_datasets_rescan.py']
for f,old,new,desc in muts:
    p=P/f; orig=p.read_text()
    if orig.count(old)!=1: print(desc,'| NOT-FOUND',orig.count(old)); continue
    p.write_text(orig.replace(old,new,1))
    try:
        r=subprocess.run(['.venv/bin/pytest','-q','-p','no:cacheprovider','-n','8',*tests],cwd=P,env={**os.environ,'PYTHONPATH':str(P/'src')},capture_output=True,text=True,timeout=900)
        last=[l for l in r.stdout.splitlines() if 'passed' in l or 'failed' in l][-1:] 
        print(desc,'|','KILLED' if r.returncode else 'SURVIVED','|',last)
    finally: p.write_text(orig)
