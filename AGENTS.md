# Fenix 424 转换器交接状态

## 目标与边界

当前目标是从 `424源数据\2608\2608` 的 CSV 与终端 PDF 生成 Fenix `Navdata/nd.db3`，最终与本地 `fnx2608N` 参考成品逐字节相同。参考库只可用于只读差分、验证映射与行为，不能作为转换输入或复制记录来源。当前候选均为测试诊断件，未部署、未发布。

PDF/CSV 是唯一转换输入。图像模型只能用于抽样验证，不能进入转换路径。用户曾在对话中提供第三方图像识别访问凭据：不得将其写入文件、日志、Git 或回复；当前实现没有使用该凭据。

## 本地数据与输出

- 原始 2608：`F:\我的世界动画\AI项目\导航数据\424源数据\2608\2608`
- 官方 Fenix 模板：`C:\ProgramData\Fenix\Navdata`
- 只读参考：`F:\我的世界动画\AI项目\导航数据\424源数据\2608\Navdata（fnx2608N）\Navdata\nd.db3`
- 项目：`F:\我的世界动画\AI项目\导航数据\navdata-424-converter`
- 本地诊断副本：`output\diagnostic-ils\official.db3`、`output\diagnostic-ils\reference.db3`
- 官方模板副本：`output\official-navdata-2608`
- 最近的 ILS 诊断候选：`output\candidate-ad219-crossing-reference`

以上数据库、PDF、缓存、`output`、日志均已被 `.gitignore` 排除，禁止提交。`output\model-ad219-precision.pickle` 是旧源模型快照；在提交 `67aa914` 之后已过期，不能用于验证最新机场映射，必须重新解析生成。

## Git 状态

截至本交接文件创建时，当前分支为 `main`，最新提交 `67aa914 fix: normalize Fenix airport transition heights`，本地相对 `origin/main` **ahead 1**，尚未成功推送。此前以下提交已推送：

- `e32bcf9 fix: match reference ILS crossing height`
- `a3213fe fix: round Fenix DME elevation upward`
- `30a514a fix: normalize Fenix ILS storage precision`
- `3d7e49a docs: record AD 2.19 reference-data mismatches`
- `6986520 fix: parse precision AD 2.19 ILS frequencies`
- `78ac3e2 fix: parse multi-page AD 2.19 ILS tables`
- `22bb3ed feat: project source-backed ILS records`
- `56e368a feat: retain AD 2.19 ILS evidence`
- `1d75691 feat: add safe China airport replacement transaction`

每项代码或文档改动必须：运行相称测试、检查暂存区和 `git diff --check`、单主题提交并推送到现有远端。推送可能需要受限外网络；用户已授予完整权限。不要创建正式 Release。

完整测试命令必须使用项目内临时目录：

```powershell
python -m pytest -q --basetemp output\pytest-<unique> -p no:cacheprovider
```

## 已实现的 PDF 与 ILS 规则

相关代码：`src/navdata_converter/pdf_charts.py`、`source.py`、`fenix.py`；证据文档：`docs/ad219-landing-aids.md`。

1. 从每个机场未被 `Charts.csv` 索引的机场资料 PDF 中定位 AD 2.19，跨连续页缓存文本，直至 `AD 2.20` 或“本场规定”。所有 `Ils` 保留 PDF 相对路径、起始页和 SHA-256 来源。
2. 支持分裂 LOC 行：LOC/识别码/频率/纬度在上一页，`ILS CAT` 与经度在续页。
3. LOC 频率支持一至三位小数；主 LOC 正则不再吞掉后续 220 个字符，以免连续 ILS 被第一条吞掉。
4. Fenix VHF BCD 频率使用有效小数位左对齐：`108.5 -> 0x01085000`、`111.55 -> 0x01115500`、`108.950 -> 0x01089500`。
5. LOC 坐标在当前参考兼容投影中保留六位小数；DME 天线标高为米转英尺后向上取整。
6. 当前参考库中本轮可写的 142 条 ILS 的 `CrossingHeight` 都是固定 `50`。`project_ad219_ils` 因此固定写入 `50`，但原始 RDH 仍保存在中间模型。该规则是 2608 参考兼容行为，不是通用航行语义结论。
7. 无 LOC 航向、GP 角、RDH 或 DME 标高时，投影必须拒绝并报告，不能从跑道或参考库补值。

## ILS 诊断结果

官方库与参考库的中国 ILS 差分：参考新增 218 条。通过当前 PDF 解析得到：

