# FURNACE-X1 frozen product specification

## Scope and numerical rules

FURNACE-X1 is synthesizable FPGA RTL for Intel Arria 10 GX
10AX115N2F45E1SG, targeting a clock period <= 10.0 ns (100 MHz or greater).
It calculates CRC32C and CRC64-NVMe simultaneously and forwards the original
AXI4-Stream payload without byte relocation, padding or modification.
This is not an ASIC tapeout or a claim of achieved FPGA timing.

| Property | CRC32C | CRC64-NVMe |
|---|---|---|
| Width | 32 | 64 |
| Normal polynomial | `1EDC6F41` | `AD93D23594C93659` |
| Reflected polynomial | `82F63B78` | `9A6C9329AC4BC9B5` |
| Initial state | `FFFFFFFF` | `FFFFFFFFFFFFFFFF` |
| Final XOR | `FFFFFFFF` | `FFFFFFFFFFFFFFFF` |
| ASCII `123456789` | `E3069283` | `AE8B14860A799888` |
| Empty packet | `00000000` | `0000000000000000` |

Consume bytes in increasing lane order, least-significant bit first within each
byte. Each bit update XORs input bit with state bit zero, shifts right and
conditionally XORs the reflected polynomial. Return the complemented reflected
state as an unsigned integer, without another reflection or byte swap.

## Public interface

Top: `furnace_x1_top`. Its sole public parameter is integer `DATA_WIDTH=512`.
Exactly 64 and 512 are legal; `BYTE_LANES=DATA_WIDTH>>3` is derived.
There is no packet-length, FIFO-depth or MAX_WORDS parameter. Illegal widths
must elaborate a diagnostic-only branch and terminate simulation with an explicit
`PARAMETER ERROR`. Diagnostic-only port bounds are clamped to at least one bit;
this does not make an illegal configuration functional.

All ports are unsigned and use a single clock:

| Direction | Port | Width |
|---|---|---|
| input | `clk`, `rst_n` | 1 each |
| input | `s_axis_tdata` | DATA_WIDTH |
| input | `s_axis_tkeep` | BYTE_LANES |
| input | `s_axis_tvalid`, `s_axis_tlast` | 1 each |
| output | `s_axis_tready` | 1 |
| input | `s_check_enable` | 2 |
| input | `s_expected_crc32c`, `s_expected_crc64_nvme` | 32, 64 |
| output | `m_axis_tdata`, `m_axis_tkeep` | DATA_WIDTH, BYTE_LANES |
| output | `m_axis_tvalid`, `m_axis_tlast` | 1 each |
| input | `m_axis_tready` | 1 |
| output | `m_crc_valid` | 1 |
| input | `m_crc_ready` | 1 |
| output | `m_crc32c`, `m_crc64_nvme` | 32, 64 |
| output | `m_crc_mismatch` | 2 |
| output | `m_crc_protocol_error` | 1 |

Enable/mismatch bit 0 denotes CRC32C and bit 1 denotes CRC64-NVMe.
Enable and both expected values are sampled only on a packet's first accepted
beat, including first-and-last beats. Disabled mismatch bits are zero; enabled
bits equal the corresponding calculated-versus-expected inequality.

## Packet and error semantics

A transfer is valid && ready sampled immediately before a rising edge.
An accepted last beat ends the packet; the next accepted beat starts another.
Nonfinal beats require all keep bits one. Final keep must be a contiguous
low-lane prefix, including all ones or all zeros. Empty packets use one last
beat with zero keep. A zero-keep final beat after full beats is also legal;
thus exact multiples may terminate on their last full beat or an extra empty
last beat. There is no finite maximum packet size.

Only enabled byte lanes affect CRC. All data bits, including disabled lanes,
and the exact keep/last fields are forwarded unchanged. Sparse final masks and
partial nonfinal masks are malformed. They still forward every beat and produce
exactly one result at the accepted packet end, with protocol-error set and
mismatch zero. Their CRC fields are unspecified. Protocol error accumulates
through the packet and clears for the following packet. Missing last leaves
the packet open with no result until last or reset.

