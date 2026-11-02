<div align="center">
  <picture>
    <source media="(prefers-color-scheme: dark)" srcset="brand/logo-dark.svg">
    <img src="brand/logo.svg" width="420" alt="Vulcan">
  </picture>
  <h1>Furnace-X · 异构多引擎 AI 与系统级芯片（SoC）系列</h1>
  <p><strong>100 MHz+ 可综合异构计算系统级芯片（SoC）· 通过 AXI4 交叉开关与 8GB 板载 DDR4 整合 Anvil AI、Billet DSP、Rivet 密码、Swage ISP 与 Bellows 压缩引擎</strong></p>
  <p>
    <img src="https://img.shields.io/badge/Platform-Intel_Arria_10_GX-0f766e?style=flat-square" alt="Platform">
    <img src="https://img.shields.io/badge/Quartus_17.1_STA-100_MHz%2B_Closed-0f766e?style=flat-square" alt="STA">
    <img src="https://img.shields.io/badge/PCIe_Gen3x8_HIL-100%25_Passed-1d4ed8?style=flat-square" alt="HIL">
    <img src="https://img.shields.io/badge/Author-Sufeng_Guo_(MSRA)-334155?style=flat-square" alt="Author">
    <img src="https://img.shields.io/badge/License-MIT-64748b?style=flat-square" alt="License">
  </p>
  <p>
    <a href="https://ahappend.github.io/vulcan/">项目主页</a> ·
    <a href="https://github.com/aHappend/vulcan-showcase">Vulcan 芯片总览</a> ·
    <a href="https://github.com/aHappend/anvil-q">Anvil-Q (大模型)</a> ·
    <a href="https://github.com/aHappend/anvil-e">Anvil-E (多模态向量)</a> ·
    <a href="https://github.com/aHappend/hammer-v">Hammer-V (RISC-V)</a> ·
    <a href="https://github.com/aHappend/furnace-x">Furnace-X (异构SoC)</a> ·
    <a href="https://github.com/aHappend/billet-t">Billet-T (频谱变换)</a> ·
    <a href="https://github.com/aHappend/billet-f">Billet-F (数字滤波)</a> ·
    <a href="https://github.com/aHappend/rivet-a">Rivet-A (认证加密)</a> ·
    <a href="https://github.com/aHappend/rivet-h">Rivet-H (杂凑认证)</a> ·
    <a href="https://github.com/aHappend/swage-s">Swage-S (视觉ISP)</a> ·
    <a href="https://github.com/aHappend/bellows-l">Bellows-L (LZ4压缩)</a> ·
    <a href="https://github.com/aHappend/bellows-n">Bellows-N (网络卸载)</a> ·
    <a href="https://github.com/aHappend/crucible-g">Crucible-G (图形渲染)</a> ·
    <a href="README.md"><strong>English</strong></a>
  </p>
</div>

---

**Furnace-X** 是 Vulcan **Furnace（工业炉）** 异构 SoC 家族的核心系列，将 **Hammer**（`RV64GC` Linux 处理器）、**Anvil**（大模型）、**Billet**（信号处理）、**Rivet**（安全密码）、**Swage**（视觉 ISP）、**Bellows**（流式解压/网络）、**Crucible**（图形渲染）与 **SABLE**（形式化求解）整合为共享板载 8GB DDR4、AXI4 QoS 片上网络与 Linux CLI 应用栈的完整异构计算机系统。

## 全系芯片 `100 MHz+` 硬件签核与双轨学术报告总览

