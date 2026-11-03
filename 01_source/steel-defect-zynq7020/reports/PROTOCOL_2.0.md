# Protocol 2.0 fused post-operation interface

| Offset | Register | Access | Expected value / meaning |
|---|---|---|---|
| 0x088 | PROTOCOL_VERSION | RO | 0x00020000 |
| 0x08C | CAPABILITIES | RO | 0x00030102; check exact compatibility value |
| 0x090 | Compatibility/layout ID | RO | 0x00000001 |
| 0x094 | POST_OP | RW while idle | 0 convolution; 1 convolution+ReLU; 2 convolution+ReLU+2x2 MaxPool |

Write/read POST_OP before START. Mode0/1 RX lengths use full output; mode2 uses quarter output for even H/W.
Modes1/2 require zero point0. Conv1 fused uses1; Conv2 fused uses2; legacy uses0 for both.
NCHW/C-major order, 32-bit packing, TKEEP and single TLAST are preserved. POST_OP is a CSR value, not a packet field.

CONTROL accepts command values0,1,2,4,8,12; it is not an arbitrary OR-able command mask.
Formal full270 uses polling; ISR firmware is a separate ELF. A user compatibility ELF performs correctness-only small runs.
Do not interpret the old suite bannerV2 as the Golden package version.
