# PNG Format Notes

## 基本信息

- **Magic**: `89 50 4E 47 0D 0A 1A 0A`（8 字节）
- **字节序**: 全部大端（Big Endian）
- **参考**: PNG (ISO/IEC 15948), https://www.w3.org/TR/PNG/
- **实现**: `ffe/parsers/png.py`

## 文件结构

```text
Signature (8B)
Chunk*
  Length   uint32 BE — Data 的字节数
  Type     4B ASCII  — "IHDR" / "IDAT" / ...
  Data     Length B
  CRC      uint32 BE — crc32(Type + Data)
```

## 实现状态

| 特性 | 状态 |
|---|---|
| Signature 校验 | ✅ 无效签名 → 整个文件判为“非 PNG”（unrecognized） |
| Chunk 遍历 | ✅ 含 offset / length / type / data range / CRC |
| CRC 校验 | ✅ 每个 chunk，`0x… (valid)` 或 `mismatch, expected 0x…` |
| IHDR 字段级拆分 | ✅ Width / Height / Bit Depth / Color Type / Compression / Filter / Interlace 各为独立可点击节点 |
| tEXt / zTXt / iTXt | ✅ Keyword 字段 + 解压后文本（metadata.text） |
| gAMA / pHYs / sRGB / tIME | ✅ 字段级解码 |
| PLTE / iCCP / IDAT | ✅ 作为 Data 范围保留（内容解码未做） |
| 未知 chunk | ✅ 照常保留 offset/length/CRC + ancillary/private/safe-to-copy 标志位 |
| 截断文件 | ✅ 标记 truncated / missing CRC / IEND missing |
| 超界 length | ✅ `chunk exceeds file boundary` error 节点 + 停止解析 |
| Trailing bytes | ✅ `Trailing garbage` error 节点 |

## 已知限制 / 未支持

- 不解压/显示像素（不做图像预览），IDAT 只显示数据范围。
- 不解析 iCCP 内嵌 ICC profile 内容、PLTE 调色板条目、hIST/sPLT/bKGD 等罕见 chunk
  （它们仍以通用 chunk 形式展示，不会丢失或报错）。
- 多 IDAT 拼接解码、interlaced 行解码均属解码器范畴，不在 Explorer 目标内。

## 测试语料（tests/corpus.py 生成到 samples/）

| 文件 | 覆盖 |
|---|---|
| minimal.png | 1×1 最小合法 PNG |
| gradient_320x200.png | 普通图像 |
| metadata.png | tEXt×2 + gAMA + pHYs + sRGB + tIME + 未知 chunk zzZz |
| gradient_1024x768.png | 较大文件 |
| corrupt/bad_signature.png | 无效 magic → unrecognized |
| corrupt/truncated.png | IDAT 中途截断 |
| corrupt/bad_crc.png | IHDR CRC 翻转 → mismatch |
| corrupt/insane_length.png | length 声称 500MB → 超界 error |
| corrupt/missing_iend.png | 缺 IEND |
| corrupt/actually_text.png | 纯文本 → unrecognized |

## Chunk 标志位

Type 的 4 个字节按位给出语义，解析器存入 `metadata.flags`：
ancillary（首字母小写）、private、reserved bit、safe-to-copy（末字母小写）。
工具栏提示如 `zzZz`：ancillary、private、unsafe-to-copy。
