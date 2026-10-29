# FURNACE-X3 frozen design contract

## Scope and authority

Top: `furnace_x3_top`. One clock, asynchronous active-low `rst_n`.
Target: Intel Arria 10 GX 10AX115N2F45E1SG, period <=10.0 ns.
This document describes implementation requirements, not measured acceptance.
The supplied X2 RTL is provenance; its copied modules retain literal interfaces,
hierarchy, CRC, parser, RSS, classifier and legacy behavior.

Parameters: DATA_WIDTH=512 (legal 64 or 512), MAX_PACKET_BYTES=9216
(legal 1..9216), MAX_SG=16 (legal 1..16). Unsupported tuples have a
diagnostic-only interface and a complete generate guard, with nonzero
`PARAMETER ERROR` termination. Eight queues are fixed. No division or modulo
operators are permitted in RTL. No sequential process mixes assignment styles
for stored state. Packet RAM is synchronous byte-wide storage without reset
contents; ownership and valid state reset.

## Public ports

Every `furnace_x2_top` port is retained unchanged: the s_axis/m_axis data,
keep, valid, last and ready channels; checksum controls and CRC result channel;
cfg_valid/op/index/value/mask/action/enable/rss_key/ready; and
m_meta_valid/header/packet_bytes/rss_hash/rss_valid/rule_hit/rule_index/action/
ready. See its module declaration for exact widths. The added ports are:

| Group | Inputs | Outputs |
|---|---|---|
| Mode | dma_enable | dma_idle |
| Queue configuration | q_cfg_valid, q_cfg_id[2:0], q_cfg_enable, q_cfg_ring_base[63:0], q_cfg_ring_entries[8:0], q_cfg_quantum[15:0], q_cfg_rate[31:0], q_cfg_burst[15:0] | q_cfg_ready |
| Doorbell | db_valid, db_queue[2:0], db_producer[31:0] | db_ready |
| Control response | ctl_ready | ctl_valid, ctl_queue[2:0], ctl_code[2:0] |
| Memory request | dma_rd_ready | dma_rd_valid, dma_rd_addr[63:0], dma_rd_len[15:0] |
| Memory response | dma_rsp_valid, dma_rsp_data[DATA_WIDTH-1:0], dma_rsp_keep[(DATA_WIDTH>>3)-1:0], dma_rsp_last, dma_rsp_error | dma_rsp_ready |
| Completion | dma_cpl_ready | dma_cpl_valid, dma_cpl_queue[2:0], dma_cpl_cookie[31:0], dma_cpl_status[2:0], dma_cpl_bytes[31:0] |

During reset every public output is zero. Reset cancels every transaction,
configuration, reservation, cached head and credit; the environment resets the
bridge and discards outstanding responses. dma_enable changes only when the
whole subsystem is quiescent. DMA mode excludes legacy ingress. Legacy mode
excludes queue controls, reads and completions, but preserves X2 configuration.
dma_idle excludes pending ring work, control responses, prefetch offers, reads,
decisions, reservations, buffered packets, completions and undrained X2 outputs.
Idle token refill is not pending work.

## Cycle & Degenerate-Boundary Table

| Boundary | Required behavior |
|---|---|
| Sampling | Only pre-edge valid AND ready transfers; registers update post-edge. A newly asserted valid cannot transfer on its creation edge. |
| Reset | Public outputs zero while reset is active; ownership state resets asynchronously. First released edge may begin ordinary refill/control/arbitration, never revive old work. |
| One byte / one SG | Real descriptor, one SG entry and one payload byte are read; one terminal output beat with keep=1 is emitted. |
| Ring depth 1 | Every retirement explicitly wraps physical index to zero. |
| Ring depth 3 or other non-power-of-two | Compare index with entries-1; explicit wrap, no bit-mask approximation. |
| Simultaneous controls | Configuration has priority; exactly one held response per accepted transaction. |
| Refill and reserve | Apply min(capacity,T+rate), then subtract reserved cost. |
| Refill and refund | Apply min(capacity,T+rate+reserved_cost) in widened arithmetic. |
| Reset versus any event | Reset cancels all events without refunds or completions. |
| Reserve/refund/retire | Mutually exclusive; completion handshake alone advances consumer/index. |

## Host ring lifecycle and control

