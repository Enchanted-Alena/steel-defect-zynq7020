# Protocol 2.0 Margin930 Results

Status: **board-tested submission candidate; public release pending**.

## Functional Closure

The same bound Protocol 2.0 bit/XSA/ELF set was used for ISR smoke and the fixed 270-sample run. ARM, Protocol 2.0 `POST_OP=0` legacy PL, and Protocol 2.0 fused PL all produced 217/270 correct predictions (80.37%). The fused and legacy paths matched the frozen reference logits and stage checks in the private audit. Five approved ISR smoke scenarios passed. The private audit independently parsed 3,246 raw records.

The 217/270 result is the frozen model's classification result, not an improvement produced by fusion.

## Timing

The primary statistic is the mean of each sample's median of three repeats:

| Path | Mean |
|---|---:|
| Scalar ARM `-O2` | 10.605938 ms |
| Protocol 2.0 legacy PL (`POST_OP=0`) | 6.095292 ms |
| Protocol 2.0 fused PL (Conv1 `POST_OP=1`; Conv2 `POST_OP=2`) | 5.917320 ms |

Fused PL is 2.9198% faster than the same-run legacy PL path. The ARM/fused ratio is 1.7924x under this restricted measurement. Timing starts from an already-quantized DDR input and ends at `argmax`. It includes PS processing, cache maintenance, DMA, waits, classification, and safety checks. It excludes BMP decoding, resizing, quantization, UART, JTAG, physical power-on, and long-term/thermal qualification. The ARM path is a scalar `-O2` reference and the BSP timer was not externally calibrated.

## Implementation

The formal 100 MHz post-route audit reported WNS `+0.718 ns`, WHS `+0.031 ns`, TNS/THS `0/0`, and zero DRC errors. Full-system utilization was 9,714 LUTs, 13,069 FFs, 28 BRAM tiles, and 69 DSPs. The DSP count is 21 higher than Protocol 1.0 (48 to 69, +43.75%). This resource cost and the modest 2.92% fusion gain must be reported together.

## Supplemental Profiling

A separate instrumented run measured a fusedPL arithmetic-mean total of `5.931708 ms` and provides a host-side interval decomposition. It is supplemental only and does not replace the formal `5.917320 ms` result. The largest observed interval was the Conv2 host call block, which includes cache maintenance, DMA setup/transfer, PL execution, polling/wait, and cleanup; it is not pure DMA time. Existing PL counters show a combined `4.845960 ms` last-input-to-core-done window, including launch/transition overhead. DDR-controller utilization and bandwidth saturation were not measured, so a Memory Wall is not established. See `PROFILING_APPENDIX.md` for the aggregate breakdown and interpretation limits.

## Evidence Boundary

The private audit package contains bit/XSA/ELF hashes, raw UART/JTAG logs, sample-level results, and private model/golden payloads. This public candidate contains none of those payloads. Their absence is intentional and does not mean the public tree can reproduce the private 270-sample run without authorized inputs.
