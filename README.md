# Furnace-X — Heterogeneous compute and SoC integration RTL

[English](README.md) · [简体中文](README.zh-CN.md) · [Repository guide / 文件导航](REPOSITORY_GUIDE.md)

Documentation updated: 2026-11-17. This page describes a repository snapshot, not a live job dashboard.

## Overview

**Furnace-X** publishes chip RTL, technical reports and verification artifacts. System-level integration of processor, AI, DSP, cryptographic, vision and data-movement engines, with shared memory/interconnect and software integration research.

The chip project is public; Vulcan itself remains private and closed-source. Future public releases must be limited to chip technology and public reproducibility materials, excluding Vulcan internal architecture and operating materials. This refresh organizes documentation only; it is not a comprehensive disclosure audit of historical material and does not claim that the existing repository tree has undergone such clearance.

## Scope and evidence

Use the [exact-directory result index](REPOSITORY_GUIDE.md). Functional simulation, synthesis, standalone/virtual-pin timing, board-bridge probing, workload readback and system-software execution are different evidence scopes. A pass at one scope does not establish another. Existing historical results are retained; this documentation refresh neither upgrades nor invalidates them.

Read timing, utilization and performance values from their specific records and applicability conditions; results from differently located copies are not merged. This page makes no fleet-wide claim of physical-board completion, full-model inference, physical Linux boot or measured power/energy efficiency.

## Repository guide

The [repository guide](REPOSITORY_GUIDE.md) lists existing source, constraints, tests, reports and result paths. Hyphenated, underscored and `chips/` directories can be different publication copies; none is silently designated authoritative, moved or deleted.

Start reproduction from the selected chip’s public specification, test instructions and scripts. Tool, input and board requirements belong to that directory. Chip experiments were not rerun as part of this documentation update.

## Existing chip directories

| Chip / variant | Existing root paths | Public artifacts |
| --- | --- | --- |
| FURNACE-X1 | [`furnace-x1/`](furnace-x1/) · [`furnace_x1/`](furnace_x1/) | [REPORT.md](furnace-x1/REPORT.md) · [REPORT.pdf](furnace-x1/REPORT.pdf) · [SHOWCASE_REPORT.pdf](furnace-x1/SHOWCASE_REPORT.pdf) · [SHOWCASE_REPORT.zh-CN.pdf](furnace-x1/SHOWCASE_REPORT.zh-CN.pdf) |
| FURNACE-X2 | [`furnace-x2/`](furnace-x2/) · [`furnace_x2/`](furnace_x2/) | [REPORT.md](furnace-x2/REPORT.md) · [REPORT.pdf](furnace-x2/REPORT.pdf) · [SHOWCASE_REPORT.pdf](furnace-x2/SHOWCASE_REPORT.pdf) · [SHOWCASE_REPORT.zh-CN.pdf](furnace-x2/SHOWCASE_REPORT.zh-CN.pdf) |
| FURNACE-X3 | [`furnace-x3/`](furnace-x3/) · [`furnace_x3/`](furnace_x3/) | [REPORT.md](furnace-x3/REPORT.md) · [REPORT.pdf](furnace-x3/REPORT.pdf) · [SHOWCASE_REPORT.pdf](furnace-x3/SHOWCASE_REPORT.pdf) · [SHOWCASE_REPORT.zh-CN.pdf](furnace-x3/SHOWCASE_REPORT.zh-CN.pdf) |
| FURNACE-X4 | [`furnace-x4/`](furnace-x4/) · [`furnace_x4/`](furnace_x4/) | [REPORT.md](furnace-x4/REPORT.md) · [REPORT.pdf](furnace-x4/REPORT.pdf) · [SHOWCASE_REPORT.pdf](furnace-x4/SHOWCASE_REPORT.pdf) · [SHOWCASE_REPORT.zh-CN.pdf](furnace-x4/SHOWCASE_REPORT.zh-CN.pdf) |

## Architecture catalog and publications