Configuration is accepted only with no pending control response and all queues,
DMA, scheduler and X2 drained. Code 0 is OK, 1 invalid configuration,
2 invalid producer update. Invalid transactions are accepted and rejected
explicitly without state changes. Capacity is 1..256, base is 32-byte aligned,
and the complete ring address range cannot overflow 64 bits. Enabled queues
require nonzero quantum and burst; disabled queues still require legal layout.
Rate zero is legal. Configuration zeroes producer, consumer, index, deficit
and tokens, and never grants implicit credit.

Producer/consumer are wrapping unsigned 32-bit sequences. Doorbell forward
delta from the previous producer must fit current free capacity. Disabled,
backward and overrun updates are rejected. Repetition is a legal no-op.
Posting transfers immutable descriptor, SG and payload ownership to the DUT.
Ownership returns only on external completion handshake, not on completion
valid or output-last. The host must not modify posted storage.

Descriptor address is base+(physical_index<<5). A 32-byte little-endian
descriptor contains SG address at 0..7, total length at 8..11, segment count at
12, zero reserved bytes at 13..15, cookie at 16..19 and zero reserved bytes at
20..31. SG address is 16-byte aligned. Each 16-byte SG entry contains payload
address at 0..7, length at 8..11 and zero reserved bytes at 12..15.
Count is 1..MAX_SG; every length is positive; widened sum must equal total
length in 1..MAX_PACKET_BYTES. Total length exceeding burst is malformed.
All address ranges and sums are checked before narrowing.
Validate the entire SG list before any payload read. Concatenate segments
without padding, loss or repetition; arbitrary unaligned payload addresses
are legal.

## Bridge and completion contract

One exact positive byte-addressed request is outstanding globally. Request
fields hold until accepted. Low byte lanes arrive first. Nonterminal beats
have full keep; terminal keep is a nonzero contiguous low mask and last occurs
at the exact requested byte count. The bridge owns physical alignment,
PCIe splitting and memory ordering. A terminal error can end a request early.
Malformed streams drain through last before further requests; a missing last
has no timeout-based progress guarantee.

Completion status: 0 success, 1 descriptor malformed, 2 SG malformed,
3 memory read error, 4 response protocol error. First detected error wins;
simultaneous response error precedes format error. Cookie is decoded from a
complete descriptor, otherwise zero. Success bytes equals full descriptor
length; failure bytes is zero. Every owned descriptor completes exactly once.
Failures after reservation emit no packet and refund exactly once. Success
requires all three public final-payload, CRC and metadata handshakes.
All completion fields hold under backpressure. DMA checksum checking is
disabled but CRC generation, protocol reporting and metadata remain active.

## Exact DRR and token arithmetic

Visit ascending queues from zero, explicitly wrapping seven to zero. Add a
16-bit quantum once on entry to a nonempty enabled queue, saturating its
32-bit deficit. Repeated successful heads in that visit do not add quantum.
An observed truly empty queue resets deficit; pending unvalidated heads are
not empty. Insufficient deficit or tokens ends the visit and retains deficit.
A successor requiring prevalidation retains the no-add visit state. Error
heads bypass scheduling without debit or extra quantum.

Tokens are unsigned 48-bit Q32.16, rate unsigned 32-bit Q16.16 bytes/clock,
capacity=burst<<16. At every enabled edge refill=min(capacity,T+rate) with
widened arithmetic. E0 eligibility uses pre-edge balance, not same-edge refill.
Grant handshake applies refill then subtracts bytes<<16. Failure refund applies
refill plus the original cost before saturation. Deficit refunds saturate at
0xffffffff. A reservation is settled once, retained until retirement, and
never refunded merely for an output stall.

## Frozen internal interface table

All five new modules have scalar clk/rst_n. Names below are literal port and
top interconnect names. Packed queue q occupies [q*W +: W].

