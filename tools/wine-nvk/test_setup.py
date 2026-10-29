#!/usr/bin/env python3
"""Exercise real native setup/rollback filesystem behavior, without Wine or GPU."""
import argparse
import fcntl
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile

parser=argparse.ArgumentParser(description=__doc__)
parser.add_argument('--runtime',type=Path,required=True)
parser.add_argument('--work',type=Path,required=True)
parser.add_argument('--helper',type=Path)
args=parser.parse_args()
runtime=args.runtime.resolve();helper=args.helper.resolve() if args.helper else runtime/'bin/nvk-runtime'
args.work.mkdir(parents=True,exist_ok=True)
scratch=Path(tempfile.mkdtemp(prefix='setup-fixtures-',dir=args.work))
checks=[]
def run(command,prefix=None,ok=True,root=runtime):
    cmd=[str(helper),command,str(root)]+([str(prefix)] if prefix else [])
    result=subprocess.run(cmd,capture_output=True,text=True)
    assert (result.returncode==0)==ok,(cmd,result.stdout,result.stderr)
    return json.loads(result.stdout)
def prefix(name):
    path=scratch/name
    system=path/'drive_c/windows/system32';system.mkdir(parents=True)
    for dll in ['d3d11.dll','dxgi.dll']:(system/dll).write_bytes(('original '+dll).encode())
    return path,system
def originals(system):
    for dll in ['d3d11.dll','dxgi.dll']:assert (system/dll).read_bytes()==('original '+dll).encode()

run('check');checks.append('final runtime hashes, signatures, x64 DLLs and provider alias')
previous_dyld=os.environ.get('DYLD_PRINT_LIBRARIES')
os.environ['DYLD_PRINT_LIBRARIES']='1'
try:run('check')
finally:
    if previous_dyld is None:os.environ.pop('DYLD_PRINT_LIBRARIES')
    else:os.environ['DYLD_PRINT_LIBRARIES']=previous_dyld
checks.append('signature validation completes with inherited library-load diagnostics')
p,s=prefix('normal');run('install',p);run('install',p)
assert (s/'d3d11.dll').read_bytes()==(runtime/'dxvk/x64/d3d11.dll').read_bytes()
run('restore',p);run('restore',p);originals(s);checks.append('install, repeat install, restore, repeat restore')
p,s=prefix('conflict');run('install',p)
expected=(s/'dxgi.dll').read_bytes();(s/'dxgi.dll').write_bytes(b'user replacement')
run('restore',p,ok=False)
assert (p/'.nvk-dxvk-originals/d3d11.dll').exists()
assert (s/'d3d11.dll').read_bytes()==(runtime/'dxvk/x64/d3d11.dll').read_bytes()
(s/'dxgi.dll').write_bytes(expected);run('restore',p);originals(s);checks.append('changed DLL refuses rollback before changing the other DLL')

p,s=prefix('damaged-backup');run('install',p)
backup=p/'.nvk-dxvk-originals/dxgi.dll';original=backup.read_bytes();backup.write_bytes(b'damaged original')
run('restore',p,ok=False)
assert (p/'.nvk-dxvk-originals/d3d11.dll').exists();backup.write_bytes(original);run('restore',p);originals(s)
checks.append('damaged backup refuses rollback before changing DLLs')

for phase in ['prepared','restoring']:
    p,s=prefix('interrupted-'+phase);run('install',p)
    state=json.loads((p/'.nvk-dxvk-state.json').read_text());state['phase']=phase
    # Model an interruption with one entry installed/restored and one pending.
    (s/'dxgi.dll').unlink();(p/'.nvk-dxvk-originals/dxgi.dll').rename(s/'dxgi.dll')
    (p/'.nvk-dxvk-state.json').write_text(json.dumps(state))
    run('restore',p);originals(s)
checks.append('partial installation and partial rollback recover without losing originals')

p,s=prefix('locked')
with (p/'.nvk-dxvk.lock').open('w') as lock:
    fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB);run('install',p,ok=False);originals(s)
checks.append('concurrent setup rejected without writes to DLLs')
p,s=prefix('escaped-system32');external=scratch/'outside-prefix';external.mkdir();shutil.rmtree(s);s.symlink_to(external)
run('install',p,ok=False);assert not list(external.iterdir());checks.append('system32 symlink outside the prefix refused')
p,s=prefix('escaped-backups');run('install',p)
backup=p/'.nvk-dxvk-originals';backup.rename(scratch/'saved-backups');backup.symlink_to(external)
run('restore',p,ok=False);assert not list(external.iterdir());checks.append('backup directory symlink outside the prefix refused')

fixture=scratch/'package with spaces';fixture.mkdir()
manifest=json.loads((runtime/'nvk-wine-runtime.json').read_text())
for name in manifest['files']:
    target=fixture/name;target.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(runtime/name,target);target.chmod(0o755)
