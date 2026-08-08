# Fenix 424 转换器交接状态

## 2026-08-08 数据库编码进近过渡标题的紧邻 via

- 适用范围：2608 NAIP 终端 PDF 数据库编码表中 `RWYxx 进近过渡via FIX` 的无空格英文连接词版式。`Terminal/ZBDH/ZBDH-4H.pdf` 原生 PDF 文本层和独立 OCR 表格均明确打印 `RWY26 进近过渡via DH504`、`RWY26 进近过渡via DH509`；此前解析器只接受空格分隔的过渡定位点，因此把两段的 `procedure_kind` 留空。
- 解决方式：`_DATABASE_APPROACH_PROCEDURE` 仅额外接受字面 `via` 后的定位点，保留原有“空格后定位点”形式；不允许任意紧邻大写字符串，以避免把其他标题文本误作过渡名。`test_extracts_database_approach_transition_with_adjacent_via_text` 固定该版式。
- 验证：全量 CSV/PDF 重解析后，`ZBDH/R26` 源模型包含 `DH504`、`DH509` 两个 `进近过渡` 段，均为 `IF, TF`。未传入参考库生成 `output/candidate-2608-transition-via-narrow`，`integrity_check=ok`，`Terminals 100685/101618`、`TerminalLegs/Ex 839320/845147`，未低于上一稳定候选。只读参考记录显示 `ZBDH/R26` 仍有对应过渡，因此下一缺口是进近图角色关联而非标题 OCR。候选 SHA-256 `d941e91c22f8f62365eed88571d4d32c6d2ecbb7039fd5d99fd968e92654dae4` 不等于参考 `ca9cdd72b80d46b4c28e884bcd2ecf4b29bc54489704771d7908b32c6e3c510f`，仍为不可部署的测试候选。

## 2026-08-08 标准图导航数据代码投影

- 适用范围：已由标准进场图“程序代号 / 导航数据代码 / 航迹简述”表唯一关联并完成航段模板替换的 STAR。`Terminal/ZBCZ/ZBCZ-4P-1.pdf` 明确打印 `P439-A1 / P439A1 / P439-CZ823-CZ700`；替换后的源段此前仍把无连字符的 `P439A1` 交给普通标签解析器，因而被拒绝。
- 解决方式：`ProcedureSegment.fenix_name` 仅由 `_replace_standard_p_arrivals()` 写入该表中打印的 `navigation_code`。Fenix 终端投影优先使用这个受来源关联保护的字段；任何未带该字段的无连字符标签仍由既有严格解析器拒绝，不扩大普通标签的接受范围。
- 验证：标准图替换与受限投影 fixture 通过，全量 `pytest` 为 `109 passed`。未传入参考库的 CSV/PDF 转换生成 `output/candidate-2608-standard-route-navigation-code`，`integrity_check=ok`，SHA-256 `09dee5ea2df32ad8c90c3f1c9c1498c11d6e575da5a9839b4e01d77a50459223`，仍不等于参考 `ca9cdd72b80d46b4c28e884bcd2ecf4b29bc54489704771d7908b32c6e3c510f`。相对上一候选，`Terminals` 从 `100683` 增至 `100685`，`TerminalLegs/Ex` 从 `839313` 增至 `839320`；只读记录核对确认 `ZBCZ/P439A1/01` 已写入 `IF, TF, TF`。`P439C3` 和 `DRQ1R` 当前仍缺唯一来源模板，未按参考回填。候选仍为 `incomplete`，禁止部署或发布。

## 2026-08-08 标准进场图航迹简述表

- 适用范围：2608 NAIP 标准仪表进场图底部的“进场程序代号 / 导航数据代号 / 航迹简述”表。`Terminal/ZBCZ/ZBCZ-4P-1.pdf` 原生 PDF 图元和文字表明确给出 `P439-A1 / P439A1 / P439-CZ823-CZ700` 以及 `P439-C3 / P439C3 / P439-CZ823-CZ622-CZ621`。这为此前 `CZ823` 分叉提供了直接来源证据，不需要 OCR 或参考记录回填。
- 解决方式：标准图解析器按渲染文字位置重建表格，仅接受程序代号、导航数据代号和完整航迹三列都存在、首固定点一致且导航代码保留版本后缀的记录。对进场数据库编码段，仅当同机场同跑道、`P###` 首固定点和倒置版本号唯一关联该表项，并能在同一机场来源编码表找到唯一完整 ARINC 航段类型模板时，才以打印导航代码和完整航迹替换原来串接的分支；缺失或多候选一律不改写。
- 验证：`test_extracts_standard_arrival_route_table_without_inferring_geometry`、缓存往返、唯一模板替换和加载顺序 fixture 均通过；全量 `pytest` 为 `108 passed`。使用未传入参考库的 CSV/PDF 转换生成 `output/candidate-2608-standard-route-tables-order`，`integrity_check=ok`，`Terminals` 为 `100683/101618`、`TerminalLegs/Ex` 为 `839313/845147`。候选 SHA-256 `0fdf940d8d7aa1a9e4172bba15f2a9a0d6b7b637ccb53ecf893a12096b092dc1` 不等于参考 `ca9cdd72b80d46b4c28e884bcd2ecf4b29bc54489704771d7908b32c6e3c510f`，仍为 `incomplete`，禁止部署或发布。

