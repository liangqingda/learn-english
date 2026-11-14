# 英语学习 Skills

这是一个面向 Codex 的个人英语学习仓库。它从真实英语输入中提取知识点，通过版本化 JSON 数据库记录重复学习、复习评分、错误模式、掌握状态和下一次复习时间。

## 核心能力

- `learn-from-english`：讲解单词、短语、句子、长文本和英文错误信息，并批量保存本轮知识点。
- `practice-learning-records`：选择到期或低分记录生成练习，在一次协调写操作中保存评分、状态变化和实际错题。
- `take-english-study-notes`：`learning-record-notes/` 的唯一 owner（规则、模板、校验器、写入实现），前两个 skill 要落笔记时都调它。
- 三级状态：`learning`、`familiar`、`mastered`。
- 间隔复习：根据得分、连续高分和遗忘次数计算 `next_review_at`。
- 掌握判定：复习中同一知识点累计 3 次达到 10 分后才进入 `mastered`。
- 精简归档：知识点进入 `mastered` 后保留稳定 ID、语义 `key`、标题、讲解、代表例句、标签和掌握时间；逐次评分历史与计数会被重置，失分回落时例句与标签仍然可用。
- 集中菜单：脚本按对话上下文生成菜单树 —— `initial`、`review-complete`、`learn`（教学侧）三种上下文共用同一生成器，历史试卷入口默认合并进 `menu` 输出；Skill 只负责渲染与分派。
- 数量就近展示：记录数量只标在对应菜单项末尾，不额外输出状态汇总开场。
- 相关检索与聚类：搜索返回相关度、命中字段和摘要；`error-clusters` 按可复用模式聚类，并把无法成组的错题作为 `unclustered` 单独列出，同时给出 `tag_families`；`duplicates --threshold 0.85` 列出可合并的近义记录。
- 进展分析：统计按日期、类别和分数段汇总，并报告到期积压、遗忘与掌握数量。
- 套题历史：每张考试试卷与多次作答保存在同一个文件中，可续答未完成 attempt 或随机重做历史试卷。
- 可配置评分：每张试卷自行定义主客观评分项、原始满分、报告满分、合格线和换算方式；四六级无听力卷报告为 710 分制，425 分合格。
- 崩溃可恢复：跨文件写入前把目标文件原始内容备份到 `learning-records/.txn/` 并写 `.txn-journal.json`；中途失败立即回滚，进程被杀时下一次写操作自动恢复并记账到 `.txn-recovery.log`。

## 架构

```text
Skill / CLI
    ↓
cli.py
    ↓
service.py ── menu.py
    │         scheduler.py
    │         papers.py
    ↓
store.py ── 校验、原子替换、事务日志
    ↓
learning-records/<category>.json
mastered-learning-records/<category>.json
exam-papers/<paper_id>.json
```

实现位于 `learn-from-english/scripts/learning_records_tool/`：

| 模块 | 职责 |
| --- | --- |
| `models.py` | Schema v2、规范化 ID、字段与关系校验 |
| `store.py` | 按分类合并读取、按库分流、临时文件、`fsync` 和原子替换 |
| `service.py` | 批量写入、评分协调、查询、迁移、历史与统计 |
| `scheduler.py` | 状态转换、复习间隔和选题优先级 |
| `menu.py` | 初始与复习完成后的菜单策略、可用性和嵌套选项 |
| `papers.py` | 完整套题校验、一卷一文件、多次作答、评分和历史菜单 |
| `cli.py` | 新旧命令的兼容入口 |

原有 `learn-from-english/scripts/learning_records.py` 路径保持不变，它现在是轻量兼容入口。

## 数据模型

学习中和已标熟记录按类别保存在 `learning-records/<category>.json`。已掌握记录按同一类别保存在 `mastered-learning-records/<category>.json`。查询、菜单和复习抽题会合并读取两个目录，所以 CLI 调用方式保持不变。

`learning-records/` 下的每个分类文件都是一个 Schema v2 数据库片段，顶层 `category` 表示该文件只保存这一类记录。记录的 `status` 仍然保存在字段里；`learning` 和 `familiar` 留在 `learning-records/`。

`mastered-learning-records/` 下的每个分类文件参考旧版 `mastered.json`，根节点直接是数组，每条只保留稳定 `id`、`title`、`explanation` 和 `mastered_at`。同一知识点累计第 3 次达到 10 分后才移动到对应的 mastered 分类文件。