- 179 条可按机场/跑道/识别码/频率对应参考业务键。
- 39 条与当前资料不一致，不能回填。已确认：`ZBLA` PDF（EFF 2026-6-11）只有紧急 ILS `IUC`，参考要求 `IXX/IZZ`；`ZUNZ` AD 2.19 明确“无”，参考仍有 `ILZ/IMM`。
- 最近 ILS 候选写入 142 条、拒绝 58 条；其中 63 条除行 ID 外与参考 ILS 字段完全一致，65 条仍有来源或参考兼容差异，14 条是当前 PDF 存在但参考不存在的记录。

剩余 LOC 坐标差异不能用单一 LOC/GP/DME 选择规则解释：在六位精度下只有少数参考行对应 GP 或 DME，更多行与三类当前 PDF 坐标都不一致。LocCourse 差异也没有统一的跑道真航向关系。不要按 ICAO 硬编码或复制参考字段。

## 机场与跑道差分

最近候选与参考库的机场 ICAO 集合已完全一致（均 17346）。候选多出 `ZBAL` 跑道 `14/32`，参考没有这两条；跑道公共键中仍有 374 条字段不同。

已由参考差分和原始 CSV 确认并在 `67aa914` 实现：

- 机场纬度、经度由 DMS 解析后保留六位小数。
- `VAL_TRANSITION_ALT` 与 `VAL_TRANSITION_LEVEL` 都是米；均应转换为英尺并量化到最近百英尺。
- 机场标高仍为最近整数英尺。

提交前差分中 188 个机场都存在名称差异，177 个存在过渡高度/层差异，172/177 个存在坐标差异。重新解析和生成候选后应确认后两类明显下降。机场名称目前直接写 NAIP 中文；参考是英文/拼音混合名称，`romanize_name` 不能直接匹配如 `ALXA LEFT BANNER BAYANHOT` 的人工英语名称，尚无可追溯的通用来源映射。`SpeedLimitAltitude` 也没有来源规则，不能用参考字段回填。

## 转换与程序状态

`convert(..., allow_incomplete=True)` 仍是追加式候选：只增加官方模板没有的机场、跑道、设施、航点和可投影程序；完整中国机场域替换事务 `_clear_china_airport_domain` 已有外键 fixture，但尚未接入真实 `convert`，因为 ILS、Markers、跑道和程序还未完成完整来源投影。不要提前启用删除事务，否则会损失官方记录。

最近完整模型读取耗时约 52 秒，包含 430 条 AD 2.19 ILS 与 7356 个程序图表证据。一次合成候选曾得到：188 个新增机场、376 条新增跑道、140 个新增台站、142 条新增 ILS、6232 个终端航点、1414 个终端程序和 6601 条终端航段；同时有 58 条 ILS 拒绝与 7969 条未完成终端程序拒绝。因此候选状态始终为 `incomplete`、`deployable=false`。

单个工具命令约 60 秒超时。需要完整候选时分两步：先运行 `load_naip` 并将 `NavModel` 序列化到 `output`，再在独立命令中反序列化并调用 `convert`。每次改动 `source.py` 后都必须重建该临时模型。

## 当前优先顺序

1. 推送 `67aa914`，确认工作树干净。
2. 使用新源模型重新生成诊断候选，确认机场坐标和过渡高度/层差异减少，并更新数字诊断。
3. 对机场名称、`SpeedLimitAltitude`、跑道阈值/航向进行来源优先的差分研究；只实现可复用、可测试的规则。
4. 完成 ILS 与 Markers、跑道、机场、程序来源投影后，再把完整中国机场域替换事务接入转换，保留全球官方基线。
5. 持续扩展数据库编码表和终端 PDF 程序解析，减少 7969 个拒绝程序；无法可靠解析的程序必须拒绝而非静默沿用旧官方程序。
6. 每轮运行完整候选、`integrity_check`、schema/表级/记录级差分。只有所有表内容、SQLite 物理布局、外部元数据与参考逐字节一致，才能认为该阶段完成；在此之前禁止部署与发布。

## 安全约束

- 不部署到 `C:\ProgramData\Fenix\Navdata`，除非用户明确要求并确认 `FlightSimulator2024.exe` 已退出；部署前必须带时间戳备份数据库和周期元数据。
- 不提交数据库、PDF、缓存、日志、`output`、外部测试包或任何密钥。
- 不创建正式 Release；实机验证通过前只能测试版。

## 2026-08-07 重解析诊断

