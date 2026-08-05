# 英语学习 Skills

这是一个面向 Codex 的个人英语学习仓库。它从真实英语输入中提取知识点，通过版本化 JSON 数据库记录重复学习、复习评分、错误模式、掌握状态和下一次复习时间。

## 核心能力

- `learn-from-english`：讲解单词、短语、句子、长文本和英文错误信息，并批量保存本轮知识点。
- `practice-learning-records`：选择到期或低分记录生成练习，在一次协调写操作中保存评分、状态变化和实际错题。
- 三级状态：`learning`、`familiar`、`mastered`。
- 间隔复习：根据得分、连续高分和遗忘次数计算 `next_review_at`。
- 掌握判定：复习中同一知识点累计 3 次达到 10 分后才进入 `mastered`。
- 精简归档：知识点进入 `mastered` 后只保留稳定 ID、标题、讲解和掌握时间；详细学习字段与逐次评分历史会被重置。
- 集中菜单：脚本根据对话上下文生成 3 至 5 个稳定入口，Skill 只负责渲染。
- 数量就近展示：记录数量只标在对应菜单项末尾，不额外输出状态汇总开场。

## 架构

```text
Skill / CLI
    ↓
cli.py
    ↓
service.py ── menu.py
    │         scheduler.py
    ↓
store.py ── 校验、原子替换
    ↓
learning-records/<category>.json
mastered-learning-records/<category>.json
```

实现位于 `learn-from-english/scripts/learning_records_tool/`：

| 模块 | 职责 |
| --- | --- |
| `models.py` | Schema v2、规范化 ID、字段与关系校验 |
| `store.py` | 按分类合并读取、按库分流、临时文件、`fsync` 和原子替换 |
| `service.py` | 批量写入、评分协调、查询、迁移、历史与统计 |
| `scheduler.py` | 状态转换、复习间隔和选题优先级 |
| `menu.py` | 初始、复习后和习题中三类菜单策略 |
| `cli.py` | 新旧命令的兼容入口 |

原有 `learn-from-english/scripts/learning_records.py` 路径保持不变，它现在是轻量兼容入口。

## 数据模型

学习中和已标熟记录按类别保存在 `learning-records/<category>.json`。已掌握记录按同一类别保存在 `mastered-learning-records/<category>.json`。查询、菜单和复习抽题会合并读取两个目录，所以 CLI 调用方式保持不变。

`learning-records/` 下的每个分类文件都是一个 Schema v2 数据库片段，顶层 `category` 表示该文件只保存这一类记录。记录的 `status` 仍然保存在字段里；`learning` 和 `familiar` 留在 `learning-records/`。

`mastered-learning-records/` 下的每个分类文件参考旧版 `mastered.json`，根节点直接是数组，每条只保留稳定 `id`、`title`、`explanation` 和 `mastered_at`。同一知识点累计第 3 次达到 10 分后才移动到对应的 mastered 分类文件。

读取精简记录时，工具会补齐复习流程需要的运行字段，但不会恢复掌握前的详细数据：`source` 使用 `explanation`，`example` 为空，`tags` 为空，首次与最近学习时间使用 `mastered_at`，`learned_count` 为 1，`mastery_score` 为 10，`review_count` 与 `lapse_count` 为 0，`high_score_streak` 为 1，`last_reviewed_at` 使用 `mastered_at`，`next_review_at` 为空，`review_history` 为空。若已掌握记录复习失分并回到 `learning`，这些补齐值会成为新一轮学习记录的起点；掌握前的例句、标签、计数和逐次历史不会恢复。这是当前精简存储的有意取舍。

```json
{
  "schema_version": 2,
  "revision": 1,
  "category": "grammar",
  "records": {
    "grammar:present-perfect-experience": {
      "id": "grammar:present-perfect-experience",
      "category": "grammar",
      "status": "learning",
      "title": "现在完成时表示经历",
      "explanation": "...",
      "source": "...",
      "example": "...",
      "tags": [],
      "first_learned_at": "...",
      "last_learned_at": "...",
      "learned_count": 1,
      "mastery_score": 0,
      "review_count": 0,
      "high_score_streak": 0,
      "last_reviewed_at": null,
      "next_review_at": null,
      "lapse_count": 0,
      "mastered_at": null,
      "review_history": []
    }
  }
}
```

旧数据迁移会保留已有数量、分数和时间。旧格式没有保存逐次评分，因此 `review_history` 只从 Schema v2 启用后开始积累。

## 协调写入与回滚

每个写命令执行：

```text
获取本机进程写锁
  → 读取并校验当前 revision
  → 在内存中应用整个操作
  → 校验完整结果
  → 把 learning/familiar 与 mastered 记录按目录和 category 拆分
  → 只为内容变化的分类文件写入同目录临时文件并 fsync
  → 逐个原子替换受影响的分类文件
  → 发生跨文件写入失败时尽力恢复本轮已替换的文件
```

任一输入无效时不会开始写入。存储层使用本机独占文件锁协调多个写进程，单个分类文件通过临时文件替换保证原子更新；多个分类文件无法由文件系统一次提交，因此中途失败时执行尽力回滚。若回滚本身失败，命令必须报告可能残留的部分变更，调用方不得声称本轮已完整保存或完整撤销。服务层不执行 Git 提交；仓库内容的提交由调用它的 agent 按 `AGENTS.md` 单独完成。

