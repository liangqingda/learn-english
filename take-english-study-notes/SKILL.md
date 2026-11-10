---
name: take-english-study-notes
description: 复习笔记（`learning-record-notes/*.md`）的唯一 owner：何时写、文件名、版式骨架、追踪字段口径、写入命令、校验与迁移全在这里。`learn-from-english` 讲解后要落讲解笔记、`practice-learning-records` 复习/练习/套题后要追加笔记，都调用本 skill 的 `scripts/note.py`，不要各自拼格式或直接写文件。
---

# 复习笔记（take-english-study-notes）

一个知识点一个 Markdown 文件，放在仓库根 `learning-record-notes/`。笔记是**可读副本，不是规范数据源**：
不参与 `validate`、统计、抽题或调度，缺失或被删除都不影响评分与复习计划，但它是给人读的唯一入口，
所以版式必须能被校验器机检、被多会话并发安全写入。

## 谁在什么时候写

| 场景 | 谁触发 | 写什么 |
|---|---|---|
| 讲解轮（用户发来一句英语、正文里实质讲解过） | `learn-from-english` | 每条实际讲解的记录一个文件，写 `## 基础信息` + 文件级 `## 讲解` |
| 有实际作答的复习 / 聚焦练习 / 套题 | `practice-learning-records` | 往该记录已有文件追加一个日期区块 `# <date> <time> · 复习\|练习\|套题` |
| 菜单型后续学习（场景对话、扩展讲解、追加练习） | 两者皆可 | 往同一日期区块追加 `## <选项原文>` 小节，不另建文件 |
| 笔记存在但缺少 `## 讲解`（历史补建、只写过复习区块） | 任一写该笔记的 skill | **先补齐讲解**：用 `explain --update` 插一份（没有正文时写占位提示），再写本轮区块 |
| 某个知识点还没有任何笔记 | 任一提到该记录的 skill | 用 `explain` 创建文件，讲解正文缺失时写占位提示，不留空文件 |

一个知识点只有一次首次讲解，复习才会多轮：讲解写成文件级固定小节，复习写成日期区块，两者不混用。
每份笔记都必须有 `## 讲解`；正文暂时没有内容时写提示文案，不要空着、也不要省略这一节
（校验器允许缺讲解，所以这一条只能靠写入路径执行，不能指望 `check` 拦住）。

## 唯一入口

```bash
python3 take-english-study-notes/scripts/note.py explain        --file learning-record-notes/<category>-<slug>.md --content-file - [--update] [--check]
python3 take-english-study-notes/scripts/note.py append         --file learning-record-notes/<category>-<slug>.md --content-file - [--check]
python3 take-english-study-notes/scripts/note.py append-section --file learning-record-notes/<category>-<slug>.md --heading "<# ...>" --content-file - [--check]
python3 take-english-study-notes/scripts/note.py replace        --file learning-record-notes/<category>-<slug>.md --heading "<# ...>" --content-file - [--rewrite-section "## ..."] [--check]
python3 take-english-study-notes/scripts/note.py sections       --file learning-record-notes/<category>-<slug>.md [--heading "<# ...>"] [--section "## <小节标题>"]
python3 take-english-study-notes/scripts/note.py sync           --file learning-record-notes/<category>-<slug>.md [--check]
python3 take-english-study-notes/scripts/note.py list           [--record <id>]
python3 take-english-study-notes/scripts/note.py check --all [--fix]
```

- 写入全程在 `learning-record-notes/.notes.lock` 排他锁内完成「读 → 拼装 → `os.replace` 原子替换」，调用方不自己改写文件。
- 禁止用 `Write` 或任何编辑器直接改笔记；也禁止先落固定路径（如 `/tmp/note-block.md`）的临时内容文件，并行会话会互相覆盖。
- 写之前先 `sections` 查目标文件已有哪些轮次与 `##` 小节，再决定 `append-section` 还是 `replace --rewrite-section`，不要拼好大段内容再被拒。
- `explain --update` 有两种语义：文件已有 `## 讲解` 时只替换该小节；文件没有 `## 讲解` 时把这一节插入到 `## 基础信息` 表之后、所有日期区块之前（返回 `inserted: true`），不覆盖任何已有内容。补讲解一律用它，不要用 `Write` 或 `replace` 手动插小块。
- `append` / `append-section` / `replace` 加 `--check` 会在写入后自动跑本 skill 的校验器，并自动修复无争议问题（行尾空格、答案题号前缀、缺失的 `---` 等），结果放在 `auto_fixed`；`explain --check` 只校验不回改。

