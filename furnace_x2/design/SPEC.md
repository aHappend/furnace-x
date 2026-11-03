# FURNACE-X2 v2.0.0-soc-multimodal

## Authority and implementation status

The admitted work order defines the product contract. This document records its
implementation-facing boundaries; it does not replace or relax that contract.
Engineering acceptance remains subject to independent review of the reconciled
provenance and closure of the timing-scope and hardware-evidence limitations below.
`design/GENERATIONAL_HANDOFF.md` is now readable and has been read. Its observed
SHA256 is `502585e7732b741a2e6ee74e634742943d23c7e4f3d28a86e2ad51b4769973c5`.
The existing shared-runtime restoration receipt explicitly attributes the
fourteen inherited modules to completed FURNACE-X1 and binds this handoff hash.
Coordinator reconciliation confirmed that the handoff and every reference and
deliverable parent module match that receipt. Attribution therefore comes from
the supplied runtime record, not from matching hashes alone. No separate linked
parent source index was supplied in the available intake: repository intake is
null, neither the receipt nor the handoff links one, and
`furnace_x1_reference/` contains only the fourteen RTL inputs. The receipt's
module inventory supplies attribution; no additional index was read or created.
This reconciliation and resolution of any conflicts remain subject to
independent review **before engineering acceptance**. The private-path
restoration record is not a portable deliverable or verification dependency.

The restoration receipt and handoff agree on historical parent Quartus 17.1
setup/hold slack of 1.464/0.038 ns at 10.0 ns and a deterministic parent PCIe HIL pass.
These are attributed historical claims, not fresh X2 verification or
independently reconstructed parent evidence.

The immutable input is `furnace_x1_reference/rtl/*.sv`. Deliverable copies retain
the usable `furnace_x1_top` and its public interface. Reference and deliverable
hierarchies must be compiled separately because their module names overlap.
The X2 top is `furnace_x2_top`; its external AXI-Lite and four AXI4 bank
interfaces retain all parent widths, directions and signedness.
All fourteen deliverable parent modules are byte-identical to their immutable
references, and their inventory matches the restored handoff. This establishes
source preservation, not correctness of every parent behavior or X2 integration.

This is not an accepted SoC. See
`ARCHITECTURE.md` for the connected datapaths, storage and ownership decisions.
Verifier exclusively owns `tests/*`. Completed independent L1 evidence and the
qualified native timing/board observations are recorded below; Designer has not
rerun those workloads for this documentation repair.

## Cycle and degenerate-boundary table

`E` denotes a rising edge with a transfer on the **pre-edge** valid and ready.
All stated outputs are observed **after** nonblocking updates. An output that
becomes valid after E cannot have transferred at E.

| Boundary | Required behavior |
| --- | --- |
| Active reset | Asynchronous assertion aborts work. Public ready, valid, payload, status and IRQ are zero. RAM contents are invalid rather than reset wholesale. |
| First release edge | Initializes the enabled flag; pre-edge request readiness remains zero. First possible transfer is the following rising edge. |
| Bilinear | Capture E; horizontal products E+1; horizontal sums E+2; vertical products E+3; rounded full sum E+4; byte publication E+5. |
| Spatial | Capture E; row partials E+1; signed final sums E+2; packed publication E+3. |
| FIR | Capture/history selection E; pair sums E+1; full sum E+2; arithmetic shift/publication E+3. |
| Arithmetic stalls | A stalled final register pauses all pipeline registers together. Payload and metadata stay stable; no combinational input/output bypass. |
| FFT butterfly | Capture B; four products B+1; complex sums B+2; Q15 shift B+3; widened plus/minus B+4; saturated outputs B+5. |
| FFT transform | Last input E; first bin after E+log2(N)*(N/2+6)+2; remaining bins one per cycle without stalls. |
| Tensor | Accept E, final-vector output E+24, next acceptance no earlier than E+25. Complete tiles own the accumulator. |
| AXI address | Upstream capture E; outgoing registered header is first valid after E and cannot transfer before E+1. |
| Fusion enqueue | No empty-FIFO bypass. Enqueue E can first form a registered pair at E+1. |
| Fusion depth one | Full FIFO may accept a replacement on the same edge its old head forms a pair. The pair sees the old head; counts do not change on simultaneous push/pop. |
| Fusion depth three | Explicit terminal comparison wraps every pointer; binary truncation is not used as modulo three. |
| 1x1 vision | First and final input coincide. Both spatial edges replicate the only pixel. No separate first/last cycle is required. |
| Single-vector legacy | First and last coincide on the same accepted vector. Mode/lane and accumulation rules remain the parent rules. |
| Simultaneous events | Reset dominates all updates. Error setting dominates sticky-fault clear. Pair output replacement is permitted only with old-output handshake; FIFO entries written that edge are not bypassed. |
| Key change | Successful clear/replacement invalidates committed multimodal weights; affected queued or executing jobs prohibit rekeying. |

