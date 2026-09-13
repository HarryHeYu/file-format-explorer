# Decisions

按时间顺序记录重要技术决策及理由。

## D1 — 语言与 GUI：Python core + 标准库本地服务 + 原生 JS 前端

- **决定**：核心（模型/parser/CLI）用 Python；GUI 用 `http.server` 起本地服务、
  浏览器打开单页 UI；无任何第三方依赖。
- **理由**：跨平台、二进制处理与测试生态成熟、原型迭代快；
  Web 技术做虚拟滚动/高亮/布局最省力；避免 Electron/Qt 这类重架构。
  大文件场景由“按需窗口读取 + 前端虚拟化”保证，不依赖 mmap 也能达标；
  将来若需要可换 mmap DataSource，parser 不动。

## D2 — 统一 Node 模型，UI 零格式知识

- **决定**：所有 parser 输出 `ParseResult`（`Node` 树），字段级节点（如 IHDR/Width）
  与容器节点（如 IDAT）同构；UI 只消费树。
- **理由**：这是“结构 ↔ 字节双向定位”能泛化到未来所有格式的前提。

## D3 — 检测只信 magic，不信扩展名

- **决定**：`registry.detect()` 仅按 magic bytes 匹配。
- **理由**：产品定位是“看文件内部是什么”，扩展名是用户输入而非事实。

## D4 — 坏 CRC 等问题表达为 error 节点 + messages，不抛异常

- **决定**：损坏信息是数据（`validation="error"`、`messages[]`），不是控制流。
- **理由**：Corruption Explorer（第 22 节）要求把“哪里坏了”作为可浏览对象；
  parser 在坏文件上返回完整可展示的部分结构比抛错更有价值。

## D5 — 反向定位先用前端线性扫描，不预建区间树

- **决定**：解析结果里 `size>0` 的节点在前端扁平化，点击字节时线性查找最小包含节点。
- **理由**：单文件节点数在千级，线性查找 <1ms；避免过早优化。
  若未来 SQLite/MP4 等产生万级节点，再换有序区间结构（数据模型不变）。

## D6 — IHDR 字段全部挂在 "Data" 节点下，而不是直接挂在 chunk 下

- **决定**：`IHDR / Length / Type / Data / Width… / CRC`（Width 在 Data 里）。
- **理由**：offset 语义精确——Length/Type/CRC 是 chunk 头尾，Width 属于 data 区间；
  反向定位“最深节点”因此天然正确（0x10 命中 Width 而不是 IHDR）。

## D7 — v0.1 范围控制：不做 hex 编辑、不做搜索、GUI 不做书签

- **理由**：第 51 节明确排除；先把“点击 Width 看到 00 00 07 80”的核心体验
  做到可用并真实验收，第二格式（WAV）再进场。

## D8 — 搜索放在服务端，流式窗口匹配（v0.2）

- **决定**：`/api/search` 由 Python 按窗口流式读取并 `bytes.find`，窗口重叠
  `len(pattern)-1` 保证跨块命中；前端只渲染命中列表。
- **理由**：大文件搜索不能把文件传给前端；服务端 find 是 C 速度，内存 O(window)。
  空间换正确性的重叠窗口比 KMP 手写实现更简单可靠。

## D9 — WAV 用 probe() 而非 magic 前缀；detect 兜底对所有 parser 调 probe

- **决定**：RIFF 格式 magic 在偏移 0 是 "RIFF"、偏移 8 才是 "WAVE"，因此
  `magic` 留空、`probe()` 覆盖；`detect()` 第二遍对**所有** parser 调 probe。
- **教训**：最初第二遍有 `if p.magic and p.probe(src)` 条件，magic 为空的
  parser 永远不会被探测——测试立刻抓住了这个 bug。

## D10 — JPEG 熵编码扫描整体跳过，标记为 "Entropy-coded scan" data 节点

- **决定**：SOS 段头之后是压缩图像数据（FF00 填充、FFD0-D7 重启标记），
  按 JPEG 规则扫描到下一个真实 marker，这段数据以单个 data 节点呈现。
- **理由**：Explorer 的目标是结构可视化，不解码像素；逐字节解释扫描数据
  没有意义。窗口尾部 carry 逻辑必须处理 EOF（曾有 search 倒退死循环，测试抓出）。

## D11 — JPEG APP1 只标注 "EXIF present"，不解析 TIFF IFD

- **理由**：EXIF 是嵌套的完整 TIFF 文件，值得独立做；v0.2 先给出存在性 +
  offset，保证用户知道“这里有元数据、在哪”。与 PDF 延后同理。

## D12 — ZIP：EOCD 是唯一锚点；丢失时按 Local Header 抢救（v0.3）

- **决定**：正常路径 EOCD（从文件尾反向搜索，容忍 zip64 前的最长注释）→
  Central Directory → Local Header，以中央目录为准。EOCD 缺失但文件以
  `PK\x03\x04` 开头时，进入"抢救模式"：顺序扫描 Local Header 并标注截断。
  既无 EOCD 又无 Local Header → unrecognized。
- **理由**：ZIP 的可靠解析必须锚定 EOCD（Local Header 的 sizes 在 bit3
  data-descriptor 模式下不可信）；但截断档的抢救有真实价值，且错误信息
  应该可浏览（Corruption Explorer 定位）。

## D13 — Central ↔ Local 关系用 `metadata.relation.nodeId` 表达

