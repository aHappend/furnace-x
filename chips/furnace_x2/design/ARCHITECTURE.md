# FURNACE-X2 implementation architecture

## Provisional implementation

The provenance prerequisite is amended as admitted: authentic parent handoff
reading, reconciliation and independently reviewed resolution of conflicts are
mandatory before acceptance, while provisional implementation may proceed.
`GENERATIONAL_HANDOFF.md` is not fabricated. Parent timing/PPA is unknown.
Historical parent acceptance cannot certify the X2 changes.

`rtl/furnace_x1_*.sv` and the other original parent modules are deliverable
copies of the immutable `furnace_x1_reference/rtl/` sources. Their original
hierarchy is retained for separate compatibility elaboration. X2 integration
must derive from that datapath, not instantiate a second independent tensor.

## Datapath decisions

Arithmetic leaves use a global elastic pipeline enable. When the final valid
register is stalled, all arithmetic and validity stages freeze together. When
it is empty or consumed, every stage advances by one. This is intentionally
simpler than individual-stage skid control and preserves the exact no-stall
latencies in `SPEC.md`.

The bilinear pipeline separates horizontal products, horizontal sums, vertical
products and rounded total. Multiplication widths cover 255*256*256 exactly.
Spatial processing forms three signed row partials for each kernel, then
reduces rows and publishes sign-extended 16-bit lanes. FIR captures coefficient
products and same-edge first-sample history selection, sums pairs, reduces, and
publishes the arithmetic shift without intermediate truncation.

Fusion uses two bounded queues and one registered paired output. A pair is
formed only from pre-edge resident heads, never newly enqueued values.
Simultaneous dequeue/enqueue changes neither queue count. Explicit terminal
comparisons support singleton and non-power-of-two depths. Unequal IDs take
precedence over feature errors; otherwise vision error takes precedence.

The QoS fabric retains parent header registration and independent read/write
ownership. Only selection changes: a scan in rotated tie order replaces the
candidate only for strictly greater QoS. Thus the first candidate at a priority
wins ties, while a later strictly higher-priority requester wins selection.
The tie cursor advances when ownership is accepted.

## Streaming storage and scheduling

`furnace_x2_vision` uses two input lines and three resized output lines, with
synchronous RAM reads and no RAM reset. It pauses input at each required source
row, reads the four resampling taps over bounded cycles, and writes interpolated
pixels to the three-line circular store. Once the following resized row exists,
it computes the preceding row's spatial neighborhoods. Top/bottom and left/right
edges replicate. Elaboration-time coordinate tables are generated using integer
shift/subtract arithmetic, not synthesizable division. Explicit row readiness
checks handle both repeated source rows during enlargement and skipped source
rows during reduction. The coordinate and row-slot constant functions are
declared at module scope for IEEE 1800 constant-function portability; their
table evaluations and storage remain inside the legal-geometry generate branch.
If output height is one, remaining source pixels are
still consumed and validated before publishing the frame token.

The four 32-bit summary accumulators feed four parallel restoring dividers.
Every divider has exactly 32 registered iterations. Storage is bounded by
2*IN_WIDTH+3*OUT_WIDTH bytes, independent of frame height.

`furnace_x2_audio` resets FIR history with the first accepted sample and feeds
filtered samples directly to the FFT. `furnace_fft_radix2` writes bit-reversed
input positions, then alternates stage memories. Each stage launches N/2
independent butterflies on consecutive clocks, drains five arithmetic stages,
and fences before switching banks. One stage occupies N/2+6 clocks.
Two final prefetch/publication clocks give the specified first-bin latency.
Output stalls freeze bin publication and prefetch, preserving the next bin.
The fixed Q15 quarter-wave table uses 17-bit signed constants; unity is 32768.
Spectral absolute values are widened to 33 bits and energy accumulators to
40 bits before the shift and final lane saturation.

Both frontends track frame/window identity and length. Malformed inputs
produce one error token, drain until the observed last where necessary, and
recover without reset. Audio error-drain state resets its private arithmetic
engines, preventing a partially collected FFT from contaminating the next
window. Vision never publishes a summary before complete input validation.

