# learning-record-notes

每完成一轮有实际作答的英语复习、聚焦练习或完整套题，`practice-learning-records` 会在此目录写 Markdown 笔记，用于事后复盘。

- 命名规则：`<category>-<slug>.md`，**不带日期**。`category` 只能是 `vocabulary`、`phrases`、`grammar`、`usage`、`errors` 五类学习记录分类，套题专用 `paper`；`mixed` **仅在**一次练习同时实质考查 ≥2 个不同分类时使用；只考单一知识点（哪怕换了练法）仍用该记录所在分类命名，禁止 `misc`、`practice` 等其它前缀。主题相同一律复用同一文件，例如 `errors-back-west-spacing.md`。
- 一个知识点只有一个文件：同一知识点反复复习时始终写回同一个文件，每轮在文件末尾追加一个 `# <YYYY-MM-DD> <HH:MM> · 复习` 区块（它同时也是文件的一级标题，不再额外写文件级 H1）（纯练习用 `· 练习`，套题用 `· 套题`），旧区块永不删除或改写。
- 每个日期区块内紧跟一个**无表头表格**（日期标题下一行直接是 `<table`，中间不留空行）（`<table style="border-collapse:collapse;width:auto">` + `<colgroup><col width="150"><col></colgroup>` + 9 行 `<tr><td>字段</td><td>值</td></tr>`，不写 `### 追踪` 子标题）：记录 ID、状态变化、本轮得分、题量与错题数、目标知识点、累计复习次数、下次复习、主观题得分、生成时间。
- 再放 `## 本轮习题`：每题一个 `### <n>. <题型>`；逐题记录题干、答案与判定；`我的答案` 只写该题答案本身，不带题号前缀（用户写 `1. B` 时记为 `B`）。**每道题都必须有一个 `知识点讲解` 折叠块**（答对的题也要写），讲解该题涉及的语言点，可超出当前复习知识点；判定为错误、部分正确或未作答的题，再追加一个 `错题讲解` 折叠块（未作答时第 2 步写 **为什么答不出**）。未作答不计入错题数，但不允许只留一行「未作答」而没有讲解。

- 若同一轮里用户还选了讲解型快捷菜单（语法/词汇扩展、场景对话、专题讲解等），在所有习题之后**直接**追加三级标题 `### <选项原文>`（去掉 emoji，不加编号、不写 `菜单：` 前缀，与习题标题同级），下面接 `**讲解要点**：` + `**可迁移表达**：`；不写 `菜单与讲解` 小节标题。该菜单项随后产生的作答（如语法/词汇扩展练习）同样记在这个菜单项标题下，用 `| 题号 | 题型 | 我的答案 | 判定 |` 表格记录，不另开 `· 练习` 日期区块、不另建文件。会切换题组的选项（继续复习、换知识点、换套题等）不属于本轮，另起日期区块记录。

所有分点内容必须结构化：`讲解要点`、`可迁移表达`、菜单项补充说明、练习作答一律用有序列表、无序列表或表格逐条记录，禁止把多条规则揉成一整段文字。

格式唯一来源是 `practice-learning-records/templates/review-note.md`。写入只能通过脚本完成，禁止直接 `Write` 整个文件：

```bash
python3 learn-from-english/scripts/learning_records.py note-append \
  --file learning-record-notes/<category>-<slug>.md \
  --content-file /tmp/note-block.md \
  --check
```

`note-append` 在 `learning-record-notes/.notes.lock` 上取排他锁，锁内完成“读现有文件 → 补 `---` 分隔 → 原子替换”，多个会话同时写同一文件不会互相覆盖；返回 `appended: false, duplicate: true` 表示该标题区块已存在，按已写入处理。修正自己刚写的区块用同一把锁的 `note-replace-block --heading "# <本轮标题>"`，不要整文件重写。`--check` 会调用 `practice-learning-records/scripts/check_note.py`，要求返回 `ok: true`。

笔记是可读副本，不是规范数据源：评分、状态、复习调度都以 `learning-records/`、`mastered-learning-records/` 和 `exam-papers/` 为准，删除笔记不会影响任何评分或复习计划。
