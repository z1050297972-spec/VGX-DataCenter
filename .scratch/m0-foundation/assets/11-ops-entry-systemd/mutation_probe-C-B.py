import subprocess, shutil, pathlib, sys
P=pathlib.Path.home()/'.cache/rdp-dispatch/m0-11/probe-C-B'
muts=[
 ('scripts/setup.sh','sha256sum --check --status ||','true ||','SHA256 校验失效'),
 ('scripts/setup.sh',"[[ $resolved == \"$destination/\"* ]] || _setup_die 1 '归档链接越界'","true","链接逃逸检查失效"),
 ('scripts/setup.sh','[[ $linger == yes ]]','[[ $linger == no ]]','linger 判断反转'),
 ('scripts/setup.sh',"if [[ $admin_status == present ]]; then printf '已有管理员，跳过创建。\\n'; return 0; fi","","已有管理员不跳过"),
 ('scripts/setup.sh',"ln -T -- \"$config_temp\" \"$config_file\" || _setup_die 1 '配置发布发生竞争，保留对方文件'","mv -f -- \"$config_temp\" \"$config_file\"","配置可覆盖"),
 ('scripts/setup.sh','if $no_systemd; then args+=(--no-systemd); fi','','不透传 --no-systemd'),
 ('scripts/setup.sh',"[[ $(uname -s) == Linux ]] || _setup_die 1 '仅支持Linux；请手动准备工具'",'true','平台检查失效'),
 ('scripts/setup.sh','write_permission=true','write_permission=false','NFS 写许可选择失效'),
]
res=[]
for f,old,new,desc in muts:
    p=P/f; orig=p.read_text()
    if orig.count(old)!=1: res.append((desc,'NOT-FOUND %d'%orig.count(old))); continue
    p.write_text(orig.replace(old,new,1))
    try:
        r=subprocess.run(['.venv/bin/pytest','-q','-x','-p','no:cacheprovider','tests/test_ops_setup_script.py'],cwd=P,env={**__import__('os').environ,'PYTHONPATH':str(P/'src')},capture_output=True,text=True,timeout=900)
        tail=r.stdout.strip().splitlines()[-1] if r.stdout.strip() else r.stderr[-200:]
        res.append((desc,'KILLED' if r.returncode else 'SURVIVED',tail))
    finally:
        p.write_text(orig)
for x in res: print(*x, sep=' | ')
