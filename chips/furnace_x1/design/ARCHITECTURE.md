# FURNACE-X1 architecture and integration

## Deliverable boundary

`design/SPEC.md` is the frozen behavioral, numerical, timing and acceptance
contract. Sources are `rtl/*.sv` and the two design documents. The independent
Verifier owns `tests/*.py`, its generated simulator harnesses, independent
references and verification results. Generated evidence is not a source input.
There is no external ROM, generated coefficient file, include search path,
software CRC implementation or dependency on runtime metadata in the RTL.

Compile all six RTL files with SystemVerilog support and select
`furnace_x1_top` as top. Set its sole parameter to 64 or 512; default is 512.
There are no debug, configuration-register or host-device interfaces.
The intended FPGA is Intel Arria 10 GX 10AX115N2F45E1SG.

## Hierarchy and data ownership

The top's legal-configuration generate branch directly instantiates:

| Instance / module | State | Assumptions and guarantees |
|---|---|---|
| `beat_pipeline` / `furnace_crc_beat_pipeline` | Seven payload/valid stages; byte/XOR tree registers | Samples input on shared advance; zeros checksum-only disabled lanes; delivers aligned beat contribution and metadata |
| `packet_accumulator` / `furnace_crc_packet_accumulator` | One beat stage, two CRC recurrence registers, open/error/first metadata | Updates recurrence only on valid incoming beat and advance; resets recurrence at packet end; preserves first-beat check association |
| `tail_pipeline` / `furnace_crc_tail_pipeline` | Seven payload/valid/CRC stages | Uses aligned last and missing count; removes padded bytes from final raw states only |
| `output_stage` / `furnace_crc_output_stage` | One payload/result stage with separate valids | Complements CRC, compares expectations, suppresses malformed mismatches, independently retires outputs |

`furnace_crc_linear` is a combinational constant-matrix helper instantiated by
the first three modules. It contains no sequential logic or runtime polynomial
iteration. The top derives the common advance from the two output handshakes.
There is no dependency from advance to an output valid through combinational
logic: both output valids originate in output-stage registers.

The internal packed metadata bus is not a public interface. From least
significant to most significant bits it contains data, keep, last, enable[1:0],
expected32[31:0], expected64[63:0], missing[6:0], protocol-error.
Its width is DATA_WIDTH+BYTE_LANES+107. Pipeline modules carry the entire bus;
the accumulator replaces expected/check/error fields with packet-associated
values. Payload bits, keep and last are never rewritten.

## Constant GF(2) composition

For each polynomial let `T` be the zero-input reflected one-bit state advance.
For width W and polynomial P,

```
T(s) = (s >> 1) XOR (P if s[0] else 0).
```

All operations here are over GF(2). For a byte b embedded in the low eight
state bits, processing that byte is `T^8(s XOR b)`. By linearity, processing
a full B-byte beat yields

```
new_state = T^(8B)(old_state)
            XOR XOR_over_i(T^(8(B-i))(byte_i)).
```

Here `i=0..B-1`, in increasing input lane order. Disabled byte lanes are zero
only in this checksum expression. The original lane values travel independently.

For every transform the helper calculates its constant matrix columns at
elaboration: column j is the transform applied to the basis vector with bit j
set. RTL then masks each constant column by its one variable input bit and
combines the columns using an explicit balanced XOR tree. Compile-time loops
operate only on constants. There is no variable-data bit-recurrence chain in
the synthesized datapath.

Stage 0 registers a byte's contribution at each of 64 fixed positions for both
CRCs. For DATA_WIDTH=64, positions 8..63 are zero and the active transforms
use B=8, not 64. A registered binary tree reduces 64 positions to 32, 16, 8,
4, 2 and 1 in stages 1..6. The heap representation stores leaves at indices
63..126 and root at zero; every internal node XORs its two child registers.
Stage 7 combines the constant full-beat transform of the current recurrence
state with this root. It registers the resulting raw state for the beat.
On a valid final beat, recurrence state instead resets to all ones so that
the immediately following beat can start a new packet without a bubble.
Bubbles never update recurrence or packet association.

## Inverse-tail proof

Both reflected polynomials have top coefficient one, so `y=T(s)` has
`y[W-1]=s[0]`. Consequently the inverse exists and is

```
q = y[W-1]
T^-1(y) = ((y XOR (P if q else 0)) << 1) OR q.
```

