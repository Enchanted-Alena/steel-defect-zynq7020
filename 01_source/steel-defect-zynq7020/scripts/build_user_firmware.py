"""Compile 1..16 user samples for existing compatible Protocol 2 hardware.

No training, HLS, Vivado, programming, formal replay, or performance benchmark.
"""
from pathlib import Path
import argparse, hashlib, json, re, shutil, subprocess, sys
from generate_user_payloads import HEADERS, BINS

def sha(p): return hashlib.sha256(p.read_bytes()).hexdigest()

def main():
    p=argparse.ArgumentParser(description=__doc__)
    for key in ('gcc','bsp','payload','out'): p.add_argument('--'+key,type=Path,required=True)
    a=p.parse_args(); root=Path(__file__).resolve().parents[1]
    payload,bsp,out,gcc=[getattr(a,k).resolve() for k in ('payload','bsp','out','gcc')]
    if any(out.is_relative_to(v) or v.is_relative_to(out) for v in (root,payload,bsp)):
        raise SystemExit('Output/source/BSP/payload directories must be disjoint')
    if out.exists() and any(out.iterdir()):raise SystemExit('New empty output required')
    lock_path=payload/'user_payload_lock.json';lock=json.loads(lock_path.read_text())
    count=lock['SampleCount']
    if lock.get('PayloadPurpose')!='USER_MODEL_COMPATIBILITY' or lock.get('FormalFrozenReplay') is not False or not 1<=count<=16:
        raise SystemExit('Dedicated non-formal compatibility lock required')
    if lock.get('ProtocolVersion')!='0x00020000' or lock.get('DoNotProgram') is not False:
        raise SystemExit('Wrong protocol or offline-only input')
    if lock.get('NeedsExplicitBoardSession') is not True:
        raise SystemExit('Explicit board-session lock required')
    if set(lock['Files'])!=set(HEADERS+BINS):raise SystemExit('Exactly eight payloads required')
    for name in HEADERS+BINS:
        if sha(payload/name)!=lock['Files'][name]:raise SystemExit('Payload mismatch: '+name)
    for name,size in zip(BINS,(4096,8192,4096,2048,12)):
        if (payload/name).stat().st_size!=count*size:raise SystemExit('Wrong binary length: '+name)
    manifest=payload/'user_input_manifest.json'
    if sha(manifest)!=lock['DataManifestSHA256']:raise SystemExit('Input manifest changed')
    for f in (gcc,bsp/'Xilinx.spec',bsp/'include/xparameters.h',bsp/'lib/libxil.a',bsp/'lib/libxilstandalone.a',bsp/'lib/libxiltimer.a'):
        if not f.is_file():raise SystemExit('Missing dependency: '+str(f))
    # Verification is mandatory before compiling. It does not access hardware.
    verify=[sys.executable,str(root/'scripts/verify_user_payloads.py'),'--payload',str(payload)]
    v=subprocess.run(verify,capture_output=True,text=True,errors='replace')
    if v.returncode:raise SystemExit(v.stdout+v.stderr)
    out.mkdir(parents=True,exist_ok=True);work=out/'software';work.mkdir()
    for name in ('user_compat_main.c','platform.c','platform.h','timing.h','model_ops.c','model_ops.h','dma_driver.inc','batch_goldens.h','lscript.ld'):
        shutil.copy2(root/'software'/name,work/name)
    for name in HEADERS:shutil.copy2(payload/name,work/name)
    header=(work/'batch_data.h').read_text()
    for pattern in (r'^#define BATCH_DATA_FORMAL 0U$',r'^#define USER_PAYLOAD_COMPATIBILITY 1U$',r'^#define BATCH_COUNT '+str(count)+r'U$'):
        if not re.search(pattern,header,re.M):raise SystemExit('Unexpected generated header flags/count')
    record={'Status':'COMPILING_USER_COMPATIBILITY','FormalResult':False,'BoardExecuted':False,
            'SampleCount':count,'PayloadLockSHA256':sha(lock_path),'InputManifestSHA256':sha(manifest),
            'CompilerSHA256':sha(gcc),'PythonVersion':sys.version,'Commands':[],
            'Sources':{f.name:sha(f) for f in work.iterdir() if f.is_file()},
            'BSPFiles':{f.relative_to(bsp).as_posix():sha(f) for f in sorted(bsp.rglob('*')) if f.is_file()}}
    (out/'payload_verification.log').write_text(v.stdout+v.stderr,encoding='utf-8')
    def save():(out/'build_record.json').write_text(json.dumps(record,indent=2)+'\n',encoding='utf-8')
    def run(cmd,name):
        save();result=subprocess.run(cmd,capture_output=True,text=True,errors='replace')
        (out/(name+'.log')).write_text(result.stdout+result.stderr,encoding='utf-8')
        record['Commands'].append({'command':cmd,'exit_code':result.returncode})
        if result.returncode:record['Status']='COMPILE_FAILED';save();raise SystemExit(result.returncode)
    version=subprocess.run([str(gcc),'--version'],capture_output=True,text=True,check=True).stdout
    (out/'compiler_version.txt').write_text(version,encoding='utf-8');record['CompilerVersion']=version.splitlines()[0]
    objs=[]
    for name in BINS:
        symbol='_binary_'+re.sub('[^A-Za-z0-9_]','_',name)+'_start'
        path=(payload/name).as_posix()
        if any(c in path for c in '"\r\n'):raise SystemExit('Unsupported data path')
        asm=out/(name+'.S');obj=out/(name+'.o')
        asm.write_text('.section .rodata.dataset,"a",%progbits\n.balign 4\n.global '+symbol+'\n'+symbol+':\n.incbin "'+path+'"\n.section .note.GNU-stack,"",%progbits\n')
        run([str(gcc),'-mcpu=cortex-a9','-mfpu=vfpv3','-mfloat-abi=hard','-c',str(asm),'-o',str(obj)],name+'.assemble');objs.append(str(obj))
    elf=out/'user_model_compatibility.elf'
    cmd=[str(gcc),'-DSDT','-mcpu=cortex-a9','-mfpu=vfpv3','-mfloat-abi=hard','-specs='+(bsp/'Xilinx.spec').as_posix(),
         '-I'+(bsp/'include').as_posix(),'-Wall','-Wextra','-Werror','-O2','-g3','-U__clang__',
         str(work/'user_compat_main.c'),str(work/'platform.c'),str(work/'model_ops.c'),*objs,'-o',str(elf),
         '-Wl,-T,'+(work/'lscript.ld').as_posix(),'-Wl,-Map,'+elf.with_suffix('.map').as_posix(),
         '-L'+(bsp/'lib').as_posix(),'-Wl,--start-group,-lxilstandalone,-lxiltimer,-lxil,-lgcc,-lc','-Wl,--end-group']
    run(cmd,'link')
    record.update(Status='USER_COMPATIBILITY_ELF_LINKED_NOT_BOARD_RUN',ELFSHA256=sha(elf))
    save();print(record['Status'])

if __name__=='__main__':main()
