# File Format Explorer (ffe)

把“文件格式规范”从文档变成可以点击、观察、探索的东西。

打开一个文件 → 识别格式 → 解析二进制结构 → 结构树 ↔ Hex 双向定位 → 逐字段解释。

## 当前状态：v0.8（PNG + WAV + JPEG + ZIP + PE + ELF + SQLite + MP4 + 搜索 + Diff + 报告）

- ✅ 八种格式（magic 检测，不看扩展名）：
  - **PNG** chunk + CRC + IHDR 字段级 · **WAV** RIFF + fmt 字段级 + 时长
  - **JPEG** marker 遍历 + SOF/DQT/JFIF/EXIF · **ZIP** CD↔Local relation + CRC32 + 截断抢救
  - **PE** DOS/COFF/Optional/Sections/Imports/Exports，全指针 RVA 映射
  - **ELF** 头/段/节/符号表（32/64-bit，LE/BE 自适应）
  - **SQLite** 页分类 + record 解码 + **schema↔root page relation**
  - **MP4** box 层级 + mvhd/tkhd/hdlr/stsd（timescale/duration/尺寸/codec）
- ✅ 结构 ↔ 字节双向定位（PE/SQLite/ZIP 的跨节点 relation 在 Inspector 中可点击跳转）
- ✅ Hex 搜索（hex/ASCII，Ctrl+F）· Go to offset（数字或节点名）· 校验汇总面板
- ✅ **Diff**：`ffe diff a b` — 字节差 run + 结构化 added/removed/changed（`Width: 320 → 128`）
- ✅ 报告导出：`ffe report`（Markdown/JSON，含 PE sections/imports 摘要）
- ✅ 虚拟化 Hex（按需 64KB 分块）· Field Inspector · 数据解释器 · 键盘导航
- ✅ 76 个测试 + 多轮对抗 fuzz（9700+ 变异 0 崩溃 0 挂起）+ 子代理代码评审/API 契约测试/文档审计；真实系统文件（notepad.exe、winbrand.dll）与真实生成数据库（sqlite3）
- ✅ CLI 与 GUI 共用同一 parser core

## 快速开始

```bash
# GUI（自动打开浏览器；可先传一个文件）
python -m ffe.gui_server path\to\image.png

# CLI
python -m ffe inspect samples/gradient_320x200.png
python -m ffe inspect samples/wav/sine_440_16bit_mono.wav --json
python -m ffe validate samples/corrupt/bad_crc.png
```

无第三方依赖，仅需 Python 3.10+。

## 测试

```bash
python -m unittest discover -s tests
```

测试语料（samples/）在首次运行时自动生成：PNG/WAV/JPEG/ZIP/ELF/SQLite/MP4 由
`tests/*_corpus.py` 脚本按需生成；PE 语料从 `C:\Windows\System32` 复制
notepad.exe 与 winbrand.dll（版权文件不入库，缺失时相关测试自动跳过）。

## 目录

```
ffe/
  core/         结构模型、数据源、注册表（与格式无关）
  parsers/      png.py …（每种格式一个模块）
  cli.py        命令行入口
  gui_server.py 本地 GUI 服务（标准库实现）
gui/static/     单页前端（原生 JS，虚拟化 hex）
docs/           架构 / 路线图 / 决策 / 格式文档
samples/        测试语料（含 corrupt/ 损坏变体）
```

详细文档见 [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md)、[docs/ROADMAP.md](docs/ROADMAP.md)、[docs/DECISIONS.md](docs/DECISIONS.md)、[docs/formats/png.md](docs/formats/png.md)。
