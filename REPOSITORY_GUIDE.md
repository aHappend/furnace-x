# Furnace-X — Repository guide / 文件导航

[English](README.md) · [简体中文](README.zh-CN.md)

Documentation inventory checked on 2026-11-17, against repository base `4f63dd48a59fac1f65b6c908c9b2c1f7c61b5f16`.

## Reading the inventory / 阅读方法

This is a path-level index, not a new experiment or a recertification. Each measurement belongs to the exact linked record and directory. Different copies of a chip can contain different source revisions and results. A recorded pass does not imply that another copy, model size, software stack or board image passed.

本页按实际路径列出交付物，不代表新实验或重新签核。同名芯片的多份目录可能有不同源码和结果；一份记录的通过不外推到其他副本、模型规模、软件栈或板卡镜像。

## Source, tests and reports / 源码、测试与报告

| Existing directory | Source / constraints | Public tests / technical documents | Reports |
| --- | --- | --- | --- |
| [`chips/furnace_x1/`](chips/furnace_x1/) | [`chips/furnace_x1/rtl/`](chips/furnace_x1/rtl/) | [`chips/furnace_x1/tests/`](chips/furnace_x1/tests/) · [`chips/furnace_x1/design/`](chips/furnace_x1/design/) | [`chips/furnace_x1/REPORT.md`](chips/furnace_x1/REPORT.md) · [`chips/furnace_x1/REPORT.pdf`](chips/furnace_x1/REPORT.pdf) · [`chips/furnace_x1/SHOWCASE_REPORT.pdf`](chips/furnace_x1/SHOWCASE_REPORT.pdf) · [`chips/furnace_x1/SHOWCASE_REPORT.zh-CN.pdf`](chips/furnace_x1/SHOWCASE_REPORT.zh-CN.pdf) |
| [`chips/furnace_x2/`](chips/furnace_x2/) | [`chips/furnace_x2/rtl/`](chips/furnace_x2/rtl/) | [`chips/furnace_x2/tests/`](chips/furnace_x2/tests/) · [`chips/furnace_x2/design/`](chips/furnace_x2/design/) | [`chips/furnace_x2/REPORT.md`](chips/furnace_x2/REPORT.md) · [`chips/furnace_x2/REPORT.pdf`](chips/furnace_x2/REPORT.pdf) · [`chips/furnace_x2/SHOWCASE_REPORT.pdf`](chips/furnace_x2/SHOWCASE_REPORT.pdf) · [`chips/furnace_x2/SHOWCASE_REPORT.zh-CN.pdf`](chips/furnace_x2/SHOWCASE_REPORT.zh-CN.pdf) |
| [`chips/furnace_x3/`](chips/furnace_x3/) | [`chips/furnace_x3/rtl/`](chips/furnace_x3/rtl/) | [`chips/furnace_x3/tests/`](chips/furnace_x3/tests/) · [`chips/furnace_x3/design/`](chips/furnace_x3/design/) | [`chips/furnace_x3/REPORT.md`](chips/furnace_x3/REPORT.md) · [`chips/furnace_x3/REPORT.pdf`](chips/furnace_x3/REPORT.pdf) · [`chips/furnace_x3/SHOWCASE_REPORT.pdf`](chips/furnace_x3/SHOWCASE_REPORT.pdf) · [`chips/furnace_x3/SHOWCASE_REPORT.zh-CN.pdf`](chips/furnace_x3/SHOWCASE_REPORT.zh-CN.pdf) |
| [`chips/furnace_x4/`](chips/furnace_x4/) | [`chips/furnace_x4/rtl/`](chips/furnace_x4/rtl/) | [`chips/furnace_x4/tests/`](chips/furnace_x4/tests/) · [`chips/furnace_x4/design/`](chips/furnace_x4/design/) | [`chips/furnace_x4/REPORT.md`](chips/furnace_x4/REPORT.md) · [`chips/furnace_x4/REPORT.pdf`](chips/furnace_x4/REPORT.pdf) · [`chips/furnace_x4/SHOWCASE_REPORT.pdf`](chips/furnace_x4/SHOWCASE_REPORT.pdf) · [`chips/furnace_x4/SHOWCASE_REPORT.zh-CN.pdf`](chips/furnace_x4/SHOWCASE_REPORT.zh-CN.pdf) |
| [`furnace-x1/`](furnace-x1/) | [`furnace-x1/rtl/`](furnace-x1/rtl/) | [`furnace-x1/tests/`](furnace-x1/tests/) · [`furnace-x1/design/`](furnace-x1/design/) | [`furnace-x1/REPORT.md`](furnace-x1/REPORT.md) · [`furnace-x1/REPORT.pdf`](furnace-x1/REPORT.pdf) · [`furnace-x1/SHOWCASE_REPORT.pdf`](furnace-x1/SHOWCASE_REPORT.pdf) · [`furnace-x1/SHOWCASE_REPORT.zh-CN.pdf`](furnace-x1/SHOWCASE_REPORT.zh-CN.pdf) |
| [`furnace-x2/`](furnace-x2/) | [`furnace-x2/rtl/`](furnace-x2/rtl/) | [`furnace-x2/tests/`](furnace-x2/tests/) · [`furnace-x2/design/`](furnace-x2/design/) | [`furnace-x2/REPORT.md`](furnace-x2/REPORT.md) · [`furnace-x2/REPORT.pdf`](furnace-x2/REPORT.pdf) · [`furnace-x2/SHOWCASE_REPORT.pdf`](furnace-x2/SHOWCASE_REPORT.pdf) · [`furnace-x2/SHOWCASE_REPORT.zh-CN.pdf`](furnace-x2/SHOWCASE_REPORT.zh-CN.pdf) |
| [`furnace-x3/`](furnace-x3/) | [`furnace-x3/rtl/`](furnace-x3/rtl/) | [`furnace-x3/tests/`](furnace-x3/tests/) · [`furnace-x3/design/`](furnace-x3/design/) | [`furnace-x3/REPORT.md`](furnace-x3/REPORT.md) · [`furnace-x3/REPORT.pdf`](furnace-x3/REPORT.pdf) · [`furnace-x3/SHOWCASE_REPORT.pdf`](furnace-x3/SHOWCASE_REPORT.pdf) · [`furnace-x3/SHOWCASE_REPORT.zh-CN.pdf`](furnace-x3/SHOWCASE_REPORT.zh-CN.pdf) |
| [`furnace-x4/`](furnace-x4/) | [`furnace-x4/rtl/`](furnace-x4/rtl/) | [`furnace-x4/tests/`](furnace-x4/tests/) · [`furnace-x4/design/`](furnace-x4/design/) | [`furnace-x4/REPORT.md`](furnace-x4/REPORT.md) · [`furnace-x4/REPORT.pdf`](furnace-x4/REPORT.pdf) · [`furnace-x4/SHOWCASE_REPORT.pdf`](furnace-x4/SHOWCASE_REPORT.pdf) · [`furnace-x4/SHOWCASE_REPORT.zh-CN.pdf`](furnace-x4/SHOWCASE_REPORT.zh-CN.pdf) |
| [`furnace_x1/`](furnace_x1/) | [`furnace_x1/rtl/`](furnace_x1/rtl/) | [`furnace_x1/tests/`](furnace_x1/tests/) · [`furnace_x1/design/`](furnace_x1/design/) | [`furnace_x1/REPORT.md`](furnace_x1/REPORT.md) · [`furnace_x1/REPORT.pdf`](furnace_x1/REPORT.pdf) · [`furnace_x1/SHOWCASE_REPORT.pdf`](furnace_x1/SHOWCASE_REPORT.pdf) · [`furnace_x1/SHOWCASE_REPORT.zh-CN.pdf`](furnace_x1/SHOWCASE_REPORT.zh-CN.pdf) |
| [`furnace_x2/`](furnace_x2/) | [`furnace_x2/rtl/`](furnace_x2/rtl/) | [`furnace_x2/tests/`](furnace_x2/tests/) · [`furnace_x2/design/`](furnace_x2/design/) | [`furnace_x2/REPORT.md`](furnace_x2/REPORT.md) · [`furnace_x2/REPORT.pdf`](furnace_x2/REPORT.pdf) · [`furnace_x2/SHOWCASE_REPORT.pdf`](furnace_x2/SHOWCASE_REPORT.pdf) · [`furnace_x2/SHOWCASE_REPORT.zh-CN.pdf`](furnace_x2/SHOWCASE_REPORT.zh-CN.pdf) |
| [`furnace_x3/`](furnace_x3/) | [`furnace_x3/rtl/`](furnace_x3/rtl/) | [`furnace_x3/tests/`](furnace_x3/tests/) · [`furnace_x3/design/`](furnace_x3/design/) | [`furnace_x3/REPORT.md`](furnace_x3/REPORT.md) · [`furnace_x3/REPORT.pdf`](furnace_x3/REPORT.pdf) · [`furnace_x3/SHOWCASE_REPORT.pdf`](furnace_x3/SHOWCASE_REPORT.pdf) · [`furnace_x3/SHOWCASE_REPORT.zh-CN.pdf`](furnace_x3/SHOWCASE_REPORT.zh-CN.pdf) |
| [`furnace_x4/`](furnace_x4/) | [`furnace_x4/rtl/`](furnace_x4/rtl/) | [`furnace_x4/tests/`](furnace_x4/tests/) · [`furnace_x4/design/`](furnace_x4/design/) | [`furnace_x4/REPORT.md`](furnace_x4/REPORT.md) · [`furnace_x4/REPORT.pdf`](furnace_x4/REPORT.pdf) · [`furnace_x4/SHOWCASE_REPORT.pdf`](furnace_x4/SHOWCASE_REPORT.pdf) · [`furnace_x4/SHOWCASE_REPORT.zh-CN.pdf`](furnace_x4/SHOWCASE_REPORT.zh-CN.pdf) |