| Generation | Chip | Architecture / research scope | Record navigation | Reports |
| --- | --- | --- | --- | --- |
| **Gen-1** | [**FURNACE-X1**](furnace_x1/) | AI Weight-Streaming & Secure Storage SoC · Bellows-L LZ4 Weight Decompressor + Rivet-A AES-GCM Decryptor + Anvil-Q Tensor Engine over AXI4 | [Exact-directory records](REPOSITORY_GUIDE.md) | [`furnace_x1/evidence/`](furnace_x1/evidence/) |
| **Gen-2** | [**FURNACE-X2**](furnace_x2/) | Multimodal Edge Perception SoC · Swage-S Vision ISP + Billet-T Audio Spectral Frontend + Anvil-E3/Q4 Unified Inference Engine | [Exact-directory records](REPOSITORY_GUIDE.md) | [`furnace_x2/evidence/`](furnace_x2/evidence/) |
| **Gen-3** | [**FURNACE-X3**](furnace_x3/) | Seven-Family Heterogeneous Compute SoC (`Hammer-V2 RV64IMAC` Host + 6 Domain Accelerators) with 8GB DDR4 EMIF DMA & QoS NoC Crossbar | [Exact-directory records](REPOSITORY_GUIDE.md) | [`furnace_x3/evidence/`](furnace_x3/evidence/) |
| **Gen-4** | [**FURNACE-X4 (`Furnace-SoC4`)**](furnace_x4/) | **Heterogeneous Linux application-computer research target** (`Hammer-V4 RV64GC + Sv39 MMU` targeting OpenSBI + Linux 6.6 + BusyBox and CLI apps `anvil-chat`, `swage-isp`, `rivet-vault`, `billet-dsp`, `bellows-pack`, `crucible-render`, `sable-verify`) | [Exact-directory records](REPOSITORY_GUIDE.md) | [**Whitepaper PDF**](furnace_x4/SHOWCASE_REPORT.pdf) · [**中文白皮书**](furnace_x4/SHOWCASE_REPORT.zh-CN.pdf) · [**SoC HIL JSON**](furnace_x4/evidence/soc-board-coexecution.json) |

## Recorded integration profiles

The [retained co-execution record](furnace-x4/evidence/soc-board-coexecution.json) lists pipeline-profile labels, SoftReg telemetry and output vectors. Those labels alone do not prove execution of every named IP, a complete model or a Linux application stack; inspect the original image, workload and output bindings. The [directory index](REPOSITORY_GUIDE.md) keeps the record copies separate.

## Related projects

- AI / embeddings: [Anvil-Q](https://github.com/aHappend/anvil-q), [Anvil-E](https://github.com/aHappend/anvil-e), [Anvil-QN](https://github.com/aHappend/anvil-qn), [Anvil-EN](https://github.com/aHappend/anvil-en), [Anvil-D](https://github.com/aHappend/anvil-d).
- Systems: [Hammer-V](https://github.com/aHappend/hammer-v), [Furnace-X](https://github.com/aHappend/furnace-x).
- DSP / vision: [Billet-F](https://github.com/aHappend/billet-f), [Billet-T](https://github.com/aHappend/billet-t), [Swage-S](https://github.com/aHappend/swage-s).
- Data / security / graphics: [Bellows-L](https://github.com/aHappend/bellows-l), [Bellows-N](https://github.com/aHappend/bellows-n), [Rivet-A](https://github.com/aHappend/rivet-a), [Rivet-H](https://github.com/aHappend/rivet-h), [Crucible-G](https://github.com/aHappend/crucible-g), [SABLE](https://github.com/aHappend/sable).
- [Public fleet catalog](https://github.com/aHappend/vulcan-showcase). Related independent research: [ACE-2](https://github.com/aHappend/ace-2), [ACE-3](https://github.com/aHappend/ace-3); these retain their own provenance and acceptance boundaries.
- DSpark is a research direction, not a published chip delivery in this repository; no implementation or repository link is asserted here.