## 2026-08-08 重复机场英文标题片段

- 适用范围：机场资料 PDF AD 2.1 标题中同一英文机场名被连续打印两次的情况。`Terminal/ZSAQ/安庆.pdf` 第 1 页明确打印 `ZSAQ/AQG-安庆ANQING/Anqing`；这是来源中的同一名称大小写重复，不是两个不同的地点名。
- 解决方式：`_airport_pdf_english_name` 仅当规范化后的英文词序列为相邻且完全重复时压缩为一个序列，故 `ANQING/Anqing -> ANQING`。不同名称的斜线分隔，例如 `ALXA LEFT BANNER/Bayanhot`，仍完整保留。合并器对已存在机场只允许修正“基线名称恰为来源名称的完整重复”这一可证明情况；不会因 PDF 标题别名、转写差异或 `AIRPORT` 后缀猜测覆盖基线。
- 验证：`test_collapses_exact_repeated_english_airport_title_fragment`、已存在机场正反例 fixture 和全量 `pytest`（104 passed）通过。使用未传入参考库的 CSV/PDF 重解析生成 `output/candidate-2608-source-name-repeat`，`integrity_check=ok`，候选 SHA-256 为 `31309afbc9b0d7083ca3fabb03caf2e9d12eab3953a9ab9bba58c3e472258842`，仍不等于参考 `ca9cdd72b80d46b4c28e884bcd2ecf4b29bc54489704771d7908b32c6e3c510f`。随后只读差分确认 `ZSAQ` 名称为 `ANQING`，机场名称差异由 72 降至 71；候选仍为 `incomplete`，禁止部署或发布。

## 2026-08-08 五字符程序基名的两字符版本投影

- 适用范围：2608 NAIP 终端 PDF 数据库编码表中的五字符普通基名、两字符版本号。`Terminal/ZBTJ/ZBTJ-4Z01.pdf` 原生文字层与离线 OCR 均明确打印 `BOTPU-2W`；同类来源标签包括 `AVBOX-1W`、`BUMDU-3H`、`DUMAP-1Q` 与 `GUVBA-1W`。
- 解决方式：Fenix 六字符名称字段对该类标签保留基名前三位及末位，然后拼接两字符版本号，即 `BOTPU-2W -> BOTU2W`、`AVBOX-1W -> AVBX1W`、`BUMDU-3H -> BUMU3H`、`DUMAP-1Q -> DUMP1Q`、`GUVBA-1W -> GUVA1W`。`P### -> P##` 的独立规则保持优先。该投影只读取 PDF 标签，不读取或复制参考记录。
- 验证：`test_fenix_procedure_name_matches_observed_database_labels` 与全量 `pytest`（`101 passed`）通过。完整 CSV/PDF 重解析并以不传入参考库的转换生成 `output/candidate-2608-five-char-procedure-rerun`；`integrity_check=ok`，`Terminals 100685/101618`、`TerminalLegs/Ex 839333/845147`。随后以只读参考进行业务键差分：缺失/额外由 `1086/116` 降至 `1013/103`，其中 STAR `368/64`、SID `394/38`、IAP `251/1`。候选 SHA-256 `7027a5c8f965083587bc65047577908f2d0169942d3118b73f2cd2437a433e7a` 不等于参考 `ca9cdd72b80d46b4c28e884bcd2ecf4b29bc54489704771d7908b32c6e3c510f`，仍禁止部署或发布。

## 2026-08-08 来源驱动 IAP 航段

- 适用范围：Fenix 2608 NAIP 数据库编码页中的进近过渡、主进近和复飞分段。`ZBAD/R01L` 的源模型保留两个进近过渡 `AD521/AD561`、主进近 `AD620 -> AD606 -> AD603`和复飞段；`ZBAD-5P-1.pdf` 明确标出 `IF/FAF/MAPT`。
- 解决方式：只对能唯一关联进近图、主进近终点有明确 `MAPT`、且全部固定点能以 CSV/PDF 坐标唯一解析的 IAP 写入。进近过渡使用 `E A/EE B`、主进近使用 `EI/EF/E`、复飞使用 `E M/EE`；由最后一个明确 `MAPT` 坐标生成 `MAP` 行，不读取或复制参考行。多图匹配、缺 MAPT 或缺坐标的 IAP 保留为拒绝记录。
- 验证：`test_projects_source_backed_iap_leg_with_approach_description` 与全量 `pytest` 均通过（`90 passed`）。候选 `output/candidate-2608-iap` 通过 `integrity_check`，`Terminals` 为 101201/101618，`TerminalLegs` 和 `TerminalLegsEx` 均为 839131/845147；IAP 业务键缺口为 589（已从 711 降低），没有参考不存在的新 IAP 键。SHA-256 `c6f6c733c445cb2571aa47c7eaf44e2ffe84f2df4b5716ba690dae66f2c331ec` 仍不等于参考，禁止部署或发布。

