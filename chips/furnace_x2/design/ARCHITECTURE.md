# FURNACE-X2 implementation

## Connected hierarchy and ownership

`rtl/furnace_x2_top.sv` is the integration top. Its legal generate branch
instantiates exactly these major blocks:

| Instance | Module | Responsibility |
|---|---|---|
| crc_core | furnace_x1_top | Unmodified streaming payload and CRC32C/CRC64/NVME |
| parser | furnace_header_parser | Capture, byte scan, validation, header and tuple construction |
| rss | furnace_rss_toeplitz | One tuple bit per edge; fixed 296-bit work schedule |
| classifier | furnace_classifier64 | Registered rule read and eight chunk comparisons per rule |

The six files copied from `furnace_x1_reference/rtl/` remain byte-identical.
Inside `crc_core`, the literal `beat_pipeline`, `packet_accumulator`,
`tail_pipeline`, `output_stage` instances and `furnace_crc_linear` instances
are retained. The parent remains independently usable. No wrapper arithmetic
changes its CRC results. No auxiliary leaf module or public parameter was added.

Designer owns only `rtl/*.sv`, `design/SPEC.md`, and this document.
Independent Verifier owns `tests/*.py`, numerical models, benches, mutation
checks and synthesis assertions. Generated files belong to new retained
execution output directories, not the source tree.

## Storage, lifetime and dependencies

| Storage | Capacity | Producer / release |
|---|---|---|
| Header capture | 256 bytes | Accepted ingress / parser finishes scanning |
| Capture bank read registers | DATA_WIDTH bits | Scan read / next scan edge |
| Working header | 512 bits | Byte parser / parser publication |
| Held header, bytes and hash | One packet | Parser/RSS / terminal result completion |
| Rule values and masks | 64 x 1024 bits | Idle configuration / replacement |
| Rule actions | 64 x 32 bits | Idle configuration / replacement |
| Rule enable vector | 64 bits | Idle configuration / clear or reset |
| RSS key | 328 bits | Idle configuration / replacement or reset |
| Metadata output | One record | Classifier completion / metadata handshake |

Capture is banked by AXI byte lane: eight banks of 32 bytes at width 64, or
64 banks of four bytes at width 512. A beat writes one row across all banks.
The registered row reads and delayed bank index supply one scan byte per edge.
Uncaptured positions explicitly read zero; uninitialized memory contents never
enter active parsing. Invalid lanes are stored as zero, while a separately
accumulated malformed-keep bit guarantees the deterministic error key.
Capture addresses stop at 256 even for arbitrarily long ingress packets.
The byte counter continues, saturating rather than wrapping.

One packet owns the engine from its first ingress handshake through all three
terminal handshakes. Its `input_ended` bit prevents any following packet from
entering X1 while metadata is computing. Top gates *both* input valid to X1 and
external ready with the same admission predicate. Parser capture uses exactly
that public transfer event, so an internal-only transfer cannot occur.

`cfg_ready` requires no ownership. Idle `cfg_valid` suppresses packet admission,
including X1's input valid. Rules/key/default action therefore cannot change
during an outstanding packet or result. No shadow-bank switch is needed.
The rule payload memories need no initialization because asynchronous reset
clears enables. Capture contents need no reset because every visible read
has an explicit received-position guard.

X1 guarantees ordered output beats and one CRC per final beat. Top observes the
final payload and CRC handshakes independently. The metadata engine neither
uses X1's advance signal nor waits for its consumers, so metadata timing remains
fixed under payload or CRC stalls. The last of the three completion handshakes
releases ownership at that edge; a new packet may start on the following edge.

## Byte parser

The parser consumes the 256 captured positions in ascending wire order.
Ethernet/VLAN states shift network-order MACs, VIDs and effective EtherType.
IPv4 state decodes IHL, total length, fragment information, protocol and compact
addresses, then skips options by the registered header-length counter.
IPv6 state gathers fixed addresses and dispatches a bounded extension scanner.
Each extension registers its next header and length before skipping the rest.
Fragment offset/M and a separate seen-fragment flag distinguish first,
non-initial, atomic and repeated fragment headers.

Absolute positions and declared IP end use 17 bits: enough for a 16-bit IP
length plus the captured L2/header offsets. Received-byte comparisons use
32-bit operands. Options, AH and TCP lengths use shifts, never division or
remainder. IP declared extents are checked even when an unsupported transport
causes early termination. Ethernet padding beyond the IP end is not parsed.

