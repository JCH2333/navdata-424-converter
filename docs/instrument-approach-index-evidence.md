# 仪表进近图索引证据

2608 的每个机场目录包含 `Charts.csv`。转换器只选择索引中明确标为“仪表进近图”或“进近图_”的页面，并保留 PDF 文件哈希、页码、图表名和从页面/图表名直接读取的跑道号。

这类证据当前只用于诊断，不能生成 `Terminals`、`TerminalLegs` 或 `TerminalLegsEx`。一张进近图只能证明某机场某跑道存在进近资料，不能可靠证明 Fenix 程序名称、航段顺序、过渡或 ARINC 语义。

使用以下命令比对证据与本地成品中 `Proc=3` 的跑道组合：

```powershell
python -m navdata_converter.cli inspect-approach-chart-coverage `
  --naip-root "<2608 原始数据目录>" `
  --reference "<fnx2608N Navdata 目录>"
```

输出中的 `reference_without_evidence` 是后续优先解析的缺口；`evidence_without_reference` 则需要人工检查图表索引、跑道命名和成品数据，不能据此直接补写程序。

诊断会单独报告不等于 `R{跑道号}` 的成品进近名称。它们通常是同一跑道上的 ILS、RNP 或其他独立进近程序，必须通过图表内容继续解析；不能将它们视为异常或用跑道简名替代。