## 2026-08-08 合并的进近与复飞标题

- 适用范围：Fenix 2608 NAIP 终端数据库编码 PDF。`Terminal/ZBAL/ZBAL-0C-2.pdf` 明确打印 `RWY14 进近及复飞`，其后先为 `IF/TF` 主进近行，再以 `CF/DF` 开始复飞行。旧解析器不识别该显式合并标题，导致全段错附到上一条进近过渡。
- 解决方式：仅当标题显式为“进近及复飞”时，将其作为主进近开始；在已有主进近行后，第一个 `CA/CF/DF` 行切换为同一显式标题下的复飞段。`test_splits_explicit_combined_approach_and_missed_heading_at_first_missed_leg` 终端跳转固化此版式，PDF 证据缓存版本升为 17。
- 验证：完整重新解析后，程序分段从 7216 增至 7588，数据库编码航段从 38882 增至 39241。候选 `output/candidate-2608-combined-approach` 通过 `integrity_check`，`Terminals` 为 101277/101618，`TerminalLegs` 和 `TerminalLegsEx` 均为 840146/845147；IAP 业务键缺口为 513，仍无新增的非参考 IAP 键。SHA-256 `d765a6fddfd887d18b321e130251e17b3d5f2f6483ee8685c1e4639dd3a20552` 仍不等于参考，禁止部署或发布。

## 2026-08-08 空格分隔的进近变体

- 适用范围：Fenix 2608 NAIP 数据库编码 PDF。`Terminal/ZBAA/ZBAA-0C-20.pdf` 使用 `RWY01 进近 z` 和 `RWY01 进近 y`，字母为小写且与“进近”以空格分隔，不是另一种 `-变体` 拼写。旧规则因此将两条不同的主进近段合并为 `R01`。
- 解决方式：进近标题变体的连字符可选、匹配不区分大小写，写入前仍归一为大写 `-W/-X/-Y/-Z`。`test_preserves_whitespace_separated_approach_variant_from_database_heading` 固定 `RWY01 进近 z -> R01-Z`。缓存版本升为 18。
- 验证：完整重新解析后，程序分段为 7671。候选 `output/candidate-2608-approach-variants` 通过 `integrity_check`，`Terminals` 为 101327/101618，`TerminalLegs` 和 `TerminalLegsEx` 均为 840588/845147；IAP 业务键缺口为 463，仍无新增的非参考 IAP 键。SHA-256 `166bda4591a5e71546f65ac1c2328a77bde2b73b5be8b2b7e5df377bdd50cc28` 仍不等于参考，禁止部署或发布。

## 2026-08-08 同页 IAP 共享分段

- 适用范围：同一机场、跑道、PDF 页内的 IAP 数据库编码表。示例 `ZBAA-0C-20.pdf` 将三个进近过渡和复飞列为无变体 `R01` 的共享段，而两条主进近明确为 `R01-Y` 与 `R01-Z`。源页本身没有为共享段重复打印变体后缀。
- 解决方式：只当变体主进近唯一，且基准标签的进近过渡/复飞段与其来自同一 PDF 页时，将共享段附加给该变体。不跨页、不跨文件、不按机场名称猜测。`test_iap_variant_uses_only_same_page_unlabelled_shared_sections` 覆盖同页接受与其他页拒绝。
- 验证：候选 `output/candidate-2608-iap-shared-sections` 通过 `integrity_check`，`Terminals` 为 101327/101618，`TerminalLegs` 和 `TerminalLegsEx` 均为 840757/845147；IAP 业务键缺口保持 463，没有新增的非参考 IAP 键。SHA-256 `29af141aea901fb584f1faa436d6564a7d8bb8a2f9f362a73f572f29a4a53b4b` 仍不等于参考，禁止部署或发布。

## 2026-08-08 IAP MAPT 图页消歧

- 适用范围：同一机场、跑道和数据库编码名称可匹配多张仪表进近图的 IAP。名称与跑道不足以区分 ILS、RNP 等不同图页，但主进近最后固定点是数据库编码表中可观察的来源事实。
- 解决方式：仍先以名称和跑道筛选；多图候选时，只有当前主进近最后固定点在其中唯一一张图的原生 `MAPT` 标注中出现，才选择该图。零张或多张 `MAPT` 命中继续拒绝。`test_iap_chart_roles_selects_unique_chart_with_explicit_final_mapt` 固化该规则；不读取或复制参考记录。
- 验证：候选 `output/candidate-2608-mapt-chart-disambiguation` 通过 `integrity_check`，`Terminals` 为 101540/101618，`TerminalLegs` 和 `TerminalLegsEx` 均为 843478/845147；IAP 业务键缺口从 463 降至 251。发现一个额外键 `ZPCW/R23-Z`：`ZPCW-5P-2.pdf` 明确标为 RNP z RWY23 且 `CY600` 为 `MAPT`，参考只有 `R23-X/Y`。只读航段差分显示其 `R23-Z` 几何对应参考 `R23-Y`，而来源 `R23-Y` 对应 `R23-X`；PDF 尚未找到可解释这种置换的命名证据，不能按机场或参考特例回填。渲染 `ZBAD-0C-18.pdf` 还确认 RWY35R 编码表确实只到 `AD605`，其仪表图 `MAPT AD602` 不在编码表中，不能把图上 MAPT 当作缺失的编码航段。候选 SHA-256 `f34009672c88393b58fb5b8b3bce5497613a41e40c949ba0c8b15c708a4ac420` 不等于参考，禁止部署或发布。