## Parent-derived X2 integration

`furnace_x2_top` retains the parent's descriptor, decompression, GCM quarantine,
four DMA clients and completion state machine. `furnace_x2_csr` extends the
parent register implementation, including its independent AW/W holding
registers and byte-mask merging. The parent CSR module remains unchanged for X1.

The literal `unified_tensor` is the only active tensor engine in X2. An owner
register spans all vectors of a legacy tile or the single vector of a fused
pair. Ownership is released only on a result handshake. The last-served class
breaks simultaneous requests in round-robin order. Crypto abort/clear resets
the private decompressor/decryptor, not a concurrent tensor job.

Authenticated candidate weights are captured from the decryptor's fenced
plaintext stream, not from externally writable plaintext memory. Flag-bit-9
descriptors are rejected unless they specify mode zero, one vector and four
weight bytes. The candidate bank commits at successful legacy retirement only
after result and completion writes succeed. Failed operations preserve the
old bank. Successful key clearing/replacement invalidates the bank. Every
accepted fusion pair snapshots the committed weights before requesting tensor
ownership, so later commits cannot mix generations.

`furnace_dma_write_arb` retains one client through its entire command and done
handshake. Source 1 shares legacy plaintext with vision writes; source 2 shares
legacy results with audio and multimodal result writes. Legacy tensor reads
use source 2's independent read channel. Sources 0 and 3 remain the secure and
control clients. QoS for each write is captured with command ownership;
read QoS is selected by source class. Configuration is locked during queued or
active work, so it cannot change the QoS of outstanding reads.

`furnace_x2_mm_control` owns independent vision/audio record writers. A feature
cannot enter the literal fusion buffer until its actual DMA write completes.
Each modality has a separate ring producer pointer and outstanding-credit
counter. Credits cover writes, fusion queues, tensor work and held completion.
They are released only on public completion consumption, not on token enqueue,
tensor completion or memory write. This protects depth-one and wrapped ring
slots against overwrite during arbitrary completion backpressure.

Multimodal results are written before public completion. The report pulse is
one cycle event at result-write completion, including an AXI error override;
it increments the CSR count once, independently of how long mm_valid stalls.
Feature/result DMA errors produce code 5 and no invalid activation reaches
tensor arithmetic. Error pairs bypass tensor execution but still produce a
zero-valued stored result and public completion.

## Independence and outstanding acceptance

Verifier owns all functional reference models, transactors, mutation tooling,
simulation and synthesis checks. No functional or synthesis checks are authored
or executed by Designer. Required runtime checks, timing and board gates remain
outstanding. The original missing-source failure is not declared passing merely
because RTL files now exist: the independent checks must execute and succeed.

## Portable source use

Run commands from the delivered project root. Compile either the reference
directory or deliverable RTL, never both in a single hierarchy. Source inputs
are `rtl/*.sv`, `design/*.md`, immutable `furnace_x1_reference/rtl/*.sv`, and
Verifier-owned flat `tests/*`. Generated evidence and compiler intermediates
are not functional source dependencies. No execution requires private runtime
metadata, a host account directory, a cable identifier or a local PCIe address.

A fast static elaboration, distinct from functional verification, is:

```
iverilog -g2012 -t null -s furnace_x2_top rtl/*.sv
```

Independent verification instructions and the mandatory suite entry point are
Verifier-owned, as listed in `SPEC.md`. Required tools are Python 3, Icarus/vvp,
Verilator with make and a C++ compiler, and Yosys; no installation is authorized.
The static-check receipt, if one is present in the handoff, records the actual
compiler version used, not a claim about versions that have not been executed.

Host startup is: assert reset, release reset and allow the initialization
edge, configure/commit the protected legacy key and legacy ring, configure three
disjoint multimodal ring buffers and QoS while both paths are idle, then enable
multimodal acceptance. Submit an authenticated weight-commit descriptor using
the unchanged legacy ring protocol. Vision/audio streams may overlap that
descriptor's processing; fusion waits for committed weights. Consume public
completions to release ring slots. All dimensions and FFT/depth choices are
elaboration parameters, not runtime register modes.
