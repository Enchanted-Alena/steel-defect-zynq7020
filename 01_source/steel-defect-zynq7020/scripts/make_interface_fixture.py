"""Create a small synthetic integer-interface fixture, not a trained model.

No real dataset, classification accuracy, or formal-result reproduction claim.
All generated numerical values are locally created test stimuli.
"""
from pathlib import Path
import argparse,csv,hashlib,json
import numpy as np

def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--out',type=Path,required=True);a=p.parse_args()
    out=a.out.resolve();root=Path(__file__).resolve().parents[1]
    if out.is_relative_to(root) or root.is_relative_to(out):raise SystemExit('Use an external fixture directory')
    if out.exists() and any(out.iterdir()):raise SystemExit('New empty directory required')
    rng=np.random.Generator(np.random.PCG64(20261102));data={};arch=[]
    for i,(ci,co) in enumerate(((1,4),(4,8)),1):
        data[f'q_w{i}']=rng.integers(-3,4,(co,ci,3,3),dtype=np.int8)
        bias=np.array(([2147483647,-2147483648,3,-3]*2)[:co],dtype=np.int32)
        m=np.array(([1,2147483647,3,0]*2)[:co],dtype=np.int32)
        s=np.array(([0,62,3,1]*2)[:co],dtype=np.uint8)
        data[f'bias_int_{i}']=bias;data[f'M{i}']=m;data[f'shift{i}']=s
        arch.extend([{'op':'hconv','shape':[1,ci,co,32,32,1,0],'K':3,'stride':1,'pad':1,
                     'bias_int':bias.tolist(),'M':m.tolist(),'shift':s.tolist(),
                     'weight_scale_per_channel':[1.0]*co,'s_in':1.0,'s_out':1.0,'output_zero_point':0},{'op':'ps_relu'}])
    data['q_w3']=rng.integers(-3,4,(6,2048),dtype=np.int8)
    data['b3_int']=np.array([2147483647,-2147483648,0,1,-1,3],dtype=np.int32)
    arch.extend([{'op':'ps_maxpool2x2','out_shape':[1,8,16,16]},
                 {'op':'ps_fc','shape':[2048,6],'bias_int':data['b3_int'].tolist()},{'op':'ps_argmax'}])
    contract={'architecture':arch,'integer_contract':{k:0 for k in ('input_zero_point','weight_zero_points','padding_value','output_zero_point')},
              'FixtureOnly':True,'TrainedModel':False,'GroundTruthLabels':False}
    out.mkdir(parents=True,exist_ok=True);np.savez(out/'fixture_model.npz',**data)
    (out/'fixture_contract.json').write_text(json.dumps(contract,indent=2)+'\n',encoding='utf-8')
    x=np.stack([np.zeros(1024,dtype=np.int8),np.arange(1024,dtype=np.int16).astype(np.int8),rng.integers(-128,128,1024,dtype=np.int8)])
    (out/'inputs_int8.bin').write_bytes(x.tobytes())
    with (out/'index.csv').open('w',encoding='utf-8',newline='') as f:
        w=csv.writer(f);w.writerow(['idx','label','input_sha256','source'])
        for i,row in enumerate(x):w.writerow([i,0,hashlib.sha256(row.tobytes()).hexdigest(),'SYNTHETIC_INTERFACE_STIMULUS_LABEL_NOT_GROUND_TRUTH'])
    (out/'FIXTURE_ONLY.txt').write_text('Synthetic interface stimuli; not trained, not real evaluation labels, not 217/270.\n')
    print('SYNTHETIC_INTERFACE_FIXTURE_CREATED_NO_CLASSIFICATION_CLAIM')
if __name__=='__main__':main()
