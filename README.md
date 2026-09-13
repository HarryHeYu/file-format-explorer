# File Format Explorer (ffe)

把“文件格式规范”从文档变成可以点击、观察、探索的东西。

打开一个文件 → 识别格式 → 解析二进制结构 → 结构树 ↔ Hex 双向定位 → 逐字段解释。
点击结构树里的 `Width = 1920`，左边真实文件里的 `00 00 07 80` 会被高亮——
你能直观看到“1920 是怎么存在文件里的”。

## 它能做什么

**结构探索**（8 种格式，magic 检测、不信任扩展名）

| 格式 | 解析深度 |
|---|---|
| PNG | chunk 遍历 + CRC 校验，IHDR 逐字段，文本/色彩元数据 |
| WAV | RIFF 子块，fmt 逐字段（编解码器/声道/采样率），时长计算 |
| JPEG | marker 遍历，SOF 尺寸/DQT 表/JFIF/EXIF 检测 |
| ZIP | 中央目录 ↔ 本地文件头双向关联，CRC32 全量校验，截断抢救 |
| PE | DOS→COFF→Optional→Sections→Imports/Exports，指针全部经 RVA 映射 |
| ELF | 32/64-bit、大小端自适应，段/节/符号表 |
| SQLite | 页分类（B-tree/自由页），行解码，schema 对象 ↔ root page 跳转 |
| MP4 | box 层级递归，timescale/时长/分辨率/编解码器 |

**交互**：结构树 ↔ Hex 双向定位（跨节点关系可点击跳转）、Hex/ASCII 搜索、
按 offset 或节点名跳转、损坏位置汇总面板、虚拟化 Hex（大文件只按需读 64KB 窗口）、
选中字节的数据解释器。

**容错**：解析器把输入当不可信数据——截断、坏 CRC、超界指针、伪 length 都
变成可浏览的错误节点，永不崩溃。损坏文件本身就是可探索的对象。

**工程**：CLI 与 GUI 共用同一 parser core；76 个测试；9700+ 变异 fuzz 无崩溃；
经独立代码评审、API 契约测试与文档审计（记录见 docs/DECISIONS.md D22）。

## 快速开始

```bash
# GUI（自动打开浏览器；可先传一个文件）
python -m ffe.gui_server path\to\image.png

# CLI
python -m ffe inspect 文件.png              # 结构树
python -m ffe inspect 文件.png --json       # JSON 输出
python -m ffe validate 文件                 # 校验（✓/✗）
python -m ffe diff 旧文件 新文件            # 字节差 + 结构差（Width: 320 → 128）
python -m ffe report 文件.exe               # Markdown 分析报告（--json 可选）
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

## 文档

- [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) — 架构与数据流
- [docs/ROADMAP.md](docs/ROADMAP.md) — 版本路线（v0.1 PNG → v0.8 diff，逐版可查）
- [docs/DECISIONS.md](docs/DECISIONS.md) — 23 条技术决策及理由
- [docs/formats/](docs/formats) — 每种格式的实现状态、已知限制、语料说明