## 常用命令

### 批量学习记录

```bash
python3 learn-from-english/scripts/learning_records.py batch-upsert \
  --input new-records.json
```

输入可以是记录数组，也可以是 `{"records": [...]}`。重复 ID 或同类高度相似知识点不覆盖原讲解，而是复用已有记录、增加 `learned_count` 并更新 `last_learned_at`，避免把同一知识点拆成多条。

单条兼容命令仍可使用：

```bash
python3 learn-from-english/scripts/learning_records.py upsert \
  --category grammar \
  --key present-perfect-experience \
  --title "现在完成时表示经历" \
  --explanation "..." \
  --source "..." \
  --example "..."
```

### 评分与错题协调写入

```bash
python3 learn-from-english/scripts/learning_records.py complete-review \
  --input review-result.json
```

输入包含目标 `id`、`score` 和 `errors` 数组。评分、状态转换、下次复习时间、历史事件和错误记录在一次加锁的协调写操作中处理；新增错题同样会先匹配同类相似记录，匹配到时只记一次新的 encounter。输入校验失败时不会写入；跨文件写入中途失败时执行尽力回滚，并由调用方明确告知用户本轮评分和记录未保存以及回滚结果。

旧的 `review` 与 `familiar-review` 命令仍可使用，但不能同时写入错题。

### 合并重复记录

```bash
python3 learn-from-english/scripts/learning_records.py merge \
  --target errors:existing-record \
  --source errors:duplicate-record \
  --title "优化后的标题" \
  --explanation "优化后的说明"
```

`merge` 只允许合并同一 category 的记录，会保留标签、学习次数、复习次数和历史事件，删除来源记录，并按合并后的最低掌握分重新确定当前状态。

### 菜单和选题

```bash
python3 learn-from-english/scripts/learning_records.py menu --context initial
python3 learn-from-english/scripts/learning_records.py menu \
  --context review-complete --focus "present perfect"
python3 learn-from-english/scripts/learning_records.py menu \
  --context exercise-active --focus "present perfect"

python3 learn-from-english/scripts/learning_records.py next-review --path errors-grammar
python3 learn-from-english/scripts/learning_records.py next-review --familiar
python3 learn-from-english/scripts/learning_records.py next-review --mastered
python3 learn-from-english/scripts/learning_records.py next-review --random
python3 learn-from-english/scripts/learning_records.py mastered-list
```

选题先考虑是否到期，再考虑到期时间、掌握分、遗忘次数和稳定 ID。随机复习按低分与遗忘次数加权。完整四六级套题入口使用 `mastered-list` 合并返回 `mastered-learning-records/` 下的已掌握素材。

### 查询和统计

```bash
python3 learn-from-english/scripts/learning_records.py list --category grammar
python3 learn-from-english/scripts/learning_records.py search \
  --query "present perfect" \
  --include-familiar \
  --include-mastered
python3 learn-from-english/scripts/learning_records.py summary \
  --include-familiar \
  --include-mastered
python3 learn-from-english/scripts/learning_records.py history \
  --id grammar:present-perfect-experience
python3 learn-from-english/scripts/learning_records.py stats --period 30d
```

### 校验、修复和迁移

```bash
python3 learn-from-english/scripts/learning_records.py validate
python3 learn-from-english/scripts/learning_records.py repair --dry-run
python3 learn-from-english/scripts/learning_records.py repair
python3 learn-from-english/scripts/learning_records.py migrate-v2 --dry-run
```

`validate` 检查 Schema 版本、规范化 ID、字段类型、ISO 时区时间、状态关系、分数范围、标签重复、复习计数和时间先后关系。`repair` 只处理无歧义问题，并支持预览。

## 目录结构

```text
.
├── AGENTS.md
├── learning-records/
│   ├── errors.json
│   ├── grammar.json
│   ├── phrases.json
│   ├── usage.json
│   └── vocabulary.json
├── mastered-learning-records/
│   ├── errors.json
│   ├── grammar.json
│   ├── phrases.json
│   ├── usage.json
│   └── vocabulary.json
├── learn-from-english/
│   ├── SKILL.md
│   ├── agents/openai.yaml
│   ├── scripts/
│   │   ├── learning_records.py
│   │   └── learning_records_tool/
│   └── tests/
├── practice-learning-records/
│   ├── SKILL.md
│   └── agents/openai.yaml
└── .github/workflows/check.yml
```

## 测试

```bash
python3 -m unittest discover -s learn-from-english/tests -v
python3 learn-from-english/scripts/learning_records.py validate
python3 -m compileall -q learn-from-english/scripts learn-from-english/tests
git diff --check
```

测试覆盖批量校验与协调回滚、重复学习、评分与错题写入、状态转换、评分历史、间隔调度、上下文化菜单、旧数据迁移、校验修复、故障注入、CLI 兼容和服务层不介入 Git。GitHub Actions 会在推送和 Pull Request 上自动执行测试、数据校验与编译检查。
