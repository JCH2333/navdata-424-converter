# Fenix 机场投影

2608 NAIP 的 `AD_HP.csv` 将机场坐标以 DMS 字符串、过渡高度和过渡高度层以米提供。Fenix 2608 参考库的新增中国机场采用小数点后六位坐标和百英尺高度精度。

投影规则如下：

- 纬度、经度由 DMS 解析后保留六位小数。
- 机场标高继续按最近整数英尺写入。
- `VAL_TRANSITION_ALT` 与 `VAL_TRANSITION_LEVEL` 都按米转换为英尺，并量化到最近百英尺；零值保持零。

该规则的证据来自 `ZBAL`、`ZBAR`、`ZHSN`、`ZLDL` 等新增机场的源字段与只读参考差分。机场名称和 `SpeedLimitAltitude` 仍存在未建立来源映射的差异，不能用参考行回填。
