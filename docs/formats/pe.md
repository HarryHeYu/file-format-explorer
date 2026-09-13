# PE Format Notes

## 基本信息

- **Magic**: `MZ`（offset 0）；真正的锚点是 `e_lfanew`（offset 0x3C）指向的 `PE\0\0`
- **字节序**: 小端（Little Endian）
- **参考**: PE Format spec (Microsoft PE/COFF, learn.microsoft.com)
- **实现**: `ffe/parsers/pe.py`

## 文件结构

```text
DOS Header (64B, e_lfanew → PE 头偏移)
DOS Stub                  ← "This program cannot be run in DOS mode"
PE Signature PE\0\0
COFF Header (20B)         Machine / NumberOfSections / Characteristics
Optional Header           PE32 (0x10B) 或 PE32+ (0x20B, 64位)
  Data Directories (16×8B) ← Export/Import/Resource/Reloc/IAT… 的 RVA
Section Table (40B × N)   .text / .rdata / .data / .rsrc / .reloc …
Import Table              IDT → DLL 描述符 → thunk 数组 → 函数名
Export Table              导出目录 → 函数名指针数组
```

## 实现状态

| 特性 | 状态 |
|---|---|
| DOS Header | ✅ e_magic / e_lfanew（越界判定） |
| DOS Stub | ✅ 作为 data 范围（可搜索，如 "This program"） |
| COFF Header | ✅ Machine / NumberOfSections / TimeDateStamp / Characteristics（含 DLL 判定） |
| Optional Header | ✅ PE32 与 PE32+；EntryPoint / ImageBase / 对齐 / Subsystem |
| Data Directories | ✅ 16 项，非空项逐个展示（RVA + size） |
| Section Table | ✅ 每节：Name / VirtualAddress / VirtualSize / SizeOfRawData / PointerToRawData / Characteristics（flags 展开）；**Raw data 节点**可直接点进字节 |
| RVA→offset | ✅ 经 section 表映射（头部区域直接映射） |
| Import Table | ✅ DLL 列表 → Functions（按名/按序号）；PE32 与 PE32+ thunk 宽度自适应 |
| Export Table | ✅ DLL 名、函数数、名称列表（上限 4096） |
| 入口点校验 | ✅ entry RVA 映射不到任何 section 时报错 |
| 边界检查 | ✅ section 数据超界 → error 节点；e_lfanew 越界 → 提前退出 |
| 防失控 | ✅ sections≤96、DLL≤512、函数≤8192、导出名≤4096 的硬上限 |

## 安全设计

所有循环有界（MAX_* 常量）；所有 RVA 先经 rva_to_off 映射并判 None；
所有 read 走 DataSource 自动钳制。解析 notepad.exe（50 DLL / 315 函数）毫秒级完成。

## 已知限制 / 未支持

- 资源树只显示目录范围，不展开 RT_ICON 等层级。
- 重定位表、TLS、Debug（PDB 路径）、CLR 元数据只显示范围不解析。
- 延迟导入（Delay Import）未解析。
- 符号表（COFF symbols）被现代链接器废弃，未解析。
- 不做反汇编——Explorer 展示结构，不做 IDA。

## 测试语料（samples/pe/）

| 文件 | 覆盖 |
|---|---|
| notepad.exe | 真实系统文件：x64、GUI、8 sections、50 DLL/315 函数 import |
| winbrand.dll | 真实 DLL：Export Table、Certificate Table、api-ms-* 转发 |
| corrupt/bad_pe_sig.dll | PE 签名被改写 → ok=False |
| corrupt/truncated.exe | 只留前 2KB → 所有 section 超界 error |