读取精简记录时，工具会补齐复习流程需要的运行字段：`source` 使用 `explanation`，`key` 由记录 ID 后缀补齐，`example` 与 `tags` 直接读归档值（旧版归档没有这两个字段时为空），首次与最近学习时间使用 `mastered_at`，`learned_count` 为 1，`mastery_score` 为 10，`review_count` 与 `lapse_count` 为 0，`high_score_streak` 为 1，`last_reviewed_at` 使用 `mastered_at`，`next_review_at` 为空，`review_history` 为空。若已掌握记录复习失分并回到 `learning`，例句与标签仍然保留，掌握前的计数与逐次评分历史不会恢复。

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

`exam-papers/<paper_id>.json` 使用独立的 Paper Schema v2。文件保存一张试卷的题目、参考答案、mastered 素材映射及全部 `attempts`；每个 attempt 独立保存增量答案、跳过项、状态和最终评分。`paper_id` 采用 `<exam_type>-YYYYMMDDTHHMMSS-<8hex>`，标题采用 `<exam_name> 模拟卷｜<主题>｜YYYY-MM-DD`。首次提交答案时创建 `in_progress` attempt，评分成功后转为 `completed`，同一试卷可以继续追加新的 attempt。

试卷通过 `answer_keys` 定义作答面，通过 `objective_items` 定义可自动判分的答案与分值，通过 `subjective_components` 定义需要人工评价的评分项。`grading_scheme` 独立保存 `raw_max_score`、`reported_max_score`、可为空的 `pass_score`、`linear/identity` 换算方式、小数精度、可选 `rounding_step`、单位和成绩说明。因此存储和菜单不依赖 CET：四六级可以把无听力 65 原始分线性报告为 710 分制，IELTS 风格练习可以配置 9 分制、0.5 Band 舍入及用户目标 Band，没有统一合格线的考试可以把 `pass_score` 设为 `null`。

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

输入可以是记录数组，也可以是 `{"records": [...]}`。重复 ID 或同类高度相似知识点会复用已有记录、增加 `learned_count`、更新时间，并用更完整的新内容补齐较弱的 `explanation`、`source` 或 `example`，同时合并标签。返回值用 `reason`、`similarity` 和 `enriched_fields` 说明匹配与补全结果，避免把同一知识点拆成多条。

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

python3 learn-from-english/scripts/learning_records.py next-review \
  --path errors-grammar --claim-owner <conversation-owner>
python3 learn-from-english/scripts/learning_records.py next-review \
  --mastered --random --claim-owner <conversation-owner>
python3 learn-from-english/scripts/learning_records.py release-claim \
  --id <record-id> --claim-owner <owner> --claim-token <token>
python3 learn-from-english/scripts/learning_records.py mastered-list
```

菜单 option 以 `kind` 决定分派，并为 CLI 操作提供结构化 `action`；调用方不得从 label 或 ID 猜行为。`scenario-dialogue` 与 `focus-story` 都是只读展示项（`writes: false`）：前者输出多轮场景对话，后者输出围绕 `focus` 的单线叙事小故事，两者都不计分、不写 `errors`。`action.status` 固定映射为 `next-review --status <value>`，`action.random: true` 映射为 `--random`。综合复习项可以带 `children`，顶层编号为 `1`，子项编号为 `1-1`。菜单还会报告 `available_count`、`claimed_count`、`busy` 和 `disabled`，避免把暂时都被领取的记录显示成可立即抽取。

选题先考虑是否到期，再考虑到期时间、掌握分、遗忘次数和稳定 ID。普通继续复习按低分与遗忘次数加权；已掌握复习使用随机抽查。完整套题入口使用 `mastered-list` 返回已掌握素材。

普通复习题组、领取凭据和失败后待重试的写入 payload 只保留在当前对话，不写入学习记录或 session 文件。抽题时为当前对话生成 `claim-owner`，并保留返回的 claim token；`complete-review` payload 携带 `claim_owner` 与 `claim_token`，保存成功时校验并释放领取。未作答练习是当前回复的唯一操作入口。保存失败时保留原 payload 和领取凭据，仅提供重试或放弃；恢复操作优先于尚未展示的练习，保存成功或明确放弃后才出题。放弃或退出题组时调用 `release-claim`。上下文丢失后不能恢复普通题组，领取等待自动过期。

完整试卷在首次展示前通过 `paper-create` 保存。`paper-submit` 按试卷自己的 `answer_keys` 增量保存答案，`paper-get` 可在上下文丢失后恢复进行中 attempt，`paper-list --status completed --random` 支持随机重做历史试卷。`paper-complete` 自动计算客观题原始分、合并通用 `subjective_scores`，再按该卷的 `grading_scheme` 生成报告分和通过判定；结果不改变 mastered 记录的复习状态。

当前 CET profile 仍保留 57 个官方题位，其中听力 25 题只保留位置、不生成内容，实际可作答 32 项。写作、阅读、翻译合计 65 原始分并线性报告为 710 分制，报告分达到 425 判定通过；成绩说明必须标注“无听力模拟折算分，不是官方成绩”。

### 考试试卷历史

```bash
python3 learn-from-english/scripts/learning_records.py paper-create --input paper.json
python3 learn-from-english/scripts/learning_records.py paper-list --status unanswered
python3 learn-from-english/scripts/learning_records.py paper-list --status completed --random
python3 learn-from-english/scripts/learning_records.py paper-get \
  --paper-id <paper-id> --attempt-id <attempt-id>