The shift is truncated to W bits. This exactly recovers the original upper
W-1 bits and restores original bit zero. Let a legal final beat have k valid
prefix bytes and m=B-k missing bytes. After the last real byte, zero padding
advances its raw CRC by `T^(8m)`, without adding a byte contribution.
Applying `T^(-8m)` therefore restores precisely the unpadded packet state.
This holds for arbitrary earlier full beats, k=B (identity), and k=0
(undo one whole padded beat). In particular an empty packet restores the
all-ones initialization, which complements to zero.

Decompose m into seven binary bits. Tail stage j applies
`T^(-8*2^j)` iff last and missing[j] are set. All are powers of the same
invertible transform, so their composition is `T^(-8m)`. Stage j has just one
constant transform, a bypass mux and a register; no several-transform
combinational chain exists. Nonfinal raw states pass through without tail
correction. Only the output stage applies final XOR.

The top calculates missing as a balanced population count of disabled lanes,
equal to B-popcount(keep), avoiding variable division and subtraction.
Adjacent low-zero/high-one keep transitions detect non-prefix final masks.
An AND reduction checks full nonfinal masks. Malformed CRCs are deliberately
unspecified, but the payload and error/result cardinality remain defined.
The Verifier must independently check this proof numerically; this derivation
is design rationale, not an executed verification result.

## Flow control, reset and boundaries

The precise cycle and degenerate-boundary table is in `SPEC.md`.
Every register stage shares
`advance = rst_n && (!payload_valid || payload_ready) &&
(!result_valid || result_ready)`. Thus there are at most sixteen beats in
the pipeline; a stage-7 partial packet may also retain recurrence state over
an arbitrary number of source bubbles or output stalls. Packet length is not
counted and has no finite limit.

On advance, stage 15 consumes the previous stage-14 beat and independently
loads payload-valid and final-result-valid. On a non-advance edge, each
already-consumed output clears its own valid without changing its fields.
For example payload can retire while a result remains stalled; payload-valid
then stays clear until movement is possible, preventing duplicate delivery.
The converse is symmetric. If both existing outputs can retire, simultaneous
movement replaces them with the next beat without losing either transfer.

First-beat metadata selection is combinational from packet-open state at
stage 7. Therefore first-and-last selects the incoming metadata rather than
stale latched expectations. Packet-open, accumulated protocol error and CRC
state all restart at the same final boundary. A malformed beat sets packet
error even when it is the first or final beat. A missing last keeps the
packet open; only reset or a later accepted last closes it.

Asynchronous active-low reset takes precedence in every sequential block.
Public outputs are additionally gated by reset so every field, including
ready, is zero during reset. Reset release exposes an empty pipeline; it
does not emit a completion or resurrect aborted payloads/results.
Integrators must assert reset before traffic and provide reset deassertion
appropriate to the local clock domain. There is one clock domain and no CDC
logic, clock generator or reset-release synchronizer in this public top.

For illegal widths the entire legal datapath is excluded by generate.
Diagnostic-only top port widths are bounded below by one so width zero does
not preempt the required `PARAMETER ERROR` with invalid internal selects.
This applies advisory lesson `exp-6d5cc92e6f5a86894eaae275`; its earlier
project's results do not establish this implementation's diagnostics.

## Timing intent and limits

At 100 MHz, the architectural peak input bandwidth is 6.4 Gb/s for 64-bit
and 51.2 Gb/s for 512-bit, before bubbles, partial tails and backpressure.
These are width-times-frequency calculations, not measured throughput.
No claim is made that a single 512-bit instance carries 100 Gb/s at 100 MHz.

Byte transforms have eight column inputs and at most three XOR2 levels.
State transforms have 32 or 64 column inputs and at most five or six XOR2
levels. Stage-7 merge adds one level. Each beat reduction stage has one XOR2
level, and each tail stage has at most one six-level transform plus bypass.
Keep validation and the six-level small-integer population tree precede the
stage-0 metadata registers. These structural bounds do not replace placement,
routing, reset/enable fanout analysis or target-device timing closure.

No synthesizable division/modulo operators or serial runtime full-beat CRC
loops are used. Sequential datapath updates are nonblocking. Actual Yosys
checks must still establish synthesis quality; actual Quartus 17.1 STA must
prove <=10.0 ns, WNS>=0 and constrained relevant synchronous paths on the
specified FPGA. Only the shared runtime performs native timing and physical
hardware gates. A missing device, license or bridge is a blocker, not proof
or permission to substitute software/simulation.