## Public result records / 公开结果记录

Status and numbers below are transcribed only from the linked record. Functional simulation, generic synthesis, standalone/virtual-pin timing, bridge connectivity, workload readback and system-software execution are separate scopes. Missing entries mean that this index found no matching public record at that path, not that an experiment failed or never occurred.

下表状态与数值只来自对应文件。功能仿真、通用综合、独立 IP／虚拟引脚时序、桥接连通性、工作负载读回和系统软件执行分别解释；未列出不等于判定失败或从未做过。

| Exact directory | Record | Recorded result and scope |
| --- | --- | --- |
| `chips/furnace_x1` | [`chips/furnace_x1/evidence/verification-receipts.json`](chips/furnace_x1/evidence/verification-receipts.json) | Recorded artifact; inspect its applicability, source binding and scope. |
| `chips/furnace_x1` | [`chips/furnace_x1/evidence/rtl-timing-lint.json`](chips/furnace_x1/evidence/rtl-timing-lint.json) | recorded status: `passed` |
| `chips/furnace_x1` | [`chips/furnace_x1/evidence/quartus-sta.json`](chips/furnace_x1/evidence/quartus-sta.json) | recorded status: `passed`; Fmax MHz: `117.15`; setup slack ns: `1.464`; hold slack ns: `0.038` |
| `chips/furnace_x1` | [`chips/furnace_x1/evidence/ppa-resource-summary.json`](chips/furnace_x1/evidence/ppa-resource-summary.json) | Recorded artifact; inspect its applicability, source binding and scope. |
| `chips/furnace_x1` | [`chips/furnace_x1/evidence/board-hil.json`](chips/furnace_x1/evidence/board-hil.json) | recorded status: `passed`; scope: BAR0/reg57 bridge-connectivity probe only; not per-chip workload execution |
| `chips/furnace_x2` | [`chips/furnace_x2/evidence/verification-receipts.json`](chips/furnace_x2/evidence/verification-receipts.json) | Recorded artifact; inspect its applicability, source binding and scope. |
| `chips/furnace_x2` | [`chips/furnace_x2/evidence/rtl-timing-lint.json`](chips/furnace_x2/evidence/rtl-timing-lint.json) | recorded status: `passed` |
| `chips/furnace_x2` | [`chips/furnace_x2/evidence/quartus-sta.json`](chips/furnace_x2/evidence/quartus-sta.json) | recorded status: `passed`; Fmax MHz: `109.24`; setup slack ns: `0.846`; hold slack ns: `0.037` |
| `chips/furnace_x2` | [`chips/furnace_x2/evidence/ppa-resource-summary.json`](chips/furnace_x2/evidence/ppa-resource-summary.json) | Recorded artifact; inspect its applicability, source binding and scope. |
| `chips/furnace_x2` | [`chips/furnace_x2/evidence/board-hil.json`](chips/furnace_x2/evidence/board-hil.json) | recorded status: `passed`; scope: BAR0/reg57 bridge-connectivity probe only; not per-chip workload execution |
| `chips/furnace_x3` | [`chips/furnace_x3/evidence/verification-receipts.json`](chips/furnace_x3/evidence/verification-receipts.json) | Recorded artifact; inspect its applicability, source binding and scope. |
| `chips/furnace_x3` | [`chips/furnace_x3/evidence/rtl-timing-lint.json`](chips/furnace_x3/evidence/rtl-timing-lint.json) | recorded status: `passed` |
| `chips/furnace_x3` | [`chips/furnace_x3/evidence/quartus-sta.json`](chips/furnace_x3/evidence/quartus-sta.json) | recorded status: `passed`; Fmax MHz: `231.05`; setup slack ns: `5.672`; hold slack ns: `-0.203` |
| `chips/furnace_x3` | [`chips/furnace_x3/evidence/ppa-resource-summary.json`](chips/furnace_x3/evidence/ppa-resource-summary.json) | Recorded artifact; inspect its applicability, source binding and scope. |
| `chips/furnace_x3` | [`chips/furnace_x3/evidence/board-hil.json`](chips/furnace_x3/evidence/board-hil.json) | recorded status: `passed`; scope: BAR0/reg57 bridge-connectivity probe only; not per-chip workload execution |
| `chips/furnace_x4` | [`chips/furnace_x4/evidence/verification-receipts.json`](chips/furnace_x4/evidence/verification-receipts.json) | Recorded artifact; inspect its applicability, source binding and scope. |
| `chips/furnace_x4` | [`chips/furnace_x4/evidence/rtl-timing-lint.json`](chips/furnace_x4/evidence/rtl-timing-lint.json) | recorded status: `passed` |
| `chips/furnace_x4` | [`chips/furnace_x4/evidence/quartus-sta.json`](chips/furnace_x4/evidence/quartus-sta.json) | recorded status: `passed`; Fmax MHz: `111.3` |
| `chips/furnace_x4` | [`chips/furnace_x4/evidence/ppa-resource-summary.json`](chips/furnace_x4/evidence/ppa-resource-summary.json) | Recorded artifact; inspect its applicability, source binding and scope. |
| `chips/furnace_x4` | [`chips/furnace_x4/evidence/board-hil.json`](chips/furnace_x4/evidence/board-hil.json) | recorded status: `passed`; scope: BAR0/reg57 bridge-connectivity probe only; not per-chip workload execution |
| `chips/furnace_x4` | [`chips/furnace_x4/evidence/soc-board-coexecution.json`](chips/furnace_x4/evidence/soc-board-coexecution.json) | recorded status: `passed`; scope: recorded multi-profile/co-execution telemetry; interpret with the associated image, workload and output bindings |
| `furnace-x1` | [`furnace-x1/evidence/verification-receipts.json`](furnace-x1/evidence/verification-receipts.json) | Recorded artifact; inspect its applicability, source binding and scope. |
| `furnace-x1` | [`furnace-x1/evidence/rtl-timing-lint.json`](furnace-x1/evidence/rtl-timing-lint.json) | recorded status: `passed` |
| `furnace-x1` | [`furnace-x1/evidence/quartus-sta.json`](furnace-x1/evidence/quartus-sta.json) | recorded status: `passed`; Fmax MHz: `117.15`; setup slack ns: `1.464`; hold slack ns: `0.038` |
| `furnace-x1` | [`furnace-x1/evidence/ppa-resource-summary.json`](furnace-x1/evidence/ppa-resource-summary.json) | Recorded artifact; inspect its applicability, source binding and scope. |
| `furnace-x1` | [`furnace-x1/evidence/board-hil.json`](furnace-x1/evidence/board-hil.json) | recorded status: `passed`; scope: BAR0/reg57 bridge-connectivity probe only; not per-chip workload execution |
| `furnace-x2` | [`furnace-x2/evidence/verification-receipts.json`](furnace-x2/evidence/verification-receipts.json) | Recorded artifact; inspect its applicability, source binding and scope. |
| `furnace-x2` | [`furnace-x2/evidence/rtl-timing-lint.json`](furnace-x2/evidence/rtl-timing-lint.json) | recorded status: `passed` |
| `furnace-x2` | [`furnace-x2/evidence/quartus-sta.json`](furnace-x2/evidence/quartus-sta.json) | recorded status: `passed`; Fmax MHz: `109.24`; setup slack ns: `0.846`; hold slack ns: `0.037` |
| `furnace-x2` | [`furnace-x2/evidence/ppa-resource-summary.json`](furnace-x2/evidence/ppa-resource-summary.json) | Recorded artifact; inspect its applicability, source binding and scope. |
| `furnace-x2` | [`furnace-x2/evidence/board-hil.json`](furnace-x2/evidence/board-hil.json) | recorded status: `passed`; scope: BAR0/reg57 bridge-connectivity probe only; not per-chip workload execution |
| `furnace-x3` | [`furnace-x3/evidence/verification-receipts.json`](furnace-x3/evidence/verification-receipts.json) | Recorded artifact; inspect its applicability, source binding and scope. |
| `furnace-x3` | [`furnace-x3/evidence/rtl-timing-lint.json`](furnace-x3/evidence/rtl-timing-lint.json) | recorded status: `passed` |
| `furnace-x3` | [`furnace-x3/evidence/quartus-sta.json`](furnace-x3/evidence/quartus-sta.json) | recorded status: `passed`; Fmax MHz: `231.05`; setup slack ns: `5.672`; hold slack ns: `-0.203` |
| `furnace-x3` | [`furnace-x3/evidence/ppa-resource-summary.json`](furnace-x3/evidence/ppa-resource-summary.json) | Recorded artifact; inspect its applicability, source binding and scope. |
| `furnace-x3` | [`furnace-x3/evidence/board-hil.json`](furnace-x3/evidence/board-hil.json) | recorded status: `passed`; scope: BAR0/reg57 bridge-connectivity probe only; not per-chip workload execution |
| `furnace-x4` | [`furnace-x4/evidence/verification-receipts.json`](furnace-x4/evidence/verification-receipts.json) | Recorded artifact; inspect its applicability, source binding and scope. |
| `furnace-x4` | [`furnace-x4/evidence/rtl-timing-lint.json`](furnace-x4/evidence/rtl-timing-lint.json) | recorded status: `passed` |
| `furnace-x4` | [`furnace-x4/evidence/quartus-sta.json`](furnace-x4/evidence/quartus-sta.json) | recorded status: `passed`; Fmax MHz: `111.3` |
| `furnace-x4` | [`furnace-x4/evidence/ppa-resource-summary.json`](furnace-x4/evidence/ppa-resource-summary.json) | Recorded artifact; inspect its applicability, source binding and scope. |
| `furnace-x4` | [`furnace-x4/evidence/board-hil.json`](furnace-x4/evidence/board-hil.json) | recorded status: `passed`; scope: BAR0/reg57 bridge-connectivity probe only; not per-chip workload execution |
| `furnace-x4` | [`furnace-x4/evidence/soc-board-coexecution.json`](furnace-x4/evidence/soc-board-coexecution.json) | recorded status: `passed`; scope: recorded multi-profile/co-execution telemetry; interpret with the associated image, workload and output bindings |
| `furnace_x1` | [`furnace_x1/evidence/verification-receipts.json`](furnace_x1/evidence/verification-receipts.json) | Recorded artifact; inspect its applicability, source binding and scope. |
| `furnace_x1` | [`furnace_x1/evidence/rtl-timing-lint.json`](furnace_x1/evidence/rtl-timing-lint.json) | recorded status: `passed` |
| `furnace_x1` | [`furnace_x1/evidence/quartus-sta.json`](furnace_x1/evidence/quartus-sta.json) | recorded status: `passed`; Fmax MHz: `117.15`; setup slack ns: `1.464`; hold slack ns: `0.038` |
| `furnace_x1` | [`furnace_x1/evidence/ppa-resource-summary.json`](furnace_x1/evidence/ppa-resource-summary.json) | Recorded artifact; inspect its applicability, source binding and scope. |
| `furnace_x1` | [`furnace_x1/evidence/board-hil.json`](furnace_x1/evidence/board-hil.json) | recorded status: `passed`; scope: BAR0/reg57 bridge-connectivity probe only; not per-chip workload execution |
| `furnace_x2` | [`furnace_x2/evidence/verification-receipts.json`](furnace_x2/evidence/verification-receipts.json) | Recorded artifact; inspect its applicability, source binding and scope. |
| `furnace_x2` | [`furnace_x2/evidence/rtl-timing-lint.json`](furnace_x2/evidence/rtl-timing-lint.json) | recorded status: `passed` |
| `furnace_x2` | [`furnace_x2/evidence/quartus-sta.json`](furnace_x2/evidence/quartus-sta.json) | recorded status: `passed`; Fmax MHz: `109.24`; setup slack ns: `0.846`; hold slack ns: `0.037` |
| `furnace_x2` | [`furnace_x2/evidence/ppa-resource-summary.json`](furnace_x2/evidence/ppa-resource-summary.json) | Recorded artifact; inspect its applicability, source binding and scope. |
| `furnace_x2` | [`furnace_x2/evidence/board-hil.json`](furnace_x2/evidence/board-hil.json) | recorded status: `passed`; scope: BAR0/reg57 bridge-connectivity probe only; not per-chip workload execution |
| `furnace_x3` | [`furnace_x3/evidence/verification-receipts.json`](furnace_x3/evidence/verification-receipts.json) | Recorded artifact; inspect its applicability, source binding and scope. |
| `furnace_x3` | [`furnace_x3/evidence/rtl-timing-lint.json`](furnace_x3/evidence/rtl-timing-lint.json) | recorded status: `passed` |
| `furnace_x3` | [`furnace_x3/evidence/quartus-sta.json`](furnace_x3/evidence/quartus-sta.json) | recorded status: `passed`; Fmax MHz: `231.05`; setup slack ns: `5.672`; hold slack ns: `-0.203` |
| `furnace_x3` | [`furnace_x3/evidence/ppa-resource-summary.json`](furnace_x3/evidence/ppa-resource-summary.json) | Recorded artifact; inspect its applicability, source binding and scope. |
| `furnace_x3` | [`furnace_x3/evidence/board-hil.json`](furnace_x3/evidence/board-hil.json) | recorded status: `passed`; scope: BAR0/reg57 bridge-connectivity probe only; not per-chip workload execution |
| `furnace_x4` | [`furnace_x4/evidence/verification-receipts.json`](furnace_x4/evidence/verification-receipts.json) | Recorded artifact; inspect its applicability, source binding and scope. |
| `furnace_x4` | [`furnace_x4/evidence/rtl-timing-lint.json`](furnace_x4/evidence/rtl-timing-lint.json) | recorded status: `passed` |
| `furnace_x4` | [`furnace_x4/evidence/quartus-sta.json`](furnace_x4/evidence/quartus-sta.json) | recorded status: `passed`; Fmax MHz: `111.3` |
| `furnace_x4` | [`furnace_x4/evidence/ppa-resource-summary.json`](furnace_x4/evidence/ppa-resource-summary.json) | Recorded artifact; inspect its applicability, source binding and scope. |
| `furnace_x4` | [`furnace_x4/evidence/board-hil.json`](furnace_x4/evidence/board-hil.json) | recorded status: `passed`; scope: BAR0/reg57 bridge-connectivity probe only; not per-chip workload execution |
| `furnace_x4` | [`furnace_x4/evidence/soc-board-coexecution.json`](furnace_x4/evidence/soc-board-coexecution.json) | recorded status: `passed`; scope: recorded multi-profile/co-execution telemetry; interpret with the associated image, workload and output bindings |

## File-management policy / 文件管理约定

- Keep RTL, constraints, tests and result originals in their existing locations. This documentation refresh does not move or delete them.
- Hyphenated, underscored and `chips/` directories are separate existing trees, not interchangeable aliases. The index lists all of them without declaring one authoritative.
- Preserve dated reports as publications. Update the README and this guide when the public source/evidence changes; do not silently rewrite an old result.
- Keep chip artifacts separate from the private Vulcan implementation. Public reproducibility instructions must not require private framework code or internal operation traces.

保留现有源码、约束、测试和原始证据路径；连字符、下划线和 `chips/` 多份目录不自动视为等价。历史报告保留其发表时范围，公开复现不得依赖私有框架实现。
