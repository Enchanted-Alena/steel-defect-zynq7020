"""Bind locally held hardware and BSP; no tool/board operations.

Checks included bit/PS init against XSA. A user's compatibility assertion is
not a new synthesis, timing, license, or board-test certificate.
"""
from pathlib import Path
import argparse,hashlib,json,zipfile
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def main():
    p=argparse.ArgumentParser(description=__doc__)
    for k in ('bit','xsa','ps7-init','bsp','out'):p.add_argument('--'+k,type=Path,required=True)
    p.add_argument('--confirm-compatible-hardware',action='store_true',required=True)
    a=p.parse_args();out=a.out.resolve();root=Path(__file__).resolve().parents[1]
    if out.is_relative_to(root) or out.exists():raise SystemExit('Use a new external lock file')
    bit,xsa,init,bsp=a.bit.resolve(),a.xsa.resolve(),a.ps7_init.resolve(),a.bsp.resolve()
    with zipfile.ZipFile(xsa) as z:
        bits=[n for n in z.namelist() if n.endswith('.bit')]
        inits=[n for n in z.namelist() if Path(n).name=='ps7_init.tcl']
        if len(bits)!=1 or hashlib.sha256(z.read(bits[0])).hexdigest()!=sha(bit):raise SystemExit('XSA/bit mismatch')
        if len(inits)!=1 or hashlib.sha256(z.read(inits[0])).hexdigest()!=sha(init):raise SystemExit('XSA/PS init mismatch')
    record={'Version':'USER_COMPATIBLE_HARDWARE_R3','UserConfirmedCompatible':True,
            'ProtocolVersion':'0x00020000','Capabilities':'0x00030102','Read90':'0x00000001',
            'Board':'Smart Zynq SL V1.3B','PLClockMHz':100,
            'Files':{k:{'Path':str(v),'SHA256':sha(v)} for k,v in [('bit',bit),('xsa',xsa),('ps7_init',init)]},
            'BSPFiles':{f.relative_to(bsp).as_posix():sha(f) for f in sorted(bsp.rglob('*')) if f.is_file()},
            'BSPAssociation':'USER_ASSERTED_SAME_INTERFACE; VERIFY ORIGINAL BSP/XSA PROVENANCE',
            'BoardExecuted':False,'NewTimingVerified':False}
    out.parent.mkdir(parents=True,exist_ok=True);out.write_text(json.dumps(record,indent=2)+'\n',encoding='utf-8')
    print('LOCAL_HARDWARE_LOCK_WRITTEN_NO_BOARD_ACCESS')
if __name__=='__main__':main()