| 代际 | 芯片代号 | 架构与数值规格 | Quartus 17.1 STA (`10.0 ns`) | Intel Arria 10 GX 资源占用 | PCIe Gen3x8 板级 HIL | 验证证据与工程目录 |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| **Gen-1** | [**FURNACE-X1**](chips/furnace_x1/) | 加密压缩权重流 AI 推理 SoC · Bellows-L 硬件实时解压 + Rivet-A AES-GCM 解密 + Anvil-Q 张量引擎 AXI4 级联系统 | `113.06 MHz` (`WNS +1.155 ns`) | `14,033 ALMs · 38 DSPs · 22 M20K` | **通过 (3/3)** | [`chips/furnace_x1/evidence/`](chips/furnace_x1/evidence/) |
| **Gen-2** | [**FURNACE-X2**](chips/furnace_x2/) | 多模态端侧感知与推理 SoC · Swage-S 视觉 ISP + Billet-T 音频频谱前端 + Anvil-E3/Q4 多模态大模型统一加速系统 | `111.78 MHz` (`WNS +1.054 ns`) | `18,621 ALMs · 53 DSPs · 64 M20K` | **通过 (3/3)** | [`chips/furnace_x2/evidence/`](chips/furnace_x2/evidence/) |
| **Gen-3** | [**FURNACE-X3**](chips/furnace_x3/) | 七大家族全集成异构计算 SoC（`Hammer-V2 RV64IMAC` 主控 + 6 大领域加速引擎）· 8GB DDR4 EMIF DMA 与 QoS NoC | `114.69 MHz` (`WNS +1.281 ns`) | `47,701 ALMs (11%) · 121 DSPs (8%) · 219 M20K` | **通过 (3/3)** | [`chips/furnace_x3/evidence/`](chips/furnace_x3/evidence/) |
| **Gen-4** | [**FURNACE-X4 (`Furnace-SoC4`)**](chips/furnace_x4/) | **八大家族全融合 Linux 应用计算机 SoC**（`Hammer-V4 RV64GC + Sv39 MMU` 引导 OpenSBI + Linux 6.6 + BusyBox，提供 `anvil-chat`、`swage-isp`、`rivet-vault`、`billet-dsp`、`bellows-pack`、`crucible-render`、`sable-verify` CLI 应用栈） | `111.30 MHz` (`WNS +1.015 ns`) | `47,300 ALMs (11%) · 69 DSPs (5%) · 223 M20K` | **通过 (3/3)** | [`chips/furnace_x4/`](chips/furnace_x4/) |

## Vulcan 九大工坊芯片家族矩阵

| 芯片家族 | 工坊意象 | 领域定位与开源仓库 |
| :--- | :--- | :--- |
| **Anvil（铁砧）** *(当前核心重心)* | 承担核心计算任务的工坊重器 | AI 与大模型计算系列 — [**Anvil-Q**（`W4A16` AWQ、`BF16` 全浮点与 `256/512-MAC` 高吞吐大模型推理）](https://github.com/aHappend/anvil-q) · [**Anvil-E**（多模态向量表征）](https://github.com/aHappend/anvil-e) |
| **Hammer（锻锤）** | 驱动全工坊执行节拍的主力锻锤 | 通用与特权级 RISC-V 处理器系列 — [**Hammer-V**（`RV32I` / `RV64IMAC` / `RV64GC` + `Sv39 MMU` Linux 引导）](https://github.com/aHappend/hammer-v) |
| **Furnace（工业炉）** | 整合多计算环节的系统级设备 | 大型异构计算机与 SoC 系列 — [**Furnace-X**（`Furnace-X1..X3` + `Furnace-SoC4` 八大家族全融合 Linux 计算机）](https://github.com/aHappend/furnace-x) |
| **Billet（金属坯料）** | 基础材料经加工组合构建计算系统 | 数字信号处理系列 — [**Billet-T**（FFT/IFFT 与功率谱）](https://github.com/aHappend/billet-t) · [**Billet-F**（FIR 与级联 SOS-IIR 滤波）](https://github.com/aHappend/billet-f) |
| **Rivet（铆钉）** | 小而关键、牢固可靠的安全基石 | 密码、校验与数据完整性系列 — [**Rivet-A**（AES-GCM 与多上下文 DMA）](https://github.com/aHappend/rivet-a) · [**Rivet-H**（SHA-256/512 与 HMAC）](https://github.com/aHappend/rivet-h) |
| **Swage（型锻模）** | 将输入加工成形的精密模具 | 图像处理与 ISP 系列 — [**Swage-S**（双线性图像缩放、3×3 空间卷积滤波、Bayer 去马赛克、色彩空间转换）](https://github.com/aHappend/swage-s) |
| **Bellows（风箱）** | 收缩展开、连续高吞吐的数据流 | 压缩解压与高速网络卸载系列 — [**Bellows-L**（流式 LZ4 解压/哈希压缩、XXH32 DMA）](https://github.com/aHappend/bellows-l) · [**Bellows-N**（100G 线速网络卸载）](https://github.com/aHappend/bellows-n) |
| **Crucible（坩埚）** | 多种材料融合成形的渲染容器 | 图形处理与渲染系列 — [**Crucible-G**（三角形建立、分块光栅化、Z-Buffer 与纹理光照着色）](https://github.com/aHappend/crucible-g) |
| **SABLE** | 精密定标与形式化约束求解器 | 硬件形式化验证与求解系列 — **SABLE**（子句并行硬件 SAT 求解器引擎，`135.57 MHz`） |

---
<p align="center"><sub>作者：<strong>Sufeng Guo</strong> · 微软亚洲研究院 (Microsoft Research Asia) · <a href="mailto:sufeng_guo@smail.nju.edu.cn">sufeng_guo@smail.nju.edu.cn</a> · <a href="LICENSE">MIT License</a></sub></p>
