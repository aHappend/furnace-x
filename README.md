<div align="center">
  <picture>
    <source media="(prefers-color-scheme: dark)" srcset="brand/logo-dark.svg">
    <img src="brand/logo.svg" width="420" alt="Vulcan">
  </picture>
  <h1>Furnace-X · Heterogeneous Multi-Engine AI & System-on-Chip (SoC) Series</h1>
  <p><strong>Synthesizable 100 MHz+ Heterogeneous SoC Integrating Anvil AI, Billet DSP, Rivet Crypto, Swage ISP & Bellows Compression over AXI4 Crossbar & 8GB DDR4 · Intel Arria 10 GX</strong></p>
  <p>
    <img src="https://img.shields.io/badge/Platform-Intel_Arria_10_GX-0f766e?style=flat-square" alt="Platform">
    <img src="https://img.shields.io/badge/Quartus_17.1_STA-100_MHz%2B_Closed-0f766e?style=flat-square" alt="STA">
    <img src="https://img.shields.io/badge/PCIe_Gen3x8_HIL-100%25_Passed-1d4ed8?style=flat-square" alt="HIL">
    <img src="https://img.shields.io/badge/Author-Sufeng_Guo_(MSRA)-334155?style=flat-square" alt="Author">
    <img src="https://img.shields.io/badge/License-MIT-64748b?style=flat-square" alt="License">
  </p>
  <p>
    <a href="https://ahappend.github.io/vulcan/">Website</a> ·
    <a href="https://github.com/aHappend/vulcan-showcase">Vulcan Showcase</a> ·
    <a href="https://github.com/aHappend/anvil-q">Anvil-Q (LLM)</a> ·
    <a href="https://github.com/aHappend/anvil-e">Anvil-E (Embedding)</a> ·
    <a href="https://github.com/aHappend/billet-t">Billet-T (FFT/DSP)</a> ·
    <a href="https://github.com/aHappend/billet-f">Billet-F (FIR/IIR)</a> ·
    <a href="https://github.com/aHappend/rivet-a">Rivet-A (AES-GCM)</a> ·
    <a href="https://github.com/aHappend/rivet-h">Rivet-H (SHA/HMAC)</a> ·
    <a href="https://github.com/aHappend/swage-s">Swage-S (ISP)</a> ·
    <a href="https://github.com/aHappend/bellows-l">Bellows-L (LZ4)</a> ·
    <a href="https://github.com/aHappend/bellows-n">Bellows-N (Network)</a> ·
    <a href="https://github.com/aHappend/hammer-v">Hammer-V (RISC-V)</a> ·
    <a href="https://github.com/aHappend/crucible-g">Crucible-G (3D)</a> ·
    <a href="https://github.com/aHappend/furnace-x">Furnace-X (SoC)</a> ·
    <a href="README.zh-CN.md"><strong>中文文档</strong></a>
  </p>
</div>

---

**Furnace-X** is the system-level integration series within Vulcan's **Furnace** silicon family, uniting specialized engines from **Hammer** (`RV64GC` Linux CPU), **Anvil** (LLM/Embedding), **Billet** (DSP), **Rivet** (Crypto), **Swage** (ISP), **Bellows** (LZ4/Network), **Crucible** (3D Graphics), and **SABLE** (SAT Verification) into cohesive multi-engine SoCs with shared DDR4 DMA, AXI4 QoS NoC, and Linux CLI application stacks.

## Silicon Signoff Matrix & Dual-Track Publications (`100 MHz+` Baseline)

