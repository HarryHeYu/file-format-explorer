# WAV Format Notes

## 基本信息

- **Magic**: `RIFF`（offset 0）+ `WAVE`（offset 8）——不是前缀 magic，走 `probe()`
- **字节序**: 小端（Little Endian）
- **参考**: RFC 2361 / multimediawiki RIFF spec
- **实现**: `ffe/parsers/wav.py`

## 文件结构

```text
"RIFF"  u32le size  "WAVE"
Sub-chunk*
  id      4B ASCII   "fmt " / "data" / "LIST" / "fact" / ...
  size    u32le
  data    size B     （size 为奇数时跟随 1 字节 padding）
```

## 实现状态

| 特性 | 状态 |
|---|---|
| RIFF 头 | ✅ magic / size（与实际文件大小对比）/ form type |
| 子块遍历 | ✅ 含奇数长度 padding 对齐 |
| `fmt ` 字段级 | ✅ Audio format（codec 名）、Channels、Sample rate、Byte rate、Block align、Bits per sample，各为独立可点击节点 |
| Byte rate 一致性 | ✅ `byteRate != sampleRate × blockAlign` 时给出 warning message |
| 时长 | ✅ `data.size / byteRate`，写入 `metadata.audio.duration` |
| `fact` | ✅ Sample length (frames) 字段 |
| LIST/INFO | ✅ 作为子块保留（内容不解码） |
| 超界 size | ✅ error 节点 + 停止解析；若为 data 块则记录剩余字节 |
| RIFF size 撒谎 | ✅ message 指出 declared vs actual |

## 已知限制 / 未支持

- 不播放、不解码音频样本（data 只显示范围）。
- WAVE_FORMAT_EXTENSIBLE (0xFFFE) 只显示 codec 名，不解析 SubFormat GUID。
- 嵌套 RIFF（LIST 内子块）按不透明 payload 保留。

## 测试语料（tests/corpus.py → samples/wav/）

| 文件 | 覆盖 |
|---|---|
| sine_440_16bit_mono.wav | stdlib wave 生成，1 秒 440Hz，44.1kHz/16bit/mono |
| stereo_8bit_list.wav | 手工在 fmt 与 data 之间拼接 LIST/INFO 子块 |
| corrupt/wav_bad_riffsize.wav | RIFF size 声称 1GB |
| corrupt/wav_truncated.wav | 文件对半截断 → data 超界 error |
