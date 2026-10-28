# FURNACE-X2 interface and numerical contract

## Cycle & Degenerate-Boundary Table

All transfers sample valid and ready **pre-edge**. Register values and latency
labels describe **post-edge** state. Reset is asynchronous, active low; every
public output is zero while reset is asserted. The first rising edge after
release may accept configuration or ingress if the corresponding ready is high.

| Boundary | Required behavior |
|---|---|
| Reset during ingress, computation, or blocked results | Abort all state and results, disable rules, restore key and zero default action |
| Idle configuration and ingress together | Configuration wins; no internal CRC-only ingress transfer |
| First and last on the same beat | Capture/check controls and terminate the same packet |
| Final keep zero | Legal prefix; count no bytes; still forward beat and produce both results |
| Non-final partial keep or final non-prefix keep | Forward unchanged; CRC follows retained X1 arithmetic; deterministic parser error key |
| Simultaneous final payload, CRC, metadata consumption | Release ownership only after all three handshakes |
| One result stalled | Other consumers can finish; metadata computation continues |
| DATA_WIDTH=64 or 512 | Legal; lane zero carries the first byte |
| DATA_WIDTH=-1,0,8,32,128,1024 | Diagnostic-only generate branch; minimum one-bit ports; explicit PARAMETER ERROR |
| Configuration clear versus write | One operation per handshake; clear disables entries without changing action/key |
| Capture at byte 256 | Stop capture, not payload forwarding or saturating byte counting |

No FIFO depth or packet-count parameter exists. There is one outstanding packet.

## Interfaces

`furnace_x2_top #(DATA_WIDTH=512)` preserves every `furnace_x1_top` port.
The legal widths are exactly 64 and 512. Data/keep ports use minimum width one
for illegal-parameter diagnostics only. All other buses are unsigned.
Keep-port widths test `DATA_WIDTH >= 8` before selecting `DATA_WIDTH >> 3`;
negative widths therefore select one diagnostic bit, not a logical-right-shift
result. Illegal configurations instantiate no legal datapath.

Configuration: inputs `cfg_valid`, `cfg_op[1:0]`, `cfg_index[5:0]`,
`cfg_value[511:0]`, `cfg_mask[511:0]`, `cfg_action[31:0]`, `cfg_enable`,
`cfg_rss_key[327:0]`; output `cfg_ready`. Operations 0,1,2,3 respectively replace
one rule, replace the RSS key, disable every rule, and set the default action.
Configuration is accepted only with no outstanding packet or result.

Metadata: outputs `m_meta_valid`, `m_header[511:0]`,
`m_packet_bytes[31:0]`, `m_rss_hash[31:0]`, `m_rss_valid`, `m_rule_hit`,
`m_rule_index[5:0]`, `m_action[31:0]`; input `m_meta_ready`.
Each valid channel holds its complete record independently until consumed.

## Header/classifier key

| Bits | Field |
|---|---|
| 127:0 / 255:128 | source / destination address; IPv4 zero-extended |
| 271:256 / 287:272 | source / destination port |
| 295:288 | final IP protocol / next header |
| 299:296 | IP version |
| 300 / 301 / 302 | IP valid / transport valid / fragmented |
| 304:303 | VLAN count |
| 316:305 / 328:317 | outer / inner VID |
| 344:329 | effective EtherType |
| 392:345 / 440:393 | source / destination MAC |
| 441 / 442 | parse error / unsupported |
| 511:443 | zero |

Multibyte values use network numerical order. Absent fields are zero.
On parse error all fields clear except bit 441 and independently established
bit 442. Classification still executes. Packet bytes count asserted keep bits,
saturating at 0xffffffff. Ethernet sizes outside 14..9216 are parse errors.

Support Ethernet II, up to two 8100/88a8 VLAN tags, IPv4 IHL 5..15 and IPv6
with up to eight 0/43/60/44/51 extension headers. IPv4 options are skipped.
IPv6 option lengths are `(length+1)<<3`, AH `(length+2)<<2`, Fragment eight.
A third VLAN, unsupported IP transport, ESP, jumbogram, over-eight extension
chain, or required extraction beyond byte 255 is unsupported. IPv6 next-header
59 is a supported terminal without transport.

