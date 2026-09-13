# SQLite Format Notes

## 基本信息

- **Magic**: `SQLite format 3\x00`（16 字节）
- **字节序**: 文件头多字节字段大端；行内整型按 serial type 有符号大端
- **参考**: SQLite file format (sqlite.org/fileformat2.html)
- **实现**: `ffe/parsers/sqlite.py`；语料由 stdlib sqlite3 生成

## 文件结构

```text
Page 1 = 100B 文件头 + sqlite_schema 的 b-tree 根
Page N = B-tree 页 / freelist trunk / overflow / ptrmap
B-tree 页头: type(2=索引内部,5=表内部,10=索引叶,13=表叶)
             cell 数 / 内容偏移 / [右指针] / cell 指针数组
表叶 cell: payload_len varint, rowid varint, record
record: header(varint 长度 + serial types) + 值
```

## 实现状态

| 特性 | 状态 |
|---|---|
| 文件头 | ✅ magic/page size/版本(WAL 检测)/freelist 指针/编码 |
| 页分类 | ✅ 每页标注：内部表/叶表/内部索引/叶索引/自由页 |
| 表叶行解码 | ✅ varint + record serial types → rowid + 值（前 6 个） |
| 溢出行 | ✅ 标注 "payload N B, first M B, overflow follows" |
| sqlite_schema | ✅ 解码全部 schema 对象（table/index），并关联 root page |
| **Schema ↔ Page 关系** | ✅ `metadata.relation` → 对应页节点，Inspector 中可点击跳转 |
| Freelist | ✅ 从 header trunk 链遍历（防环，上限 1024） |
| 容错 | ✅ 坏 cell → error；坏 magic → unrecognized；截断不崩溃 |

## 已知限制 / 未支持

- 不解码 overflow 页链的完整 payload（只标注存在）。
- 不解析 interior 页的 key 分布、不做索引内容解读。
- WAL 文件（-wal/-shm）不解析。
- 保留空间（encrypted/padding）按 0 处理。

## 测试语料（samples/sqlite/）

| 文件 | 覆盖 |
|---|---|
| demo.sqlite | 2 表 + 1 索引 + 250 行 + 删除一半（真实 sqlite3 生成） |
| corrupt/bad_magic.sqlite | magic 破坏 → unrecognized |
| corrupt/truncated.sqlite | 截断 1/3 → 页遍历降级不崩溃 |