## 2026-08-08 AD 2.1 英文机场名称

- 适用范围：每个机场资料 PDF 的 AD 2.1/2.2 首页标题。该标题在 ICAO/IATA 和中文名之后直接印有英文机场名，例如 `ZBAL/AXF-阿拉善左旗/巴彦浩特ALXA LEFT BANNER/Bayanhot`。
- 解决方式：仅在非图表机场资料 PDF 的前两页中，解析出唯一匹配本机场 ICAO 的拉丁名称片段；以空格规范斜线和大小写，并把 PDF 页码和 SHA-256 记录为 `Airport.name_source`。多候选、冲突或没有英文名时继续使用 CSV 名称和确定性拼音。`test_extracts_english_airport_name_printed_after_ad21_chinese_name` 与歧义拒绝 fixture 覆盖该规则。
- 验证：完整重新解析得到 271/275 条唯一 PDF 英文名证据。候选 `output/candidate-2608-airport-pdf-names` 的机场 `Name` 差异由 81 降至 72；`Latitude`、`Longtitude`、`Elevation`、`TransitionAltitude`、`TransitionLevel`、`SpeedLimit` 均保持零差异，`SpeedLimitAltitude` 仍有 44 条差异。`integrity_check=ok`，表计数为 `Airports 17346/17346`、`Terminals 101540/101618`、`TerminalLegs 843478/845147`；候选 SHA-256 `0bd011543f2176475fd51a3cc093495e0450a5b14342018b293b1d8cc463a07b` 仍不等于参考，禁止部署或发布。

## 2026-08-08 机场限速高度

- 适用范围：新增中国机场的 Fenix `Airports.SpeedLimitAltitude`。来源 CSV 已提供 `VAL_TRANSITION_LEVEL`，经现有投影后为整数百英尺。
- 解决方式：限速高度为 `max(10000, TransitionLevel - 1800)` 英尺；只依赖机场 CSV 已投影的过渡层，不读取参考字段。对 188 个实际新增机场的只读验证中，该公式全部命中；低过渡层机场由 10,000 英尺下限处理。`test_projects_airport_speed_limit_altitude_from_transition_level_with_floor` 覆盖正常与下限两种情况。
- 验证：候选 `output/candidate-2608-speed-limit-altitude` 的 `SpeedLimitAltitude` 差异由 44 降至 0；`Latitude`、`Longtitude`、`Elevation`、`TransitionAltitude`、`TransitionLevel` 和 `SpeedLimit` 仍为零差异，机场名称差异为 72。`integrity_check=ok`，表计数为 `Airports 17346/17346`、`Terminals 101540/101618`、`TerminalLegs 843478/845147`；候选 SHA-256 `37c8e836fe9d690a877e283bfe3ed5a645ed489ebe88058f681cf613d94a6cda` 仍不等于参考，禁止部署或发布。

## 2026-08-08 SID/STAR 四字符程序基名

- 适用范围：2608 NAIP 终端 PDF 数据库编码表中 `BASE-REVISION` 形式的 SID/STAR 标签。对完整来源模型按 `(机场, Proc, 跑道)` 与只读参考业务键统计，四字符普通基名有 1,029 个段命中完整 `BASE+REVISION`，而五字符基名有 618 个段命中三字符截断；`P###` 仍有 471 个段命中既有 `P##` 专用缩写。
- 解决方式：`fenix_procedure_name` 保留四字符普通基名，仅截断长度大于四的普通基名，并先执行 `P### -> P##` 规则。`AVBO-8Y -> AVBO8Y` 与既有 `KAKAT-9ZA -> KAK9ZA` 回归测试共同固定边界；统计仅用于验证规则，不读取或复制参考记录。
- 验证：使用完整 CSV/PDF 来源模型生成 `output/candidate-2608-procedure-four-char-base`，转换未传入参考库。候选 `integrity_check=ok`；`Terminals 101147/101618`、`TerminalLegs/Ex 841232/845147`。终端业务键差异由缺失 1,895、额外 1,840 降为缺失 1,286、额外 838，其中 STAR 为 `500/509`、SID 为 `535/328`、IAP 保持 `251/1`。候选 SHA-256 `ac24e80c6d3f605c7b48e10e98804dff90612557688f1b97102e182b66d2dceb` 仍不等于参考，禁止部署或发布。

## 2026-08-08 多跑道数据库编码标题

