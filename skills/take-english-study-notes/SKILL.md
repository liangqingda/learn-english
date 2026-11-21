---
name: take-english-study-notes
description: 复习笔记（`learning-record-notes/*.md`）的唯一 owner：何时写、文件名、版式骨架、追踪字段口径、写入命令、校验与迁移全在这里。`learn-from-english` 讲解后要落讲解笔记、`practice-learning-records` 复习/练习/套题后要追加笔记，都调用本 skill 的 `scripts/note.py`，不要各自拼格式或直接写文件。
---

# 复习笔记（take-english-study-notes）

一个知识点一个 Markdown 文件，放在仓库根 `learning-record-notes/` 下**按分类分的子目录**里
（`learning-record-notes/errors/errors-out-west.md`），目录名与文件名前缀必须一致，`categories.json` 与 `README.md`
留在目录根。笔记是**可读副本，不是规范数据源**：
不参与 `validate`、统计、抽题或调度，缺失或被删除都不影响评分与复习计划，但它是给人读的唯一入口，
所以版式必须能被校验器机检、被多会话并发安全写入。

## 谁在什么时候写

| 场景 | 谁触发 | 写什么 |
|---|---|---|
| 讲解轮（用户发来一句英语、正文里实质讲解过） | `learn-from-english` | 每条实际讲解的记录一个文件，写 `## 基础信息` + 文件级 `## 讲解` |
| 有实际作答的复习 / 聚焦练习 / 套题 | `practice-learning-records` | 往该记录已有文件追加一个日期区块 `# <date> <time> · 复习\|练习\|套题` |
| 菜单型后续学习（场景对话、小故事、扩展讲解、对比相近表达） | 两者皆可 | 只讲解、不带习题的写成 `## 讲解` 之后的文件级 `## <选项原文>` 小节（`append-explain-section`），不进日期区块 |
| 带习题的菜单项（如「练习…的关键语法结构」） | `practice-learning-records` | 讲解要点写文件级小节（第一轮写一次；之后要改或要补用 `append-explain-section --rewrite` 整节替换），本轮习题写日期区块里同名小节（`append-section`）；当轮没有讲解要点时，`append-section` 自动在讲解区补一份只挂复习历史索引的同名骨架小节 |
| 笔记存在但缺少 `## 讲解`（历史补建、只写过复习区块） | 任一写该笔记的 skill | **先补齐讲解**：用 `explain --update` 插一份（没有正文时写占位提示），再写本轮区块 |
| 某个知识点还没有任何笔记 | 任一提到该记录的 skill | 用 `explain` 创建文件，讲解正文缺失时写占位提示，不留空文件 |

一个知识点只有一次首次讲解，复习才会多轮：讲解写成文件级固定小节，复习写成日期区块，两者不混用。
每份笔记都必须有 `## 讲解`；正文暂时没有内容时写提示文案，不要空着、也不要省略这一节
（校验器允许缺讲解，所以这一条只能靠写入路径执行，不能指望 `check` 拦住）。

## 唯一入口

```bash
python3 skills/take-english-study-notes/scripts/note.py explain        --file learning-record-notes/<category>/<category>-<slug>.md --content-file - [--update] [--check]
python3 skills/take-english-study-notes/scripts/note.py append         --file learning-record-notes/<category>/<category>-<slug>.md --content-file - [--check]
python3 skills/take-english-study-notes/scripts/note.py append-explain-section --file learning-record-notes/<category>/<category>-<slug>.md --content-file - [--rewrite] [--check]
python3 skills/take-english-study-notes/scripts/note.py append-explain-part    --file learning-record-notes/<category>/<category>-<slug>.md --section "## <小节标题>" --content-file - [--check]
python3 skills/take-english-study-notes/scripts/note.py append-section --file learning-record-notes/<category>/<category>-<slug>.md --heading "<# ...>" --content-file - [--check]
python3 skills/take-english-study-notes/scripts/note.py append-part    --file learning-record-notes/<category>/<category>-<slug>.md --heading "<# ...>" --section "## <小节标题>" --content-file - [--check]
python3 skills/take-english-study-notes/scripts/note.py replace        --file learning-record-notes/<category>/<category>-<slug>.md --heading "<# ...>" --content-file - [--rewrite-section "## ..."] [--check]
python3 skills/take-english-study-notes/scripts/note.py sections       --file learning-record-notes/<category>/<category>-<slug>.md [--heading "<# ...>"] [--section "## <小节标题>"]
python3 skills/take-english-study-notes/scripts/note.py sync           --file learning-record-notes/<category>/<category>-<slug>.md [--check]
python3 skills/take-english-study-notes/scripts/note.py list           [--record <id>]
python3 skills/take-english-study-notes/scripts/note.py check --all [--fix]
```