| Gen | Accelerator | Architecture & Numerical Scope | Quartus 17.1 STA (`10.0 ns`) | Intel Arria 10 GX Utilization | PCIe Gen3x8 HIL | Evidence & Artifacts |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| **Gen-1** | [**FURNACE-X1**](furnace_x1/) | AI Weight-Streaming & Secure Storage SoC · Bellows-L LZ4 Weight Decompressor + Rivet-A AES-GCM Decryptor + Anvil-Q Tensor Engine over AXI4 | `113.06 MHz` (`WNS +1.155 ns`) | `14,033 ALMs · 38 DSPs · 22 M20K` | **PASSED (3/3)** | [`furnace_x1/evidence/`](furnace_x1/evidence/) |
| **Gen-2** | [**FURNACE-X2**](furnace_x2/) | Multimodal Edge Perception SoC · Swage-S Vision ISP + Billet-T Audio Spectral Frontend + Anvil-E3/Q4 Unified Inference Engine | `111.78 MHz` (`WNS +1.054 ns`) | `18,621 ALMs · 53 DSPs · 64 M20K` | **PASSED (3/3)** | [`furnace_x2/evidence/`](furnace_x2/evidence/) |
| **Gen-3** | [**FURNACE-X3**](furnace_x3/) | Seven-Family Heterogeneous Compute SoC (`Hammer-V2 RV64IMAC` Host + 6 Domain Accelerators) with 8GB DDR4 EMIF DMA & QoS NoC Crossbar | `114.69 MHz` (`WNS +1.281 ns`) | `47,701 ALMs (11%) · 121 DSPs (8%) · 219 M20K` | **PASSED (3/3)** | [`furnace_x3/evidence/`](furnace_x3/evidence/) |
| **Gen-4** | [**FURNACE-X4 (`Furnace-SoC4`)**](furnace_x4/) | **8-Family Unified Linux Application Computer** (`Hammer-V4 RV64GC + Sv39 MMU` booting OpenSBI + Linux 6.6 + BusyBox with CLI apps `anvil-chat`, `swage-isp`, `rivet-vault`, `billet-dsp`, `bellows-pack`, `crucible-render`, `sable-verify`) | `111.30 MHz` (`WNS +1.015 ns`) | `47,300 ALMs (11%) · 69 DSPs (5%) · 223 M20K` | **PASSED (3/3)** | [**Whitepaper PDF**](furnace_x4/SHOWCASE_REPORT.pdf) · [**中文白皮书**](furnace_x4/SHOWCASE_REPORT.zh-CN.pdf) · [**SoC HIL JSON**](furnace_x4/evidence/soc-board-coexecution.json) |


## Physical Intel Arria 10 GX Multi-IP Heterogeneous SoC Co-Execution (`evidence/soc-board-coexecution.json`)

All four heterogeneous SoC pipelines were physically co-executed back-to-back on the **Intel Arria 10 GX1150 (`10AX115N2F45E1SG`, Chip ID `23645547322997765`, `netsys17`)** via PCIe Gen3x8 MMIO & shared on-chip M20K streaming windows (`SoftReg 4096..4438` -> `Anvil` tensor engine -> `SoftReg 16..21` 64-bit output vectors):

| SoC Co-Execution Pipeline | Multi-IP Hardware Chain Executed on Board | Status (`SoftReg 2`) | Cycles (`SoftReg 11`) | Mem Beats (`SoftReg 12`) | 6-Lane 64-Bit Output Vector (`SoftReg 16..21`) |
| :--- | :--- | :---: | :---: | :---: | :--- |
| **`soc_pipe_1_furnace_x1`** | `Bellows-L5` LZ4 Decompress + `Rivet-A5` AES-GCM Decrypt -> **`Anvil-D1`** (DeepSeek MLA+MoE) | `0x000000010000060e` | `160,831` | `0x000000e0000005a8` | `['0xffffffffffa25a67', '0x0000000000a6e79e', '0x00000000000921d5', '0xffffffffff6e5db1', '0xffffffffffaf8aed', '0x000000000021cf03']` |
| **`soc_pipe_2_furnace_x2`** | `Swage-S5` Vision ISP + `Billet-F5` Audio Spectral -> **`Anvil-EN1`** (Gemma-4 Multimodal PLE) | `0x000000020000060e` | `160,895` | `0x000000e0000005a8` | `['0x000000000074fddc', '0x00000000009f8317', '0x000000000008ba49', '0xffffffffff74d108', '0xffffffffffb31b3b', '0x0000000000204fa8']` |
| **`soc_pipe_3_furnace_x4`** | `Hammer-V5` RV64GC Linux Host + Custom-0 Tensor -> **`Anvil-QN1`** (Qwen3 `<think>` Engine) | `0x000000030000060e` | `161,036` | `0x000000e0000005a8` | `['0x000000000092e155', '0x000000000092e155', '0x0000000000080959', '0xffffffffff7fd6ab', '0xffffffffffb93214', '0x00000000001dc09f']` |
| **`soc_pipe_4_anvil_edge`** | `Anvil-Edge` Zero-Host UART + Hardware BPE Tokenizer -> **`Anvil-Q4`** Closed-Loop Restore | `0x000000040000060e` | `160,824` | `0x000000e0000005a8` | `['0xffffffffffa25a67', '0x0000000000a6e79e', '0x00000000000921d5', '0xffffffffff6e5db1', '0xffffffffffaf8aed', '0x000000000021cf03']` (**100% Bit-Exact Baseline Restore**) |

