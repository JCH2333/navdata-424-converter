# Fenix 中国机场域替换

Fenix 2608 官方库中已有部分中国机场。仅追加 NAIP 机场会保留这些旧行，无法复现本地 `fnx2608N` 成品的机场、跑道和程序变更。因此适配器提供了一个受限的中国机场域清理事务，匹配 ICAO 前缀 `ZB`、`ZG`、`ZH`、`ZJ`、`ZL`、`ZP`、`ZS`、`ZU`、`ZW`、`ZY`。

事务的删除顺序固定为：

1. 与目标机场终端程序关联的 `TerminalLegs`。
2. 同 ID 的 `TerminalLegsEx`。
3. `Terminals`、`Runways`、`AirportLookup` 和 `Airports`。

临时 ID 表只来自 `Airports`，因此不会按航点标识符、台站标识符或航路名称猜测区域归属。它不触及 `Waypoints`、`WaypointLookup`、`Navaids`、`Airways` 或 `AirwayLegs`，避免误删被区域外航路引用的实体。

该事务当前仅由最小 SQLite fixture 覆盖，尚未接入 `convert`。实际 Fenix 库还有 `ILSes` 和 `Markers` 依赖 `Runways` 或 `Airports`；2608 NAIP 到这两张表的来源映射尚未建立。若在映射完成前启用机场替换，将丢失这两类设施，既不安全也不可能得到字节级参考结果。

启用完整区域替换前必须同时完成：

- 从 NAIP 解析并投影 ILS 与标记台；
- 按确定性顺序回填所有受影响的机场、跑道、终端和相关设施；
- 对完整候选运行 `foreign_key_check`、`integrity_check`、表级差异和参考库字节比较；
- 保持候选为测试版，未经实机验证不得部署或发布正式版本。
