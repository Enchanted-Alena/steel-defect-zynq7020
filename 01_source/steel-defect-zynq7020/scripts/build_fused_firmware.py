# Modified by B on 2026-11-01; notice added in R2 on 2026-11-02.
# Adds explicit offline-demo lock handling; formal payload checks remain required.
"""Prepared fused firmware linker. Requires a separately received C frozen lock.

This source builds the frozen Protocol2 suite from separately authorized
payloads and locks. This packaging copy has not been rebuilt or board-tested.
It performs no board operations or synthetic fallback.
"""
from pathlib import Path
import argparse,hashlib,json,re,shutil,subprocess

HEADERS=['model_params.h','board_vectors.h','batch_data.h']
BINS=['conv1_golden_int8.bin','conv2_golden_int8.bin',
      'fused_conv1_relu_golden_int8.bin','fused_conv2_relu_pool_golden_int8.bin',
      'batch_fused_stage_fnv']
EXPECTED_LENGTHS=dict(zip(BINS,[1105920,2211840,1105920,552960,3240]))

def sha(path):return hashlib.sha256(path.read_bytes()).hexdigest()

def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--gcc',type=Path,required=True)
    p.add_argument('--bsp',type=Path,required=True)
    p.add_argument('--private-dir',type=Path,required=True)
    p.add_argument('--lock',type=Path,required=True)
    p.add_argument('--baseline-lock',type=Path,required=True,help='Original authorized baseline payload hash JSON; kept outside this repository')
    p.add_argument('--demo-offline',action='store_true',help='Only accept user-generated OFFLINE DEMO locks; resulting ELF must not be programmed')
    p.add_argument('--out',type=Path,required=True)
    a=p.parse_args();root=Path(__file__).resolve().parent.parent
    lock=json.loads(a.lock.read_text(encoding='utf-8'))
    purpose=lock.get('PayloadPurpose')
    if a.demo_offline:
        if purpose!='USER_MODEL_OFFLINE_DEMO' or lock.get('DoNotProgram') is not True:
            raise SystemExit('Offline demo requires an explicitly marked user demo lock')
    elif purpose is not None and purpose!='AUTHORIZED_FROZEN_REPLAY':
        raise SystemExit('User/demo payloads are not accepted by the frozen-replay entry')
    if lock.get('SampleCount')!=270 or lock.get('ProtocolVersion')!='0x00020000':
        raise SystemExit('Expected separately frozen C 270-sample Protocol2.0 lock')
    hashes=lock.get('Files',{})
    if set(hashes)!=set(HEADERS+BINS):raise SystemExit('Lock must identify all eight private files')
    baseline=json.loads(a.baseline_lock.read_text(encoding='utf-8'))
    if a.demo_offline and baseline.get('PayloadPurpose')!='USER_MODEL_OFFLINE_DEMO':
        raise SystemExit('Do not mix a frozen baseline lock with user demo data')
    old=baseline['Files']
    if not all(name in old for name in HEADERS+BINS[:2]):
        raise SystemExit('Baseline lock must cover model, inputs and both legacy golden files')
    for name in HEADERS+BINS:
        expected=hashes[name]
        if not isinstance(expected,str) or not re.fullmatch('[0-9a-f]{64}',expected):
            raise SystemExit('Missing valid frozen SHA-256: '+name)
        f=a.private_dir/name
        if not f.is_file() or sha(f)!=expected:raise SystemExit('Missing/mismatched C payload: '+name)
        if name in old and expected!=old[name]:raise SystemExit('Frozen model/input/legacy golden changed: '+name)
        if name in EXPECTED_LENGTHS and f.stat().st_size!=EXPECTED_LENGTHS[name]:
            raise SystemExit('Unexpected binary length: '+name)
    gcc=a.gcc.resolve();bsp=a.bsp.resolve()
    for f in [gcc,bsp/'Xilinx.spec',bsp/'include/xparameters.h']:
        if not f.is_file():raise SystemExit('Missing compiler/BSP: '+str(f))
    out=a.out.resolve()
    if out==root or out.is_relative_to(root):raise SystemExit('Build outside source candidate')
    if out.exists() and any(out.iterdir()):raise SystemExit('Use new empty output directory')
    out.mkdir(parents=True,exist_ok=True)
    work=out/'software';shutil.copytree(root/'software',work)
    for name in HEADERS:shutil.copy2(a.private_dir/name,work/name)
    if a.demo_offline:
        header=(work/'batch_data.h').read_text(encoding='ascii')
        if not re.search(r'^#define\s+BATCH_DATA_FORMAL\s+0U?\s*$',header,re.M) or not re.search(r'^#define\s+USER_PAYLOAD_OFFLINE_ONLY\s+1U?\s*$',header,re.M):
            raise SystemExit('Offline demo header must remain explicitly non-formal')
        # Modify ONLY the disposable build copy's printed banner. Numerical,
        # protocol, error-recovery and DMA code stay identical to the source.
        main_c=work/'main.c';text=main_c.read_text(encoding='utf-8')
        if text.count('NEU_FULL270_FUSED_POSTOP_V2')!=2:
            raise SystemExit('Unknown main.c banner layout; do not patch implicitly')
        text=text.replace('NEU_FULL270_FUSED_POSTOP_V2','USER_MODEL_OFFLINE_DEMO_NOT_BOARD_VALIDATED')
        text=text.replace('SMART_SL_COUNTER_PREDICT_20261017_FUSED_POSTOP_CANDIDATE','USER_MODEL_OFFLINE_BUILD_DO_NOT_PROGRAM')
        main_c.write_text(text,encoding='utf-8')
    record={'Status':'BUILDING_NOT_BOARD','NoBoardAccess':True,'ELFContainsPrivateData':True,
            'PayloadPurpose':purpose or 'AUTHORIZED_FROZEN_REPLAY','DoNotProgram':bool(a.demo_offline),
            'PrivateLockSHA256':sha(a.lock),'BaselineLockSHA256':sha(a.baseline_lock),'CompilerSHA256':sha(gcc),'Commands':[],
            'SourceSHA256':{f.name:sha(f) for f in work.iterdir() if f.is_file()},
            'BSPFileHashes':{f.relative_to(bsp).as_posix():sha(f) for f in bsp.rglob('*') if f.is_file()}}
    def save():(out/'build_record.json').write_text(json.dumps(record,indent=2),encoding='utf-8')
    objects=[]
    for name in BINS:
        obj=out/(name+'.o')
        # The installed AMD objcopy lacks --set-section-alignment. GNU assembler
        # .balign guarantees the uint32 FNV table's alignment on this toolchain.
        symbol='_binary_'+re.sub('[^A-Za-z0-9_]','_',name)+'_start'
        end=symbol[:-5]+'end'
        data_path=(a.private_dir/name).resolve().as_posix()
        if '"' in data_path or '\n' in data_path:raise SystemExit('Unsupported incbin path')
        assembly=out/(name+'.S')
        assembly.write_text('\n'.join([
            '.section .rodata.dataset,"a",%progbits','.balign 4',
            '.global '+symbol,'.type '+symbol+',%object',symbol+':',
            '.incbin "'+data_path+'"','.size '+symbol+',.-'+symbol,
            '.global '+end,end+':','.section .note.GNU-stack,"",%progbits','']),encoding='utf-8')
        cmd=[str(gcc),'-mcpu=cortex-a9','-mfpu=vfpv3','-mfloat-abi=hard',
             '-c',str(assembly),'-o',str(obj)]
        result=subprocess.run(cmd,capture_output=True,text=True)
        record['Commands'].append({'command':cmd,'exit_code':result.returncode})
        (out/(name+'.assemble.log')).write_text(result.stdout+result.stderr,encoding='utf-8')
        if result.returncode:
            record['Status']='BINARY_ASSEMBLY_FAILED';save();raise SystemExit(result.returncode)
        objects.append(str(obj))
    elf=out/('user_model_offline_demo.elf' if a.demo_offline else 'cnn_neu_full270_fused_candidate.elf')
    cmd=[str(gcc),'-DSDT','-mcpu=cortex-a9','-mfpu=vfpv3','-mfloat-abi=hard',
         '-specs='+(bsp/'Xilinx.spec').as_posix(),'-I'+(bsp/'include').as_posix(),
         '-Wall','-Wextra','-Werror','-O2','-g3','-U__clang__',
         str(work/'main.c'),str(work/'platform.c'),str(work/'model_ops.c'),*objects,
         '-o',str(elf),'-Wl,-T,'+(work/'lscript.ld').as_posix(),
         '-Wl,-Map,'+elf.with_suffix('.map').as_posix(),
         '-L'+(bsp/'lib').as_posix(),'-Wl,--start-group,-lxilstandalone,-lxiltimer,-lxil,-lgcc,-lc',
         '-Wl,--end-group']
    if a.demo_offline:cmd.insert(1,'-DOFFLINE_FIXTURE_BUILD')
    result=subprocess.run(cmd,capture_output=True,text=True)
    record['Commands'].append({'command':cmd,'exit_code':result.returncode})
    (out/'build.log').write_text(result.stdout+result.stderr,encoding='utf-8')
    record['Status']='COMPILE_FAILED' if result.returncode else ('OFFLINE_DEMO_LINKED_DO_NOT_PROGRAM' if a.demo_offline else 'LINKED_NOT_BOARD_MEASURED')
    if not result.returncode:record['ELFSHA256']=sha(elf)
    save();raise SystemExit(result.returncode)

if __name__=='__main__':main()
