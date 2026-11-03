"""Compile/run actual C model_ops against generated user payloads, host only."""
from pathlib import Path
import argparse,hashlib,json,shutil,subprocess,os
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def main():
    p=argparse.ArgumentParser(description=__doc__)
    for k in ('cc','payload','out'):p.add_argument('--'+k,type=Path,required=True)
    a=p.parse_args();root=Path(__file__).resolve().parents[1];out=a.out.resolve();payload=a.payload.resolve()
    if any(out.is_relative_to(v) or v.is_relative_to(out) for v in (root,payload)):raise SystemExit('Use disjoint external output')
    if out.exists() and any(out.iterdir()):raise SystemExit('New empty output required')
    lock=json.loads((payload/'user_payload_lock.json').read_text())
    if lock.get('PayloadPurpose')!='USER_MODEL_COMPATIBILITY':raise SystemExit('Compatibility payload required')
    for name,h in lock['Files'].items():
        if sha(payload/name)!=h:raise SystemExit('Payload mismatch '+name)
    out.mkdir(parents=True,exist_ok=True)
    for name in ('model_ops.c','model_ops.h','user_payload_cpu_check.c'):shutil.copy2(root/'software'/name,out/name)
    for name in ('model_params.h','batch_data.h'):shutil.copy2(payload/name,out/name)
    exe=out/('cpu_check.exe' if os.name=='nt' else 'cpu_check')
    cmd=[str(a.cc.resolve()),'-std=c11','-Wall','-Wextra','-Werror','-O2',str(out/'model_ops.c'),str(out/'user_payload_cpu_check.c'),'-o',str(exe)]
    build=subprocess.run(cmd,capture_output=True,text=True);(out/'compile.log').write_text(build.stdout+build.stderr)
    record={'CompileCommand':cmd,'CompileExit':build.returncode,'BoardExecuted':False,'FormalResult':False,
            'CompilerSHA256':sha(a.cc),'PayloadLockSHA256':sha(payload/'user_payload_lock.json'),
            'Sources':{f.name:sha(f) for f in out.iterdir() if f.suffix in ('.c','.h')}}
    if build.returncode:
        (out/'record.json').write_text(json.dumps(record,indent=2));raise SystemExit(build.returncode)
    bins=['conv1_golden_int8.bin','conv2_golden_int8.bin','fused_conv1_relu_golden_int8.bin','fused_conv2_relu_pool_golden_int8.bin','batch_fused_stage_fnv']
    cmd=[str(exe),*[str(payload/f) for f in bins]];run=subprocess.run(cmd,capture_output=True,text=True)
    (out/'run.log').write_text(run.stdout+run.stderr)
    record.update(RunCommand=cmd,RunExit=run.returncode,ExecutableSHA256=sha(exe),Status='HOST_C_PASS' if run.returncode==0 else 'HOST_C_FAILED')
    (out/'record.json').write_text(json.dumps(record,indent=2)+'\n');print(run.stdout,end='');raise SystemExit(run.returncode)
if __name__=='__main__':main()
