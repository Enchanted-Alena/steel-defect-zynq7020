"""Generate eight firmware inputs for the fixed 1->4->8 integer interface.

Default: 270-sample offline demo (never programmable).
--compatibility: 1..16 samples, independent correctness-only firmware path.
No generated payload is a replay of the accepted formal results.
R3 synthetic generation/scalar/C/ARM-link checks are recorded separately.
"""
from pathlib import Path
import argparse
import csv
import hashlib
import json
import sys

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / 'cnn_accelerator/model'))
sys.path.insert(0, str(ROOT / 'cnn_accelerator/tools'))
import numpy as np
from int8_reference import Int8ConvParams, conv2d_int8, wrap_int32
from packet_v1 import JobConfig, describe_layout, pack_job

HEADERS = ['model_params.h', 'board_vectors.h', 'batch_data.h']
BINS = ['conv1_golden_int8.bin', 'conv2_golden_int8.bin',
        'fused_conv1_relu_golden_int8.bin', 'fused_conv2_relu_pool_golden_int8.bin',
        'batch_fused_stage_fnv']
PURPOSE = 'USER_MODEL_OFFLINE_DEMO'


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def json_write(path, value):
    path.write_text(json.dumps(value, sort_keys=True, indent=2) + '\n', encoding='utf-8')


def fnv1a(data):
    value = 0x811C9DC5
    for byte in data:
        value = ((value ^ byte) * 0x01000193) & 0xFFFFFFFF
    return value


def c_array(ctype, name, values, shape=None):
    arr = np.asarray(values)
    dims = shape or arr.shape
    suffix = ''.join('[' + str(d) + ']' for d in dims)
    # Flat initialization of a multi-dimensional C array is legal but triggers
    # -Wmissing-braces. Emit explicit row braces for the 2D firmware tables.
    if len(dims) == 2:
        rows = arr.reshape(dims)
        body = ''.join(' {' + ','.join(str(int(v)) for v in row) + '},\n' for row in rows)
    else:
        flat = arr.reshape(-1)
        body = ''.join(' ' + ','.join(str(int(v)) for v in flat[i:i+24]) + ',\n'
                       for i in range(0, flat.size, 24))
    return 'static const ' + ctype + ' ' + name + suffix + ' = {\n' + body + '};\n'


def integer_array(values, shape, low, high, name):
    arr = np.asarray(values)
    if arr.shape != shape or arr.dtype.kind not in 'iu' or np.any(arr < low) or np.any(arr > high):
        raise ValueError('Invalid integer shape/range for ' + name)
    return arr.astype(np.int64)