- 写入全程在 `learning-record-notes/.notes.lock` 排他锁内完成「读 → 拼装 → `os.replace` 原子替换」，调用方不自己改写文件。
- 禁止用 `Write` 或任何编辑器直接改笔记；也禁止先落固定路径（如 `/tmp/note-block.md`）的临时内容文件，并行会话会互相覆盖。
- 写之前先 `sections` 查目标文件已有哪些轮次与 `##` 小节，再决定 `append-explain-section`（文件级讲解小节首次写入）、
  `append-explain-part`（往文件级小节末尾补第二段故事 / 对话原文）、`append-section`（往日期区块最前插入带习题的菜单项，区块内小节按落盘时间倒序、新的在前）、
  `append-part`（往日期区块既有小节末尾补一段）还是 `replace --rewrite-section`，不要拼好大段内容再被拒。
- 同一天多次练同一菜单项：**日期标题不变**，同一天的多个区块算一个「天组」，同一菜单项的习题小节从第 2 份起按时间升序编号
  （`## <选项原文> - 01`、` - 02`…），当天只有一份时不带后缀；同一轮隔天再练仍在同一个区块、同一个「天组」，重复菜单项照样另建带序号的同标题小节（一节一表、题号从 1 起），不并入既有小节。`append` / `append-section` 在锁内自动补号
  （把已有那份改成 ` - 01`）并把实际标题放进返回的 `section`、被改名的旧标题放进 `section_renamed`，校验器核对单份不带后缀、多份连续。
  后缀按时间升序（最早 `- 01`），与正文展示方向相反：区块内小节按落盘时间倒序（最新一节在最前，`## 本轮习题` 固定居首），所以最上面的小节可能带最大的后缀号。
- 自带派生内容，都由写入命令生成、不要手写：每份带习题的菜单项小节与每个区块的 `## 本轮习题`，都在**标题行右侧**
  挂一个空元素锚点 `<a id="practice-<date>-<HHMM>-<8 hex>"></a>` / `<a id="round-<date>-<HHMM>"></a>`（同一菜单项当天有多份小节时，`practice-…` 末尾再拼上该小节的 ` - 01` / ` - 02` 序号）
  （渲染不可见，点击直接落在标题上）；文件级同名小节的**讲解内容之后**（纯答题的骨架小节没有讲解内容，索引直接挂在标题之下）另有一行 `复习历史：` + `<!-- practice-index -->` …
  `<!-- /practice-index -->` 索引块（该菜单项全部习题小节，按时间倒序、新的在前），`## 讲解` 的讲解内容之后同样是
  `复习历史：` + `<!-- round-index -->` … `<!-- /round-index -->` 复习目录（每个日期区块的 `## 本轮习题`）。
  索引条目与日期区块标题同口径（`<日期> <HH:MM> · <复习|练习|套题>`），同一天同一菜单项有多份时按时间先后补 ` - 01`、` - 02`。
  每次写入与 `check --all --fix` 都会按真实小节重建，所以改标题、加删小节或区块后不必手工同步；校验器逐条比对，
  缺锚点、锚点与区块/标题对不上、缺索引、缺 `复习历史：`、索引后还写正文、条目对不上或残留索引块都报错。
  格式见 `references/note-format-validation.md` 的「可跳转索引」与「复习目录」。
- 讲解型内容（讲解要点、对比、场景对话、小故事）一律写 `## 讲解` 之后；日期区块只放 `## 本轮习题` 与带习题的菜单项。
  同一个菜单项重复选中时，除场景对话与小故事外不再按新内容重复记录：`append-explain-section` 返回 `duplicate: true` 就停手。
  讲解要点要改、要补，三类文件级小节（带习题的讲解要点、场景对话、小故事）走同一条规则：同一命令加 `--rewrite` 整节替换，
  并带上已有的 `场景对话原文` / `故事原文`（漏掉原文的重写会被拒绝）；只多一段原文时用 `append-explain-part`。
- 场景对话 / 小故事每段原文都要带标题：summary 写 `场景对话原文 · <标题>` / `故事原文 · <标题>`，标题就是聊天里这一段正文首行 `**<标题>**` 的文字（4–16 字中文场景名，不加引号），缺标题会被写入命令直接拒绝。
  只有一段时不编号、块前不写标签行；出现第二段起第一段改成 `场景对话原文 1 · <标题>` / `故事原文 1 · <标题>`，其余按 `2 · <标题>`、`3 · <标题>`… 编号，写入命令会自动完成改名并保留每段标题。
