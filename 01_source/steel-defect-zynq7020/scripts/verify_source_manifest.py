"""Read-only source manifest verification. No compiler or board access."""
from pathlib import Path, PurePosixPath
import argparse
import hashlib

# Only these explicitly named tool/Git artifacts are outside source coverage.
HLS_BUILD = ('hardware', 'hls_source', 'build_fused_csim_2025_2')

def excluded(rel):
    return rel.parts[0] == '.git' or rel.parts[:len(HLS_BUILD)] == HLS_BUILD


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--root', type=Path, default=Path(__file__).resolve().parent.parent)
    p.add_argument('--manifest', default='RC_SHA256SUMS.txt')
    args=p.parse_args()
    root = args.root.resolve()
    manifest_rel=PurePosixPath(args.manifest)
    if manifest_rel.is_absolute() or '..' in manifest_rel.parts or len(manifest_rel.parts)!=1:
        raise SystemExit('Manifest must be a root-level filename')
    covered = set()
    for line in (root / args.manifest).read_text(encoding='utf-8').splitlines():
        digest, name = line.split('  ', 1)
        rel = PurePosixPath(name)
        if rel.is_absolute() or '..' in rel.parts or ':' in name or '\\' in name or excluded(rel):
            raise SystemExit('Unsafe manifest path')
        f = (root / name).resolve()
        if not f.is_relative_to(root) or not f.is_file() or name in covered:
            raise SystemExit('Missing, duplicate, or escaping payload: ' + name)
        if hashlib.sha256(f.read_bytes()).hexdigest() != digest:
            raise SystemExit('Hash mismatch: ' + name)
        covered.add(name)
    actual = {f.relative_to(root).as_posix() for f in root.rglob('*') if f.is_file()
              and f.relative_to(root).as_posix() != args.manifest
              and not excluded(f.relative_to(root))}
    if actual != covered:
        raise SystemExit('Unlisted or missing files: ' + repr(sorted(actual ^ covered)))
    print('SOURCE_MANIFEST_PASS files=' + str(len(covered)))
    print('This confirms file integrity only; release permission and clean-build status are separate.')


if __name__ == '__main__':
    main()
