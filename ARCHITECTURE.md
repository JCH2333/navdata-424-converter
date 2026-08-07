# 架构

`source` 只读取 NAIP CSV、图表索引和 PDF，并生成保留来源的中间模型。`fenix` 是唯一了解 Fenix SQLite 字段和替换顺序的适配器。`validation` 不修改候选，只检查模板契约、引用和报告。`deployment` 负责停止检查、备份、复制和恢复。

Fenix 官方库是 schema 与全球数据模板；NAIP 是中国区域导航内容来源；参考成品只可传给校验器做本地字节和内容诊断。三者不得混用。
