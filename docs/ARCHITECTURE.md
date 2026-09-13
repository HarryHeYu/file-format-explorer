# Architecture

## 总览

```
┌──────────┐   ┌───────────────────────────────┐
│ CLI      │──▶│  ffe.api (inspect)            │
└──────────┘   └───────────────┬───────────────┘
┌──────────┐                   ▼
│ GUI 服务 │──▶ Format Detection ─▶ ParserRegistry
│ (stdlib) │                          │
└────┬─────┘                 FormatParser.parse(DataSource)
     │ HTTP/JSON                        │
     ▼                                  ▼
浏览器单页 UI  ◀────  ParseResult (Node 树, 统一结构模型)
(虚拟化 Hex / Tree / Inspector)
```

核心原则：**UI 不依赖任何具体格式的数据结构**。PNG/WAV/PE/… 都只产出统一的
`ParseResult`（一棵 `Node` 树），UI 只消费这棵树。

## 统一结构模型（ffe/core/model.py）

```text
Node
├─ name / kind          container | field | data | error | info
├─ offset / size        该节点在文件中的绝对位置与覆盖字节数
├─ value                解码后的语义值（int / str / "0x… (valid)"）
├─ data_type / endian   uint32、chunk-type、timestamp…
├─ raw                  小字段的原始字节（用于 Inspector 直接展示）
├─ validation           ok | warning | error
├─ description          人话解释
├─ children / metadata
└─ id                   稳定 id，前端用于节点 ↔ 字节互查
```

`parent` 反向链接由 `link_parents()` 统一建立，`path_string()` 生成
`PNG / IHDR / Data / Width` 这样的可读路径。

### 节点范围的语义约定

- 一般规则：子节点的 `[offset, end)` 必须落在父节点范围内（GUI 契约测试校验此项）。
- 唯一例外是**描述符模式**（PE/ELF 的 section 节点）：节点锚定它在表中的
  40/64 字节表项，其下的 `Raw data` 子节点指向文件另一处的真实数据。
  这是刻意设计（DECISIONS D16）——点击表项看元数据，点开 Raw data 看字节。
  前端 `deepestAt()` 用扁平范围匹配，不受父子包含关系影响。

## 数据访问（ffe/core/datasource.py）

`DataSource` 只提供有界读取（自动 clamp 到 EOF），从不整读文件。
GUI 的 Hex 视图按 64KB 窗口经 `/api/bytes` 拉取并缓存在前端；
将来超大文件只需把 DataSource 换成 mmap 实现，parser 不用改。

## 格式检测与注册（ffe/core/registry.py）

- `FormatParser` 基类：`probe()` / `parse()`。
- `@register` 装饰器自注册；`load_parsers()` 显式导入内置 parser。
- 检测只认 magic bytes（扩展名永不参与判断——错误扩展名的 PNG 仍被识别）。
- UI/CLI 永远不写 `if format == "png"`。

## GUI（ffe/gui_server.py + gui/static/）

- 服务端仅用标准库 `http.server`：静态文件 + 四个 API
  （`/api/open` 解析一次、`/api/bytes` 按需读窗口、`/api/search` 字节/文本搜索、
  `/api/formats` 注册格式列表）。字节→节点的反向定位由前端在解析树上完成，
  无需服务端按 offset 查询的端点。
- 前端原生 JS 单页：
  - **Hex 虚拟化**：16 字节/行、行高固定，只渲染可视区 ±缓冲，spacer 撑起
    总高度；因此 1GB 文件的浏览成本与 1KB 相同。
  - **反向定位**：解析时把所有 `size>0` 节点扁平化并按 size 排序，
    点击字节时线性找“包含该字节的最小节点”即最深节点（节点数 < 万级，足够快）。
  - **正向定位**：节点带 id/offset/size，点击即滚动 + 高亮区间
    （只给可视行加样式，大范围高亮不产生渲染负担）。

## 容错策略（Parser 安全）

- 所有 parser 收到的都是不可信输入：length/offset 一律不信任，
  读取走 `DataSource`（自动 clamp），CRC/边界异常都转成 `error` 节点而不是异常。
- chunk 长度超过文件边界时：停止解析、标记错误、报告剩余字节，绝不 panic。
- 未知 chunk 类型：照常保留 offset/length/CRC，仅不解码内容。

## 已知取舍

- 反向定位目前是前端线性扫描（按 size 排序后提前退出并不做，因为通常命中即前段）；
  格式多了以后可换排序区间树。数据模型已支持，见 DECISIONS.md。
- 大范围（如整个 IDAT）的高亮只作用于可见行，符合“不一次渲染整个范围”的要求。
