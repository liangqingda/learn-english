> 本文件是 `skills/practice-learning-records/SKILL.md` 的分支参考（从知识点记录 ID 进入一轮学习）。只在用户整条消息只是一条知识点记录 ID 时读取。
> 出题、评分、写笔记这些共用步骤只在 `note-path-entry.md` 维护一份，这里只写记录 ID 独有的定位差异。

## 从知识点记录 ID 学习知识点

用户消息（去掉首尾空白、可带反引号或引号）整条只是 `<category>:<key>` 形态的一条记录 ID，形如
`phrases:not-any-more-in-negative` 时，直接以这条记录为目标开始一轮学习，不再弹初始菜单、也不要用户重发“复习”。
这条 ID 本身就是复习触发：它带英文、又像一条查询参数，但不要按英文讲解或命令查询去回答，也不走 `AGENTS.md` 的工程语境豁免。

先确认它确实是知识点记录 ID：分类必须是知识点记录的五个分类之一（`vocabulary`、`phrases`、`grammar`、`usage`、`errors`），
`key` 只含小写 ASCII 字母、数字与连字符。`paper` 是 `learning-record-notes/categories.json` 里的套题笔记分类（`hidden: true`），
`paper:<...>` 形态不是知识点记录，不按这条规则处理。不符合这个形态、或同一句话里还有别的文字时，这条规则不成立，按普通规则处理那条消息。

1. 取记录事实：先跑
   `python3 skills/learn-from-english/scripts/learning_records.py list --category <category> --brief` 按 `id` 精确筛出
   `title`、`explanation`、`source`、`example`、`status`；该分类的 `list` 结果里没有这条 ID 时再跑
   `python3 skills/learn-from-english/scripts/learning_records.py mastered-list --brief` 找 `status: mastered` 的同一条记录
   （`mastered` 的 source/example 是补齐值，出题只用 `title` 与 `explanation` 并另造新语境）。这些查询都不增加学习或复习次数。
2. 定位笔记文件：路径固定为 `learning-record-notes/<category>/<category>-<key>.md`（现有笔记的文件名后缀一律等于记录 `key`），
   再用 `python3 skills/learn-from-english/scripts/learning_records.py snapshot --record <id>` 的 `record_file` 复核；
   `record_file: null` 可能只是缓存落后，也可能表示这轮才第一次建笔记，落盘前用文件是否真的存在来分辨，不要凭它断言笔记不存在。
3. 笔记还没有建过时，本轮由 `review-round` 的 `note` 段带 `explain.content` 建文件（`## 基础信息` 的 `记录 ID` 写用户给的这条 ID），
   不为了建笔记单独跑 `note.py explain` 再写区块。
4. 其余步骤完全按 `note-path-entry.md` 的第 3 至 7 步执行：**不领取 claim**（不调 `next-review`、不带 `claim_owner` / `claim_token`），
   出题范围只限这一条记录（5 至 10 题，默认 6 题），评分走 `review-round` 的 `review` 段（只写 `id`、`score` 和 `errors`），
   笔记写到第 2 步定位出的那个文件，占位讲解先补成真实讲解。
5. `list --category <category> --brief` 与 `mastered-list --brief` 都查不到这条记录时，如实说明定位不到知识点，并给出可用提示
   （同分类的 `list` 结果，或 `search --query "<key>"` 的输出），不猜记录、不凭空造知识点。
   但若第 2 步的笔记文件确实存在（记录被自动删除后留下的练习材料），转 `note-path-entry.md`「记录已不在库中时」那一节，
   不要报“定位不到知识点”：按笔记正文出题、不写 `review` 段、只把本轮题目与得分写进笔记，并在回复里点明该知识点已退出复习库。
