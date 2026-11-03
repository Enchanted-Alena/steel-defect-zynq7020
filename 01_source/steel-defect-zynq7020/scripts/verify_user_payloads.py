"""Check eight-file layout, headers, Golden stages, FNV and ordered identities.

Independent scalar convolution/requantization for compatibility sets (1..16).
Does not use int8_reference.py or generate_user_payloads.py to compute outputs.
"""
from pathlib import Path
import argparse, hashlib, json, re, struct
import numpy as np

def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def array(text,name):
    m=re.search(r'\b'+re.escape(name)+r'((?:\[\d+\])+)\s*=\s*\{(.*?)\};',text,re.S)
    if not m:raise ValueError('Missing array '+name)
    shape=tuple(map(int,re.findall(r'\d+',m[1])))
    return np.array(list(map(int,re.findall(r'-?\d+',m[2]))),dtype=np.int64).reshape(shape)
def wrap(x):return (int(x)+(1<<31))%(1<<32)-(1<<31)
def conv(x,w,b,m,s):
    ci,h,width=x.shape;co=w.shape[0];out=np.empty((co,h,width),dtype=np.int8)
    pad=np.pad(x,((0,0),(1,1),(1,1)))
    for o in range(co):
        for y in range(h):
            for xx in range(width):
                acc=wrap(int(b[o])+sum(int(pad[c,y+dy,xx+dx])*int(w[o,c,dy,dx]) for c in range(ci) for dy in range(3) for dx in range(3)))
                product=acc*int(m[o]);shift=int(s[o])
                if shift:
                    q,rem=divmod(product,1<<shift);half=1<<(shift-1)
                    product=q+int(rem>half or (rem==half and q%2!=0))
                out[o,y,xx]=max(-128,min(127,product))
    return out
def fnv(data):
    value=0x811c9dc5
    for v in data:value=((value^v)*0x01000193)&0xffffffff
    return value
def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--payload',type=Path,required=True);a=p.parse_args();d=a.payload
    lock=json.loads((d/'user_payload_lock.json').read_text());n=lock['SampleCount']
    if lock.get('PayloadPurpose')!='USER_MODEL_COMPATIBILITY' or not 1<=n<=16:raise ValueError('Compatibility input required')
    if (lock.get('ProtocolVersion')!='0x00020000' or lock.get('FormalFrozenReplay') is not False or
        lock.get('DoNotProgram') is not False or lock.get('NeedsExplicitBoardSession') is not True):
        raise ValueError('Compatibility protocol/session lock required')
    names=['model_params.h','board_vectors.h','batch_data.h','conv1_golden_int8.bin','conv2_golden_int8.bin','fused_conv1_relu_golden_int8.bin','fused_conv2_relu_pool_golden_int8.bin','batch_fused_stage_fnv']
    if set(lock['Files'])!=set(names):raise ValueError('Eight-file lock mismatch')
    for name in names:
        if sha(d/name)!=lock['Files'][name]:raise ValueError('SHA mismatch '+name)
    manifest=json.loads((d/'user_input_manifest.json').read_text())
    if sha(d/'user_input_manifest.json')!=lock['DataManifestSHA256']:raise ValueError('Manifest mismatch')
    mt=(d/'model_params.h').read_text();bt=(d/'batch_data.h').read_text();vt=(d/'board_vectors.h').read_text()
    x=array(bt,'batch_inputs').astype(np.int8);logits=array(bt,'batch_logits');pred=array(bt,'batch_predictions')
    if x.shape!=(n,1024) or logits.shape!=(n,6) or pred.shape!=(n,):raise ValueError('Header shape mismatch')
    arrays=[]
    for i,(ci,co) in enumerate(((1,4),(4,8))):
        arrays.append((array(mt,f'model_weights_{i}').reshape(co,ci,3,3),array(mt,f'model_bias_{i}'),array(mt,f'model_mult_{i}'),array(mt,f'model_shifts_{i}')))
    fw=array(mt,'fc_weights').reshape(6,2048);fb=array(mt,'fc_bias');gs=[bytearray() for _ in range(5)]
    for idx in range(n):
        if manifest['OrderedInputs'][idx]['idx']!=idx or hashlib.sha256(x[idx].tobytes()).hexdigest()!=manifest['OrderedInputs'][idx]['input_sha256']:raise ValueError('Ordered identity mismatch')
        q1=conv(x[idx].reshape(1,32,32),*arrays[0]);r1=np.maximum(q1,0).astype(np.int8)
        q2=conv(r1,*arrays[1]);r2=np.maximum(q2,0).astype(np.int8)
        pool=np.empty((8,16,16),dtype=np.int8)
        for c in range(8):
            for y in range(16):
                for xx in range(16):pool[c,y,xx]=max(int(r2[c,y*2+dy,xx*2+dx]) for dy in (0,1) for dx in (0,1))
        flat=pool.ravel();score=[wrap(int(fb[c])+sum(int(v)*int(w) for v,w in zip(flat,fw[c]))) for c in range(6)]
        if list(logits[idx])!=score or int(pred[idx])!=max(range(6),key=lambda c:score[c]):raise ValueError('FC/argmax mismatch')
        for target,value in zip(gs[:4],(q1,q2,r1,pool)):target.extend(value.tobytes())
        gs[4].extend(struct.pack('<III',fnv(r1.tobytes()),fnv(pool.tobytes()),fnv(struct.pack('<6i',*score))))
        if idx==0:
            for layer,inp,golden in ((0,x[0].tobytes(),q1),(1,r1.tobytes(),q2)):
                w,b,m,s=arrays[layer];payload=bytearray(w.astype(np.int8).tobytes())
                payload.extend(b.astype('<i4').tobytes());payload.extend(m.astype('<i4').tobytes());payload.extend(s.astype('u1').tobytes())
                payload.extend(bytes((-len(payload))%4));payload.extend(inp);payload.extend(bytes((-len(payload))%4))
                if array(vt,f'payload_{layer}').astype('u1').tobytes()!=payload or array(vt,f'golden_{layer}').astype('u1').tobytes()!=golden.view('u1').tobytes():raise ValueError('Job packet/Golden header mismatch')
    for name,value in zip(names[3:],gs):
        if (d/name).read_bytes()!=value:raise ValueError('Independent scalar comparison failed '+name)
    print(json.dumps({'Status':'EIGHT_PAYLOADS_SCALAR_REFERENCE_PASS','SampleCount':n,'FourGoldenBytewise':True,'StageFNVLittleEndian':True,'HeaderAndJobPackets':True,'OrderedInputIdentity':True,'BoardExecuted':False,'FormalResultReproduced':False}))
if __name__=='__main__':main()