(fixture/'lib/libMoltenVK.dylib').symlink_to('libnvk_wine.dylib')
(fixture/'nvk-wine-runtime.json').write_text(json.dumps(manifest));run('check',root=fixture)
checks.append('critical package relocation with spaces')
bad=fixture/'dxvk/x64/dxgi.dll';original=bad.read_bytes();bad.write_bytes(original+b'tamper');run('check',ok=False,root=fixture);bad.write_bytes(original)
checks.append('tampered artifact refused')
# Moving between app-local and installed providers must retain the user's
# original DLLs even though the coherent runtime identities differ.
p,s=prefix('provider-migration');run('install',p)
original_state=json.loads((p/'.nvk-dxvk-state.json').read_text())
manifest['runtime_id']='same-pair-new-provider'
(fixture/'nvk-wine-runtime.json').write_text(json.dumps(manifest))
run('install',p,root=fixture)
adopted=json.loads((p/'.nvk-dxvk-state.json').read_text())
assert adopted['runtime_id']==manifest['runtime_id'] and adopted['files']==original_state['files']
run('restore',p,root=fixture);originals(s)
checks.append('same DLL pair adopts a new provider identity while preserving original rollback files')
p,s=prefix('changed-pair');run('install',p)
data=bytearray(original);data[-1]^=1;bad.write_bytes(data)
manifest['files']['dxvk/x64/dxgi.dll']=hashlib.sha256(data).hexdigest()
(fixture/'nvk-wine-runtime.json').write_text(json.dumps(manifest))
unchanged=(p/'.nvk-dxvk-state.json').read_bytes();run('install',p,ok=False,root=fixture)
assert (p/'.nvk-dxvk-state.json').read_bytes()==unchanged
run('restore',p);originals(s);bad.write_bytes(original)
checks.append('different DXVK pair refuses identity adoption before modifying the existing setup')
# Updating a corrupt DLL hash cannot make an ARM64 image an x64 DLL.
data=bytearray(original);offset=int.from_bytes(data[60:64],'little');data[offset+4:offset+6]=(0xaa64).to_bytes(2,'little');bad.write_bytes(data)
manifest['files']['dxvk/x64/dxgi.dll']=hashlib.sha256(data).hexdigest()
(fixture/'nvk-wine-runtime.json').write_text(json.dumps(manifest));run('check',ok=False,root=fixture)
checks.append('wrong DLL architecture refused independently of its hash')

if json.loads((runtime/'nvk-wine-runtime.json').read_text()).get('vkd3d'):
    def d3d12_prefix(name):
        p,s=prefix(name)
        for dll in ['d3d12.dll','d3d12core.dll']:(s/dll).write_bytes(('original '+dll).encode())
        return p,s
    def all_originals(system):
        originals(system)
        for dll in ['d3d12.dll','d3d12core.dll']:assert (system/dll).read_bytes()==('original '+dll).encode()

    assert run('check')['supports_d3d12'] is True
    p,s=d3d12_prefix('optional-d3d12');run('install',p)
    assert not (p/'.nvk-vkd3d-state.json').exists()
    assert (s/'d3d12.dll').read_bytes()==b'original d3d12.dll'
    dxvk_state=json.loads((p/'.nvk-dxvk-state.json').read_text())
    run('install-d3d12',p);run('install-d3d12',p);run('install',p)
    assert json.loads((p/'.nvk-dxvk-state.json').read_text())['files']==dxvk_state['files']
    for dll in ['d3d12.dll','d3d12core.dll']:
        assert (s/dll).read_bytes()==(runtime/'vkd3d/x64'/dll).read_bytes()
    run('restore',p);run('restore',p);all_originals(s)
    checks.append('D3D12 is opt-in; existing D3D11 journal survives upgrade/repeat install; both pairs restore')

    p,s=d3d12_prefix('changed-d3d12');run('install-d3d12',p)
    saved=(s/'d3d12core.dll').read_bytes();(s/'d3d12core.dll').write_bytes(b'user replacement')
    run('restore',p,ok=False)
    assert (s/'dxgi.dll').read_bytes()==(runtime/'dxvk/x64/dxgi.dll').read_bytes()
    assert (p/'.nvk-dxvk-originals/dxgi.dll').exists()
    (s/'d3d12core.dll').write_bytes(saved);run('restore',p);all_originals(s)
    checks.append('changed D3D12 DLL blocks rollback before either graphics pair is modified')

    for phase in ['prepared','restoring']:
        p,s=d3d12_prefix('interrupted-d3d12-'+phase);run('install-d3d12',p)
        state=json.loads((p/'.nvk-vkd3d-state.json').read_text());state['phase']=phase
        (s/'d3d12core.dll').unlink();(p/'.nvk-vkd3d-originals/d3d12core.dll').rename(s/'d3d12core.dll')
        (p/'.nvk-vkd3d-state.json').write_text(json.dumps(state))
        run('restore',p);all_originals(s)
    checks.append('interrupted D3D12 pair installation/rollback restores all four originals')

    for existing_dxvk in [False,True]:
        p,s=d3d12_prefix('failed-d3d12-'+str(existing_dxvk))
        if existing_dxvk:run('install',p)
        (p/'.nvk-vkd3d-originals').mkdir()
        run('install-d3d12',p,ok=False)
        if existing_dxvk:
            assert (s/'dxgi.dll').read_bytes()==(runtime/'dxvk/x64/dxgi.dll').read_bytes()
            run('restore',p)
        else:
            assert not (p/'.nvk-dxvk-state.json').exists()
        all_originals(s)
    checks.append('failed D3D12 setup rolls back a newly added D3D11 pair and retains an existing one')

    # A legacy provider still supports normal installation but must reject the
    # D3D12 command before any prefix modifications.
    clean=json.loads((runtime/'nvk-wine-runtime.json').read_text());clean.pop('vkd3d')
    bad.write_bytes(original)
    (fixture/'nvk-wine-runtime.json').write_text(json.dumps(clean))
    assert run('check',root=fixture)['supports_d3d12'] is False
    p,s=d3d12_prefix('legacy-provider-no-d3d12');run('install-d3d12',p,root=fixture,ok=False)
    all_originals(s);assert not (p/'.nvk-dxvk-state.json').exists()
    checks.append('legacy provider rejects D3D12 before changing prefix files')

result={'result':'PASS','checks':checks,'scratch':str(scratch),'uses_real_native_setup':True,'wine_or_gpu_started':False}
(args.work/'setup-tests.json').write_text(json.dumps(result,indent=2)+'\n')
print(json.dumps(result,indent=2))
