"""Prepare a Cortex-A9 standalone SDT BSP from the user's rebuilt XSA.

Run with Vitis 2025.2's embedded Python API (not ordinary system Python).
API signatures were read from the installed 2025.2 vendor source. This new
recipe has not been executed in this RC. No JTAG or board access.
"""
from pathlib import Path
import argparse
import hashlib
import json
import shutil
import sys


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--xsa', type=Path, required=True)
    parser.add_argument('--out', type=Path, required=True, help='New external workspace/export directory')
    args = parser.parse_args()
    root = Path(__file__).resolve().parent.parent
    xsa, out = args.xsa.resolve(), args.out.resolve()
    if not xsa.is_file():
        raise SystemExit('Missing rebuilt XSA')
    if out.is_relative_to(root) or root.is_relative_to(out) or xsa.is_relative_to(out):
        raise SystemExit('Use a tree-external output separate from the input XSA')
    if out.exists() and any(out.iterdir()):
        raise SystemExit('Use a new empty output directory')
    import vitis
    out.mkdir(parents=True, exist_ok=True)
    workspace = out / 'workspace'
    record = {'Status': 'BSP_BUILD_RUNNING', 'RequestedToolRelease': '2025.2',
              'PythonVersion': sys.version, 'XSA_SHA256': sha(xsa),
              'VitisAPI_SHA256': sha(Path(vitis.__file__)),
              'Processor': 'ps7_cortexa9_0', 'OS': 'standalone',
              'Domain': 'standalone_a9', 'BoardAccess': False}

    def save():
        (out / 'bsp_record.json').write_text(json.dumps(record, indent=2), encoding='utf-8')

    save()
    try:
        client = vitis.create_client()
        client.set_workspace(path=str(workspace))
        platform = client.create_platform_component(
            name='margin930_platform', hw_design=str(xsa), cpu='ps7_cortexa9_0',
            os='standalone', domain_name='standalone_a9', architecture='32-bit',
            compiler='gcc', no_boot_bsp=True)
        record['BuildReturnValue'] = str(platform.build())
        exported = workspace / 'margin930_platform/export/margin930_platform/sw/standalone_a9'
        required = ['Xilinx.spec', 'include/xparameters.h', 'include/xil_types.h',
                    'lib/libxilstandalone.a', 'lib/libxiltimer.a', 'lib/libxil.a']
        if not all((exported / name).is_file() for name in required):
            raise RuntimeError('Expected SDT BSP export layout/libraries absent; inspect vendor logs, do not substitute an unrelated BSP')
        shutil.copytree(exported, out / 'bsp')
        init = workspace / 'margin930_platform/hw/sdt/ps7_init.tcl'
        if not init.is_file():
            raise RuntimeError('No matching ps7_init.tcl generated from the input XSA')
        shutil.copy2(init, out / 'ps7_init.tcl')
        record.update(Status='BSP_GENERATED_NOT_FIRMWARE_OR_BOARD_VALIDATED',
                      BSPFiles={p.relative_to(out / 'bsp').as_posix(): sha(p)
                                for p in (out / 'bsp').rglob('*') if p.is_file()},
                      PS7InitSHA256=sha(out / 'ps7_init.tcl'))
        save()
    except BaseException:
        record['Status'] = 'BSP_BUILD_FAILED_STOP'
        save()
        raise


if __name__ == '__main__':
    main()
