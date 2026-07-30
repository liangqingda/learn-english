# 英语学习 Skills

这是一个面向 Codex 的个人英语学习仓库。它把日常遇到的英文作为学习材料，自动沉淀知识点，并基于真实学习记录安排后续复习、评分和归档。

## 核心能力

- **即时学习**：讲解单词、短语、句子、段落、英文报错和用户自己写的英语。
- **分类记录**：把实际讲解过的内容保存为词汇、短语、语法、用法和错误五类记录。
- **针对性复习**：优先选择掌握分较低、较久未复习的知识点生成练习。
- **掌握度追踪**：每次有效作答按 0 至 10 分记录掌握情况。
- **自动归档**：普通知识点单次获得 8 至 9 分后，移入熟练知识点目录；获得 10 分时精简归入完全掌握目录。
- **多种练习形式**：支持语法、词汇、翻译、场景对话，以及参照 CET-4/CET-6 形式设计的文本习题。

## `AGENTS.md` 提供的功能

`AGENTS.md` 是整个仓库的统一行为规范。两个 Skill 都需要遵守它，主要负责以下能力：

- **统一回复格式**：规定动态回复标题，以及使用 Skill 时的来源标记格式。
- **统一学习菜单**：英语讲解、纠错和复习分支回复会提供 3 至 5 个可直接选择的后续活动，并始终包含场景对话；首次复习入口菜单可用完整四六级套题替代单道四六级习题，避免重复。
- **菜单上下文衔接**：用户回复上一轮菜单编号时，直接执行对应活动，不要求重新发送学习内容。
- **四六级习题规范**：根据知识点生成一道聚焦的 CET-4/CET-6 文本任务，支持选词填空、段落匹配、仔细阅读、汉译英和短写作；出题时不提前公布答案。
- **习题讲解闭环**：四六级习题出题后和批改后都保留“讲解当前习题”入口，用于说明题目文本、考点、推理过程和选项或参考答案。
- **错题记录规范**：只记录用户在明确练习中真实出现的错误，通过记录脚本写入稳定、可复用的错误模式；普通对话、未作答题目和完全正确的答案不会生成错题记录。

## 各 Skill 提供的功能

### `learn-from-english`

用于从用户真实遇到的英语中学习，适合单词、短语、句子、段落、对话、标题、引用、英文报错，以及用户自己写的英语。

- 给出自然中文含义，并结合当前语境解释实际意图。
- 按需讲解句子结构、语法、词汇、搭配、语气、自然度和发音。
- 区分“语法错误”“可以理解但不自然”和“表达正确但风格不同”。
- 面对英文报错或技术文本时，先帮助解决实际问题，再提取值得学习的英语。
- 每轮只提取 1 至 4 个得到实质讲解的知识点，并通过脚本分类写入学习记录，避免重复记录。
- 根据用户表现调整讲解深度，并提供翻译、改写、造句、辨析、场景对话和四六级规格习题等后续活动。

单独发送 `hello`（不区分大小写）或“你好”时不会触发此 Skill，而是交给 `practice-learning-records` 打开复习入口。

### `practice-learning-records`

用于复习已记录的知识点、评价掌握程度并维护知识点的学习状态。

- 单独收到 `hello` 或“你好”时，读取记录数量并生成动态复习菜单。
- 按掌握分从低到高选择知识点；同分时优先选择更久未复习的内容。
- 支持复习错误与语法、词汇与短语、语气与场景用法，也支持基于学习记录生成场景对话和四六级规格习题。
- 普通复习默认生成 2 至 4 个小题，并至少组合两种题型；用户完成后逐题反馈并给出 0 至 10 分的总体评分。
- 每组练习只记一次评分；部分作答时等待补全，用户明确跳过后才按实际完成情况评分。
- 普通知识点单次获得 8 至 9 分时，自动移入 `familiar-learning-records/`；获得 10 分时精简归入 `mastered-learning-records/`。
- 已标熟知识点会按最久未复习顺序再次抽查；得分低于 8 分时自动移回普通复习列表，得分为 10 分时精简归入完全掌握目录。
- 批改过程中发现的真实错误，会同时按 `AGENTS.md` 规范写入错题记录。

