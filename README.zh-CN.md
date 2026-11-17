# Furnace-X — 异构计算与 SoC 集成 RTL

[English](README.md) · [简体中文](README.zh-CN.md) · [Repository guide / 文件导航](REPOSITORY_GUIDE.md)

文档更新：2026-11-17。本页对应仓库快照，不是实时作业看板。

## 概览

**Furnace-X**：异构计算与 SoC 集成 RTL。下方保留芯片技术与报告入口；具体实现范围以所链接目录、规范、测试和结果原件为准。

芯片项目公开；Vulcan 本身保持私有、闭源。今后公开发布仅限芯片技术与公开复现资料，不得包含 Vulcan 内部架构或运作资料。本次更新仅整理文档，并非对全部历史材料进行全面披露审查，也不声称既有仓库树已完成此类清查。

## 范围与证据

按实际目录核对[公开结果索引](REPOSITORY_GUIDE.md)。功能仿真、综合、独立 IP／虚拟引脚时序、板卡桥接探测、工作负载数值读回和系统软件执行是不同层级；一种通过不能替代另一种。现有历史结果保留，不因本次文档更新自动升级或作废。

时钟、资源与性能指标必须读取对应目录的原始记录和适用条件；同名副本不合并为一个数值。此处不宣称全系完成上板、完整模型推理、Linux 实机启动或功耗／能效测量。

## 文件导航

[文件与证据导航](REPOSITORY_GUIDE.md)列出真实存在的源码、约束、测试、报告及结果路径。连字符、下划线和 `chips/` 目录可能是不同发布副本，不自动指定某份为权威，也不移动或删除原件。

公开复现从对应芯片的规范、测试说明和脚本开始；所需工具、输入和板卡条件以该目录为准。文档更新没有重新执行芯片实验。

## 已有芯片目录

| 芯片／变体 | 现存根路径 | 公开交付物 |
| --- | --- | --- |
| FURNACE-X1 | [`furnace-x1/`](furnace-x1/) · [`furnace_x1/`](furnace_x1/) | [REPORT.md](furnace-x1/REPORT.md) · [REPORT.pdf](furnace-x1/REPORT.pdf) · [SHOWCASE_REPORT.pdf](furnace-x1/SHOWCASE_REPORT.pdf) · [SHOWCASE_REPORT.zh-CN.pdf](furnace-x1/SHOWCASE_REPORT.zh-CN.pdf) |
| FURNACE-X2 | [`furnace-x2/`](furnace-x2/) · [`furnace_x2/`](furnace_x2/) | [REPORT.md](furnace-x2/REPORT.md) · [REPORT.pdf](furnace-x2/REPORT.pdf) · [SHOWCASE_REPORT.pdf](furnace-x2/SHOWCASE_REPORT.pdf) · [SHOWCASE_REPORT.zh-CN.pdf](furnace-x2/SHOWCASE_REPORT.zh-CN.pdf) |
| FURNACE-X3 | [`furnace-x3/`](furnace-x3/) · [`furnace_x3/`](furnace_x3/) | [REPORT.md](furnace-x3/REPORT.md) · [REPORT.pdf](furnace-x3/REPORT.pdf) · [SHOWCASE_REPORT.pdf](furnace-x3/SHOWCASE_REPORT.pdf) · [SHOWCASE_REPORT.zh-CN.pdf](furnace-x3/SHOWCASE_REPORT.zh-CN.pdf) |
| FURNACE-X4 | [`furnace-x4/`](furnace-x4/) · [`furnace_x4/`](furnace_x4/) | [REPORT.md](furnace-x4/REPORT.md) · [REPORT.pdf](furnace-x4/REPORT.pdf) · [SHOWCASE_REPORT.pdf](furnace-x4/SHOWCASE_REPORT.pdf) · [SHOWCASE_REPORT.zh-CN.pdf](furnace-x4/SHOWCASE_REPORT.zh-CN.pdf) |

## 架构目录与技术报告

| 代际 | 芯片 | 架构／研究范围 | 记录导航 | 报告 |
| --- | --- | --- | --- | --- |
| **Gen-1** | [**FURNACE-X1**](chips/furnace_x1/) | 加密压缩权重流 AI 推理 SoC · Bellows-L 硬件实时解压 + Rivet-A AES-GCM 解密 + Anvil-Q 张量引擎 AXI4 级联系统 | [Exact-directory records](REPOSITORY_GUIDE.md) | [`chips/furnace_x1/evidence/`](chips/furnace_x1/evidence/) |
| **Gen-2** | [**FURNACE-X2**](chips/furnace_x2/) | 多模态端侧感知与推理 SoC · Swage-S 视觉 ISP + Billet-T 音频频谱前端 + Anvil-E3/Q4 多模态大模型统一加速系统 | [Exact-directory records](REPOSITORY_GUIDE.md) | [`chips/furnace_x2/evidence/`](chips/furnace_x2/evidence/) |
| **Gen-3** | [**FURNACE-X3**](chips/furnace_x3/) | 七大家族全集成异构计算 SoC（`Hammer-V2 RV64IMAC` 主控 + 6 大领域加速引擎）· 8GB DDR4 EMIF DMA 与 QoS NoC | [Exact-directory records](REPOSITORY_GUIDE.md) | [`chips/furnace_x3/evidence/`](chips/furnace_x3/evidence/) |
| **Gen-4** | [**FURNACE-X4 (`Furnace-SoC4`)**](chips/furnace_x4/) | **异构 Linux 应用计算机 SoC 研究目标**（`Hammer-V4 RV64GC + Sv39 MMU` 面向 OpenSBI + Linux 6.6 + BusyBox 及 `anvil-chat`、`swage-isp`、`rivet-vault`、`billet-dsp`、`bellows-pack`、`crucible-render`、`sable-verify` CLI 应用栈） | [Exact-directory records](REPOSITORY_GUIDE.md) | [`chips/furnace_x4/`](chips/furnace_x4/) |

## 关联项目

- AI / embeddings: [Anvil-Q](https://github.com/aHappend/anvil-q), [Anvil-E](https://github.com/aHappend/anvil-e), [Anvil-QN](https://github.com/aHappend/anvil-qn), [Anvil-EN](https://github.com/aHappend/anvil-en), [Anvil-D](https://github.com/aHappend/anvil-d).
- Systems: [Hammer-V](https://github.com/aHappend/hammer-v), [Furnace-X](https://github.com/aHappend/furnace-x).
- DSP / vision: [Billet-F](https://github.com/aHappend/billet-f), [Billet-T](https://github.com/aHappend/billet-t), [Swage-S](https://github.com/aHappend/swage-s).
- Data / security / graphics: [Bellows-L](https://github.com/aHappend/bellows-l), [Bellows-N](https://github.com/aHappend/bellows-n), [Rivet-A](https://github.com/aHappend/rivet-a), [Rivet-H](https://github.com/aHappend/rivet-h), [Crucible-G](https://github.com/aHappend/crucible-g), [SABLE](https://github.com/aHappend/sable).
- [Public fleet catalog](https://github.com/aHappend/vulcan-showcase). Related independent research: [ACE-2](https://github.com/aHappend/ace-2), [ACE-3](https://github.com/aHappend/ace-3); these retain their own provenance and acceptance boundaries.
- DSpark 是研究方向，不代表本仓库已交付对应芯片；此处不虚构实现或仓库链接。
