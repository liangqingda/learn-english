> 本文件是 `practice-learning-records/SKILL.md` 的分支参考（菜单数字分派）。只在用户回复最近菜单里的纯数字或数字路径时读取：它逐条给出每个 option `kind` 要执行的 CLI、参数与禁止事项。
> 规则只在本文维护一份，SKILL.md 只留入口与硬约束。

## 处理数字选择

只把对最近一轮菜单的纯数字或纯数字路径回复解释为菜单选择。始终根据 option 的 `kind` 分派，不根据 `label` 或 `id` 猜测行为；有 `action` 时按其中的 command 和参数调用 CLI，option ID 只用于稳定身份和父子关系：

- `review-path`：运行 action 指定的 `next-review --path <path>`。
- `continue-review`：运行 `next-review --random`。
- `familiar-review`：按 action 运行 `next-review --status familiar`。
- `mastered-review`：按 action 运行 `next-review --status mastered --random`，把它作为已掌握知识点的随机抽查；评分照常走 `review-round` 的 `review` 段。已掌握记录连续第 3 次 10 分时脚本会自动删除这条记录（返回 `deleted: true`；本轮带 `note` 段时另返回 `note_skipped: record-auto-deleted`），笔记 md 保留、不补写、不删除，照常输出得分行、判定表格与后续菜单。
- `mastered-exam-paper`：运行 `mastered-list`；用户已指定考试类型时使用相应 profile，未指定时根据当前学习目标选择合适类型并在卷首明确考试名称和评分规则。
- `paper-history`：只作为包含历史试卷 children 的导航父项，不直接执行。
- `historical-unanswered-paper`：按 action 运行 `paper-get --paper-id <paper_id>`，展示不含答案和解析的原卷；选择本身不创建作答。
- `continue-paper-attempt`：按 action 运行带 `paper_id` 和 `attempt_id` 的 `paper-get`，恢复已保存答案，只列出仍缺少的可作答项并继续该 attempt。
- `retry-random-paper`：运行 `paper-list --status completed --random`，再对返回的 `paper_id` 运行 `paper-get`；展示原卷但不展示旧答案，首次提交时省略 `attempt_id` 以创建新的 attempt。
- `starter-practice`：在没有学习记录时，围绕一个日常表达生成 2 至 3 道基础英语练习；题目未作答时不显示菜单；用户提交后按「练习计分」评分并只写笔记（没有可锚定的记录时只给聊天里的得分行与判定表格，不新建笔记），并仅在实际出错时用一次 `batch-upsert` 保存可复用错误。
- `scenario-dialogue`：有当前记录或 focus 时围绕它输出完整多轮场景对话；仅在两者都不存在时使用脚本给出的日常场景。不要把已有记录替换成咖啡店主题，也不要默认开启互动角色扮演，除非用户明确要求 role-play。菜单不记录你选过什么，同一个知识点下这一项可以反复被选中：再次选中时必须换人物、换场合、换冲突，不得复用上一次的台词骨架；笔记里写 `## 讲解` 之后的文件级小节（首次 `append-explain-section`，第二次起 `append-explain-part`），只有一段时 summary 写 `场景对话原文`，第二段起第一段改成 `场景对话原文 1`、第二段写 `场景对话原文 2`（记法见 `take-english-study-notes/references/note-format.md`）。
- `focus-story`：围绕 option 的 `focus` 输出单线叙事小故事，不写成对话；篇幅、结构、目标表达落点、中文对照与收尾三列表按仓库根目录 `AGENTS.md` 的小故事规则执行。它不生成练习、不计分、不调用 `complete-review`、不写错题记录，完整故事只是示例材料；展示完照常给下一轮菜单。同一知识点下再次选中时，必须换场景、换人物、换情节走向，不得只改几个词重写上一版；笔记里写 `## 讲解` 之后的文件级小节（首次 `append-explain-section`，第二次起 `append-explain-part`），summary 按 `故事原文`（单段）/ `故事原文 1`、`故事原文 2`（多段）编号，每段各带自己的三列表并折叠在各自的故事原文块内，讲解要点仍只有首次那一份。
- `follow-up-directions`：只作为 5 个练习方向的导航父项，本身不执行、不单独作答；用户选中其子项时按子项自己的 `follow-up-learning` 分派。
- `follow-up-learning`：围绕 option label 和 `focus` 生成语法、词汇、对比、发音或产出内容。若生成未作答练习，不显示菜单；用户提交后按「练习计分」评分并把得分只写进笔记，不调用 `complete-review`。只把实际展示的可复用错误用一次 `batch-upsert` 保存。若讲解引入新的稳定知识点，读 `references/knowledge-recording.md` 后保存。
- `explain-current-exercise`：`review-complete` 菜单已不再返回该项，保留分派只为兼容历史菜单；它只在用户刚完成的复习答案存在错误或存在未作答题时解释该题组，不生成新题；错题说明考点、错误机制与正确表达，未作答题说明卡点与参考表达背后的英语计量、语义或结构逻辑。
- `error-clusters`：运行 `error-clusters`，按返回的 `options` 顺序与 `label` 原文展示（脚本已生成全部可选项，**禁止**再手工拼 `1-1` 子项、自行追加「未归类」入口或调整分组）。`tag_families` 只用来说明错题集中在哪类问题。
- `error-cluster-review`：用返回的 `cluster_id` 运行 `error-cluster-get --id <cluster_id>`，按取回的材料围绕该错误模式生成一组聚焦练习；明确这是只写笔记的计分练习（见「练习计分」），不显示菜单，不调用 `complete-review`，也不批量修改成员记录。
- `error-cluster-review-unclustered`：运行 `error-cluster-get --unclustered --limit 8`，用取回的记录组成聚焦练习，其余规则同上。
- 上述两类练习在用户作答后，按「练习计分」评分并把得分写进取回记录中作为锚点的那条笔记，同时只把本次实际展示的新可复用错误用一次 `batch-upsert` 保存。
- `status`：执行返回的 action；初始进度入口通常运行 `stats --period 30d`，只请求分类数量时运行 `summary --include-familiar --include-mastered`。

上下文丢失或数字路径无效时重新运行初始菜单。不要要求用户重新发送“你好”，也不要尝试从规范学习记录恢复普通复习题组或待保存 payload；持久化套题必须通过 `paper-menu`、`paper-get` 和 attempt 数据恢复。

删除知识点或笔记不是菜单动作：用户直接说“删掉某条知识点／某篇笔记”时，不在本文件分派，按 `practice-learning-records/SKILL.md` 的「删除记录与笔记」走 `delete-record` 或 `delete-note`，不要自己改 JSON 或 `rm` 文件。
