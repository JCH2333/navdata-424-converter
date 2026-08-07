# Fenix 机场投影

2608 NAIP 的 `AD_HP.csv` 将机场坐标以 DMS 字符串、过渡高度和过渡高度层以米提供。Fenix 2608 参考库的新增中国机场采用小数点后六位坐标和百英尺高度精度。

投影规则如下：

- 纬度、经度由 DMS 解析后保留六位小数。
- 机场标高继续按最近整数英尺写入。
- `VAL_TRANSITION_ALT` 与 `VAL_TRANSITION_LEVEL` 都按米转换为英尺，并量化到最近百英尺；零值保持零。
- 非 ASCII 的 `TXT_NAME` 使用确定性拼音投影；斜杠转换为空格，例如 `赤峰/玉龙 -> CHIFENG YULONG`。ASCII 名称保持原样。

该规则的证据来自 `ZBAL`、`ZBAR`、`ZBCF`、`ZHSN`、`ZLDL` 等新增机场的源字段与只读参考差分。该拼音规则将本轮候选中的机场名称差异从 188 条降至 81 条。需要行政区缩写、英文语义翻译或非标准拼写的其余名称，以及 `SpeedLimitAltitude`，仍不存在 CSV/PDF 可追溯映射，不能用参考行回填。