- 适用范围：2608 NAIP 终端 PDF 数据库编码表中 `RWY18L/19`、`RWY01/36L/36R` 这类同一标题列出的共享跑道。原解析器只保留首条跑道，例如 `ZBAA-0C-19.pdf` 原生文字层明确打印 `RWY18L/19 进场AVBO4A`，却只生成 `18L` 段。
- 解决方式：提取每条标题中显式打印的跑道并为每条创建来源段；当同一机场、SID/STAR 类型和规范化标签由来源明确关联到多条跑道时，适配器写入一个 `Rwy=NULL` 的共享终端，同时保留每条来源段自己的 `RWxx` 过渡。单跑道程序继续保留其跑道键。`test_normalizes_dashless_database_procedure_label_from_printed_heading`、`test_extracts_direction_from_shared_runway_database_heading` 和 `test_merges_explicit_multi_runway_database_heading_into_shared_terminal` 覆盖提取、共享与单腿过渡。
- 验证：重新解析完整 CSV/PDF（证据缓存版本 19）得到 9,520 个程序段，并生成未传入参考库的 `output/candidate-2608-multi-runway-heading`。`integrity_check=ok`；`Terminals 100557/101618`、`TerminalLegs/Ex 838900/845147`。终端业务键差异为缺失 1,203、额外 165，其中 STAR `452/96`、SID `500/68`、IAP `251/1`。候选 SHA-256 `17f62988e52dc566d3c51e7468d92aaa6b5da218d157f88660afbf93b00b5c4c` 仍不等于参考，禁止部署或发布。

## 2026-08-08 六字符 SID/STAR 名称投影

- 适用范围：2608 PDF 数据库编码标签的普通基名与版本后缀。按来源标签与只读参考业务键统计，目标名称的普通形式保持六字符宽度：五字符基名配两字符后缀时取前三字符和末字符，配三字符后缀时取前三字符。示例：`BOTPU-2W -> BOTP2W`、`OPIMU-9ZD -> OPI9ZD`；`P### -> P##` 专用规则仍优先执行。
- 解决方式：`fenix_procedure_name` 根据显式打印后缀长度计算可保留的基名长度，不再仅按基名固定截断。`test_fenix_procedure_name_matches_observed_database_labels` 覆盖两字符和三字符后缀边界，映射仅使用 PDF 标签。
- 验证：用已完整重解析的 CSV/PDF 模型生成 `output/candidate-2608-six-char-procedure-name`，转换未传入参考库。`integrity_check=ok`；`Terminals 100497/101618`、`TerminalLegs/Ex 837666/845147`。终端业务键差异为缺失 1,203、额外 105，其中 STAR `452/69`、SID `500/35`、IAP `251/1`。候选 SHA-256 `80858fd57967b72cf8f69f68c0f9214a1c4593c26c2e332e1a59c5105010be9c` 仍不等于参考，禁止部署或发布。

## 2026-08-08 无空格中文跑道标题

- 适用范围：数据库编码页中跑道号直接连接中文类型的标题，例如 `RWY02离场P311-99D`。多跑道标题辅助提取器错误要求跑道号后的单词边界；数字与中文同属 Unicode 单词字符，导致此类标题得到空跑道集合，进而整页航段被丢弃。
- 解决方式：跑道列表只以显式 `RWY` 或 `/` 分隔符识别，不要求跑道号后的单词边界。`test_extracts_shared_runways_when_the_heading_is_adjacent_to_chinese_text` 固定 `RWY02/20离场` 的双跑道证据；缓存版本升至 20。
- 验证：重新解析完整 CSV/PDF 得到 9,561 个程序段，其中 ZBTL 从 4 条恢复为 43 条；未传入参考库的 `output/candidate-2608-runway-heading-boundary` 通过 `integrity_check=ok`。`Terminals 100538/101618`、`TerminalLegs/Ex 837861/845147`；终端业务键缺失 1,162、额外 105，其中 STAR `430/69`、SID `481/35`、IAP `251/1`。候选 SHA-256 `e24582792b28e9f0ef5815a0101381e56930e3ebe01749a919d2773caf5678c9` 仍不等于参考，禁止部署或发布。

## 2026-08-08 纯数字程序版本号

- 适用范围：数据库编码页中 `RWY17进场UPGE94`、`RWY35进场CEH65` 这类基名后仅带两位数字的程序标签。常规标签规则要求数字后有字母，因而拒绝这些页面。
- 解决方式：使用独立的纯数字版本号标题正则，仅匹配显式跑道和中文程序类型，避免与 `P389-09D`、`IDKE5Y` 的既有语法歧义。适配器接受带连字符的两位数字版本号。`test_extracts_numeric_only_database_procedure_revision` 和既有常规标签测试共同覆盖该分支；缓存版本升至 21。
- 验证：重新解析完整 CSV/PDF 得到 9,814 个程序段，ZPDL 从 14 增至 34 个段。未传入参考库的 `output/candidate-2608-numeric-procedure` 通过 `integrity_check=ok`；`Terminals 100609/101618`、`TerminalLegs/Ex 838057/845147`。终端业务键缺失 1,110、额外 124，其中 STAR `419/76`、SID `440/47`、IAP `251/1`。候选 SHA-256 `8e699b29cb47e49fc93698bff492a196446470bfa4c2454218c777526c68c219` 仍不等于参考，禁止部署或发布。

