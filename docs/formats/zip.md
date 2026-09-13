# ZIP Format Notes

## 基本信息

- **Magic**: 无前缀 magic。锚点是文件尾的 EOCD 签名 `PK\x05\x06`
  （`probe()` 反向搜索最后 64KB+22，容忍注释）；文件以 `PK\x03\x04` 开头
  但无 EOCD 时按“截断 ZIP”识别
- **字节序**: 小端（Little Endian）
- **参考**: PKWARE APPNOTE.TXT
- **实现**: `ffe/parsers/zip.py`

## 文件结构

```text
[Local File Header + File Data]*        ← 流式视角（字节在磁盘上的顺序）
[Central Directory entry]*              ← 汇总视角（权威元数据）
EOCD (PK\x05\x06)                       ← 唯一可靠锚点
```

同一文件在档内出现两次：Local Header（供流式读取）和 Central Directory
条目（供随机访问）。Explorer 把两者都展示并用 relation 关联。

## 实现状态

| 特性 | 状态 |
|---|---|
| EOCD | ✅ 反向搜索；Entries、CD size/offset 字段级 |
| Central Directory | ✅ 每条目：filename / method / sizes / CRC32 / DOS 时间 / local offset |
| Local File Header | ✅ 同上；bit3 data-descriptor 模式下注明"sizes 在数据之后" |
| **Central ↔ Local 关系** | ✅ `metadata.relation = {label: "Local File Header", nodeId}`，描述中含 `Local File Header at 0x…` |
| CRC32 校验 | ✅ Stored 直接验；Deflate 解压后先比 usize 再 CRC；其他方法诚实标注未验证 |
| 截断档 | ✅ 数据不足 → per-entry error；EOCD 丢失 → 顺序抢救 Local Header |
| 非 ZIP | ✅ 无锚点 → unrecognized |

## 已知限制 / 未支持

- 不解压展示文件内容（校验时解压但不呈现 payload）。
- ZIP64（4GB+/65535+ 条目）、加密档、分卷档未实现（遇到会按普通字段展示，
  sizes 可能读不懂但不会崩溃）。
- bzip2/LZMA 等 method 不做内容校验。
- 目录条目（`name/` 结尾）正常展示，不建树形嵌套。

## 测试语料（tests/corpus.py → samples/zip/）

| 文件 | 覆盖 |
|---|---|
| mixed.zip | Deflate + Stored + 嵌套目录 + 空文件，4 条目 |
| corrupt/bad_data_crc.zip | Deflate 数据翻转 1 字节 → CRC MISMATCH |
| corrupt/truncated.zip | 对半截断 → EOCD 丢失，抢救模式，stored.bmp 标记截断 |
| corrupt/not_a_zip.zip | 纯文本 → unrecognized |