## Native adapter integration blocker and provision contract

The native adapter is **not implemented**. The current source inventory contains
only the six core RTL files; there is no `fpga/board_hil.json`, board project,
PCIe shell/IP source or supported hardware-side bridge interface declaration.
The Python interfaces in `tests/native_gates.py` and `tests/native_vectors.py`
specify configuration and trace formats, not a synthesizable bridge protocol.
In particular, they do not establish whether the shell exposes memory-mapped
transactions, streaming transfers, or a different interface. Choosing one would
invent a platform binding. No replacement core, dummy bridge or assumed board
pinout has been added.

The retained prerequisite failure is exit 2 at
`evidence/preparation/native-gates-validation-01/results/run-20261026T124301Z-1231c20557/commands/0002/receipt.json`;
its `stderr.log` identifies the missing configuration. The existing export at
`evidence/native/integration-r2/run-20261026T122843Z-cec25ecbbe/native-contract.json`
explicitly says its adapter is not supplied. Its virtual-pin projects and
provisional 2 ns I/O budget are not implementation projects or a derived
platform timing budget. Neither those templates nor orchestration-test fixtures
may be promoted to an actual board binding.

The shared runtime must provision authoritative, project-local platform inputs:

| Missing input | Required content and responsibility |
|---|---|
| Supported bridge RTL/interface | Shell top and exact port declarations, directions, widths, transfer/flow-control semantics, host address or stream framing, ordering, error handling and available storage. The platform provider supplies the real interface and integration sources; Designer implements the adapter against it. |
| Clock and reset integration | Actual reference clock, generated core clock and their relationship, PLL/IP sources and constraints, reset assertion/release sequence and PCIe reset relationship. Designer can then document any required CDC/reset synchronization without altering the core reset contract. |
| Board implementation | Authoritative package pin assignments, I/O standards, PCIe lane/reference-clock bindings, transceiver/IP configuration and all referenced source files for 10AX115N2F45E1SG with Quartus 17.1. Do not infer these from the device name. |
| Capture transport | Supported command/data upload and trace readback ABI, capacity/overflow behavior and a capture-only host implementation. The shared runtime binds the physical device and command; Designer does not invent commands or program an image. |
| Physical image provenance | A matching implementation image/build manifest and active-image identity mechanism, plus actual PCIe Gen3x8 link status and run identity. These are runtime provisions, not constants an RTL wrapper can truthfully manufacture. |

Once these inputs are supplied, the adapter must instantiate the unchanged
`furnace_x1_top` at each legal width and drive/capture its actual public nets.
The complete mapping must contain exactly these names, with widths from SPEC:
`clk`, `rst_n`, `s_axis_tdata`, `s_axis_tkeep`, `s_axis_tvalid`,
`s_axis_tlast`, `s_axis_tready`, `s_check_enable`, `s_expected_crc32c`,
`s_expected_crc64_nvme`, `m_axis_tdata`, `m_axis_tkeep`, `m_axis_tvalid`,
`m_axis_tlast`, `m_axis_tready`, `m_crc_valid`, `m_crc_ready`, `m_crc32c`,
`m_crc64_nvme`, `m_crc_mismatch`, `m_crc_protocol_error`.
Actual hierarchical net names and physical shell bindings remain unavailable;
this list is a mapping obligation, not a completed pin map.

Stimulus must be established before the accepting core edge; capture registers
must sample all listed data/control nets at that edge, observing their pre-edge
values, including reset and idle cycles. Capture must not derive observations
from expected CRCs, handshake predictions or host oracle rows. The transport must
preserve the prescribed cycle sequence and independent ready inputs, with no
silent trace loss or substitution when storage fills. Width 64 and width 512
must each have an explicit source/image binding and physical capture coverage.