两个 Skill 的分工可以概括为：`learn-from-english` 负责“学习并沉淀”，`practice-learning-records` 负责“复习、评分和归档”，`AGENTS.md` 则为两者提供统一的回复、菜单、习题和错题记录规则。

## 工作流程

```text
输入英语
   ↓
learn-from-english 讲解并提取知识点
   ↓
learning-records 保存待巩固内容
   ↓
practice-learning-records 生成复习并评分
   ↓
10 分精简归入完全掌握目录；8 至 9 分归档
   ↓
familiar-learning-records 归档熟练内容
mastered-learning-records 归档完全掌握内容
```

当用户只发送 `hello` 或“你好”时，会直接进入基于学习记录的复习菜单；其他英语学习请求由 `learn-from-english` 处理。

## 目录结构

```text
.
├── AGENTS.md                         # 仓库级回复与练习规则
├── learn-from-english/
│   ├── SKILL.md                      # 英语讲解与知识点记录流程
│   ├── scripts/learning_records.py   # 学习记录命令行工具
│   └── tests/                        # 记录工具的单元测试
├── practice-learning-records/
│   └── SKILL.md                      # 复习、评分与归档流程
├── learning-records/                 # 当前需要复习的知识点
├── familiar-learning-records/        # 已熟练并归档的知识点
└── mastered-learning-records/        # 已完全掌握的精简知识点
```

三个记录目录都按以下五类保存 JSON 文件：

| 分类 | 内容 |
| --- | --- |
| `vocabulary` | 单词及其语境含义 |
| `phrases` | 短语、固定表达和搭配 |
| `grammar` | 语法规则和可复用句型 |
| `usage` | 语气、语域、自然度和场景选择 |
| `errors` | 用户出现并得到讲解的错误模式 |

## 学习记录工具

所有学习记录都应通过 `learn-from-english/scripts/learning_records.py` 读写，避免直接编辑 JSON 文件。

```bash
# 查看各分类的待复习数量
python3 learn-from-english/scripts/learning_records.py summary

# 同时查看待复习、已标熟和完全掌握数量
python3 learn-from-english/scripts/learning_records.py summary \
  --include-familiar \
  --include-mastered

# 查看某一分类，结果按掌握分从低到高排列
python3 learn-from-english/scripts/learning_records.py list --category grammar

# 搜索已有知识点，可按需包含已标熟记录
python3 learn-from-english/scripts/learning_records.py search \
  --query "present perfect" \
  --include-familiar \
  --include-mastered

# 生成复习入口菜单
python3 learn-from-english/scripts/learning_records.py menu

# 从一个复习路径里选择下一条应练习的记录
python3 learn-from-english/scripts/learning_records.py next-review \
  --path errors-grammar

# 记录一次复习得分
python3 learn-from-english/scripts/learning_records.py review \
  --category grammar \
  --key present-perfect-experience \
  --score 9

# 检查并迁移旧格式记录
python3 learn-from-english/scripts/learning_records.py validate
python3 learn-from-english/scripts/learning_records.py migrate
```

脚本还提供 `upsert` 命令供 Skill 写入新知识点。规范化后的分类与键共同组成稳定 ID；待复习和已归档目录中存在相同 ID 时，不会重复写入或覆盖。

`menu` 和 `next-review` 把复习入口生成、分类合并、已标熟入口统计、低分优先选择等规则放在脚本里，Skill 应优先使用它们，避免临场拼接菜单时漏掉数量或选错记录。

## 运行测试

项目只依赖 Python 标准库。可在仓库根目录运行：

```bash
python3 -m unittest discover -s learn-from-english/tests -v
```

测试覆盖知识点写入、去重、搜索、分类统计、结构化菜单、下一条复习选择、评分排序、达标归档、10 分精简归入完全掌握目录、旧记录迁移、数据校验，以及损坏数据保护等行为。
