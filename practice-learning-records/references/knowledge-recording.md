> 本文件是 `practice-learning-records/SKILL.md` 的分支参考。新的稳定知识点如何入库。只在讲解或练习引入了新的稳定知识点、需要按 batch-upsert 保存时读取。 文中的「小节名」都指 `practice-learning-records/SKILL.md` 里的同名小节。

## 后续学习知识点记录

`follow-up-learning` 不记录分数，但不是“只讲不存”。当后续学习内容引入当前记录之外的稳定、可复习知识点时，先讲解，再用 `upsert` 或一次 `batch-upsert` 写入学习记录：

```bash
python3 learn-from-english/scripts/learning_records.py batch-upsert --input <JSON 文件或 ->
```

输入格式：

```json
{
  "records": [
    {
      "category": "phrases",
      "key": "go-ahead-with-for-approved-plan",
      "title": "go ahead with：按计划推进",
      "explanation": "go ahead with + 名词表示获得允许或决定后继续推进某个计划、活动或安排，语气比 proceed with 更口语。",
      "source": "We can go ahead with the launch.",
      "example": "The team decided to go ahead with the launch.",
      "tags": ["follow-up-learning"]
    }
  ]
}
```

记录边界：

- 记录 `go ahead with`、`move on to`、`continue along` 这类新搭配，或一个新语法/用法差异。
- 不记录只是重复当前复习记录的规则、普通例句改写、临时练习题、完整示例对话台词、发音提示或用户尚未提交答案的题目。
- 若一次扩展讲到多个紧密相关的新知识点，合并为一次 `batch-upsert` 批量写入；每条记录使用稳定语义 `key`，选择 `vocabulary`、`phrases`、`grammar` 或 `usage`，不要为了普通新知识点使用 `errors`。
- 若脚本返回匹配到已有记录而不是新建，照常说明“已遇到/更新已有记录”；不要手工改 JSON。
- 写入失败时仍完成讲解，说明“本轮新知识点未能保存；本轮记录变更已回滚”，并把原始 payload 只保留在当前对话。不要输出得分行与判定表格，只显示“重试保存”和“放弃保存并继续”；重试时原样提交，放弃时清除 payload。若回滚未完整成功，说明可能残留部分变更并停止后续写入。