python3 learn-from-english/scripts/learning_records.py paper-submit --input answers.json
python3 learn-from-english/scripts/learning_records.py paper-complete --input grading.json
python3 learn-from-english/scripts/learning_records.py paper-menu
```

`paper-menu` 返回未作答试卷树、进行中 attempt 树和随机重做入口，供两个英语技能统一插入 `Popular Menus`。`paper-complete` 在同一写锁下协调保存 completed attempt 和用户实际展示且已解释的错误；任一步失败时恢复试卷与学习记录文件。放弃失败的评分保存只丢弃待提交评分，不删除已经增量保存的答案。

### 复习笔记

`learning-record-notes/` 下的 Markdown 笔记是可读副本，也只能通过脚本写入。讲解写成文件级的 `## 讲解` 小节（紧跟 `## 基础信息`、在所有日期区块之前，一个知识点只有一份），同一知识点的复习继续追加到同一个文件：

```bash
python3 take-english-study-notes/scripts/note.py append \
  --file learning-record-notes/errors-back-west-spacing.md \
  --content-file - --check <<'EOF'
# 2026-11-07 21:30 · 复习
…本轮区块全文…
EOF
python3 take-english-study-notes/scripts/note.py replace \
  --file learning-record-notes/errors-back-west-spacing.md \
  --heading "# 2026-11-07 21:30 · 复习" \
  --content-file - <<'EOF'
# 2026-11-07 21:30 · 复习
…修正后的本轮区块全文…
EOF
```

区块走标准输入，不落中间文件；确需文件时用 `mktemp` 生成唯一路径，**不要**用 `/tmp/note-block.md` 这类固定路径，否则并行会话会互相覆盖内容源。`append` 在 `learning-record-notes/.notes.lock` 上取排他锁，锁内完成“读现有文件 → 追加 `---` 分隔 → `os.replace` 原子替换”，因此多个会话同时写同一个笔记文件不会互相覆盖。判重按「标题 + 正文」：同标题同内容返回 `appended: false, duplicate: true`（不要重试）；同标题但内容不同不会丢内容，命令会把时间顺延到不冲突且保持升序的分钟并返回 `heading_adjusted: true` 与新的 `heading`。`append-section` 用同一把锁把单个 `## <菜单项>` 小节塞进既有区块，区块其余内容一字不动，因此给已有区块补一节不需要整块重写；`replace` 只用于修正本轮自己写错的区块，一次只允许改一个小节（批量迁移逐节加 `--rewrite-section`，返回 `modified_sections`），并在锁内自动保留新内容没有带上的既有小节（返回 `preserved_sections`），只有 `--drop-section` 显式列出的小节才允许真的删除。

`take-english-study-notes/scripts/note.py` 是复习笔记的统一入口，写入与校验都在 `take-english-study-notes` 内完成（`note_store.py` 负责锁与原子替换，`check_note.py` 负责校验），不需要安装其他 skill 才能写。唯一跨 skill 依赖是只读的记录事实：追踪表比对通过 `learning_records.py record-tracking --id <id>` 取回期望值（按 `$LEARN_ENGLISH_CLI`、仓库内同级目录、安装位依次查找），取不到时返回 `tracking_skipped` 而不阻断写入。写入命令会自己完成三件事：撞上已有笔记时拒绝另建文件并给出应复用的路径；校验不过时自动执行可安全修复项再复检（`auto_fixed`）；把追踪表与规范记录逐字段比对，不一致时返回 `tracking_mismatch` 与 `tracking_expected`，其中记录直接拥有的 `累计复习次数` / `下次复习` 会按记录值自动回填（`basic_info_synced`），其余字段仍需调用方修正；已有笔记顶部停在旧值时用 `note.py sync --file <笔记>` 就地修复。CI 与本地体检都用 `note.py check --all`。`--check` 结果放进 `check` 字段，并用 `check_ok` / `note_status` 区分写入与合规：`valid` 通过，`invalid` 表示写入成功但校验未过（进程退出码 1），`unverified` 表示校验器不可用。笔记格式的唯一规则来源是 `take-english-study-notes/references/note-format.md`，版式以 `templates/review-note.md` 为准。

