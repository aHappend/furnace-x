# FURNACE-X3 scheduler firmware

Build from the delivered project root with Python3 and no installed packages:

```
python3 firmware/build.py
```

For another legal input geometry:

```
python3 firmware/build.py --in-width 3 --in-height 2 --fft-n 32 --output firmware/c2.hex
```

Image dimensions and FFT_N must match the instantiated RTL. Ring/fusion depths
come from parent CSRs. The image is hexadecimal **32-bit instruction words**,
one word per line, in ascending address order starting at CPU0x10000. Each
word is stored little-endian. The adjacent JSON contains the entry, byte
count, geometry, symbols and SHA256 hashes of assembly text and image bytes;
the listing contains actual encoded RV64 instructions. These files are
generated product inputs, not executed workload/acceptance evidence.

## Host boot

1. Apply global reset, release it and wait for CPU_STATUS.halted.
2. Provision ordinary DDR through the platform's memory initialization path:
   graph records, descriptor images, encrypted/compressed frames, activations,
   input pixels/samples and guard regions. The AXI-Lite port is not a DDR
   initialization aperture.
3. Write every image word at host aperture0x4000+image_offset with all four
   byte strobes. Initialize the ten32-bit manifest words at host0x8000:
   graph DDR address, node count, parent ring base, vision feature base,
   audio feature base, result base and four public-test AES key words.
   CPU addresses for these are0x20000..0x20027.
4. With legacy inputs quiescent, set FW_MODE(0x2020)=1 and check OKAY.
   This is a sticky ownership transfer, not a reset of legacy state.
5. Write CPU_CTRL(0x2004)=1. No further host writes perform scheduling,
   sample injection, dependency resolution or completion acknowledgement.
   Host reads and mailbox pops are permitted.
6. Observe mailbox0 DATA(0x2600), public DDR statuses and CPU_STATUS.halted.
   Firmware itself removes RUN after its final mailbox write.

The scheduler programs the real parent key, ring and feature buffers. Ring
base must be128-byte aligned DDR and allocate128*RING_DEPTH bytes. Feature
buffers must satisfy the preserved parent's alignment, allocation and
nonoverlap checks. Every status record must be16-byte-aligned DDR. Graph
record alignment is64 bytes. All addressed input bytes must be initialized.
CPU local memories do not acquire defined contents merely from reset.

To execute another graph without discarding wrap history, wait until firmware
has halted, initialize its next manifest/image/data as needed, write
CPU_CTRL=2 for core-only reset, and then CPU_CTRL=1. FW_MODE, parent counters/
ring slots, fusion credits, mailbox pointers and synchronization state are
not globally reset. Pop final messages often enough to leave capacity;
firmware intentionally waits rather than dropping a notification.

## Software ABI and scheduling

The graph/descriptor/numerical formats are frozen in `design/SPEC.md`.
Opcodes1/2/3/4 are native DMA, real parent descriptor, multimodal frame and
barrier. Descriptor bytes, including authenticated flags/AAD, are copied
unchanged. Tensor mode is never replaced with a firmware calculation.
Only one node per resource is active, but the three resources are independent.
The scan does not busy-wait on a descriptor before starting other runnable
nodes; stream input feeding similarly advances incrementally.

The descriptor retirement counter is polled because IRQ-request bit8 belongs
to authenticated descriptor content and cannot be changed to force an event.
DMA and frame completions use hardware semaphore0/1 and IRQ mask bits1/2.
Graph wait/post semaphores are2..15 or0xffffffff for none. Status publication
uses acknowledged public DDR stores and fences; software post and success-mask
updates follow actual hardware completion, not a timer or predicted result.
Errors propagate to consumers as dependency-failed without launching them.

Firmware owns these CPU DMEM regions:

| Range | Use |
|---|---|
| 0x20000..0x20027 | Input manifest |
| 0x20040/0x20044 | Execution state(1 running,2 success,3 failure)/summary error |
| 0x20048/0x20050 | Synchronous trap cause/PC, each u64 |
| 0x20100..0x210ff | Up to64 cached graph records |
| 0x21200..0x215ff | Local node state/error |
| 0x21800..0x219ff | Scheduler resource/work state |
| Downward from0x23ff0 | LP64-aligned stack |

Final mailbox0 message: `0x58430000 | node_count | (failure ? 0x8000 : 0)`.
Malformed/unsafe manifest or synchronous-trap notification:
`0x5843ff00 | firmware_error`. An invalid status pointer is never dereferenced.
Hardware node errors retain0..8. Firmware node errors are:

| Error | Meaning |
|---|---|
| 0x100 | Malformed manifest/graph/opcode/indices/unused fields |
| 0x101 | Dependency cycle |
| 0x102 | Failed predecessor |
| 0x103 | Unsatisfied waits with no runnable or active producer |
| 0x104 | Software post would overflow a semaphore |
| 0x105 | Invalid descriptor/frame input source arguments |
| 0x106 | Synchronous firmware trap; cause/PC retained in DMEM |

The interrupt handler preserves its touched registers, acknowledges parent
IRQ status and aggregator events, and returns with MRET. The parent
multimodal-fault level source0 is masked during scheduling to prevent a fault
storm; the next quiescent boot clears it. WFI uses an MIE-disabled condition
check with MEIE enabled, so a completion cannot be acknowledged between the
last check and sleeping. No private binary, custom instruction, host device
identifier or unavailable Hammer-V image is required or claimed.
