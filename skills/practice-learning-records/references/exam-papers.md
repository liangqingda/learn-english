> 本文件是 `skills/practice-learning-records/SKILL.md` 的分支参考。四六级 / IELTS 风格套题的生成、持久化、续答与评分。只在走套题流程时读取。 文中的「小节名」都指 `skills/practice-learning-records/SKILL.md` 里的同名小节。

## 完整英语考试套题

先确定本卷的 `exam_type`、考试名称、题型和评分 profile。用户明确指定考试时服从；未指定时根据已掌握素材选择 CET-4 或 CET-6。生成 CET 之外的考试前，先查证该考试当前的官方题型与计分方式；如果考试没有统一合格线，把 `pass_score` 设为 `null`，除非用户给出目标分，此时将目标分作为本卷合格线并在 `score_note` 说明。不要把 710 分制、425 合格线或省略听力规则套到其他考试。

生成新套题的入口先运行：

```bash
python3 skills/learn-from-english/scripts/learning_records.py mastered-list
```

只使用返回的 `status: mastered` 记录作为素材池。生成完整试卷内容、参考答案及“每道可作答题对应的一个或多个 mastered ID”映射后，在首次展示前运行：

```bash
python3 skills/learn-from-english/scripts/learning_records.py paper-create --input <JSON 文件或 ->
```

当前四六级套题使用通用 Paper Schema v2 的 CET profile。输入必须包含 `exam_type`（`cet4` 或 `cet6`）、对应的 `exam_name`（`CET-4` 或 `CET-6`）、`format_id: cet-no-listening-v1`、简短 `theme`、`source_record_ids`、`sections`、`answer_keys`、`objective_items`、`subjective_components`、`grading_scheme`，以及覆盖全部 answer key 的 `record_map`。严格使用以下配置：

- `writing`：`directions`、`prompt`、`word_requirement`、`reference_answer`。
- `listening`：固定为 `{"omitted": true, "question_slots": 25}`。
- `reading.section_a`、`section_b`、`section_c`：各含 `directions`、`passage` 和 10 个 `questions`；每题含正确范围内的 `number`、`prompt`、字符串 `choices`、`answer` 和 `explanation`。
- `translation`：`directions`、`source_text`、`reference_answer`。
- `answer_keys`：依次为 `writing`、字符串 `26` 至 `55`、`translation`。
- `objective_items`：Questions 26-35 每题 0.5 原始分，36-45 每题 1 分，46-55 每题 2 分；每项同时保存 `answer`。
- `subjective_components`：`writing.max_score` 和 `translation.max_score` 均为 15。
- `grading_scheme`：`raw_max_score: 65`、`reported_max_score: 710`、`pass_score: 425`、`conversion: linear`、`precision: 2`、`rounding_step: null`、`score_unit: 分`，并用 `score_note` 明确这是无听力模拟折算分。

`record_map` 的每个值是至少含一个 source ID 的数组。只把命令返回的 `paper_id` 和标准标题显示在卷首，不向用户展示存储的参考答案、解析或映射。所有 source 和 mapping ID 必须是当前 `mastered` 记录。文件自动保存到 `exam-papers/<paper_id>.json`，一卷一文件。其他考试可使用不同 `exam_type`、answer keys、主客观评分项与 `grading_scheme`，不要把 CET 题型或 710 分制写成通用规则。

按 CET-4/CET-6 笔试形式生成，不声称来自官方真题。卷首同时标明“官方题位 57、当前实际生成并可作答 32”：写作 1 题、听力题位 25 个但不生成、阅读 30 题、翻译 1 题。保留官方考试时间和占比：CET-4 125 分钟、CET-6 130 分钟；写作 15%、听力 35%、阅读 35%、翻译 15%。不要把省略听力后的试卷称为 65% 满分或减少版。

完整套题必须保持官方笔试顺序、题型、题量和内部比例：