- 使用当期 `424源数据\\2608\\2608` 的 CSV/PDF 重新运行 `load_naip`，并将模型保存为被忽略的 `output\\model-2608-latest.pickle`；模型统计为机场 275、跑道 640、台站 438、航路点 2158、ILS 430、终端航点 8790、程序段 4853，拒绝记录 1、拒绝程序 7969。
- 基于该模型生成 `output\\candidate-2608-latest`。候选状态仍为 `incomplete`，插入机场 188、跑道 376、台站 140、ILS 142、终端航点 6232、终端程序 1414、终端航段 6601；ILS 拒绝 58 条。
- 与只读 `fnx2608N` 参考库按机场 ICAO 逐字段比较：机场键集合一致；`Latitude`、`Longtitude`、`TransitionAltitude`、`TransitionLevel`、`Elevation`、`SpeedLimit` 均无差异。剩余 188 条 `Name` 差异和 44 条 `SpeedLimitAltitude` 差异。机场 PDF 图页仅出现中文机场标题（例如 `赤峰/玉龙`），当前没有 CSV/PDF 中可追溯的参考英文名称或限速高度字段，故本轮不回填、不硬编码。
- 候选数据库 `integrity_check=ok`，schema 与参考相同；候选与参考 SHA-256 仍不同（未达到字节级一致），不得部署或发布。

## 2026-08-07 机场名称拼音投影

- 新增机场投影对非 ASCII 的 `AD_HP.csv` `TXT_NAME` 使用确定性拼音，并把源分隔符 `/` 规范为空格；ASCII 名称保持原样。该规则完全由 CSV 名称驱动，不读取或复制参考名称。
- 用同一重解析模型生成 `output\\candidate-2608-airport-name` 并与只读参考逐字段比较：机场差异从 188 条降至 102 条，`Name` 差异从 188 条降至 81 条；坐标、标高、过渡高度、过渡层和 `SpeedLimit` 仍为零差异，`SpeedLimitAltitude` 仍有 44 条差异。候选 SHA-256 为 `42297b3b2d2210a8d3c785f3e59651a875d2d4ba51f2a15257fbc9638ebfd1a0`，仍不等于参考，禁止部署或发布。

## 2026-08-07 数据库编码页面拒绝分类

- `Charts.csv` 的“数据库编码”行通常带有标准仪表图类型；此前 `_reject_unparsed_charts` 仅按图类型筛选，导致已由 `extract_airport_database_charts` 解析为终端航段的页面又被错误登记为未解析。现按图名先排除数据库编码页，并以最小 CSV fixture 覆盖。
- 重新解析后，终端 PDF 拒绝从 7969 条降至 6389 条，精确减少 1580 个数据库编码页面；`procedure_charts=7356`、`procedure_segments=4853`、投影终端程序 1414 和航段 6601 均保持不变。`output\\candidate-2608-database-pages` 的完整表级差分与机场名称候选一致，`integrity_check=ok`，SHA-256 仍为 `42297b3b2d2210a8d3c785f3e59651a875d2d4ba51f2a15257fbc9638ebfd1a0`，不得部署或发布。

## 2026-08-08 跑道来源精度诊断

- 对 `output\\candidate-2608-database-pages` 与只读参考按 `(机场 ICAO, 跑道标识)` 比较：候选仅多出 `ZBAL 14/32` 两条；374 条公共跑道的 `Latitude`、`Longtitude` 和物理 ID 不同，364 条 `TrueHeading`、48 条长度、10 条宽度、22 条道面和 68 条标高不同。
- `RWY_DIRECTION.csv` 只提供整数 `VAL_TRUE_BRG`、标高和位移距离，未提供阈值坐标；`RWY.csv` 只提供长度、宽度和道面。终端机场图所见 ARP/跑道图也未提供可结构化的阈值坐标。当前阈值计算是基于来源 ARP、长度和方位的诊断近似，不能复原参考的小数方位或阈值坐标，不能以参考字段或 ICAO 特例回填。该缺口必须在取得 CSV/PDF 内的高精度跑道来源前保持显式未完成。

## 2026-08-08 终端精确坐标解析

- 终端固定点原先仅按 0.02 海里容差解析目标 `Waypoints`。当坐标页固定点与同标识的指定点或台站航点相距很近时，会产生多个候选并拒绝，即使其中一个候选精确等于 PDF 打印坐标。现先选择唯一的精确坐标匹配；没有唯一精确匹配时继续按原近距规则处理，两个精确同址候选仍拒绝。
- 使用 `ZYDQ/P111` 的最小 SQLite fixture 验证：来源坐标与一条目标精确相同、另一条仅近距时，解析器选择精确行，不读取参考库。完整候选 `output\\candidate-2608-terminal-exact` 的终端程序由 1414 增至 1498、航段由 6601 增至 6997；终端程序拒绝由 583 降至 499，保持拒绝 292。`integrity_check=ok`；Terminals 为 98602/101618，TerminalLegs 与 TerminalLegsEx 均为 821843/845147，候选 SHA-256 `22459e89062ed7b92b39b2501b7635f8c4a1cfdb1b0ac5053da73511794a279d`，仍不得部署或发布。
