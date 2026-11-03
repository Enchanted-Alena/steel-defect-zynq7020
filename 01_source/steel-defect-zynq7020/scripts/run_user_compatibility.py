"""Guarded user compatibility session. Volatile JTAG download only, no flash.

Requires an explicit current board-session flag, compatible local hardware,
matching BSP/ELF/payload locks, and exclusive serial access. Saves private UART.
"""
from pathlib import Path
import argparse,hashlib,json,subprocess,time
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def validate_rows(data,n,expected=None):
    rows=[]
    for line in data.decode('ascii',errors='replace').splitlines():
        if line.startswith('R,'):
            fields=line.strip().split(',')
            if len(fields)!=24:raise ValueError('Malformed result row')
            v=[int(s,16) for s in fields[1:]]
            mode,phase,idx,repeat=v[:4]
            if mode not in (0,1,2) or phase!=2 or not 0<=idx<n or repeat!=0:raise ValueError('Unexpected result scope')
            if v[15]!=0:raise ValueError('Guard error')
            if expected is not None:
                prediction,logits,hashes=expected
                if v[5]!=int(prediction[idx]) or v[6:12]!=[int(x)&0xffffffff for x in logits[idx]] or v[12:15]!=[int(x) for x in hashes[idx]]:
                    raise ValueError('UART numerical output mismatch')
            if mode==0:
                if any(v[16:23]):raise ValueError('ARM path unexpectedly reported DMA activity')
            else:
                if v[22]!=2 or v[16]!=0 or v[19]!=0 or any(x&0x770 for x in (v[17],v[18],v[20],v[21])):raise ValueError('DMA/CNN status mismatch')
            rows.append((mode,idx))
    if len(rows)!=n*3 or set(rows)!={(m,i) for i in range(n) for m in range(3)}:raise ValueError('Missing or duplicate correctness results')
    if b'PASS: USER_MODEL_COMPATIBILITY_NOT_FORMAL' not in data:raise ValueError('No dedicated compatibility PASS')
    return {'Status':'USER_COMPATIBILITY_BOARD_PASS','SampleCount':n,'CorrectnessRows':len(rows),'FormalResult':False,'PerformanceMeasuredForSubmission':False}
def main():
    p=argparse.ArgumentParser(description=__doc__)
    for k in ('xsdb','hardware-lock','build','payload','out'):p.add_argument('--'+k,type=Path,required=True)
    p.add_argument('--port',required=True);p.add_argument('--timeout',type=int,default=120)
    p.add_argument('--confirm-current-board-session',action='store_true',required=True)
    a=p.parse_args();root=Path(__file__).resolve().parents[1];out=a.out.resolve()
    if any(out.is_relative_to(v) or v.is_relative_to(out) for v in (root,a.build.resolve(),a.payload.resolve())):raise SystemExit('Use disjoint external output')
    if out.exists():raise SystemExit('Output must not exist')
    hardware=json.loads(a.hardware_lock.read_text());build=json.loads((a.build/'build_record.json').read_text());payload=json.loads((a.payload/'user_payload_lock.json').read_text())
    if not hardware.get('UserConfirmedCompatible') or build.get('Status')!='USER_COMPATIBILITY_ELF_LINKED_NOT_BOARD_RUN' or payload.get('PayloadPurpose')!='USER_MODEL_COMPATIBILITY':raise SystemExit('Wrong lock/build purpose')
    if build['BSPFiles']!=hardware['BSPFiles']:raise SystemExit('BSP association mismatch')
    if build['PayloadLockSHA256']!=sha(a.payload/'user_payload_lock.json'):raise SystemExit('Payload lock changed')
    for name,h in payload['Files'].items():
        if sha(a.payload/name)!=h:raise SystemExit('Payload file changed')
    for rec in hardware['Files'].values():
        if sha(Path(rec['Path']))!=rec['SHA256']:raise SystemExit('Hardware input changed')
    elf=a.build/'user_model_compatibility.elf'
    if sha(elf)!=build['ELFSHA256'] or b'USER_MODEL_COMPATIBILITY_NOT_FORMAL' not in elf.read_bytes():raise SystemExit('Wrong ELF')
    import serial
    out.mkdir(parents=True);data=bytearray();capture=out/'serial_private.log';record={'Status':'STARTING','BoardExecuted':False,'FormalResult':False,'CurrentBoardSessionConfirmed':True,'HardwareLockSHA256':sha(a.hardware_lock),'PayloadLockSHA256':sha(a.payload/'user_payload_lock.json'),'ELFSHA256':sha(elf),'SampleCount':payload['SampleCount']}
    def save():(out/'session_record.json').write_text(json.dumps(record,indent=2)+'\n',encoding='utf-8')
    save();child=None
    try:
        with serial.Serial(a.port,115200,timeout=.2,exclusive=True) as port:
            port.reset_input_buffer()
            files=hardware['Files'];cmd=[str(a.xsdb.resolve()),str(root/'scripts/run_batch.tcl'),files['bit']['Path'],files['ps7_init']['Path'],str(elf.resolve())]
            record['LaunchCommand']=cmd;record['BoardExecuted']=True;save()
            with (out/'jtag_private.log').open('wb') as log,capture.open('wb') as uart:
                child=subprocess.Popen(cmd,stdout=log,stderr=subprocess.STDOUT)
                deadline=time.monotonic()+a.timeout
                while time.monotonic()<deadline:
                    chunk=port.read(65536)
                    if chunk:data.extend(chunk);uart.write(chunk);uart.flush()
                    if b'FAIL:' in data:raise RuntimeError('Board firmware failure; inspect private logs')
                    if b'PASS: USER_MODEL_COMPATIBILITY_NOT_FORMAL' in data:break
                    if child.poll() not in (None,0):raise RuntimeError('JTAG launch failed')
                else:raise RuntimeError('Compatibility run timed out')
                rc=child.wait(timeout=20)
                if rc:raise RuntimeError('JTAG launcher returned nonzero')
            if ('DATA_SHA256='+build['InputManifestSHA256']).encode() not in data:raise ValueError('UART input manifest mismatch')
            import numpy as np
            from verify_user_payloads import array
            header=(a.payload/'batch_data.h').read_text()
            expected=(array(header,'batch_predictions'),array(header,'batch_logits'),
                      np.frombuffer((a.payload/'batch_fused_stage_fnv').read_bytes(),dtype='<u4').reshape(-1,3))
            record.update(validate_rows(data,payload['SampleCount'],expected))
            record['UARTSHA256']=hashlib.sha256(data).hexdigest();save();print(record['Status'])
    except BaseException as exc:
        record.update(Status='USER_COMPATIBILITY_STOP',Failure=str(exc));save();raise
    finally:
        if child is not None:
            if child.poll() is None:child.terminate()
            # Halt the primary core after capture/failure. No flash or baseline writes.
            stop=out/'stop_cpu.tcl';stop.write_text('connect -url tcp:localhost:3121\ntargets -set -filter {name =~ "ARM*#0"}\nstop\ndisconnect\nexit\n')
            with (out/'stop_cpu_private.log').open('wb') as log:
                subprocess.run([str(a.xsdb.resolve()),str(stop)],stdout=log,stderr=subprocess.STDOUT,timeout=30)
if __name__=='__main__':main()
