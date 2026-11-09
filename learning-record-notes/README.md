# learning-record-notes

每次英语讲解、每一轮有实际作答的复习、聚焦练习或完整套题，豆包都会在此目录写 Markdown 笔记，用于事后复盘；同一个知识点的讲解与之后的复习都写在同一个文件里。

规则只有一处权威来源：**[`take-english-study-notes/references/note-format.md`](../take-english-study-notes/references/note-format.md)**。
版式以 [`templates/review-note.md`](../take-english-study-notes/templates/review-note.md) 为准，合规性由
`take-english-study-notes/scripts/check_note.py` 强制校验。本文件只列四条速查：

- 文件名 `<category>-<slug>.md`，不带日期；类别取 `vocabulary` / `phrases` / `grammar` / `usage` / `errors`，
  套题用 `paper`，`mixed` 仅用于一次练习实质考查 ≥2 个分类。主题相同一律复用同一文件。
  记录 ID 必须与文件名一致（`errors:back-west-spacing` → `errors-back-west-spacing.md`）。
- 文件顶部先放 `## 基础信息` 表格；文件级 `## 讲解` 小节每份笔记都必须有（一个知识点只有一份，固定在基础信息之后、所有日期区块之前，不带 `讲解时间` 等本轮字段）。历史记录补建笔记时正文可先写占位提示，但这一节不能省。
  `## 讲解` 只讲本文件那一层（`phrases` 讲短语、`grammar` 讲语法机制、`usage` 讲语气语域），栏目按分类自选，不必凑齐固定的几项。
- 记录库里的每个知识点在 `learning-records/`、`mastered-learning-records/` 中都对应本目录的一份笔记；缺笔记或笔记缺 `## 讲解` 时，用 `explain`（缺小节时加 `--update` 插入）补齐后再写本轮区块。每个文件都有一份 `## 讲解`，是写入路径的责任，校验器不拦这一点。
- 复习 / 练习 / 套题一轮一个 `# YYYY-MM-DD HH:MM · 复习|练习|套题` 区块，旧区块永不删除或改写，按时间升序排列。
- 写入只能走 `take-english-study-notes/scripts/note.py`：`explain` 创建含 `## 讲解` 的笔记、`append` 追加整轮区块、`append-section` 往既有区块里追加单个 `## ` 小节、`replace` 修正本轮区块（同一把锁内原子替换），
  写入时会自动拒绝「同一记录另建文件」、自动修可安全修复项、自动比对追踪表；禁止用 `Write` 改写整个文件，也不要用固定路径的中转文件。
- 笔记是可读副本，不是规范数据源：评分、状态与复习调度以 `learning-records/`、`mastered-learning-records/`、
  `exam-papers/` 为准，删除笔记不影响任何评分或复习计划。

写入示例（区块走标准输入）：

```bash
python3 take-english-study-notes/scripts/note.py append \
  --file learning-record-notes/<category>-<slug>.md \
  --content-file - --check <<'EOF'
# <YYYY-MM-DD HH:MM> · 复习
…本轮区块全文…
EOF
```

全量体检：`python3 take-english-study-notes/scripts/note.py check --all [--fix]`。

返回 `note_status: valid` 才算通过；`invalid` 表示写入成功但校验未过，用替换命令就地修正；`unverified` 表示校验器不可用，
需要在回复里说明「本轮笔记未校验」。

替换是整块覆盖，但命令在锁内兜底：新内容没带上、而文件里已存在的 `## ` 小节会被原样保留在区块末尾，
并列入返回值 `preserved_sections`（这些是别的对话的成果，不要手工删）。只有 `--drop-section` 明确列出的小节才允许删除。
加菜单小节请用 `append-section`，不要为了一节去整块 `replace`。
