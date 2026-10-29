# FURNACE-X2 v2.0.0-soc-multimodal

## Authority and implementation status

The admitted work order defines the product contract. This document records its
implementation-facing boundaries; it does not replace or relax that contract.
Implementation is provisional under the independently admitted recovery.
Authentic `design/GENERATIONAL_HANDOFF.md`, any associated parent source index,
provenance reconciliation and independently reviewed resolution of conflicts
are mandatory **before engineering acceptance**, not before implementation.
No authentic handoff has been supplied at the time of this document. No parent
timing or PPA figures are inferred from the RTL.

The immutable input is `furnace_x1_reference/rtl/*.sv`. Deliverable copies retain
the usable `furnace_x1_top` and its public interface. Reference and deliverable
hierarchies must be compiled separately because their module names overlap.
The eventual X2 top is `furnace_x2_top`; its external AXI-Lite and four AXI4 bank
interfaces retain all parent widths, directions and signedness.

This is a provisional implementation, not an accepted SoC. See
`ARCHITECTURE.md` for the connected datapaths, storage and ownership decisions.
Verifier exclusively owns `tests/*`. No simulation, synthesis, timing or board
result is claimed by this document.

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

After design handoff, the independent Verifier supplies and executes:

```
python3 tests/verify.py --suite smoke
python3 tests/verify.py --suite behavior
python3 tests/verify.py --suite compatibility
python3 tests/verify.py --suite protocol
python3 tests/verify.py --suite mutations
python3 tests/verify.py --suite synthesis
python3 tests/verify.py --suite reproduction
```

These are mandatory interfaces for the future verification entry point, not
claims that it currently exists or that these commands have passed. All seven
checks remain outstanding. So do native timing lint, Quartus STA and three
deterministic consecutive hardware passes. The independently approved product
PDF is authored by the shared runtime only after engineering acceptance.