Declared IP lengths must fit received bytes; padding beyond IP length is ignored.
Wrong IP versions, reserved IPv4 fragment flag, repeated IPv6 Fragment headers,
invalid extension extent, invalid TCP offset/header extent, UDP length below
eight, and unfragmented UDP length beyond its IP payload are errors.
Non-initial fragments never extract ports. First fragments require the complete
transport header; UDP may declare beyond the fragment when more fragments follow.
Atomic IPv6 Fragment headers are not fragmented. Fragmented packets cannot RSS.
No checksum validation, reassembly, tunneling, FCS stripping, or payload action
execution is implemented.

## RSS and classifier

RSS requires IP and L4 validity, TCP(6) or UDP(17), and no error, unsupported
condition or fragmentation. Tuple byte order is source address, destination
address, source port, destination port, protocol: 13 bytes for IPv4, 37 for IPv6.
Tuple/key bits are MSB first. XOR the 32-bit key window at each asserted tuple
bit into an initially zero hash. There is no reflection or final XOR.
This is **five-field** RSS, not conventional four-tuple equivalence; the
328-bit key accommodates the protocol byte of the IPv6 tuple.
Default network-order key:
`6d5a56da255b0ec24167253d43a38fb0d0ca2bcbae7b30b477cb2da38030f20c6a42b73bbeac01fa00`.
Ineligible records return zero hash and validity.

The 64 enabled ternary entries match `((header ^ value) & mask)==0`;
one means care. Lowest index wins. Zero mask is wildcard. No match reports
hit/index zero and the configured default action. Reserved bits can be cared.

CRC32C polynomial is reflected 82f63b78; CRC64/NVME is reflected
9a6c9329ac4bc9b5. Both initialize/final-XOR all ones.
ASCII `123456789` gives e3069283 / ae8b14860a799888; empty gives zero.
First-beat controls, malformed keep arithmetic, protocol error accumulation and
independently consumed payload/CRC are unchanged from the supplied X1.
Malformed keep CRC processes full-width zero-filled beats, then undoes the
missing final lanes; it does not compact malformed masks.

## Exact timing

E0 accepts the final ingress beat. E1 registers captured byte zero; E2 consumes
it and registers byte one; E257 consumes byte 255; E258 publishes parser output.
E259 consumes parser valid and hashes bit zero, E260..E554 hash bits 1..295,
and E555 publishes RSS. E556 reads classifier rule zero. Each rule has one
registered read, eight 64-bit compares, and one commit. Rule r reads at
E(556+10r) and commits at E(565+10r). Rule 63 publishes at E1195.
Top metadata becomes valid post-E1196 and may transfer at E1197.
This schedule does not depend on legacy consumer stalls.

Without stalls the unchanged X1 sixteen captures produce an accepted beat
post-E15, including final CRC. Stalls preserve parent advance semantics.
No next packet starts until final payload, CRC, and metadata all transfer.

## Reproduction and claim boundaries

From the project root, after independent Verifier supplies `tests/verify.py`:

```
python3 tests/verify.py
python3 tests/verify.py --mode smoke --out evidence/l1/smoke
python3 tests/verify.py --mode behavior --seed 17 --out evidence/l1/behavior-17
python3 tests/verify.py --mode behavior --seed 43 --out evidence/l1/behavior-43
python3 tests/verify.py --mode behavior --seed 89 --out evidence/l1/behavior-89
python3 tests/verify.py --mode defects --out evidence/l1/defects
python3 tests/verify.py --mode synthesis --out evidence/l1/synthesis
python3 tests/verify.py --mode portability --out evidence/l1/portability
```

Dependencies: Python 3 standard library, Icarus/vvp with SystemVerilog 2012,
Verilator, C++ compiler, make, Yosys. Required versions actually used must be
recorded in execution receipts; no dependency is installed by these commands.
Each invocation must retain a unique child output directory and raw evidence.
These are required verification commands, not claims of completed checks.

Independent L1 evidence must establish packet/oracle parity, parent compatibility,
latency/stall/reset behavior, measured coverage and separately killed defects.
Generic Yosys evidence establishes structure/no latches, not physical timing.
The shared runtime separately owns L1.5 timing lint, Quartus 17.1 STA on
10AX115N2F45E1SG (period <=10 ns, WNS >=0), and three consecutive native
PCIe Gen3x8 bridge hardware passes. Those gates and the independently approved
runtime-authored product PDF remain mandatory and are not certified by this file.
