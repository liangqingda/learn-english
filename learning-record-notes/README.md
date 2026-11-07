# learning-record-notes

每完成一轮有实际作答的英语复习、聚焦练习或完整套题，`practice-learning-records` 会在此目录写 Markdown 笔记，用于事后复盘。

- 命名规则：`<category>-<slug>.md`，**不带日期**。`category` 为记录分类，混合知识点用 `mixed`，套题用 `paper`，例如 `errors-back-west-spacing.md`。
- 一个知识点只有一个文件：同一知识点反复复习时始终写回同一个文件，每轮在文件末尾追加一个 `## <YYYY-MM-DD> <HHMM> · 复习` 区块（纯练习用 `· 练习`，套题用 `· 套题`），旧区块永不删除或改写。
- 每个日期区块内紧跟一个**无表头表格**（`<table>` + 9 行 `<tr><td>字段</td><td>值</td></tr>`，不写 `### 追踪` 子标题）：记录 ID、状态变化、本轮得分、题量与错题数、目标知识点、累计复习次数、下次复习、主观题得分、生成时间。
- 再放「本轮习题」：逐题记录题干、用户原样答案与判定；错题在同一题下方用 `<details>` 折叠块给出四步讲解（考点 / 为什么错 / 英语表达逻辑 / 正确表达与可迁移）。

格式唯一来源是 `practice-learning-records/templates/review-note.md`；写完后必须通过校验（要求返回 `ok: true`）：

```bash
python3 practice-learning-records/scripts/check_note.py learning-record-notes/<category>-<slug>.md
```

笔记是可读副本，不是规范数据源：评分、状态、复习调度都以 `learning-records/`、`mastered-learning-records/` 和 `exam-papers/` 为准，删除笔记不会影响任何评分或复习计划。