def load_model(model, contract_path):
    contract = json.loads(contract_path.read_text(encoding='utf-8-sig'))
    if [x['op'] for x in contract['architecture']] != ['hconv', 'ps_relu', 'hconv', 'ps_relu', 'ps_maxpool2x2', 'ps_fc', 'ps_argmax']:
        raise ValueError('Only the documented convolution/ReLU/pool/FC chain is supported')
    rules = contract['integer_contract']
    if any(rules[k] != 0 for k in ['input_zero_point', 'weight_zero_points', 'padding_value', 'output_zero_point']):
        raise ValueError('Only the frozen interface zero-point-zero/padding-zero convention is supported')
    layers = [x for x in contract['architecture'] if x['op'] == 'hconv']
    if len(layers) != 2:
        raise ValueError('Only the two-layer 1->4->8 interface is supported')
    params, weights = [], []
    with np.load(model, allow_pickle=False) as data:
        for i, (ci, co) in enumerate([(1, 4), (4, 8)]):
            layer = layers[i]
            if layer['shape'] != [1, ci, co, 32, 32, 1, 0] or layer['K'] != 3 or layer['stride'] != 1 or layer['pad'] != 1:
                raise ValueError('Unsupported shape, stride, padding or zero point')
            if layer.get('output_zero_point', 0) != 0:
                raise ValueError('This adapter requires symmetric zero-point-zero activations')
            w = integer_array(data[f'q_w{i+1}'], (co, ci, 3, 3), -128, 127, 'weights').astype(np.int8)
            bias = integer_array(layer['bias_int'], (co,), -(1 << 31), (1 << 31)-1, 'bias')
            mult = integer_array(layer['M'], (co,), 0, (1 << 31)-1, 'multiplier')
            shifts = integer_array(layer['shift'], (co,), 0, 62, 'shifts')
            # Bind NPZ parameters to the contract instead of silently choosing
            # one of two potentially inconsistent parameter sources.
            for key, expected in [(f'bias_int_{i+1}', bias), (f'M{i+1}', mult), (f'shift{i+1}', shifts)]:
                actual = integer_array(data[key], (co,), -(1 << 31), (1 << 31)-1, key)
                if not np.array_equal(actual, expected):
                    raise ValueError('NPZ/contract mismatch: ' + key)
            scale = np.asarray(layer['weight_scale_per_channel'], dtype=np.float64)
            if scale.shape != (co,) or not np.all(np.isfinite(scale)) or np.any(scale <= 0):
                raise ValueError('Invalid weight scales')
            if any(not np.isfinite(float(layer[k])) or float(layer[k]) <= 0 for k in ['s_in', 's_out']):
                raise ValueError('Invalid activation scales')
            params.append(Int8ConvParams(name=f'conv{i+1}', K=3, stride=1, pad=1,
                          Cin=ci, Cout=co, activation='none', leaky_alpha=0.1,
                          zero_point=0, s_in=float(layer['s_in']), s_out=float(layer['s_out']),
                          s_w=scale, bias_int=bias, M=mult, shift=shifts))
            weights.append(w)
        fc_w = integer_array(data['q_w3'], (6, 2048), -128, 127, 'FC weights').astype(np.int8)
        fc_b = integer_array(data['b3_int'], (6,), -(1 << 31), (1 << 31)-1, 'FC bias')
    fc_layers = [x for x in contract['architecture'] if x['op'] == 'ps_fc']
    if len(fc_layers) != 1 or fc_layers[0]['shape'] != [2048, 6] or not np.array_equal(fc_b, fc_layers[0]['bias_int']):
        raise ValueError('FC contract mismatch')
    if contract['architecture'][4]['out_shape'] != [1, 8, 16, 16] or params[1].s_in != params[0].s_out:
        raise ValueError('Pool shape or inter-layer scale contract mismatch')
    return params, weights, fc_w, fc_b


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--model', type=Path, required=True, help='User model NPZ from train_quantize_eval.py')
    parser.add_argument('--contract', type=Path, required=True, help='Matching model_contract_v1.json')
    parser.add_argument('--inputs', type=Path, required=True, help='Default: 270x1024 signed INT8 bytes; --compatibility: Nx1024, N=1..16; NCHW')
    parser.add_argument('--index', type=Path, required=True, help='Matching CSV: default idx=0..269; --compatibility idx=0..N-1; label=0..5')
    parser.add_argument('--out', type=Path, required=True, help='New external private output directory')
    parser.add_argument('--compatibility', action='store_true',
                        help='Independent 1..16 sample compatibility payload, never formal 270 results')
    args = parser.parse_args()
    inputs = [args.model.resolve(), args.contract.resolve(), args.inputs.resolve(), args.index.resolve()]
    out = args.out.resolve()
    if out.is_relative_to(ROOT) or ROOT.is_relative_to(out) or any(p.is_relative_to(out) for p in inputs):
        raise SystemExit('Use a new tree-external output, separate from all inputs')
    if out.exists() and any(out.iterdir()):
        raise SystemExit('Output directory must be new and empty')
    if not all(p.is_file() for p in inputs):
        raise SystemExit('Missing model/contract/quantized-input/index file')
    raw = args.inputs.read_bytes()
    count = len(raw)//1024
    if len(raw) % 1024 or (not args.compatibility and count != 270) or (args.compatibility and not 1 <= count <= 16):
        raise SystemExit('Expected 270 offline samples, or 1..16 samples with --compatibility')
    purpose = 'USER_MODEL_COMPATIBILITY' if args.compatibility else PURPOSE
    x = np.frombuffer(raw, dtype=np.int8).reshape(count, 1, 1, 32, 32)
    with args.index.open(encoding='utf-8-sig', newline='') as f:
        rows = list(csv.DictReader(f))
    if len(rows) != count or any(int(row['idx']) != i or not 0 <= int(row['label']) < 6 for i, row in enumerate(rows)):
        raise SystemExit('Invalid ordered sample index')
    for i,row in enumerate(rows):
        actual = hashlib.sha256(raw[i*1024:(i+1)*1024]).hexdigest()
        if row.get('input_sha256') and row['input_sha256'].lower() != actual:
            raise SystemExit('Per-input identity mismatch at row '+str(i))
    params, weights, fc_w, fc_b = load_model(args.model, args.contract)
    out.mkdir(parents=True, exist_ok=True)
    record = {'PayloadPurpose': purpose, 'FormalFrozenReplay': False, 'PrivateDerivedData': True,
              'Inputs': {name: sha(p) for name, p in zip(['model', 'contract', 'inputs', 'index'], inputs)},
              'ReferenceSHA256': {p.name: sha(p) for p in [ROOT / 'cnn_accelerator/model/int8_reference.py',
                                                        ROOT / 'cnn_accelerator/model/tensor_utils.py',
                                                        ROOT / 'cnn_accelerator/tools/packet_v1.py']},
              'GeneratorSHA256': sha(Path(__file__)), 'SampleCount': count,
              'OrderedInputs': [{'idx':i, 'label':int(row['label']),
                 'input_sha256':hashlib.sha256(raw[i*1024:(i+1)*1024]).hexdigest()} for i,row in enumerate(rows)],
              'ExpectedResult': 'computed from supplied user model; no promised 217/270'}
    manifest_path = out / 'user_input_manifest.json'
    json_write(manifest_path, record)
    arrays = [np.empty((count, size), dtype=np.int8) for size in [4096, 8192, 4096, 2048]]
    g1, g2, r1s, pools = arrays
    logits = np.empty((count, 6), dtype='<i4')
    predictions = np.empty(count, dtype=np.uint32)
    hashes = np.empty((count, 3), dtype='<u4')
    for i in range(count):
        q1 = conv2d_int8(x[i], weights[0], params[0], fuse_activation=False)
        r1 = np.maximum(q1, 0).astype(np.int8)
        q2 = conv2d_int8(r1, weights[1], params[1], fuse_activation=False)
        r2 = np.maximum(q2, 0).astype(np.int8)
        pooled = r2.reshape(1, 8, 16, 2, 16, 2).max(axis=(3, 5))
        g1[i], g2[i], r1s[i], pools[i] = q1.ravel(), q2.ravel(), r1.ravel(), pooled.ravel()
        logits[i] = wrap_int32(pooled.reshape(1, 2048).astype(np.int64) @ fc_w.T.astype(np.int64) + fc_b).reshape(6)
        predictions[i] = int(np.argmax(logits[i]))
        hashes[i] = [fnv1a(r1s[i].tobytes()), fnv1a(pools[i].tobytes()), fnv1a(logits[i].tobytes())]
    for name, arr in zip(BINS, [g1, g2, r1s, pools, hashes]):
        (out / name).write_bytes(arr.tobytes(order='C'))
    header = '#ifndef MODEL_PARAMS_H\n#define MODEL_PARAMS_H\n#include <stdint.h>\n'
    for i, param in enumerate(params):
        for typ, key, arr in [('int8_t', 'weights', weights[i]), ('int32_t', 'bias', param.bias_int),
                              ('int32_t', 'mult', param.M), ('uint8_t', 'shifts', param.shift)]:
            header += c_array(typ, f'model_{key}_{i}', arr, (arr.size,))
    header += c_array('int8_t', 'fc_weights', fc_w, (fc_w.size,))
    header += c_array('int32_t', 'fc_bias', fc_b) + '#endif\n'
    (out / 'model_params.h').write_text(header, encoding='ascii')
    header = '#ifndef BOARD_VECTORS_H\n#define BOARD_VECTORS_H\n#include "xil_types.h"\n'
    descriptors = []
    for i, (ci, co, data, golden) in enumerate([(1, 4, x[0], g1[0]), (4, 8, r1s[0].reshape(1, 4, 32, 32), g2[0])]):
        cfg = JobConfig(1, ci, co, 32, 32, 1, 0)
        param = params[i]
        payload = pack_job(cfg, weights[i], param.bias_int, param.M, param.shift, data)
        layout = describe_layout(cfg)
        if len(payload) > 16383 or golden.size > 16383:
            raise ValueError('DMA packet exceeds the fixed interface')
        header += c_array('u8', f'payload_{i}', np.frombuffer(payload, dtype=np.uint8))
        header += c_array('u8', f'golden_{i}', golden.view(np.uint8))
        fields = [1, ci, co, 32, 32, 1, 0, len(payload), golden.size,
                  layout['input_offset'], layout['input_bytes'], -1 if i == 0 else 0]
        descriptors.append(' {' + ','.join(map(str, fields)) + f',payload_{i},golden_{i}' + '}')
    header += ('typedef struct {int n,ci,co,h,w,p,z;u32 tx_bytes,rx_bytes,input_offset,input_bytes;'
               'int parent;const u8 *payload,*golden;} Job;\n'
               '#define JOB_COUNT 2U\n#define MAX_TX_BYTES 16383U\n#define MAX_RX_BYTES 16383U\n'
               'static const Job jobs[JOB_COUNT]={\n' + ',\n'.join(descriptors) + '\n};\n#endif\n')
    (out / 'board_vectors.h').write_text(header, encoding='ascii')
    header = ('#ifndef BATCH_DATA_H\n#define BATCH_DATA_H\n#include <stdint.h>\n'
              '#define BATCH_DATA_FORMAL 0U\n#define USER_PAYLOAD_OFFLINE_ONLY '+str(int(not args.compatibility))+'U\n'
              '#define USER_PAYLOAD_COMPATIBILITY '+str(int(args.compatibility))+'U\n#define BATCH_COUNT '+str(count)+'U\n'
              '#define BATCH_MANIFEST_SHA256 "' + sha(manifest_path) + '"\n')
    header += c_array('int8_t', 'batch_inputs', x.reshape(count, 1024))
    header += c_array('int32_t', 'batch_logits', logits)
    header += c_array('unsigned', 'batch_predictions', predictions) + '#endif\n'
    (out / 'batch_data.h').write_text(header, encoding='ascii')
    files = {name: sha(out / name) for name in HEADERS + BINS}
    lock = {'PayloadPurpose': purpose, 'SampleCount': count, 'ProtocolVersion': '0x00020000',
            'Files': files, 'DataManifestSHA256': sha(manifest_path), 'DoNotProgram': not args.compatibility,
            'NeedsExplicitBoardSession': True, 'FormalFrozenReplay': False}
    json_write(out / 'user_payload_lock.json', lock)
    json_write(out / 'user_baseline_lock.json', {'PayloadPurpose': purpose,
               'Files': {name: files[name] for name in HEADERS + BINS[:2]}})
    (out / 'PRIVATE_USER_PAYLOAD.txt').write_text(
        'User-derived numerical payload. Not a public source artifact or formal frozen replay.\n'
        'Compatibility requires a dedicated builder and explicit board session. Never cite formal accuracy.\n', encoding='utf-8')
    print('USER_PAYLOADS_GENERATED_NOT_FORMAL_OR_BOARD_VALIDATED')


if __name__ == '__main__':
    main()