## 2026-08-08 复合程序编码标题

- 适用范围：ZPDQ 等数据库编码页中 `SHGRL1-DQ770`、`DEQIN1-P211`、`RNV16-DQ560` 形式的复合标题。原规则从内部 `DQ770` 开始匹配，丢失左侧程序族。
- 解决方式：先识别显式跑道、离场/进场类型、左侧程序族和右侧三位序号；普通族取左侧前三字符，`RNVnn` 取 `Rnn`，再拼接三位序号。示例：`SHGRL1-DQ770 -> SHG-770 -> SHG770`，`RNV34-P186 -> R34-186 -> R34186`。`test_normalizes_compound_database_procedure_headings` 覆盖两类来源标题；缓存版本升至 22。
- 验证：重新解析完整 CSV/PDF 得到 9,823 个程序段，ZPDQ 解析段为 28，未传入参考库的 `output/candidate-2608-compound-procedure` 通过 `integrity_check=ok`。`Terminals 100625/101618`、`TerminalLegs/Ex 838114/845147`；终端业务键缺失 1,086、额外 116，其中 STAR `405/74`、SID `430/41`、IAP `251/1`。候选 SHA-256 `2797a2e6e814ed137979703f3bcebe78da70814fde5c0ccf722873fc5f8cd112` 仍不等于参考，禁止部署或发布。

## 2026-08-08 无连字符程序标签

- 适用范围：Fenix 2608 NAIP 终端数据库编码 PDF。证据：`Terminal/ZBAA/ZBAA-0C-01.pdf` 的原生文字层打印 `RWY36L/36R 离场IDKE5Y`，旧正则只接受 `IDKE-5Y`，因而丢弃整页 25 条可观察航段。这是完整的原生文字层，不需 OCR 或参考库回填。
- 解决方式：标题正则同时捕获带、不带连字符的“基名 + 后缀”，观察到的排版归一为 `基名-后缀`。该规则无 ICAO 特例；`test_normalizes_dashless_database_procedure_label_from_printed_heading` 覆盖共享跑道标题与 `CA/DF/TF` 航段，PDF 证据缓存版本升为 16。
- 验证：完整重新解析 2608 CSV/PDF 后，数据库编码航段从 22775 增至 38882，程序分段从 4878 增至 7216。候选 `output/candidate-2608-dashless-label` 通过 `integrity_check`，`Terminals` 为 101079/101618，`TerminalLegs` 和 `TerminalLegsEx` 均为 837242/845147；SHA-256 为 `4d301f1b7cef29d34cdd03a26b987e3327b22720443d09392b276eaa0f041e18`，不等于参考 `ca9cdd72b80d46b4c28e884bcd2ecf4b29bc54489704771d7908b32c6e3c510f`，仍不得部署或发布。

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

截至 2026-08-08 当前分支为 `main`，最新提交 `47be081 fix: disambiguate IAP charts by explicit MAPT` 已推送到 `origin/main`，工作树干净。近期已推送提交包括：

- `47be081 fix: disambiguate IAP charts by explicit MAPT`
- `7660b14 docs: record same-page shared IAP sections`
- `c46ed4a fix: associate same-page shared IAP sections`

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

1. 继续从 PDF 标题、有效日期、编码表及图表索引推导 IAP 变体的通用命名规则，解释 `ZPCW/R23-Z` 与参考 X/Y 的来源置换，禁止参考回填。
2. 对机场名称、`SpeedLimitAltitude`、跑道阈值/航向进行来源优先的差分研究；只实现可复用、可测试的规则。
3. 完成 ILS 与 Markers、跑道、机场、程序来源投影后，再把完整中国机场域替换事务接入转换，保留全球官方基线。
4. 持续扩展数据库编码表和终端 PDF 程序解析；编码表没有 MAPT 航段时不得用仪表图虚构该航段。
5. 每轮运行完整候选、`integrity_check`、schema/表级/记录级差分。只有所有表内容、SQLite 物理布局、外部元数据与参考逐字节一致，才能认为该阶段完成；在此之前禁止部署与发布。

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

## 2026-08-08 终端坐标页来源相位

- 终端坐标页点与指定点/台站同标识、同坐标时，二者均需保留为独立的来源相位；但数据库编码程序明确引用终端坐标页点。转换时在连接内建立临时的终端来源点映射，仅在该 `(机场, 标识, 坐标)` 唯一对应本轮终端写入航点时优先解析该 ID。映射不进入输出 schema，不删除或修改同址的指定点和台站航点；缺少唯一终端映射时仍采用精确/近距规则并拒绝歧义。
- `ZSRZ/P09` 最小 fixture 验证两个目标同坐标时可由终端来源相位唯一选择其写入 ID。完整候选 `output\\candidate-2608-terminal-source-phase`：终端程序由 1498 增至 1857、航段由 6997 增至 8496，程序拒绝由 499 降至 140，保持拒绝仍为 292。`integrity_check=ok`；Terminals 为 98961/101618，TerminalLegs 与 TerminalLegsEx 均为 823342/845147，候选 SHA-256 `9c4b56567b9a8b4d786fe7065889a384425e4100efd7829c00bd29f3b35e46f2`，仍不得部署或发布。

