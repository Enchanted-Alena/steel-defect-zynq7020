# Supplemental Profiling Appendix

Status: **independent instrumented measurement; supplemental evidence only**.

The formal Protocol 2.0 result remains fusedPL `5.917320 ms` (mean of per-sample medians from three repeats across 270 samples). This appendix describes a separate, instrumented run using an isolated profiling ELF and the same approved bit/XSA and frozen private inputs. It does not replace the formal result or its artifact identity.

## Measured Composition

The instrumented fusedPL arithmetic-mean total was `5.931708 ms` over 810 measured inference records. The following mutually exclusive host-side intervals add to that total:

| Host-side interval | Mean (ms) | Share |
|---|---:|---:|
| Input copy and software setup | 0.001715 | 0.029% |
| Conv1 host call block | 1.399457 | 23.593% |
| Conv1 result handling | 0.010111 | 0.170% |
| Conv2 host call block | 4.412575 | 74.390% |
| Conv2 result handling | 0.011577 | 0.195% |
| PS fully connected head | 0.088087 | 1.485% |
| PS argmax | 0.000270 | 0.005% |
| Added hardware snapshot reads | 0.007621 | 0.128% |
| Boundary/residual | 0.000295 | 0.005% |
| **Instrumented total** | **5.931708** | **100.000%** |

The host call blocks include software preparation, cache maintenance, DMA configuration/transfer, hardware execution, polling/wait, and cleanup. They must not be labelled as pure DMA transfer time.

## Hardware Windows

Existing PL counters showed a combined `4.845960 ms` in the two `last input -> core done` windows, about `81.70%` of the instrumented total. Those windows include launch and transition overhead and are not an isolated HLS compute measurement. The input/output handshake windows together were `0.207380 ms`. These hardware windows are nested inside the host call blocks and must not be added to the host total a second time.

The profiling run measured neither DDR-controller utilization nor bandwidth saturation. It does not prove a DDR Memory Wall, and the wait interval cannot be attributed solely to data movement. It also did not measure CPU utilization or quantify released scheduling capacity.

## Interpretation Limits

- Use this decomposition only when clearly labelled as a supplemental instrumented run (`5.931708 ms`).
- Do not draw the decomposition as if it were a breakdown of the official `5.917320 ms` result.
- Do not describe the `last input -> core done` window as exact accelerator compute time.
- Do not claim DDR saturation, a proven Memory Wall, or measured PS scheduling-pressure reduction.
- The report is aggregate-only; raw logs, per-sample records, profiling ELF, private inputs, and goldens remain private.