## Parameters

Defaults are `MAX_TILE_BYTES=4096`, `RING_DEPTH=8`, `IN_WIDTH=IN_HEIGHT=8`,
`OUT_WIDTH=OUT_HEIGHT=8`, `FFT_N=16`, and `FUSION_DEPTH=4`.
Tile bytes are legal from 1 through 65536, ring and fusion depths from 1 through
16, and each geometry dimension independently from 1 through 64.
FFT sizes are exactly 8, 16, 32 or 64. Illegal configurations use an isolated
diagnostic generate branch with `PARAMETER ERROR`; illegal arrays/selects must
not prevent that diagnostic from elaborating.

## Numerical and stream contract

Every stream transfer requires valid and ready. IDs are unsigned 16-bit values,
latched with the first item, invariant within an input, and compared by exact
equality including 65535-to-zero wrap. Last marks the whole frame/window.

Vision uses unsigned grayscale, endpoint-aligned Q8 coordinates, full-width
bilinear products with rounding bias 32768 before a 16-bit shift, and
replicated-edge Sobel X, Sobel Y and four-neighbor Laplacian. Packed spatial
lanes are pixel, signed Gx, signed Gy and signed L, low lane first.
The feature lanes are floor means of pixel, abs(Gx), abs(Gy), abs(L);
32-bit parallel restoring dividers execute exactly 32 iterations.
No intermediate saturation is allowed.

FIR history starts at zero for every audio window. Coefficients are 1,3,3,1,
followed by a signed arithmetic shift of three. FFT is unscaled forward radix-2
DIT, bit-reversed input placement, natural-order outputs, signed-17 Q15
twiddles with positive unity 32768. Four exact products form two widened sums;
each sum is shifted once by 15 before signed-32 A plus/minus and saturation.
Audio lanes are the FIR absolute mean, DC absolute-component mean, low-quarter
spectral absolute-component mean, and remaining-to-Nyquist mean. Spectral
lanes saturate at 32767 after division by N; no magnitude approximation.

Fusion concatenates vision lanes below audio lanes. Different head IDs consume
both and produce code 8; otherwise vision error precedes audio error.
Malformed input length or within-frame ID produces code 7, one token per
logical input, and drains through the observed last before resynchronization.
Missing last never starts an inferred new frame and has no fabricated timeout.
Parent errors 0 through 6 retain their meanings. Error results are zero and
never enter tensor arithmetic.

## Integration obligations

X2 must contain functional literal instances `vision_frontend`, `audio_frontend`,
`fusion_buffer`, `unified_tensor` and `axi_crossbar`. There is exactly one active
`furnace_tensor8`, shared with legacy complete-job round-robin arbitration.
The vision hierarchy contains `bilinear_kernel` and `spatial_kernel`; audio
contains `fir_kernel` and `fft_kernel`.

Descriptor version 1 gains only flag bit 9, `MM_WEIGHT_COMMIT`, legal only for
W4A16 mode zero, one vector and four weight bytes. Candidate weights commit
only after authentication, plaintext transfer, tensor calculation, result
write and completion write all succeed. Failure preserves the previous bank.
Key changes invalidate it. Each pair snapshots one committed generation.

Four actual DMA source slots share the QoS crossbar: secure reads at source 0;
plaintext/vision writes at source 1; legacy/audio/result traffic at source 2;
descriptor/completion traffic at source 3. Shared-client arbitration is fair
at complete-command boundaries. Feature writes complete before FIFO admission;
result writes complete before public completion. Slots are held through
completion consumption. Security progress must not depend on a consumer that
is itself waiting for authentication or weight commitment.

Crossbar selection is greatest AxQOS, ties rotating from source zero separately
for each target and direction. An accepted owner is not preempted; response
handshake releases it. Target is address[31:30]; external ID is source plus
two-bit local ID. Preserve aligned INCR bursts of 1..16 beats, no page crossing,
strobes and parent invalid-header DECERR/drain behavior.

## Control and memory records

Parent CSR offsets 0x0000..0x0040 and identity remain unchanged.

| Offset | X2 register |
| --- | --- |
| 0x1000 | Read-only identity 0x02000000 |
| 0x1004 | Enable bit 0; sticky-fault W1C bit 1, not stored |
| 0x1008 | Weights-valid, sticky-fault, vision-busy, audio-busy, fusion/result-busy in bits 0..4 |
| 0x1010 / 0x1014 / 0x1018 | Vision / audio / result base |
| 0x101c | Read-only elaborated fusion depth |
| 0x1020 | Completed-pair count |
| 0x1024 / 0x1028 | Last multimodal error / ID |
| 0x1030 | Five QoS nibbles: secure, vision, audio, tensor, control; reset 0x000f4c8f |

