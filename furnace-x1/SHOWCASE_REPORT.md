# Anvil-E1 · Hybrid-Attention Text Embedding Accelerator — Product Whitepaper & Benchmark Evaluation Report

[English Whitepaper PDF (`SHOWCASE_REPORT.pdf`)](SHOWCASE_REPORT.pdf) · [Chinese Edition (`SHOWCASE_REPORT.zh-CN.md`)](SHOWCASE_REPORT.zh-CN.md) · [Chinese Whitepaper PDF (`SHOWCASE_REPORT.zh-CN.pdf`)](SHOWCASE_REPORT.zh-CN.pdf) · [Developer Engineering Report (`REPORT.pdf`)](REPORT.pdf)

## 1. Executive Key Performance Indicators (KPIs)

| Dimension | Measured Result | Engineering Significance |
| :--- | :--- | :--- |
| **Output Fidelity** | **100% Bit-Exact Match** | Zero output mismatches across all verification suites |
| **Numerical Precision** | **0.999999995** | Cosine similarity vs. official FP32 software baseline |
| **100 MHz+ STA & Physical FPGA HIL** | **Fmax 117.15 MHz** | Intel Arria 10 GX PCIe Gen3x8 HIL with **0 bit errors**, setup slack **+1.464 ns** at `100.0 MHz` |
| **Silicon Utilization & Scaling** | **5.88% ALMs / 6.59% DSPs** | **>94.1%** fabric headroom; 8 GB on-board DDR4 scales up to **7B–8B AWQ LLMs** |

## 2. Official-Weight Multimodal Numerical Benchmark

- **Worst-Case Maximum Absolute Error**: `1.204e-05` (**166x tighter** than the `2.000e-03` specification tolerance bound)
- **Mean Absolute Error (MAE)**: `6.884e-06`
- **Minimum Cosine Similarity vs. Official FP32**: `0.999999995`

## 3. Intel Arria 10 GX Utilization & 7B–8B LLM Scaling Roadmap

| Hardware Resource | Single-Core Utilization | Arria 10 GX Capacity | Utilization | Multi-Core & LLM Scaling Target |
| :--- | :--- | :--- | :--- | :--- |
| **Adaptive Logic Modules (ALMs)** | `25,135` | `427,200` | `5.88%` | Scales to 8–16x parallel compute engines |
| **On-Chip Memory (M20K BRAM)** | `192` | `2,713` | `7.08%` | Deep on-chip KV cache & ping-pong weight buffers |
| **Precision DSP Blocks (18x19)** | `100` | `1,518` | `6.59%` | 1,024+ DSP MAC array for >100x throughput |
| **Clock Frequency (Fmax)** | **`117.15 MHz`** (`WNS +1.464 ns` @ `100.0 MHz`) | `20nm Arria 10` | `0 Failing Paths` | Surpassed **100 MHz** baseline; scales to **150–250 MHz** |
| **On-Board 8 GB DDR4 Capacity** | `0.5B` (`0.35 GB`) | `8.0 GB DDR4` | `4.4%` | **0.5B $\to$ 1.5B (`0.95 GB`) $\to$ 3B (`1.8 GB`) $\to$ 7B–8B (`3.9 GB` W4 weights + `4 GB` KV Cache)** |

## Whitepaper Page Preview

### Page 1
![Whitepaper Page 1](showcase_figures/page-1.png)

### Page 2
![Whitepaper Page 2](showcase_figures/page-2.png)

### Page 3
![Whitepaper Page 3](showcase_figures/page-3.png)