Sources hold valid and all input fields stable until accepted. Payload and
result outputs have independent ready/valid handshakes and remain ordered.
Every output field stays stable while its own valid is set and ready is low.
An unconsumed result may stall the entire engine.

## Cycle & degenerate-boundary table

All sequential logic uses `always @(posedge clk or negedge rst_n)`.
Reset has priority over movement and retirement. It aborts packets, payloads
and results, resets raw accumulators to all ones and prevents aborted results
from reappearing. During reset every output port is zero, including ready,
both valids, payload, keep, last, CRC and status.

`advance = rst_n && (!m_axis_tvalid || m_axis_tready) &&
(!m_crc_valid || m_crc_ready)` and `s_axis_tready=advance`.

| Boundary | Pre-edge decision | Post-edge state/output |
|---|---|---|
| Active reset | No transfer; all outputs zero | All pipeline valids zero; accumulators all ones |
| First edge after reset release | Ready is high if no pending outputs; accept valid input | Stage 0 receives that beat; output valids remain zero |
| Input accepted at E | Valid and ready sampled before E | Stage 0 owns beat |
| E+6, no stalls | Seventh advancing edge including E | Stage 6 owns full padded contribution |
| E+7 | Stage 6 valid gates recurrence | Stage 7 owns updated packet raw CRC |
| E+8 through E+14 | Successive advance events | Seven inverse-tail stages |
| E+15 | Output stage loads | Payload valid observable; result valid iff last |
| E+16 | Earliest ready/valid output transfers | Outputs may retire and next stage-14 beat may replace them |
| No advance | Hold all interior state | Independently accepted output valids clear; other output stays stable |
| Concurrent retire and advance | Old outputs transfer | New outputs replace old outputs without a bubble |
| First && last | Use this beat's input expected metadata and fresh state | Emit its result; next packet starts fresh |
| Last && zero keep | No packet bytes appended by this beat | Undo an entire padded beat before final XOR |
| Malformed then legal packet | Preserve malformed payload, suppress its mismatches | Reset packet CRC/error/metadata association at boundary |
| Reset with occupied/stalled pipeline | Reset wins over acceptance and retirement | Abort every pending item |
| DATA_WIDTH=64 or 512 | Same protocol and stage count | 8 or 64 byte lanes, respectively |
| DATA_WIDTH=0,8,128,1024 | Illegal | Explicit simulation PARAMETER ERROR |

With stalls, replace each subsequent edge in the latency table by the next
advance event. Independent retirement on non-advance edges does not move
interior stages. Consecutive accepted single-beat packets produce consecutive
results with continuously ready sinks.

## Required implementation structure and timing

The top directly instantiates the four functional modules below; combinational
helpers are permitted. Both configurations have exactly sixteen stages.

| Module | Global stages | Function |
|---|---|---|
| `furnace_crc_beat_pipeline` | 0..6 | Register 64 constant-position byte contributions, then six balanced XOR reduction stages |
| `furnace_crc_packet_accumulator` | 7 | Constant full-beat state advance XOR contribution; first-beat metadata and protocol accumulation |
| `furnace_crc_tail_pipeline` | 8..14 | Conditional inverse-zero-byte transforms for missing-count bits 0..6 |
| `furnace_crc_output_stage` | 15 | Final XOR, checking, unchanged payload and independent output retirement |

Checksum-only padding zeros disabled lanes. Unused reduction positions are
zero in the 64-bit configuration. The final missing count is
BYTE_LANES-popcount(keep), including 64 for an empty 512-bit beat.
Stage 7 resets its recurrence immediately after a final beat.

Constant GF(2) transforms must resolve to constant coefficients in synthesis,
with at most six XOR2 reduction levels; stage-7 merge adds at most one XOR2
level. Each tail stage has one transform and bypass mux. No serial full-beat
variable-data recurrence or chain of variable-length transforms is permitted.
No synthesizable division/modulo, mixed blocking/nonblocking sequential
assignments, latches or combinational feedback are permitted.

## Independent acceptance requirements

