# MP4 Format Notes

## 基本信息

- **Magic**: 首个 box 为 `ftyp`（offset 4-8）——无固定文件头 magic，走 `probe()`
- **字节序**: 大端（Big Endian）
- **参考**: ISO/IEC 14496-12 (ISO BMFF) / 14496-14 (MP4)
- **实现**: `ffe/parsers/mp4.py`；语料 `tests/mp4_corpus.py`（手工构造最小结构档）

## 文件结构

```text
Box = size(u32 BE) | type(4CC) | [largesize u64 if size==1] | payload
size==0 → box 延伸到 EOF
容器 box（moov/trak/mdia/minf/stbl/…）递归嵌套
ftyp → [free] → moov{mvhd, trak{tkhd, mdia{mdhd, hdlr, minf{stbl}}}} → mdat
```

## 实现状态

| 特性 | 状态 |
|---|---|
| Box 遍历 | ✅ 层级递归（深度≤12、每层≤4096、总数≤200000 的硬上限） |
| 64-bit largesize / 到 EOF 的 size==0 | ✅ |
| ftyp | ✅ major brand / minor version / compatible brands |
| mvhd | ✅ timescale / duration（v0/v1 两种布局）+ 秒换算 |
| tkhd | ✅ track id / 16.16 定点 dimensions |
| hdlr | ✅ handler 类型（vide/soun/hint/meta） |
| mdhd | ✅ media timescale |
| stsd | ✅ codec fourcc（avc1/mp4a/…） |
| mdat | ✅ payload 字节范围节点 |
| 坏 size / 截断 | ✅ error 节点 + 停止该层 |

## 已知限制 / 未支持

- 不解码任何媒体内容；stco 指向的 chunk 不做交叉引用展示。
- 其他 box（stsc 语义、elst、sgpd…）仅按范围保留。
- 片段档（moof/traf）能遍历结构但不聚合片段时长。

## 测试语料（samples/mp4/）

| 文件 | 覆盖 |
|---|---|
| minimal.mp4 | 手工最小档：ftyp/free/moov(mvhd+trak(tkhd+mdia(mdhd+hdlr+minf(smhd+dinf+stbl(stsd+stts+stsz+stco)))))/mdat |
| corrupt/bad_size.mp4 | ftyp size 声称 10MB → error |
| corrupt/truncated.mp4 | moov 内截断 → error |
