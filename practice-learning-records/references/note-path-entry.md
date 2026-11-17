> 本文件是 `practice-learning-records/SKILL.md` 的分支参考（从笔记相对路径进入一轮学习）。只在用户整条消息只是一条复习笔记相对路径时读取。
> 规则只在本文维护一份，SKILL.md 只留入口与硬约束。

## 从笔记相对路径学习知识点

用户消息（去掉首尾空白、可带反引号或引号）整条只是一条复习笔记的相对路径，形如
`learning-record-notes/errors/errors-before-begin-gerund-or-clause.md`（也接受带仓库根前缀的写法，以及迁移前的平铺写法
`learning-record-notes/errors-before-begin-gerund-or-clause.md`，它按文件名前缀解析到同一个笔记文件）时，直接以这条笔记
对应的知识点为目标开始一轮学习，不再弹初始菜单、也不要用户重发“复习”。这条路径本身就是复习触发，不走
`AGENTS.md` 的工程语境豁免，不要当成文件操作去回答。

1. 先跑 `python3 take-english-study-notes/scripts/note.py sections --file <path>` 取 `record_id`。
   文件不存在、不在 `learning-record-notes/` 下、不是 `README.md`、或返回不出 `record_id` 时，如实说明定位不到知识点，
   并给出可用路径提示（`python3 take-english-study-notes/scripts/note.py list` 的输出），不要猜记录、不要凭空造知识点。
2. 用返回的 `record_id` 取记录事实：`learning_records.py list --category <category> --brief` 按 id 精确筛出
   `title`、`explanation`、`source`、`example`、`status`；要确认记录→笔记的对应关系再跑
   `learning_records.py snapshot --record <record_id>`（命中缓存时可能滞后于刚建的笔记，`record_file: null` 不代表文件不存在，
   以用户给的路径和第 1 步的 `record_id` 为准）。这些查询都不增加学习或复习次数。
   **查不到这条记录时**（已掌握记录连续三次满分后被自动删除，只剩笔记）转「记录已不在库中时」那一节，不要报“定位不到知识点”。
3. 这一轮**不领取 claim**：它不经 `next-review` 抽取，所以不要调 `next-review` 和 `release-claim`，也不要带
   `claim_owner` / `claim_token`。评分直接走 `review-round` 的 `review` 段，这一段只写 `id`、`score` 和 `errors`。
4. 出题范围只限这一条记录：按「开展普通复习」的题型组合、由易到难和答案隔离规则设计一组建模在 5 至 10 题（默认 6 题），
   不要在题干暴露知识点名称或答案。首次出题时把题组作为本轮唯一操作入口，不显示菜单。
5. 用户作答后按「评分与协调记录」的评分自检与 0 至 10 分口径评分，`errors` 只收本次实际展示并已解释的错误；
   保存成功后按「生成本轮学习笔记」写到**用户给出的那个文件**（不是另建新文件），并先确认或补齐 `## 讲解`。
6. 该记录的笔记若还挂着占位讲解（“历史知识点补建笔记”那段提示），先按记录事实补写一份真实讲解再写本轮区块：
   用 `note.py explain --update` 替换占位内容，本分类必写栏按 `note-format.md` 填。
7. 后续若用户回复数字选择本轮生成的菜单，按「处理数字选择」正常分派。

## 记录已不在库中时

已掌握记录连续三次 10 分后记录被自动删除，笔记 md 保留（这是设计好的状态，不是数据损坏）。用户再发这条笔记路径时：

- 只当练习素材用：知识点来源于笔记正文——`## 讲解` 的讲解要点、例句，以及各区块里已写下的题目、答案与中文翻译；
  不要凭文件名猜语义，也不要凭空补一份记录里没有的讲解。
- 仍然**不领取 claim**，也**不写 `review` 段**：没有记录可写，硬写会报 `record does not exist`。
- 评分照常判分、照常解释错误；本轮只把题目与得分写进这个笔记文件（`append-section`，先跑 `note.py sections` 看该节是否已存在）。
  表里只写这一轮自带的行，`record-tracking` 此时拿不到记录事实（`tracking_skipped`），所以不要手抄「累计复习次数」「下次复习」，
  也不要写「分类 · 状态变化」。
- `errors` 若确实要落成新知识点，按普通练习用一次 `batch-upsert` 写，与这条已退出的记录无关。
- 回复里点明一句：该知识点已退出复习库（记录已删），本轮只记笔记、不再更新记录；之后仍可继续按这条路径练习。
- 退出记录库的那一轮本身不写区块（`review-round` 返回 `note_skipped`）：那一轮的追踪行来自刚被删掉的记录，写了只会留下永远不再刷新的旧数字；从下一次按路径练习起才写新的区块。