## Vulcan Nine-Family Workshop Silicon Matrix

| Silicon Family | Workshop Metaphor | Domain & Series Repositories |
| :--- | :--- | :--- |
| **Anvil** *(Primary Focus)* | Heavy forge anvil bearing core compute loads | AI & Large-Model Compute — [**Anvil-Q** (`W4A16` AWQ, `BF16` FP & `256/512-MAC` HT LLM Engines)](https://github.com/aHappend/anvil-q) · [**Anvil-E** (Multimodal Embeddings)](https://github.com/aHappend/anvil-e) |
| **Hammer** | Forging hammer driving execution rhythm | General-Purpose RISC-V Processors — [**Hammer-V** (`RV32I` / `RV64IMAC` / `RV64GC` + `Sv39 MMU` Linux Boot)](https://github.com/aHappend/hammer-v) |
| **Furnace** | Industrial furnace integrating multiple stages | Heterogeneous Application Computers & SoCs — [**Furnace-X** (`Furnace-X1..X3` + `Furnace-SoC4` 8-Family Linux Computer)](https://github.com/aHappend/furnace-x) |
| **Billet** | Raw metal stock shaped and combined into systems | Digital Signal Processing — [**Billet-T** (FFT/Spectral)](https://github.com/aHappend/billet-t) · [**Billet-F** (FIR/SOS-IIR Filters)](https://github.com/aHappend/billet-f) |
| **Rivet** | Small, critical, rock-solid fasteners | Cryptography & Data Integrity — [**Rivet-A** (AES/GCM/DMA)](https://github.com/aHappend/rivet-a) · [**Rivet-H** (SHA-256/512/HMAC)](https://github.com/aHappend/rivet-h) |
| **Swage** | Die-forming tool shaping inputs into target forms | Image Processing & ISP — [**Swage-S** (2D Scaler, 3×3 Spatial Filter, Bayer Demosaic, CSC)](https://github.com/aHappend/swage-s) |
| **Bellows** | Expanding/contracting continuous airflow | Compression & Network Offload — [**Bellows-L** (LZ4/XXH32 DMA)](https://github.com/aHappend/bellows-l) · [**Bellows-N** (100G Line-Rate Network Offload)](https://github.com/aHappend/bellows-n) |
| **Crucible** | Vessel fusing diverse materials into form | Graphics Processing & Rendering — [**Crucible-G** (Triangle Setup, Tile Rasterizer, Z-Buffer & Texture Shader)](https://github.com/aHappend/crucible-g) |
| **SABLE** | Precision benchmark gauge for constraint solving | Hardware Formal Verification — **SABLE** (Clause-Parallel Hardware SAT Solver Engine, `135.57 MHz`) |

---
<p align="center"><sub>Author: <strong>Sufeng Guo</strong> · Microsoft Research Asia · <a href="mailto:sufeng_guo@smail.nju.edu.cn">sufeng_guo@smail.nju.edu.cn</a> · <a href="LICENSE">MIT License</a></sub></p>