## 2026-08-08 终端航点同标识去重

- 终端航点阶段此前按纯位置排除已存在航点，导致数据库编码页引用的 `ZHQQ/QQ508`、`ZUBD/P79`、`ZUXC/XC900` 等来源固定点被近距但不同标识的航点、台站或跑道标签抑制。终端坐标页已由程序引用，故去重条件收紧为“同标识且近距”；不同标识的同址点均保留，指定点和台站阶段仍独立。
- 最小 fixture 断言终端点 `SKIP` 即使与既有 `OLD` 同址也会写入。完整候选 `output\\candidate-2608-terminal-identities`：终端航点由 6232 增至 6463、终端程序由 1857 增至 1922、航段由 8496 增至 9021，程序拒绝由 140 降至 75，且“来源坐标存在但无目标航点”的拒绝归零；保持拒绝仍为 292。`integrity_check=ok`；Waypoints 为 328831/330043，Terminals 为 99026/101618，TerminalLegs 与 TerminalLegsEx 均为 823867/845147，候选 SHA-256 `84fcb5610bb8fe81e3efe3d4e74b180fdb35bc273a3f0e87728dc1eeb8b01d31`，仍不得部署或发布。

## 2026-08-08 终端指定点后备来源

- 程序引用点优先使用同机场终端坐标页；只有该页没有对应标识时，才可使用 `DESIGNATED_POINT.csv` 中全局唯一的同标识坐标作为后备来源。多坐标指定点、已有终端坐标页歧义及没有 CSV/PDF 坐标的记录继续拒绝。该规则使 `ZYBA/P105`、`EKADO` 等有明确结构化来源的固定点参与投影，不使用参考行。
- 最小 SQLite fixture 覆盖唯一指定点到目标航点的解析。完整候选 `output\\candidate-2608-designated-terminal-fallback-2`：终端程序由 1922 增至 1926、航段由 9021 增至 9040，程序拒绝由 75 降至 71（其中无来源坐标 3 条、目标歧义/缺失 58 条），保持拒绝仍为 292。`integrity_check=ok`；Terminals 为 99030/101618，TerminalLegs 与 TerminalLegsEx 均为 823886/845147，候选 SHA-256 `e2f9ec58f112d714da748677342fdf580cc0a94bb3bba5e8a61fe13271a28a2e`，仍不得部署或发布。

## 2026-08-08 共享终端与指定点来源相位

- 同一终端坐标页固定点可被多个邻近机场引用；去重后它们共用一个物理 `Waypoint`，但每个机场的程序解析都需能追溯到该 ID。临时终端来源映射现为每个 `(机场, 标识, 坐标)` 登记同一写入 ID。指定点阶段也登记 `(标识, 坐标)` 的写入 ID，以便没有本场终端坐标页时按指定点来源相位消解同址航点。两类映射均为连接内临时表，不进入输出 schema。
- 最小 fixture 覆盖 `ZSJD/ZSTX` 共享 `P473` 终端点及同址指定点的独立来源 ID。完整候选 `output\\candidate-2608-shared-source-phases`：终端程序由 1926 增至 1984、航段由 9040 增至 9327，普通程序拒绝由 71 降至 13，目标航点歧义归零；保持拒绝仍为 292。剩余普通拒绝为 8 个 RF 弧心无来源坐标、3 个固定点无来源坐标、1 个未知程序类型和 1 个 HF 航段。`integrity_check=ok`；Waypoints 为 328831/330043，Terminals 为 99088/101618，TerminalLegs 与 TerminalLegsEx 均为 824173/845147，候选 SHA-256 `9a3f2de5a7b1e8eb2a392f13d4e31bc87c53ed62f7c3a350ca9e694a7e0ecc2b`，仍不得部署或发布。

## 2026-08-08 ILS 来源缺口抽查

- 对拒绝的 `ZBXH/IYR` 直接读取 `Terminal\\ZBXH\\锡林浩特.pdf` AD 2.19 第 15 页原生文本与文字坐标：LOC 22 给出识别码、109.3 MHz 与坐标；GP 22 给出 3 度下滑角和 RDH 16.7 m；DME 22 给出标高 1013 m，但该页没有 LOC 磁航向。故 `missing LOC course` 是 2608 PDF 内容缺口而非解析正则遗漏，不能由跑道方位或参考 ILS 回填。

## 2026-08-08 航路输入与参考差异

