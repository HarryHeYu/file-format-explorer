# ELF Format Notes

## 基本信息

- **Magic**: `7F 45 4C 46`（`\x7fELF`）；e_ident 第 5/6 字节给出 32/64 位与字节序
- **字节序**: 由文件自身声明（ELF 支持 LE/BE，parser 自适应）
- **参考**: System V ABI / man 5 elf
- **实现**: `ffe/parsers/elf.py`；语料 `tests/elf_corpus.py`（按规范手工构造，每个 offset 自洽）

## 文件结构

```text
ELF Header          e_ident + type/machine/entry/phoff/shoff/counts
Program Headers*    segments (PT_LOAD/PT_DYNAMIC/...) — loader 视角
Section Headers*    .text/.data/.symtab/.strtab/.shstrtab — linker 视角
  shstrtab          section 名字符串表（shstrndx 指向）
  .symtab/.dynsym   符号表，link 指向对应 .strtab
```

## 实现状态

| 特性 | 状态 |
|---|---|
| Header | ✅ Class/Endianness/OSABI/Type/Machine/Entry/偏移与数量，32/64-bit 自适应；EI_CLASS/EI_DATA 非法值 → error |
| Program Headers | ✅ Type/offset/vaddr/filesz + 越界检测（phentsize 异常值安全：按固定类长度截取） |
| Section Headers | ✅ 经 shstrtab 解析名称；Type/Flags(展开)/Address/Offset/Size；**扩展编码**（shnum==0 → section 0 sh_size、shstrndx==SHN_XINDEX → sh_link） |
| Raw data 节点 | ✅ 每个 section 的字节范围可直接点击（SHT_NOBITS 除外） |
| Symbol tables | ✅ .symtab/.dynsym，按 link 找 .strtab 解析符号名（LOCAL/GLOBAL/WEAK） |
| 边界/上限 | ✅ section≤1024、segment≤256、符号≤16384；超限时 message 明示截断；表截断/超界 → error |

## 已知限制 / 未支持

- 动态段（.dynamic）、重定位（.rela/.rel）、NOTE 不解析内容。
- ELF32 语料已覆盖（minimal32.elf）；**大端（EI_DATA=2）代码路径已写但语料未覆盖**。
- 无真实 Linux 二进制语料（Windows 环境无交叉工具链）。

## 测试语料（tests/elf_corpus.py 生成 → samples/elf/）

| 文件 | 覆盖 |
|---|---|
| minimal64.elf | 手工 ELF64：2 PT_LOAD、6 sections、.symtab 含 `main`（GLOBAL, 0xB0） |
| minimal32.elf | 手工 ELF32（x86）：验证 32 位头/表解码路径 |
| corrupt/bad_magic.elf | 7E 替换 7F → unrecognized |
| corrupt/truncated.elf | 200 字节截断 → section 表截断 error |
| corrupt/bad_shoff.elf | e_shoff 指向 2^40 → error |

> 有趣的插曲：第一版语料生成器自身布局算错，产出的“畸形”ELF 被 parser
> 精确报错——意外获得一个 fuzz 用例（见 DECISIONS D18）。另一个更严重的：
> ELF32 分支曾有一个漏名字段的解包 bug（任何 ELF32 必崩），由 2400 样本
> 的 fuzz 代理抓出并修复。
