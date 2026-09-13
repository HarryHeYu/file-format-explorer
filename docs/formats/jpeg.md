# JPEG Format Notes

## 基本信息

- **Magic**: `FF D8 FF`（SOI + 第一个 marker 的 0xFF）
- **字节序**: marker 段内长度/字段为大端
- **参考**: ITU-T T.81 / JPEG (jpeg.org)
- **实现**: `ffe/parsers/jpeg.py`

## 文件结构

```text
SOI (FFD8)
Segment*
  Marker   FFxx       （SOI/TEM/RSTn 无长度字段）
  Length   u16 BE     （含长度字段自身的 2 字节）
  Payload  Length-2 B
SOS (FFDA)
  段头 + 熵编码扫描数据（FF00 填充 / FFD0-D7 重启标记 / FFFF 填充）
EOI (FFD9)
```

## 实现状态

| 特性 | 状态 |
|---|---|
| marker 遍历 | ✅ 全部标准 marker 命名（SOF0-15、DHT、DQT、APPn、COM、DRI、RSTn…） |
| SOF 字段级 | ✅ Precision / Height / Width / Components（含渐进 SOF2 等 13 种） |
| DQT | ✅ 表摘要（id、8/16-bit、64 entries），按 Pq/Tq 规则遍历多表 |
| APP0 JFIF | ✅ version / density unit / X/Y density |
| APP1 EXIF | ✅ 检测 `Exif\0\0` 头并标注存在（TIFF IFD 未解析，见 DECISIONS D11） |
| DRI | ✅ Restart interval 字段 |
| 熵编码扫描 | ✅ 整体跳过，呈现为 "Entropy-coded scan" data 节点 |
| marker 失步 | ✅ 期望 0xFF 处读到其他字节 → error 节点 + 停止 |
| 截断 | ✅ EOI missing message |
| 段长超界 | ✅ error 节点 + 停止 |

## 已知限制 / 未支持

- 不解码像素、不显示图像预览。
- EXIF/TIFF IFD、ICC profile（APP2）、XMP（APP1 另一种）不解析内容。
- DHT 霍夫曼表内容未解码（仅保留段范围）。
- 12-bit / lossless JPEG（SOF3）能遍历结构但字段时间语义未特殊处理。

## 测试语料（tests/corpus.py → samples/jpeg/）

| 文件 | 覆盖 |
|---|---|
| gradient_256x128.jpg | PIL 基线 JPEG，双 DQT + 多 DHT + SOF0 + SOS + EOI |
| with_exif.jpg | 带 EXIF（Make/DateTime） |
| gray_256x128.jpg | 灰度（components=1） |
| corrupt/jpeg_truncated.jpg | EOI 前截断 |
| corrupt/jpeg_desync.jpg | SOF marker 被改写 → lost marker sync |
