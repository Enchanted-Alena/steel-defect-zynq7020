"""Extract local PS settings from a lawfully obtained board reference archive.

Does not download, execute archive content, redistribute the reference project,
run synthesis, or program hardware. Vivado generates the normalized TSV later.
"""
from pathlib import Path
import argparse, hashlib, json, zipfile

EXPECTED_ARCHIVE = 'db2d96bb8406bafb67f6b57b5b5b80dd476bf88a498105ac39d653c1a2323b15'
EXPECTED_BD = 'f6dc792f2f3ecc58a5d73fe9f72146692cefe76f21986c7bb6b41e15ff836eeb'
ENTRY = '08_PS_UART_TEST/UART_TEST/UART_TEST.srcs/sources_1/bd/ZYNQ/ZYNQ.bd'

def sha(data): return hashlib.sha256(data).hexdigest()

def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--archive', type=Path, required=True)
    p.add_argument('--out', type=Path, required=True)
    p.add_argument('--confirm-lawful-local-use', action='store_true', required=True,
                   help='Confirm you may use this board reference locally; not a redistribution license')
    a = p.parse_args(); root = Path(__file__).resolve().parents[1]
    archive, out = a.archive.resolve(), a.out.resolve()
    if out.is_relative_to(root) or root.is_relative_to(out) or archive.is_relative_to(out):
        raise SystemExit('Use a new external directory separate from source and archive')
    if out.exists() and any(out.iterdir()): raise SystemExit('Output must be new and empty')
    if sha(archive.read_bytes()) != EXPECTED_ARCHIVE:
        raise SystemExit('Unknown board archive: do not guess DDR/MIO configuration')
    with zipfile.ZipFile(archive) as z:
        raw = z.read(ENTRY)
    if sha(raw) != EXPECTED_BD: raise SystemExit('Board reference identity mismatch')
    config = json.loads(raw)['design']['components']['processing_system7_0']['parameters']
    if len(config) != 355: raise SystemExit('Unexpected PS parameter count')
    lines = []
    for key, item in sorted(config.items()):
        value = item['value']
        if not isinstance(value, str) or any(c in key+value for c in '\t\r\n'):
            raise SystemExit('Unsupported PS parameter encoding')
        lines.append(key+'\t'+value+'\n')
    out.mkdir(parents=True, exist_ok=True)
    (out/'vendor_ps_parameters.tsv').write_text(''.join(lines), encoding='utf-8')
    # This local entry uses team-authored connection code, not the old exported
    # Vivado framework. $root and $board_inputs are set by the build recipe.
    (out/'cnn_system_bd.tcl').write_text(
        '# Local generated entry; not the historical exported BD Tcl.\n'
        'source [file join $root scripts create_cnn_connections.tcl]\n', encoding='utf-8')
    files = {f.name:sha(f.read_bytes()) for f in out.iterdir() if f.is_file()}
    record = {'Version':'BOARD_LOCAL_INPUTS_R3','ArchiveSHA256':EXPECTED_ARCHIVE,
              'OriginalBDEntry':ENTRY,'OriginalBDSHA256':EXPECTED_BD,'Files':files,
              'RedistributionPermissionConfirmed':False,'LocalUseConfirmed':True,
              'NormalizedTSV':'GENERATED_LOCALLY_BY_VIVADO_NOT_YET_RUN',
              'GeneratorSHA256':sha(Path(__file__).read_bytes())}
    (out/'board_input_lock.json').write_text(json.dumps(record,indent=2)+'\n',encoding='utf-8')
    print('LOCAL_PS_PARAMETERS_AND_TEAM_BD_ENTRY_PREPARED_NO_IMPLEMENTATION')

if __name__ == '__main__': main()
