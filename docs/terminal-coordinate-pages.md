# 终端航路点坐标页

终端目录中由 `Charts.csv` 索引的“航路点坐标”PDF 是终端航路点的证据来源。解析器使用 PDF 的文本层，要求标识符列与坐标列数量完全一致后才配对。

每个已接受点保留机场、标识符、PDF 相对路径、页码和 PDF SHA-256。它们与 `DESIGNATED_POINT.csv` 保持分离，尚未直接写入 Fenix `Waypoints`；写入前必须完成物理位置去重、来源优先级、确定性 ID 阶段和与本地成品的只读对照。

无法配对的坐标页会作为 `terminal-coordinate-page` 拒绝记录写入转换报告，不能静默忽略。2608 当前已知的异常页为 `ZHXY`、`ZLZY`、`ZPDQ` 和 `ZPNL`。

使用 `inspect-terminal-waypoint-coverage` 可对照官方模板和本地成品。匹配条件是标识符相同且坐标距离小于 0.02 海里，报告会把与成品不匹配的样本列出，供后续排查，不会把成品数据作为转换输入。