New writable values other than QoS reset to zero. Byte strobes and independently
arriving AW/W are supported. Unsafe, unaligned, reserved-bit and read-only
writes fail without mutation. Configuration requires both paths idle including
queues. Enable requires nonoverlapping aligned buffers, each 16*FUSION_DEPTH
bytes, without address wrap; software also avoids live legacy allocations.

Record slot i is base+16*i with explicit wrap. All three record types contain
data/result [63:0], zero [95:64], ID [111:96], zero [119:112], error [127:120].
Public completion holds its fields under backpressure. Completion count advances
once per reported pair. Any multimodal error sets sticky fault and IRQ; error
setting wins over simultaneous clear.

## Acceptance and reproduction

Target is Intel Arria 10 GX `10AX115N2F45E1SG` at <=10.0 ns. Active RTL must
have no combinational division/remainder, no mixed blocking/nonblocking
sequential assignments, no latches, and bounded registered arithmetic.
Generic synthesis is not timing evidence.

The independent Verifier owns the portable entry point. Run these mandatory
commands from the project root:

```
python3 tests/verify.py --suite smoke
python3 tests/verify.py --suite behavior
python3 tests/verify.py --suite compatibility
python3 tests/verify.py --suite protocol
python3 tests/verify.py --suite mutations
python3 tests/verify.py --suite synthesis
python3 tests/verify.py --suite reproduction
```

The retained shared-runtime attempts record all seven commands as passed,
with aggregate receipt exit code zero in each case:

| Suite | Attempt | Completed receipt |
| --- | --- | --- |
| smoke | 125 | `evidence/l1-smoke-20261030T081721Z-0d841f1b4c0e/receipt.json` |
| behavior | 128 | `evidence/l1-behavior-20261030T090329Z-d8bf30b7d0ea/receipt.json` |
| compatibility | 129 | `evidence/l1-compatibility-20261030T094222Z-a9203d523620/receipt.json` |
| protocol | 130 | `evidence/l1-protocol-20261030T094741Z-5f1a38636555/receipt.json` |
| mutations | 131 | `evidence/l1-mutations-20261030T095425Z-dc9505c9c7e6/receipt.json` |
| synthesis | 132 | `evidence/l1-synthesis-20261030T095913Z-aa784e553b51/receipt.json` |
| reproduction | 133 | `evidence/l1-reproduction-20261030T100034Z-c6d30c2a9563/receipt.json` |

The behavior aggregate contains all 21 passed geometry/seed entries, not a
partial matrix. The mutation aggregate records a passing unmutated control
and eight compiled, functionally killed mutations. Compatibility evidence is
separate from byte identity and from historical parent acceptance. These
receipts retain their original source hashes, including pre-reconciliation
documentation hashes; this documentation-only repair neither rewrites them nor
claims a new execution. Earlier failed/interrupted receipts remain retained.
The missing-source and interrupted-behavior failures are followed by completed
attempts 125 and 128; neither file existence nor a partial run is the pass basis.

### Native timing and hardware evidence limits

The shared runtime records native L1.5 timing lint as passed with zero
combinational divide/modulo and mixed-assignment hazards. Current Quartus
post-fit results are separate from L1 generic synthesis and parent history.
The retained `top.fit.rpt` reports **29,663 ALMs, 23,765 registers, 42 RAM
blocks (M20K), and 114 DSP blocks**. Native STA reports setup/hold slack of
**0.846/0.037 ns at 10.0 ns**.

Timing scope is not complete external-interface signoff. Raw `top.sta.rpt`
states that setup and hold requirements are not fully constrained;
`top.sta.ucp.rpt` lists **703 unconstrained input ports and 1046 unconstrained
output ports**, despite the native receipt's zero unconstrained-path/endpoint
markers. Positive reported slack covers the analyzed constrained paths only.
Valid external constraints or independently approved scope exclusions must be
reconciled before signoff; this document grants no timing waiver.

Board evidence is **L3_BRIDGE_CONNECTIVITY_PROBE_ONLY**. The retained
`board-hil.json` records three deterministic register-57 reads returning 178
(0xB2). Its passed status does not demonstrate flashed-X2 multimodal workload
execution, numerical correctness on hardware, or OS boot. The mandatory
three-consecutive-pass X2 hardware validation requirement remains unchanged
and is not discharged by these connectivity reads.

Native receipts and Quartus reports are retained shared-runtime observations,
not shipped source inputs or prerequisites for the portable L1 commands.
Independent review must resolve the provenance, timing and hardware limitations
without weakening any mandatory check. The independently approved product PDF
is authored by the shared runtime only after engineering acceptance.
