# 424 到 Fenix 导航数据转换器

测试版 Windows 工具：以用户本机的官方 Fenix 全球导航库为模板，读取本地 424/NAIP 数据并生成隔离候选目录。它不会提交、下载或分发任何导航数据库、航图或原始 CSV。

## 当前状态

`0.1.0` 是开发测试版。已实现结构化 CSV 的机场、跑道、VOR/NDB、航路点、航路和保持解析，Fenix schema/profile 校验、候选复制、区域替换、部署备份和更新包校验。终端 PDF 的程序语义提取尚未完成；无法可靠解析的图表会列入报告并阻止部署，绝不会静默写入不完整的 SID/STAR/IAP。

## 使用

```powershell
python -m pip install -e .
python -m navdata_converter.gui
python -m navdata_converter.cli convert --official-navdata C:\ProgramData\Fenix\Navdata --naip-root <2608\2608> --output <新目录>
```

候选必须通过校验并且没有被拒绝的程序，才会允许部署。部署前会检查 `FlightSimulator2024.exe` 已退出，并备份数据库与周期元数据。

## 开发约束

- 原始 NAIP、官方 Fenix 数据和生成结果均为本地输入/输出，不能提交。
- 参考 `fnx2608N` 仅可作为本地回归基准，不是转换内容来源。
- 未完成实机验证前仅可创建 GitHub 预发布测试包，不能创建正式 Release。