Candidate ports are private until the complete declared TCP header or eight-byte
UDP header fits. Unsupported extraction beyond capture never commits partial
ports. Non-initial fragments terminate without transport parsing. Incomplete
received headers become errors without processing zero padding as real bytes.
Parser errors clear the packed header except error and independently discovered
unsupported bits. Every record, including errors, reaches classification.
The detailed supported/error/unsupported limits are in `design/SPEC.md`.

## Pipeline edge accounting

Let E0 accept the final beat. Parser engine start is registered at E0.
The first synchronous bank read is E1. Delayed read index/valid consume byte 0
at E2; after consuming byte 255 at E257 the engine enters publication.
Parser output registers update at E258.

RSS sees parser valid pre-E259; that edge performs tuple bit zero while loading
the shifted tuple/key. Its counter starts at one. Bits 1..295 occupy E260..E554.
The following publication edge is E555. Contributions outside the 104-bit
IPv4 tuple are suppressed, without shortening the schedule.
The tuple is MSB-aligned, and both shift registers move toward their MSB outputs.
Each asserted input bit XORs the current key's top 32-bit window.

Classifier starts on RSS valid at E556, reading rule zero's complete
value/mask/action into registers and its enable separately.
Eight edges compare and shift one low 64-bit chunk, accumulating equality.
The ninth subsequent edge commits a match, only if no earlier enabled rule won.
The next rule read uses the following edge. Thus each rule occupies ten edges,
including disabled rules and rules after a winner.
Rule 63 commits and registers output at E1195; top consumes that pulse and
registers the combined metadata at E1196. No extra ready/valid register is
interposed. The first possible public metadata handshake is E1197.

RSS and classifier completion valids are single-cycle pulses. Top retains
their payloads and independently holds public metadata valid and its entire
record until `m_meta_ready`. Reset aborts any stage without emitting completion.

## Timing and throughput tradeoff

The synchronous target is Arria 10 GX `10AX115N2F45E1SG`, period <=10.0 ns.
There is no combinational division/remainder and no sequential blocking
assignment in the new RTL. Registered byte reads, one-bit hash steps and
64-bit care comparisons bound the intended work between registers.
These structural choices are a timing-oriented implementation, **not** a
physical timing-closure claim. Native timing lint and Quartus STA remain gates.

Serialization deliberately trades packet throughput for bounded control and
comparison depth. Metadata becomes available 1196 edges after final ingress:
11.96 microseconds at an assumed 100 MHz clock, plus output waiting.
Packet ingress duration and terminal handshake time add to ownership lifetime.
There is no minimum packet-throughput requirement; no line-rate claim is made.
The unchanged X1 top remains available at its original pipelined throughput.

## Evidence mapping and integration

Use the port, reset, configuration, numerical and cycle rules in
`design/SPEC.md`. Assert reset before traffic, release it on a safe clock phase,
configure only by accepted cfg transfers, and hold every producer payload
stable while stalled. Payload actions are opaque metadata, not modifications.
Do not append FCS/preamble expecting this parser to strip it.

Required source inputs are `rtl/*.sv`, `design/SPEC.md`,
`design/ARCHITECTURE.md`, independent `tests/*.py`, and the six reference RTL
files for compatibility checks. No runtime metadata or prior generated artifact
is a product input. Portable reproduction commands and dependency requirements
are listed in `design/SPEC.md`.

| Claim | Required independent evidence |
|---|---|
| CRC and forwarded payload compatibility | Both-width parent/copy and independent polynomial checks |
| Header, true five-field RSS, priority classifier | Independent packet dictionary/oracle and complete-vector comparisons |
| Stalls, reset, exact E1196 latency | Cycle-by-cycle channel/latency assertions |
| Coverage and checker sensitivity | Measured directed/seeded counters and separately executed killed RTL mutants |
| Synthesizable substantive implementation | Both-width real Yosys hierarchy, mapped structure and zero-latch checks |
| Portable package | Fresh-directory Icarus and compiled Verilator reproduction |
| <=10 ns Arria 10 operation | Native target Quartus STA, not generic synthesis |
| Physical PCIe bridge behavior | Native hardware gate with three consecutive deterministic passes |
| Final product report | Runtime-authored, independently approved PDF after engineering acceptance |

No functional, synthesis, timing, hardware or report acceptance is asserted by
the implementation documents. Independent verification immediately follows
this design handoff; failures must retain their original receipts.
