"""Rebuild fused HLS in a new external directory, using Vitis 2025.2.

Runs synthetic CSim, synthesis, Verilog co-simulation and IP export. No board.
The project-metadata path normalization works around the observed first-create
relative-source issue; it never edits synthesized Verilog.
"""
from pathlib import Path
import argparse,hashlib,json,subprocess,xml.etree.ElementTree as ET

def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--vitis-run',type=Path,required=True)
    p.add_argument('--out',type=Path,required=True)
    a=p.parse_args()
    source=Path(__file__).resolve().parent
    candidate=source.parents[1]
    out=a.out.resolve()
    if out==candidate or out.is_relative_to(candidate):raise SystemExit('Build outside candidate source tree')
    if out.exists() and any(out.iterdir()):raise SystemExit('Use a new empty build directory')
    out.mkdir(parents=True,exist_ok=True)
    tool=a.vitis_run.resolve()
    if not tool.is_file():raise SystemExit('Missing vitis-run')
    def quoted(path):
        s=path.as_posix()
        if any(c in s for c in '{}\n\r'):raise ValueError('Unsupported Tcl path characters')
        return '{'+s+'}'
    project=out/'project'
    design=source/'int8_conv3x3.cpp';tb=source/'test_fused_extended.cpp'
    setup='\n'.join([
      'open_project '+quoted(project),
      'set_top int8_conv3x3',
      'add_files '+quoted(design),
      'add_files -tb '+quoted(tb),
      'open_solution solution1 -flow_target vivado',
      'set_part xc7z020clg484-1',
      'create_clock -period 8 -name default',
      'config_compile -pipeline_loops 0',
      'close_project','exit',''])
    (out/'setup.tcl').write_text(setup,encoding='utf-8')
    state={'status':'PREPARED','board_authorized':False,'source_hashes':{},'commands':[]}
    sha=lambda f:hashlib.sha256(f.read_bytes()).hexdigest()
    state['source_hashes']={f.name:sha(f) for f in [design,source/'int8_conv3x3.h',tb]}
    def save(): (out/'build_record.json').write_text(json.dumps(state,indent=2),encoding='utf-8')
    def run(stage,script):
        state['status']=stage+'_RUNNING';save()
        command=[str(tool),'--mode','hls','--tcl',str(script)]
        result=subprocess.run(command,cwd=out,capture_output=True,text=True,errors='replace')
        (out/(stage+'.log')).write_text(result.stdout+result.stderr,encoding='utf-8')
        state['commands'].append({'stage':stage,'command':command,'exit_code':result.returncode})
        print(stage,'exit',result.returncode,flush=True)
        if result.returncode:
            state['status']=stage+'_FAILED';save();raise SystemExit(result.returncode)
    run('setup',out/'setup.tcl')
    app=project/'hls.app'
    (out/'hls.app.before_normalization.xml').write_bytes(app.read_bytes())
    tree=ET.parse(app)
    for f in tree.getroot().find('files'):
        f.attrib['name']=(tb if f.attrib.get('tb') in ['1','true'] else design).as_posix()
        if f.attrib.get('tb') in ['1','true']:
            f.attrib['cflags']='-Wno-unknown-pragmas'
    tree.write(app,encoding='utf-8',xml_declaration=False)
    for stage,commands in [('csim',['csim_design -clean']),
       ('synth_cosim_export',['csynth_design','cosim_design -rtl verilog -tool xsim -trace_level none',
                             'export_design -format ip_catalog -output '+quoted(out/'int8_conv3x3_fused.zip')])]:
        script=out/(stage+'.tcl')
        script.write_text('\n'.join(['open_project '+quoted(project),'open_solution solution1 -flow_target vivado',
                                    *commands,'close_project','exit','']),encoding='utf-8')
        run(stage,script)
    top=project/'solution1/syn/verilog/int8_conv3x3.v'
    if 'input  [31:0] post_op;' not in top.read_text():raise SystemExit('Missing expected post_op port')
    state.update(status='SYNTHETIC_HLS_REBUILD_PASS_NOT_BOARD',
                 ip_sha256=sha(out/'int8_conv3x3_fused.zip'),
                 generated_rtl={f.name:sha(f) for f in (project/'solution1/syn/verilog').glob('*.v')})
    save();print(state['status'],flush=True)

if __name__=='__main__':main()