Numerical launch/capture budgets cannot yet be derived: launch/capture registers,
clock phases/skew, routing boundaries and IP timing are unknown. For a same-clock
register path, let S be capture-clock minus launch-clock arrival, U the applicable
uncertainty, and D the combinational/routing delay. Setup requires
`tCQ_max + D_max + tSetup + U_setup <= T + S`; hold requires
`tCQ_min + D_min >= tHold + S + U_hold`, with `T <= 10.0 ns`.
Both stimulus-to-core and core-to-capture paths, including ready feedback,
must be constrained using their actual endpoints. Internal register paths use
normal timing analysis, not fictitious external I/O delays. Any real external
boundary needs independently justified min/max delays and clock relationships;
reset paths need applicable recovery/removal analysis. No numeric delay,
false-path or multicycle exception is justified by the missing interface.

Before dependent native checks are admitted, Coordinator and independent
Reviewer must admit ownership and the complete source-selector additions for
`fpga/board_hil.json`, both actual Quartus revisions' `.qpf`/`.qsf` files,
`.sdc` constraints, the public-net mapping and timing-budget evidence, and every
referenced `.qip`, IP, HDL, memory initialization and Tcl source. Exact filenames
must follow the supplied projects rather than invented revisions. Designer
continues to own adapter `rtl/*.sv` and this document; board/configuration and
platform-IP ownership require explicit admission. Verifier owns adapter
simulation, synthesis and capture-scoreboard integration. Generated images,
manifests and reports remain separate from implementation source closure.

This blocker does not establish a core RTL defect or invalidate historical L1
results, and it does not close native acceptance. All existing checks and failed
receipts remain mandatory/retained. Required follow-on evidence is both-width
Quartus 17.1 implementation/post-fit STA with nonnegative setup and hold slack,
no relevant unconstrained paths and <=10 ns period, then three consecutive
physical PCIe Gen3x8 passes per width. A post-map report or a passed label with
negative hold slack cannot satisfy that requirement. Engineering acceptance and
the runtime-generated product PDF remain pending.

## Dependencies and portable commands

Required portable dependencies are Python 3 (standard library), Icarus Verilog
with SystemVerilog 2012 support, `vvp`, and Yosys with SystemVerilog frontend
support. No dependency installation or version compatibility claim is made
by the source alone. Actual tool versions belong in retained run receipts.
Native acceptance additionally requires Quartus 17.1, the target part and the
shared runtime's physical PCIe Gen3x8 bridge; local cable/device identifiers
are not portable configuration inputs and are not embedded here.

Run from the delivered project root. A syntax/elaboration-only command is:

```
iverilog -g2012 -t null -s furnace_x1_top -P furnace_x1_top.DATA_WIDTH=64 rtl/*.sv
iverilog -g2012 -t null -s furnace_x1_top -P furnace_x1_top.DATA_WIDTH=512 rtl/*.sv
```

The independent Verifier supplies the following mandatory portable commands:

```
python3 tests/verify.py --mode behavior --out evidence/l1/behavior
python3 tests/verify.py --mode defects --out evidence/l1/defects
python3 tests/verify.py --mode synthesis --out evidence/l1/synthesis
python3 tests/verify.py --mode portable --out evidence/l1/portable
```

`python3 tests/verify.py` runs all L1 checks; smoke is a bounded reproduction
selector, not a replacement for full acceptance. Verification outputs must
use fresh unique child directories and preserve earlier failures. Portable
reproduction copies only RTL, these documents and Verifier-owned Python
sources, never evidence, old binaries or runtime-owned directories.

## Claims and retained results

| Claim | Required evidence / status at Designer handoff |
|---|---|
| Implemented numerical and protocol architecture | Inspect the six RTL sources and SPEC; correctness pending independent verification |
| Static syntax/elaboration | Designer may retain only a fast static check under `evidence/preparation`; any actual receipt is identified in the handoff |
| Bit-exact CRC/payload/reset/backpressure behavior | Pending independent `behavior` execution and strict scoreboards |
| Detection of injected RTL defects | Pending independent `defects` execution with retained functional failures |
| Real synthesis, preserved hierarchy/state, zero latches/division | Pending independent `synthesis` execution and inspected netlists |
| Portable isolated reproduction | Pending independent `portable` execution |
| 100 MHz+ timing | Pending native timing lint and actual Quartus STA |
| Physical operation | Pending native three-consecutive-pass HIL at both widths |
| Engineering acceptance and final PDF | Pending independent review, followed by shared-runtime report generation/review |

The Designer has not authored or executed functional simulation, reference
models, mutation harnesses or synthesis checks. Static elaboration is not a
numerical verdict. No engineering acceptance, timing success, hardware result
or approved product PDF is inferred from the presence of these sources.