## 规则来源与优先级

冲突时按此顺序取：`templates/review-note.md`（骨架与 meta）→ `scripts/check_note.py`（可机检的硬规则）→
`references/note-format.md`（口径、字段取值、命令用法、迁移）。三者不能各写一份：模板 meta 与校验器常量必须一致。

- 模板：`take-english-study-notes/templates/review-note.md`
- 校验器：`take-english-study-notes/scripts/check_note.py`（独立运行，不依赖任何其他 skill）
- 口径全集：`take-english-study-notes/references/note-format.md`

## 骨架要点

- 文件顶部唯一一份 `## 基础信息`：记录 ID / 试卷 ID、目标知识点、累计复习次数、下次复习、笔记生成时间、笔记更新时间。
  记录级字段来自规范记录，写入后用 `learning_records.py record-tracking --id <id>`（`learn-from-english` 提供）逐字段比对。
  `累计复习次数` 与 `下次复习` 由记录直接决定，`append` / `replace` / `sync --check` 会自动回填成记录的值
  （返回 `basic_info_synced`），不需要调用方手抄；身份行（记录 ID / 目标知识点）与其余本轮字段不一致仍返回
  `tracking_mismatch` / `tracking_expected`。已有笔记顶部是旧值时用 `note.py sync --file <note>` 就地修复，
  `append` / `replace` 只写日期区块、不会更新这张表。找不到记录库时返回 `tracking_skipped`，不阻断写入。
- 文件级唯一一份 `## 讲解`，紧跟基础信息表之后、所有日期区块之前，固定展示不折叠，不带 `讲解时间` 等本轮字段。
  栏目按本记录分类聚焦、自由选取（至少两栏，每栏列表或表格），模板 meta `explain-required-labels` 声明各分类必写栏：
  `vocabulary` / `phrases` → `核心含义`；`grammar` → `语法机制`；`usage` → `语气与语域`；`errors` → `错误机制`。
  讲语法时不要写历史文化背景与发音；讲短语、用法时可以写。
- 每个日期区块 `# <YYYY-MM-DD> <HH:MM> · 复习|练习|套题` 下是一张裸表格（不加小标题）：复习时间、分类 · 状态变化、
  本轮得分、题量与错题数；套题再加主观题得分。整个文件时间必须升序。
- 文件名必须等于记录 ID：`<category>-<key>.md`，`<key>` 小写、连字符。同一记录已有笔记时，命令会拒绝另建文件并给出应复用的路径。
- 批量改写小节必须用锚点定位到下一个同级标记（下一个 `##`、`###`、`**完整场景对话**：`），禁止按「读到区块结束」收边，
  否则会静默吞掉同节内的其他内容。

## 校验

`check --all` 用 `$LEARN_ENGLISH_REPO_ROOT`（缺省取本脚本所在仓库根）定位 `learning-record-notes/`，跳过 `README.md`；CI 每次 push 跑这一条。

- `ok: true` 才算通过；`invalid` 表示写入成功但校验未过（进程退出码 1），用 `replace` 就地修正本轮区块。
- issue 落在更早的历史区块时，不为通过校验重排旧区块；如实说明「本轮笔记未通过校验，已保留待修正」。
- 模板演进导致历史笔记不合规时允许一次性迁移（`check --all --fix` 只做无争议修复），迁移前后用 `git diff` 确认没有正文删除。

## 失败恢复

| 情况 | 处理 |
|---|---|
| 写入失败（路径不合规、缺标题、同标题小节已存在等） | 正文照常发送，原样说明命令报错原因；不得改用 `Write` 绕过 |
| `duplicate: true`（同标题同内容） | 按已写入处理，不重试、不补写 |
| `inserted: true`（`explain --update` 在缺讲解的旧笔记里插入了这一节） | 按已补齐处理，接着写本轮区块；不要再用 `append` 或 `Write` 另加一份讲解 |
| `heading_adjusted: true` | 按返回的 `heading` 继续，两轮内容都已保留，不要用原时间再追加一遍 |
| `note_status: unverified` | 回复里明确写「本轮笔记未校验」 |

## 与其他 skill 的边界

- `learn-from-english`：记录库、菜单、讲解正文；讲解要落笔记时调本 skill 的 `explain`。
- `practice-learning-records`：复习、练习、套题评分；要落笔记时调本 skill 的 `append` / `append-section` / `replace`。
- 本 skill 不读抽题调度、不算分、不改规范记录，只写 `learning-record-notes/` 下的可读副本。