- **决定**：CD 条目节点带 `relation = {label, nodeId}` 指向对应 Local 节点。
- **理由**：关系是 ZIP 最值得展示的结构事实（"同一文件的两种元数据视图"）。
  用现有 id 引用而不是新模型，UI 以后可以做点击跳转而不改数据模型。
  双向列表（local → central）暂不需要，Deep 节点路径已可反查。

## D14 — ZIP CRC 校验在解压后进行，method 未支持时跳过而非误报

- **决定**：Stored 直接 CRC；Deflate 解压后先比大小再 CRC；其他方法
  标注 "method not verified"，不给 error。
- **理由**：Explorer 的校验应诚实——没验证就说没验证，不制造假错误。

## D15 — PE 的一切访问经 RVA→offset 映射 + 有界循环（v0.4）

- **决定**：Import/Export 的所有指针先过 `rva_to_off()`（基于 section 表，
  判 None）；遍历硬上限 sections≤96 / DLL≤512 / 函数≤8192 / 导出名≤4096。
- **理由**：PE 是恶意/损坏文件最常出现的格式，任何"信任指针直接读"都会
  变成越界或死循环。上限意味着畸形文件得到"截断但完整可浏览"的结构。

## D16 — PE section 同时给出表项与 Raw data 节点

- **决定**：`.text` 等节点是 40 字节的表项描述，其下挂 `Raw data` 节点
  （offset=PointerToRawData, size=SizeOfRawData）。
- **理由**：表项是元数据，Raw data 才是字节本身——"点 .text 看代码字节"
  是 PE 探索最自然的动作，与"点击 IDAT 看压缩数据"同一体验。

## D17 — PE 语料用真实系统文件（只读复制），不只手工构造

- **理由**：现代 PE（api-ms-win-* 转发导入、Certificate Table、非常规
  section 名如 fothk/didat）在手工语料里永远见不到。测试第一版就抓到了
  "以为会直接导入 KERNEL32" 的错误假设——新版 notepad 全走 umbrella DLL。

## D18 — ELF 语料手工构造时布局必须顺序打包（v0.5）

- **教训**：第一版生成器用独立变量计算各段 offset，与实际拼接顺序差了
  对齐字节，产出"畸形 ELF"。parser 正确报错（意外 fuzz），但合法语料
  必须自洽——重写为顺序打包 + 显式对齐。手工构造二进制的通用教训：
  **offset 必须从单一游标推导，不能各算各的**。

## D19 — ParseResult.ok 改为派生属性（v0.5）

- **决定**：`ok` 不再是手填字段，而是"树中无 validation=error 节点"的派生。
- **理由**：ELF 截断档曾报 ok=True（忘了手工置位）。正确性不依赖每个
  parser 记得设置它——从数据推导而不是命令式赋值。

## D20 — diff 以结构对比为主、字节 diff 为辅（v0.8）

- **决定**：`ffe diff a b` 同时给出合并的字节差 run（阈值 16B 合并）和
  结构级 added/removed/changed（按唯一化路径匹配同名兄弟节点）。
- **理由**：roadmap 明确"structured diff 比 raw byte diff 更重要"——
  用户想知道 `Width: 320 → 128`，而不是 12 万个差异字节。
  GUI 双栏 diff 留待后续（引擎与 CLI 已可用，见 ROADMAP）。

## D21 — MP4 语料手工构造最小结构档（v0.7）

- **理由**：无 ffmpeg/PIL 视频能力。MP4 的 Explorer 价值在 box 层级而非
  解码，最小结构档（ftyp/moov/mdat + 完整 trak 链）即可全覆盖解析路径；
  解码器兼容性与本产品无关。

## D22 — 独立审查轮：多代理评审是必要的（v0.8 之后）

- **过程**：4 个子代理并行审查——对抗 fuzz、代码评审、API 契约测试、文档审计。
- **战果**：
  - fuzz（2400+4000+3000 变异）：抓出 7 个 P0——ELF32 解包漏字段名
    （任何 ELF32 必崩）、EI_CLASS 未校验、phentsize/shentsize 可信、
    struct.unpack 的"精确长度"陷阱（超长同样报错）、PE dirs 越界、
    PE Optional Header 无最短长度检查、PE 导出名指针无边界。
  - 代码评审：抓出 2 个 P0 规格错误——WAV fmt 字段按均匀 2 字节步进
    （实际布局 0/2/4/8/12/14，GUI 高亮的是错误字节）、MP4 tkhd 偏移差
    8 字节（把 duration 当 Track ID）；外加 SQLite 行节点 size 语义错误、
    JPEG DQT 无 offset、PE 解析状态存共享单例（线程不安全）等。
  - 契约测试：负偏移 500、多处容器不含子节点。
- **结论**：74 个测试全绿的代码仍藏着这些——单元测试验证"值对"，
  防不住"字段偏移/语义错"和并发问题；fuzz 防崩溃但防不了语义错误。
  三者互补，缺一不可。修复后 76 测试 + 9700+ 变异全过。

## D23 — 节点范围的"描述符模式"是显式模型规则

- **决定**：子节点范围必须落在父节点内，唯一例外是 PE/ELF 的 section
  表项节点（锚定表内 40/64 字节）及其 `Raw data` 子节点（指向文件另
  一处的数据）。已写入 ARCHITECTURE.md，契约测试按此豁免。