| Producer -> consumer | Exact signals and widths | Transfer / ownership |
|---|---|---|
| Top -> rings | public q_cfg_*, db_*, ctl_* with public directions; ctl_allow, dma_enable, pf_allow | ctl_allow permits drained configuration only; DMA mode permits doorbells |
| Rings -> scheduler/shaper | cfg_commit, cfg_commit_queue[2:0], cfg_commit_enable, cfg_commit_quantum[15:0], cfg_commit_rate[31:0], cfg_commit_burst[15:0] | valid accepted configuration edge event; zero credits and load operands |
| Rings -> scheduler/top | q_enabled[7:0], q_pending[7:0], head_valid[7:0], head_seq[255:0], head_bytes[255:0], head_cookie[255:0], head_status[23:0], q_quantum[127:0], q_burst[127:0] | read-only view, rings exclusively authoritative |
| Rings -> DMA | pf_valid, pf_queue[2:0], pf_seq[31:0], pf_desc_addr[63:0], pf_burst[15:0]; reverse pf_ready | registered stable offer; handshake claims {queue,consumer sequence} |
| DMA -> rings | pf_done_valid, pf_done_queue[2:0], pf_done_seq[31:0], pf_done_bytes[31:0], pf_done_cookie[31:0], pf_done_status[2:0]; reverse pf_done_ready | registered result publishes only matching claim, after all reads terminate |
| Shaper -> scheduler | token_balance[383:0] | read-only pre-edge state view |
| Scheduler -> top | grant_valid, grant_queue[2:0], grant_seq[31:0], grant_bytes[31:0]; reverse grant_ready | post-E2 stable grant |
| Top -> DMA | run_valid, run_queue[2:0], run_seq[31:0], run_bytes[31:0]; reverse run_ready | exactly same transfer edge as grant, no hidden command queue |
| Top -> owners | reserve_fire, refund_fire, retire_fire; evt_queue[2:0], evt_seq[31:0], evt_bytes[31:0]; retire_reserved to scheduler/shaper | atomic non-backpressurable events, mutually exclusive |
| DMA -> X2 via top | pkt_valid, pkt_data[DATA_WIDTH-1:0], pkt_keep[(DATA_WIDTH>>3)-1:0], pkt_last; reverse pkt_ready | whole successful packet only, stable registered stream |
| Top -> DMA | x2_done | edge accepting last outstanding public result |
| DMA -> top | run_done_valid, run_done_queue[2:0], run_done_seq[31:0], run_done_status[2:0]; reverse run_done_ready | registered result, lock/cache retained to retirement |
| Scheduler -> top | decision_busy, scheduler_idle | E0 through rejection or reserved retirement |
| DMA -> top | dma_busy | includes prefetch, held results, active run, RAM/stream and retirement wait |
| Rings -> top | rings_idle | no pending descriptors, claims, heads, offers or control response |
| Top -> scheduler | decision_allow | gates new E0 only |

Rings exclusively owns configuration, producer/consumer/index, prefetch claims
and valid head records. Head records remain stable from publication through
completion handshake; cookies are not identities. DMA exclusively owns eight
SG caches, read sequencing, response staging and one packet RAM. Successful
cache data retains exact identity until retirement; cache validity never
replaces ring head authority. Scheduler exclusively owns visits, deficits,
snapshots, grant and deficit reservation. Shaper exclusively owns balances and
token reservation. Top owns arbitration, one active identity, X2 result flags
and held external completion, not duplicate queue/credit state.

An unaccepted prefetch offer holds unchanged. No new offer is created after E0.
An in-flight prefetch may finish while a decision waits; grant waits until that
offer and execution finish. At dispatch boundaries errors receive first
round-robin opportunity, then cached service, then discovery. Prefetch returns
to arbitration rather than chaining. Top serializes dispatch through external
completion. Doorbells may append during stalls but cannot replace heads.
Internal identity mismatch is an invariant violation, not a successful fallback.

## Frozen cycle tables (verbatim contract)

Parent edge convention remains unchanged. With no stalls a legacy beat accepted E0 emerges from X1 post-E15: seven beat registers E0..E6, accumulator E7, seven tail registers E8..E14 and output register E15. A legacy final input beat accepted E0 gives parser output E258, RSS acceptance E259 and output E555, classifier acceptance E556 and output E1195, held top metadata valid E1196. Independently verify these timings. X1 advancement stalls freeze its pipeline; completed X2 metadata holds independently. Configuration stays excluded until all three packet-result channels drain.

New scheduler cycle table: visit-entry edge V commits a single saturating quantum addition when required. E0 is no earlier than V+1 and captures a stable head identity/length, applicable credited deficit and pre-edge token balance. E1 registers deficit and token comparisons from that snapshot. E2 commits rejection or asserts the registered grant. Grant is visible post-E2 and transfers no earlier than E3. No new candidate replaces it before rejection or completion-driven retirement. Deficit/token debit occurs on grant handshake only. Ordinary token refill continues on E0/E1/E2 and stalled-grant edges; eligibility deliberately remains based on E0, which is safe because no competing reservation can reduce its balance.