The independent Verifier owns `tests/*.py`, including the portable entrypoint
`tests/verify.py --mode all|behavior|defects|synthesis|portable|smoke
--out PROJECT_RELATIVE_DIRECTORY`. No arguments run all mandatory portable L1.
Every invocation retains fresh unique results, source hashes, exact child
commands/cwd, tool versions, raw logs, exit/timeout and measured coverage.
Simulator wall-clock allowances are at least 3600 seconds, with bounded
cycle-progress/drain assertions. Exit zero alone is not a scoreboard verdict.

Behavior uses actual Icarus/vvp RTL at both widths and seeds 17, 89, 2026.
Each cell must complete at least 512 legal packets against an independent
serial Python polynomial reference with exact CRC, payload, keep, last,
ordering and result-cardinality comparison. Cover lengths 0..2*BYTE_LANES+1;
255,256,257,511,512,513,4095,4096,4097,65535,65536,65537; at least 100 additional
random lengths 0..4096; zero, ones, walking-bit and random contents; every final
byte count; single/multibeat packets and both exact-multiple encodings; all four
enable masks with correct/incorrect expectations; source bubbles and independent
sink stalls. Cross-check the serial reference against a normal-polynomial,
MSB-first implementation with explicit reflections using known-answer vectors
and at least 128 deterministic random messages.

Each cell additionally executes at least 128 matched single-enabled-payload-bit
flip packet pairs over single, boundary-tail and multibeat lengths. Prove the
input difference, compare both new CRCs against fresh references and detect
both algorithm mismatches against original expectations. Disabled-lane flips
must be forwarded but leave CRC unchanged. Observe at least 32 stalls on each
output, eight completed back-to-back single-beat packets, eight legal empty
packets and eight malformed packets covering holey final and partial nonfinal
masks plus following-packet recovery. Exercise idle, partial-packet,
internal-occupancy and independently stalled-output resets; exact unstalled
latency, ready/valid behavior, stalled stability and active-output X/Z rejection.
Add bounded directed occupancy/retirement corner cases and illegal-width
diagnostics. Do not mask unknowns or weaken assertions.

Defect testing uses disposable copies, not delivered-RTL edits. At least three
independent mutants cover recurrence/polynomial, tail correction and packet
checking/association, each at both widths with the same oracles/scoreboard.
Each mutant must elaborate and simulate, then fail an explicit functional
comparison/assertion. Compile errors, timeouts and textual PASS searches are
not defect detection. Retain mutations, sources, logs and failing assertions;
unmodified RTL must pass the same cases.

Real Yosys synthesis for both widths must include read/elaboration,
`hierarchy -check`, process lowering, optimization, technology-independent
synthesis and `check -assert`. Check hierarchy before flattening, both CRC
calculations, nontrivial sequential state, driven outputs, no undriven or
multiply-driven active nets, no latches and no division/modulo cells.
Structural scans alone do not establish synthesis correctness or timing.

Portable reproduction copies only declared deliverable inputs into a fresh
temporary directory, clears inherited project-specific Python search paths and
runs fresh smoke compilation/simulation and synthesis at both widths. Include
known-answer, empty, multibeat-tail, independent-stall and reset behavior with
strict CRC/payload scoreboards and zero-latch checks. It must not depend on
old outputs, private host paths or runtime metadata.

The shared runtime additionally performs native L1.5 timing lint, L2 Quartus
17.1 STA on the specified part and L3 physical PCIe Gen3x8 hardware-bridge
checks. Require <=10.0 ns, WNS>=0, no relevant unconstrained synchronous paths,
both width configurations and at least three consecutive deterministic HIL
passes with independent CRC/payload comparisons including tails/multibeat.
Adapters must connect the actual public top protocol and disclose limitations.
Missing tools, licensed Quartus, device or bridge are blockers, not waivers.
Only actual Quartus STA meeting the original period can support a Coordinator
timing waiver. No local cable or PCIe BDF is embedded in portable sources.

All admitted checks remain mandatory. Preparation evidence is advisory only.
The independently approved product PDF is generated by the shared runtime
after engineering acceptance; it is not a prerequisite or an engineering-role
deliverable at this handoff.