- Part I Writing：短文写作 1 题，30 分钟，占 15%。给出正式 Directions、题目和字数要求；不附范文或答案。
- Part II Listening Comprehension：CET-4/CET-6 均为 25 题，占 35%；CET-4 为 25 分钟，CET-6 为 30 分钟。按当前仓库规则省略听力，不生成听力材料、听力题、听力答案或伪音频文本；只写一行省略说明并保留该部分在试卷中的位置。
- Part III Reading Comprehension：30 题，40 分钟，占 35%。Section A 词汇理解/选词填空 10 题，占 5%；Section B 长篇阅读/匹配 10 题，占 10%；Section C 仔细阅读 10 题，占 20%（通常两篇短文，每篇 5 题）。阅读题号按真实试卷习惯标为 Questions 26-55，不因听力省略而从 1 重新编号。
- Part IV Translation：汉译英段落翻译 1 题，30 分钟，占 15%。给出正式 Directions 和中文段落；不附参考译文。

根据素材的词汇抽象度、句法复杂度、话题和语域判断 CET-4 或 CET-6，用户指定时服从指定级别。首次呈现时不附答案、解析、提示或菜单；把整套未作答试卷作为唯一操作入口，并在其后的 attribution block 标注 `*Picked from mastered-learning-records · mastered*`。

允许用户按题号、Section 或 Part 分段提交。每次只确认收到的范围并列出仍缺少的可作答题，不提前公布答案或评分。用户完成 32 个可作答项，或明确提交并跳过剩余项后，才结束作答；用户提前要求答案时，先确认这会结束当前作答，再在确认后揭示。

每次收到答案或明确跳过项时立即运行：

```bash
python3 skills/learn-from-english/scripts/learning_records.py paper-submit --input <JSON 文件或 ->
```

首次提交只传 `paper_id`、`answers` 和 `skipped`，让命令创建新的 `attempt_id`；后续提交必须复用该 `attempt_id`。`answers` 的键使用 `writing`、`26` 至 `55`、`translation`。命令成功后以返回的覆盖数量为准；上下文丢失时通过 `paper-get --paper-id <paper_id> --attempt-id <attempt_id>` 恢复，不让用户重答已保存内容。

结束作答后按题逐项批改阅读，按 CET 写作与翻译维度评价内容、组织、准确性和语言质量；错题按“讲解错题”的固定模板写进套题笔记的 `错题讲解` 折叠块，按题目映射汇总哪些 mastered 知识点表现稳定、哪些需要重新巩固的内容同样只写进笔记；聊天只按「评分后的回复」输出得分行、判定表格与后续菜单。只提取用户实际展示且已解释的独立可复用错误，不因总分低或选错一道题推断其他弱点。选择题错误可用用户所选的错误内容作 `source`，写作和翻译用用户原句作 `source`，并为每条错误提供修正后的代表句。

把批改结果和错误组成一次协调写入：

```bash
python3 skills/learn-from-english/scripts/learning_records.py paper-complete --input <JSON 文件或 ->
```

输入包含 `paper_id`、`attempt_id`、`subjective_scores: {"writing": 0-15, "translation": 0-15}`、完整 `feedback` 和 `errors`。工具按存储的参考答案计算 35 原始阅读分，与写作、翻译组成 65 原始分，再按试卷的线性配置报告为 710 分制。报告满分为 710，达到 425 返回 `passed: true`。向用户展示 `reported_score / 710` 和 425 合格线，同时明确说明这是对应 CET 级别的“无听力模拟折算分”，不是官方考试成绩。

`paper-complete` 在同一写锁下保存 completed attempt 和实际错误；不调用 `complete-review`，不改变 mastered 记录的分数、状态、次数或调度。保存失败时保留完整 payload，只显示“重试保存本次试卷评分”和“放弃评分保存并保留进行中作答”；放弃时不得删除已保存答案，且不得声称成绩或错误已保存。保存成功后先按「生成本轮学习笔记」写一份套题笔记，再按「评分后的回复」输出得分行、判定表格与后续菜单。