Read commands are registered, including commands issued after descriptor/SG processing. Response handling uses a registered full-beat staging register and bounded byte-serial unpacking. A response accepted R0 is captured post-R0; its bytes are consumed from a fixed eight-bit shift slice starting R1, one byte per edge in ascending order. dma_rsp_ready is deasserted while the staging beat is being consumed, except terminal-drain logic may discard malformed data without writes. No response byte writes packet RAM at R0. Packet RAM is byte-wide with synchronous registered reads and one-byte writes. A successful final response's last staged byte writes at W, followed by a separate validation/publication edge W+1. No packet RAM output read issues before W+2. Packet read edge P0 registers one addressed byte; P1 appends that old registered byte to a beat-assembly register. When the final byte of a full or terminal output beat is appended at P1, a separate P2 edge transfers the assembled beat to the registered pkt_* output. Consequently a final successful response at R0 cannot produce packet valid before R1 or first transfer before R2; this chosen implementation is intentionally later and has the explicit P0/P1/P2 RAM/assembly/output stages. Hold assembled output during stalls, and issue no read that can overwrite needed staged data. All lane shifts are constant byte shifts; packet-length-dependent packing chains are forbidden. This staging supports one-byte packets and both lane widths without asynchronous RAM assumptions.

If the last of the three public X2 result handshakes occurs at H0, run_done_valid may first assert post-H1; result handshake is no earlier than H2 and registered external success completion appears no earlier than post-H2. Error result similarly uses a separate registered transition after error detection and terminal drainage; external error completion is registered, not combinationally asserted from input response valid. Prefetch-detected error completion follows head publication and registered arbitration, never the detection edge. Document these tables verbatim in SPEC. Extra registered address/check stages may delay prefetch/read issue but must not alter these frozen local scheduler, RAM and result-stage conventions.

## Independent acceptance and reproduction

Run from the delivered root (dependencies: python3, iverilog/vvp, verilator,
make, g++, yosys; versions are recorded by verification, not assumed here):

```
python3 tests/verify.py --suite behavior
python3 tests/verify.py --suite defects
python3 tests/verify.py --suite synthesis
python3 tests/verify.py --suite delivery
```

Default invocation executes all four self-contained suites. Verifier owns their
sources and independent models. Required matrix is both widths crossed with
(1,1),(65,3),(9216,16), seeds 17,43,89; each cell >=64 successful DMA handshakes
across eight queues and >=16 legacy packets. Capacities 1 and 3 have two actual
wraps each; maximum cells also exercise 8 and 256 with two actual wraps and
independently justified sequence rollover. No generated-request labels replace
observations. Every error, reset, protocol, numerical, overlap, stalled-output
and invalid-parameter obligation in the admitted plan remains mandatory.
At least six compiling functional mutants must be killed by specific numerical
or assertion failures, not compiler failure or timeout. Yosys covers real
hierarchy, both widths and all three storage tuples, preserved tops, zero
latches, no black boxes and substantive connected state.

| Claim | Required independent evidence |
|---|---|
| Legacy byte/CRC/header/RSS/classification correctness and exact latency | behavior receipt, independent bytewise/numerical models and public handshake scoreboards |
| Ring, SG, DRR, tokens, refund, reset and backpressure | behavior receipt with observed coverage and frozen interface assertions |
| Defect sensitivity | defects receipt with disposable source provenance and first functional failure |
| Synthesis portability and storage connectivity | synthesis receipt and real Yosys JSON/statistics |
| Portable reproduction | delivery receipt from a fresh isolated copy using only declared sources, compact legacy-plus-DMA smoke |
| 100 MHz timing and physical PCIe | shared-runtime native timing lint, Quartus 17.1 STA with WNS>=0, three consecutive physical Gen3x8 deterministic passes |
| Product PDF | runtime authors and independently reviews after engineering acceptance |

Evidence is generated in fresh project-relative evidence/<suite>-<timestamp_or_hash>/
directories with immutable receipts, exact command/cwd, hashes, tools, times,
exit/timeout and raw logs. Preparation is advisory only. No timing, hardware,
verification or review success is claimed by this design handoff. Delivery
smoke is bounded portability evidence, not a second full matrix. Metadata,
private paths, credentials, transcripts and existing generated binaries are
not product inputs. Missing tools or boards are unmet gates, never waivers.
