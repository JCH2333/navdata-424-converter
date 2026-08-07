# 仪表进近图索引证据

2608 的每个机场目录包含 `Charts.csv`。转换器只选择索引中明确标为“仪表进近图”或“进近图_”的页面，并保留 PDF 文件哈希、页码、图表名和从页面/图表名直接读取的跑道号。

这类证据当前只用于诊断，不能生成 `Terminals`、`TerminalLegs` 或 `TerminalLegsEx`。一张进近图只能证明某机场某跑道存在进近资料，不能可靠证明 Fenix 程序名称、航段顺序、过渡或 ARINC 语义。

使用以下命令比对证据与本地成品中 `Proc=3` 的跑道组合：

```powershell
python -m navdata_converter.cli inspect-approach-chart-coverage `
  --naip-root "<2608 原始数据目录>" `
  --official-navdata "<官方 Fenix Navdata 目录>" `
  --reference "<fnx2608N Navdata 目录>"
```

对于带有可提取文本层的图页，解析器还保留与 `IAF`、`IF`、`FAF`、`MAP` 或 `MAHF` 同一文本块且位置相邻的固定点标识。该证据可通过下列命令只读核对：

```powershell
python -m navdata_converter.cli inspect-role-fix-coverage `
  --naip-root <2608原始目录> `
  --official-navdata C:\ProgramData\Fenix\Navdata `
  --reference <本地成品Navdata> `
  --pdf-cache <本地缓存目录>
```

它不表示完整航段顺序，也不会直接写入 `TerminalLegs` 或终端航路点表。`GP`、`INOP` 等下滑道状态文字被显式排除。

输出中的 `reference_without_evidence` 是后续优先解析的缺口；`evidence_without_reference` 则需要人工检查图表索引、跑道命名和成品数据，不能据此直接补写程序。

诊断会单独报告不等于 `R{跑道号}` 的成品进近名称。它们通常是同一跑道上的 ILS、RNP 或其他独立进近程序，必须通过图表内容继续解析；不能将它们视为异常或用跑道简名替代。

当前会从标题中保守推导名称候选，且名称推导只使用标题中的跑道，避免正文附带的其他跑道污染。带 `ILS/DME w/x/y/z` 或 `RNP w/x/y/z` 的标题可给出相应的 `I...` 或 `R...` 变体，并保留同族基础名称；无变体的 ILS、RNP、VOR/DME、NDB、NDB/DME 标题分别给出 `I`、`R`、`D`、`N`、`Q` 前缀。VOR/DME、NDB、NDB/DME 不保留标题变体字母。`matched_names` 只衡量候选与成品的精确交集，不能作为写入许可。

`delta_names` 与 `matched_delta_names` 是转换工作应采用的指标：它们只统计相对官方模板新增或变更的成品 `Proc=3` 程序。官方模板中逐字段未变的程序不是转换器的写入对象。

`ZYTL` 的 2608 RNP(AR) 图表是已验证的局部兼容规则：标题的 `x/y/z` 变体除常规候选外还产生 `R10-AR-X/Y/Z`。这只是与本地参考成品的诊断匹配，不可推广到其他机场或作为程序写入依据。