- `RTE_SEG.csv` 已解析为 1354 条航路、4446 条来源航段，但 Fenix 适配器尚未投影。与只读参考相对官方模板新增的 478 条航路比较，2608 CSV 有 483 条官方缺失航路；有向航段集合精确一致为 0 条，只有 185 条存在至少一条同向重叠航段。CSV 独有 3 条航路，参考独有 `P777`、`UP777` 两条。
- 已验证样本：CSV 的 `H118` 仅为 `PAN -> NIXAS`，参考的 H118 为 `PAN <-> SADGO`；CSV 的 `FANS-1` 为 `NIVUX -> XIC -> LEVBA`，参考为 `JHG <-> POXUB` 与 `JHG <-> SADAV`。因此不能把参考航段复制或反推为 CSV 映射；按 CSV 直接写入会产生来源正确但不等于本地参考的航路内容。用户已确认成品全部可由当前 PDF/CSV 推导，故此差异只说明航路 PDF/CSV 来源链或解析尚未完成，必须继续寻找和解析原始证据，不能作为停止逐字节一致目标的依据。

## 2026-08-08 数据库编码表格文字坐标重建

- 适用范围：Fenix 2608 NAIP 终端数据库编码 PDF。证据：`Terminal/ZLXH/ZLXH-4G.pdf` 的 `OMBON-9D` 行在 PDF 对象流中被交错为 `RF[XHC26,TF 5] XH678XH606`，但原生文字对象的同一基线坐标明确给出 `RF[XHC26, 5] XH678 R MAX230 RNP0.3`，下一基线为 `TF XH606`。
- 解决方式：`_positioned_database_text` 以 2.5 点基线容差分组 PDF words，再按 x 坐标重建行；只恢复表中可见文本，不推断航段语义或读取参考库。`test_rebuilds_interleaved_database_rf_table_row_from_word_positions` 覆盖该对象流交错模式。
- 验证：重新解析 2608 PDF/CSV 后，数据库编码程序段从 4853 增至 4878；完整候选的普通终端程序拒绝从 13 降至 4，写入程序从 1984 增至 2004、航段从 9327 增至 9776。`integrity_check=ok`，全量 pytest 85 passed。候选 SHA-256 `43c9690e6831bfa479f1fa1c1f593f6ca866f0be2b501e3fb90228abebedc03f` 仍不等于参考 `ca9cdd72b80d46b4c28e884bcd2ecf4b29bc54489704771d7908b32c6e3c510f`，因此仍为不可部署的测试候选。

## 2026-08-08 终端程序台站坐标后备

- 适用范围：Fenix 2608 终端程序固定点解析。`ZGHA/GUS-1W` 的固定点 `W` 不在终端坐标页或 `DESIGNATED_POINT.csv`，但 `NDB.csv` 第 71 行明确给出谷塘台 `W` 的坐标，候选库中存在唯一的同标识近距航点。
- 解决方式：仅当本场终端坐标页和指定点均无该标识时，使用全局唯一的 VOR/NDB 来源坐标；多坐标台站仍按现有歧义规则拒绝。`test_terminal_procedure_resolution_falls_back_to_unique_navaid` 覆盖该优先级。
- 验证：使用已重新解析的 PDF/CSV 模型生成候选后，`GUS-1W` 被投影，普通终端程序拒绝从 4 降至 3，程序为 2005、航段为 9790，`integrity_check=ok`。候选仍不等于参考，禁止部署或发布。

## 2026-08-08 分钟坐标无末尾引号

- 适用范围：2608 终端坐标页。`Terminal/ZHXY/ZHXY-4E.pdf` 明确打印 `XY608 N32°35.4'E114°20.1`；最后一个经度分钟字段未带引号，旧 `_DM_COORDINATE` 因强制末尾引号拒绝该行。
- 解决方式：分钟格式的末尾分隔符改为可选，仍要求完整的 N/E、度和分钟字段；`test_pairs_coordinate_page_row_without_terminal_longitude_quote` 使用同一 PDF 的 word 坐标行覆盖。证据缓存版本随解析行为升级。
- 验证：重新解析完整 PDF/CSV 后，`XY608` 被写入终端航点并投影 `P536-09D`、`P536-19D`；普通终端程序拒绝从 3 降至 1，程序为 2007、航段为 9796，`integrity_check=ok`。唯一剩余普通程序拒绝为 `ZYTN/NUBKI-19D` 的 `HF` 航段；候选仍不可部署或发布。

## 2026-08-08 HF 保持至定位点航段

- 适用范围：Fenix 2608 终端数据库编码页的 `HF` 航段。`Terminal/ZYTN/ZYTN-4Z01.pdf` 为 `NUBKI-19D` 明确打印 `HF TN653 Y 257 L`，高度列为 `1800 m / or by ATC`。该页的高度文字基线比 HF 主行高约 6 点，排序后位于其紧邻前行；同页 `HM` 采用相同版式。
- 解决方式：HF 与 HM 共用保持属性解析和 Fenix `TrackCode` 投影；仅在保持航段无其他高度时，使用紧邻前置的纯数字高度行。`test_extracts_holding_to_fix_course_altitude_and_turn` 与 HF 投影 fixture 覆盖航向、转向和 1800m 到 `5900A` 的量化，未读取参考记录。
- 验证：完整重新解析后 `NUBKI-19D` 的 HF 解析为 `TN653/257/L/1800m`；候选普通终端程序拒绝归零，程序为 2008、航段为 9802，`integrity_check=ok`。现有 `HM` 保持航段仍按专用延后策略计数 309 条，候选仍不可部署或发布。