- 小故事的三列表（`故事里的位置` / `当时想表达什么` / `为什么不换别的表达`）折叠在同一个 `故事原文` 块内，
  写在英文叙事与译文之后；写到 `</details>` 外面等于这一段没有交付，校验器会拦。
- `explain --update` 有两种语义：文件已有 `## 讲解` 时只替换该小节；文件没有 `## 讲解` 时把这一节插入到 `## 基础信息` 表之后、所有日期区块之前（返回 `inserted: true`），不覆盖任何已有内容。补讲解一律用它，不要用 `Write` 或 `replace` 手动插小块。
- `append` / `append-section` / `append-part` / `replace` 加 `--check` 会在写入后自动跑本 skill 的校验器，并自动修复无争议问题（行尾空格、答案题号前缀、缺失的 `---` 等），结果放在 `auto_fixed`；`explain --check` 只校验不回改。

## 规则来源与优先级

冲突时按此顺序取：`templates/review-note.md`（骨架与 meta）→ `scripts/check_note.py`（可机检的硬规则）→
`references/note-format.md`（口径、字段取值、命令用法、迁移）。三者不能各写一份：模板 meta 与校验器常量必须一致。

- 模板：`skills/take-english-study-notes/templates/review-note.md`
- 校验器：`skills/take-english-study-notes/scripts/check_note.py`（独立运行，不依赖任何其他 skill）
- 口径全集：`skills/take-english-study-notes/references/note-format.md`；追加与改写的命令细则在 `references/note-format-append.md`，校验、派生索引与迁移在 `references/note-format-validation.md`

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
- 文件级讲解区 = `## 讲解` + 若干只讲解、不带习题的菜单小节（场景对话、小故事、对比、扩展讲解），全部在所有日期区块之前。
  每个日期区块 `# <YYYY-MM-DD> <HH:MM> · 复习|练习|套题` 先写本轮题组标题（没有菜单项标题时用兜底标题 `## 本轮习题`，题目自带菜单项标题时直接用那个标题，此时不写 `## 本轮习题`），本轮信息表（生成时间、本轮得分、题量与错题数，套题再加主观题得分；
  `分类 · 状态变化` 只在本轮真的改了记录状态时插在 `生成时间` 之后，没改或没评分就整行不写）紧跟在这个标题之下、第一题之前，表格本身不加小标题；带习题的菜单项小节
  也在自己的标题下先写三行表（`生成时间` / `本轮得分` / `题量与错题数`）。`生成时间` 由写入脚本按落盘时间盖，不需要也不允许
  自己编；文件级 `复习历史` 链接文案与跳转锚点用的就是这个小节的 `生成时间`。有习题的菜单项一律 0 至 10 计分、得分只写在这份笔记里，
  没有写入规范记录的练习、以及状态没有变化的轮次，都不写 `分类 · 状态变化` 这一行。区块按时间倒序排列：最新一轮紧跟文件级讲解区，旧区块依次排在它之后。
- 文件名必须等于记录 ID：`<category>-<key>.md`，`<key>` 小写、连字符。同一记录已有笔记时，命令会拒绝另建文件并给出应复用的路径。
- 批量改写小节必须用锚点定位到下一个同级标记（下一个 `##`、`###`、`</details>`），禁止按「读到区块结束」收边，
  否则会静默吞掉同节内的其他内容。

## 校验

`check --all` 用 `$LEARN_ENGLISH_REPO_ROOT`（缺省取本脚本所在仓库根）定位 `learning-record-notes/`，跳过 `README.md`；CI 每次 push 跑这一条。

- `ok: true` 才算通过；`invalid` 表示写入成功但校验未过（进程退出码 1），用 `replace` 就地修正本轮区块。
- `--all` 另返回 `missing_notes`：还没有笔记文件的记录，含 `count`、`by_category` 与按分类轮流取样的前 50 条 `records`。
  笔记按需生成，这一项只做体检报告、不影响 `ok`。
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
| `note does not exist`（记录仍在，文件被 `delete-note --keep-record` 删掉或从未建过） | 不放弃落笔记：先 `explain --file <note> --content-file -` 写 `## 基础信息` 与 `## 讲解`，再按本轮需要补文件级讲解要点（`append-explain-section`），最后用 `append` / `append-section` 写本轮内容；重建后在回复里说明「这份笔记此前不存在或被删除，已重建」 |

## 与其他 skill 的边界

- `learn-from-english`：记录库、菜单、讲解正文；讲解要落笔记时调本 skill 的 `explain`。
- `practice-learning-records`：复习、练习、套题评分；要落笔记时调本 skill 的 `append` / `append-explain-section` / `append-explain-part` / `append-section` / `append-part` / `replace`。
- 本 skill 不读抽题调度、不算分、不改规范记录，只写 `learning-record-notes/` 下的可读副本。