### 查询和统计

```bash
python3 learn-from-english/scripts/learning_records.py list --category grammar
python3 learn-from-english/scripts/learning_records.py search \
  --query "present perfect"
python3 learn-from-english/scripts/learning_records.py search \
  --query "article" --status learning --status familiar
python3 learn-from-english/scripts/learning_records.py summary \
  --include-familiar \
  --include-mastered
python3 learn-from-english/scripts/learning_records.py history \
  --id grammar:present-perfect-experience
python3 learn-from-english/scripts/learning_records.py stats --period 30d
python3 learn-from-english/scripts/learning_records.py error-clusters
python3 learn-from-english/scripts/learning_records.py error-cluster-get \
  --id <cluster-id>
python3 learn-from-english/scripts/learning_records.py error-cluster-get \
  --unclustered --limit 8
python3 learn-from-english/scripts/learning_records.py familiar-list --brief
python3 learn-from-english/scripts/learning_records.py snapshot --record "<record-id>"
python3 learn-from-english/scripts/learning_records.py snapshot --notes
python3 learn-from-english/scripts/take-english-study-notes/scripts/note.py sections \
  --file "learning-record-notes/<note>.md" --section "## <section title>"
```

`search` 默认检索全部状态，按相关度排序，并返回 `matched_fields`、`snippet` 和 `relevance`；调用方可以用重复的 `--status` 限制范围。`stats` 在基础总数与事件之外返回 `snapshot_totals`、`daily`、`by_category`、`score_distribution`、`due_backlog`、`mastered_random_pool`、`lapse_count` 和 `mastery_count`；其中 `due_backlog` 只统计仍需调度的 learning/familiar 记录，已掌握记录作为随机抽查池单列。

`error-clusters` 默认返回**精简**结果：`clusters`（id / label / count / record_ids）与 `options`（脚本生成的错题专题菜单项，含未归类入口）、`unclustered_count`、`tag_families`（最多 12 条）+ `tag_family_total`，不再内联全部记录（`errors` 记录上百条时输出从 230 KB 降到 17 KB 量级）。需要某一类的完整材料时用 `error-cluster-get` 取回精简字段（id / title / explanation / source / example / tags），它的 `--minimum-size` 必须与 `error-clusters` 一致，否则拿到的 cluster id 可能对不上；它不自动合并记录，也不改变多个规范记录的分数。`list` / `familiar-list` / `mastered-list` 加 `--brief` 可省略 `review_history` 与调度时间戳。

`snapshot` 是一次拿齐“仓库现在到哪了”的只读入口：`git_head`、笔记文件清单、每个文件的**轮次区块与 `##` 小节标题索引**、`record_files`（记录 ID → 笔记文件，记录已改名也能定位）。结果缓存在 `.cache/snapshot.json`，默认 30 分钟有效（`--max-age` 可改，`--refresh` 强制重建），命中时带 `source: cache` 与 `age_seconds`；`live_git_head` 与 `head_drift` 给出一次实时 HEAD 比对，`head_drift: true` 表示工作树已被别的会话推进，只读展示可继续，写入前再 `--refresh`。笔记写入已独立到 `take-english-study-notes`，不再刷新这份快照；写前确认目标区块用 `take-english-study-notes/scripts/note.py sections`，需要新的仓库索引时再跑 `snapshot --refresh`。缓存只是加速层：读索引前会比对文件的 `size` 与 `mtime`，不一致就回退到真实解析，删掉缓存文件也永远安全。菜单 option 现在带 `writes`：`false` 的项（场景对话、小故事、学习进度、错题聚类、剖析当前题、历史试卷导航）只展示内容，不做仓库核对；校验器只在写入路径运行。

`sections` 是写笔记前的只读体检：返回该文件的全部轮次标题与每个轮次下的 `##` 小节标题，`--heading` 只看一个轮次；带 `--section "## ..."` 时额外返回 `has_section`，据此决定 `append-section` 还是 `replace --rewrite-section`，不必拼好整段内容再被拒。它同样走缓存索引，文件被外部改动时自动回真实解析。

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
├── exam-papers/
│   └── <paper_id>.json
├── learning-record-notes/
│   ├── README.md
│   └── <category>-<slug>.md
├── learn-from-english/
│   ├── SKILL.md
│   ├── agents/openai.yaml
│   ├── scripts/
│   │   ├── learning_records.py
│   │   └── learning_records_tool/
│   └── tests/
├── practice-learning-records/
│   ├── SKILL.md
│   ├── references/note-format.md
│   ├── templates/review-note.md
│   ├── scripts/check_note.py
│   ├── scripts/note.py
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
