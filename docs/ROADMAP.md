# Roadmap

## v0.1 — PNG（已完成）
- [x] 项目骨架、统一 Node 模型、DataSource、Parser Registry
- [x] PNG magic 检测、chunk 遍历 + CRC、IHDR 字段级节点
- [x] 虚拟化 Hex + Structure Tree + Field Inspector
- [x] 结构 ↔ Hex 双向定位、数据解释器、Go to offset
- [x] CLI `inspect / validate / info`，语料含损坏变体 + fuzz

## v0.2 — 搜索与 WAV / JPEG（已完成）
- [x] Hex/ASCII 服务端流式搜索（窗口重叠跨块不漏，Ctrl+F）
- [x] WAV parser（RIFF 子块 + fmt 字段级 + 时长）
- [x] JPEG parser（marker 遍历 + SOF/DQT/JFIF/EXIF + 熵编码扫描）

## v0.3 — ZIP 与结构关系（已完成）
- [x] ZIP parser：EOCD → CD → Local Header，**Central ↔ Local relation**
- [x] CRC32 全量校验（诚实标注未验证的方法）
- [x] 截断档抢救模式（EOCD 丢失时按 Local Header 顺序扫描）
- [x] `ffe report`（Markdown/JSON）
- [x] Go to offset 支持节点名；校验汇总面板（✓/⚠/✗ 可点击）

## v0.4 — PE（已完成）
- [x] DOS Header → COFF → Optional Header（PE32/PE32+）→ Data Directories → Sections（含 Raw data）
- [x] Imports（DLL + 函数名，thunk 宽度自适应）与 Exports
- [x] 全指针 RVA 映射 + 有界循环；真实系统文件语料（notepad.exe/winbrand.dll）

## v0.5 — ELF（已完成）
- [x] ELF64 头/Program Headers/Section Headers（名称经 shstrtab 解析）
- [x] Symbol tables（link 关联 strtab）；Raw data 节点
- [x] `ParseResult.ok` 改为派生属性（全局正确性）
- [x] 手工构造自洽语料 + 3 种损坏变体

## v0.6 — SQLite（已完成）
- [x] 100 字节文件头；全页分类（B-tree 内部/叶、自由页）
- [x] varint + record 解码（rowid + 值）；溢出行标注
- [x] sqlite_schema 解码 + **schema 对象 ↔ root page relation**（Inspector 可点击跳转）
- [x] Freelist 链遍历；stdlib sqlite3 生成真实语料

## v0.7 — MP4（已完成）
- [x] Box 层级递归（64-bit largesize、size==0、深度/数量上限）
- [x] mvhd/tkhd/hdlr/mdhd/stsd 字段级（timescale/duration/尺寸/handler/codec）
- [x] 手工最小结构档语料 + 2 种损坏变体

## v0.8 — Diff（当前，引擎已完成）
- [x] 字节 diff：合并 run（阈值 16B）、公共前缀、差异计数
- [x] 结构化 diff：按路径 + 同名去重匹配，added/removed/changed
- [x] `ffe diff a b [--json]`；`Width: 320 → 128` 级别的输出
- [ ] GUI 双栏 diff 视图（引擎已就绪）

## v0.9+ — 探索方向
- [ ] 二进制编辑（Safe Editing Model，禁止原地写）
- [ ] 自定义 schema / Kaitai 调研
- [ ] MP3、PDF（高价值但复杂，最后做）
- [ ] 大文件性能基准（1MB/100MB/1GB）

原则（见 DECISIONS.md）：一个格式的体验做到位再加下一个。
