---
name: practice-learning-records
description: 从规范学习记录中选择到期或低分知识点开展复习，按回答记录 0 至 10 分，并在一次协调写操作中保存评分、状态变化和实际错题；有习题的练习项（`starter-practice`、`follow-up-learning`、两个错题聚类练习）也按 0 至 10 计分，但得分只写进 `learning-record-notes/` 的笔记、不写规范记录；也支持复习已标熟或已掌握知识点、查看历史统计、基于已掌握知识点生成/持久化/续答/重做/评分四六级与 IELTS 风格等考试套题，以及按用户给出的复习笔记相对路径直接学习该笔记对应的知识点。当用户消息去除首尾空白后仅为中文“你好”或“复习”，仅为单独的英文单词 review、hi 或 practice（忽略大小写），或仅为一条复习笔记的相对路径（形如 `learning-record-notes/<category>/<category>-<slug>.md`）时必须使用；其中 practice 跳过菜单、直接从综合复习范围随机抽一条记录出题；在本 Skill 打开的复习或套题流程中，用户回复最近菜单中的数字或答案时也使用。除 review、hi、practice 之外的英文输入（含 hello 等单词）一律由 learn-from-english 讲解，本 Skill 不拦截其它英文触发词。
---

# 复习英语学习记录

使用仓库根目录 `learning-records/` 与 `mastered-learning-records/` 中按 category 拆分的规范记录开展复习。`learning-records/<category>.json` 保存 `learning` 与 `familiar` 记录；同一知识点累计第 3 次达到 10 分后，写操作会把它移动到 `mastered-learning-records/<category>.json`。mastered 分类文件参考旧版 `mastered.json`，根节点直接是精简数组，每条保留稳定 `id`、`key`、`title`、`explanation`、`example`、`tags` 和 `mastered_at`。读取时工具会用 `explanation` 补 `source`，逐次评分历史和历史计数会重置；若记录此后失分回到 `learning`，`example` 与 `tags` 仍然可用，掌握前的逐次评分历史不会恢复。所有读取和写入必须通过 `learn-from-english/scripts/learning_records.py`；不得直接编辑 JSON。

## 分支参考文件

本文件只保留每轮都走的流程。下面这些分支按需读取 `practice-learning-records/references/` 里的文件，规则只在那里维护一份，本文件不重复：

| 触发情况 | 读取 |
|---|---|
| 生成、持久化、续答、重做或评分四六级 / IELTS 风格套题 | `references/exam-papers.md` |
| 用户要求讲某道题，或要按四步模板补讲错题 / 未作答题 | `references/error-explanation.md` |
| 讲解或练习引入了新的稳定知识点，要按 `batch-upsert` 入库 | `references/knowledge-recording.md` |
| 某个写操作失败，要决定重试还是放弃 | `references/failure-recovery.md` |
| 用户回复最近菜单里的数字、要按 option `kind` 分派 | `references/menu-dispatch.md` |
| 一轮练习（`starter-practice` / `follow-up-learning` / 错题聚类练习）计分并只写笔记 | `references/practice-scoring.md` |
| 用户整条消息只是一条复习笔记的相对路径 | `references/note-path-entry.md` |

只走普通复习、练习计分、写笔记和给菜单的轮次不读这些文件。

## 打开复习菜单

收到触发词“你好”或“复习”（中文，去除首尾空白后仅为此二者），或单独的英文单词 review、hi（去除首尾空白后仅为此内容，忽略大小写）时运行下面的初始菜单；消息仅为一条复习笔记相对路径时按「从笔记相对路径学习知识点」直接开始那一轮，不弹初始菜单；消息为单独的英文单词 practice 时按「practice 直接随机出题」直接开始一轮，同样不弹初始菜单：

```bash
python3 learn-from-english/scripts/learning_records.py menu --context initial
```

严格按返回的 `options` 顺序、`label` 原文和 `group` 展示菜单，不自行增加、删除、重新分组或估算数量。数量只保留在脚本生成的标签末尾。顶层选项跨分组连续编号为 `1`、`2`；option 含 `children` 时，在父项下把子项编号为 `1-1`、`1-2`，更深层继续追加段。把编号路径与 option 对象只保留在当前对话。脚本保证 `Other Menus` 至少动态生成 3 项；把 `mastered-exam-paper` 和返回的历史试卷选项原样放在 `Popular Menus`。把 `disabled: true` 的项显示为暂不可用但不执行；用户选择时说明记录正被其他会话领取并保持当前菜单。

若 `state` 为 `empty`，说明目前没有学习记录，并直接展示脚本返回的状态、基础练习和咖啡店场景入口，不编造历史知识点。

## practice 直接随机出题

用户消息（去掉首尾空白）整条只是英文单词 `practice`（忽略大小写）时，直接开始一轮普通复习：不运行 `menu`、不展示任何菜单。抽题范围与初始菜单的 `1-1` / `1-2` / `1-3` 完全相同，即 `vocabulary`、`phrases`、`grammar`、`usage`、`errors` 五个分类中 `learning` 状态的记录（当前 301 条），再由 `--random` 按低分与遗忘次数加权抽取，所以这一轮落在哪个分类、哪个知识点是随机的。

1. 先生成当前对话专属 owner，再运行：

```bash
python3 learn-from-english/scripts/learning_records.py next-review --path mixed+usage+vocabulary-phrases+errors-grammar --random --claim-owner <owner>
```

   不要把范围扩到 `familiar` 或 `mastered`：那两类仍然只在初始菜单里主动选择。
2. 保留返回的 `id`、`category`、`status`、`owner` 与 `token`，按「开展普通复习」出 5 至 10 题（默认 6 题），并把题组作为本轮唯一操作入口：不显示菜单，也不在题目之前泄露知识点名称或答案方向。
3. 用户作答后按「评分与协调记录」评分，把评分、本轮笔记与后续菜单用一次 `review-round` 提交（见「会话效率」），再按「评分后的回复」输出得分行、判定表格与后续菜单；此后与普通复习完全一致。
4. 返回 `record: null` 时说明当前没有可抽的 `learning` 记录，不编造知识点，改为运行初始菜单。

## 从笔记相对路径学习知识点

用户消息（去掉首尾空白、可带反引号或引号）整条只是一条复习笔记的相对路径时，直接以该笔记对应的知识点开一轮学习：不弹初始菜单、不领取 claim、不把这条路径当成文件操作。定位记录、出题、评分与补写占位讲解的步骤见 `references/note-path-entry.md`。

## 会话效率

只读选择（option 带 `writes: false`，即 `scenario-dialogue`、`focus-story`、`follow-up-directions`、`status`、`error-clusters`、`explain-current-exercise`、`paper-history`、`historical-unanswered-paper`）只展示内容或查询结果，不核对仓库状态：不运行 `git status`、`git log`、`git diff`，不扫描 `learning-record-notes/` 目录，不用 grep 判断小节是否存在。直接根据当前对话和快照作答。

需要知道“仓库现在到哪了”（HEAD、笔记文件清单、记录→笔记文件映射、某个文件已有哪些区块和小节）时，只运行一次 `snapshot`，不要用多条 `ls` / `git` / `grep` 拼出同一个答案：

```bash
python3 learn-from-english/scripts/learning_records.py snapshot --record "<record id>"
python3 learn-from-english/scripts/learning_records.py snapshot --notes
```

结果来自 30 分钟有效的会话缓存；笔记写入已独立到 `take-english-study-notes`，不再刷新该缓存，只读路径不必加 `--refresh`，写入前若怀疑被别的会话改过则加一次 `--refresh` 或直接用 `note.py sections` 复核。

一轮有作答的复习、练习或套题，评分、写笔记、校验笔记和后续菜单用**一次** `review-round` 完成，不要拆成 `complete-review`、`note.py sections`、`note.py append`、`note.py check`、`menu` 五次调用：

```bash
python3 learn-from-english/scripts/learning_records.py review-round --input -    # payload 走 stdin 或 --input <file>
```

payload 只有四段，缺省段跳过：

- `review`：一次 `complete-review` 的入参（`id`、`score`、`errors`，带 claim 时再加 `claim_owner` / `claim_token`）。普通复习、套题评分必填；纯练习轮次不评分，整段省略。
- `note`：本轮笔记。`file` 是笔记相对路径；`date`（`YYYY-MM-DD`）、`time`（`HH:MM`）、`kind`（`复习` / `练习` / `套题`）决定区块标题；`body` 是本轮区块正文，从该轮题组标题开始（兜底标题 `## 本轮习题`，或题目自带菜单项标题时用那个标题），不含 `# 标题` 行。目标文件还没有文件级 `## 讲解` 时必须给 `explain.content`（含 `## 基础信息` 与 `## 讲解`），命令会先补讲解再写区块。`explain_sections` / `explain_parts` 用来写 `## 讲解` 之后的文件级小节：`explain_sections` 的 `content` 是**整段**文件级小节（含 `## 标题` 行），同名小节已存在时只回报 `duplicate` 并跳过这一项（除场景对话与小故事外不再重复记录），不需要先跑 `sections` 判断；`explain_parts` 的 `content` 只是**正文片段**（不带标题），用于同一菜单项再产出一段故事 / 对话原文，追加到 `title` 指定的小节末尾。
- `menu`：后续菜单的入参（`context`、`focus`、`has_answer_errors`、`current_exercise_explained`、`grammar_explained`）。
- `check`：默认 `true`，写完自动跑校验器，能安全修的先修再复验。

命令返回一个 JSON：`review`、`note`、`check` / `note_status`、`menu`。区块本来就在时返回 `already_saved: true` 并跳过全部讲解区写入，原样重试同一份 payload 不会多存一份故事 / 对话原文；要再加一段故事或对话，用下一轮的 `explain_parts`，不要靠重试。`ok: false` 时看 `failed_step` 与 `steps`：`steps` 里已完成的步骤已经落盘，按 `references/failure-recovery.md` 处理，不要整轮重试。

`note.py` 的 `append-section` / `append-part` / `replace --rewrite-section` 只在组合命令不适用时单独使用（给已有区块补小节——同一菜单项再选一次也走它、由写入器编号成 ` - 01` / ` - 02` 各建一节；`append-part` 只在确实要给同一个小节多补题目时用；改写刚写错的内容、批量迁移）。

一轮的全部错题用一次 `batch-upsert` 写入（已评分复习由 `review-round` 的 `review` 段带 `errors` 一起写），不逐题调用。只读展示不运行 `check_note.py`；校验只在写入路径上跑，结果如实报告。快照 `stale: true` 或怀疑被别的会话改动时，只读内容照常展示，只在真正写入前重新取一次快照。

彼此独立的只读查询（例如 `next-review` 与 `snapshot`）在同一轮并行发出，不要为它们各开一轮。

大块笔记（多题题组的区块）写入前先按 `take-english-study-notes/references/note-format-append.md` 的「写入前预校验与最小改写」用 `mktemp` 草稿跑一次 `note.py check`（约 0.1s），把装配错误在写入前清零；已经落盘后要改一两处时用 `replace --rewrite-section` 只换那一个小节，不重新生成整块正文。

## 处理数字选择

用户回复最近菜单里的纯数字或数字路径时，按该 option 的 `kind` 分派，不按 `label` 或 `id` 猜行为；先读 `references/menu-dispatch.md`，它逐条给出每种 `kind` 要执行的 CLI、参数与禁止事项（导航父项不执行、`disabled` 项不执行、切换题组的项按新一轮记录）。只把最近一轮菜单的数字当成选择；上下文丢失或数字路径无效时重开初始菜单。

## 练习计分

`starter-practice`、`follow-up-learning`、`error-cluster-review`、`error-cluster-review-unclustered` 的题组照常按 0 至 10 计分，但得分只写进 `learning-record-notes/` 的笔记，不改 `learning-records/`、`mastered-learning-records/`；笔记锚点、`未入库` 写法、错题入库与后续菜单见 `references/practice-scoring.md`。

## 选择复习记录

脚本优先返回已经到期的记录，再综合 `next_review_at`、掌握分、遗忘次数和 ID 排序。没有到期记录时返回当前范围内优先级最高的记录。`--random` 只在优先范围中按低分和遗忘次数加权抽取。

执行任何 `next-review` action 前，先为当前对话生成不复用到其他对话的 owner 字符串，并追加 `--claim-owner <owner>`。命令会在写锁保护下写入短期 `review_claim`；保留返回的 owner 与 token，其他会话会跳过该记录。领取会自动过期，且不改变复习次数、分数或状态。

只在当前对话中保留题组、标准答案、作答进度、当前记录 ID、owner、token 和错误讲解状态；不要创建普通复习 session 文件。上下文仍在时继续当前题组；上下文丢失时明确说明不能恢复，并重新打开初始菜单，原领取等待自动过期。用户在评分前明确放弃或退出题组时运行 `release-claim --id <record id> --claim-owner <owner> --claim-token <token>`；释放失败时如实说明领取会等待过期。

“放弃保存”必须放弃当前复习事务的全部结果：评分、状态、复习次数、复习历史、下次复习时间、本轮新增或更新的 `errors`，以及 claim。只保留本轮开始前已经存在的未提交改动和其他任务产生的改动。`complete-review` 报错时，先以脚本的事务回滚结果为准；不得只释放 claim 就把本轮其他残留结果当作已放弃。

不得用 `git restore`、手工回退整份分类文件或其他宽范围操作实现放弃，因为这可能误伤本轮开始前的合法改动。若脚本报告回滚不完整，必须逐项确认本轮目标分类文件、`errors.json`、mastered 文件和 claim 的状态；在无法只撤销本轮结果时，明确说明仍有残留，停止输出得分行与判定表格，并请求修复，不得声称“已放弃”。

命令返回 `record: null` 时明确说明当前范围没有记录，然后重新生成初始菜单；不得临时编造复习记录。

保留返回记录的 `id`、`category` 和 `status`，直到当前题组完成。新抽出记录并首次呈现题目时，直接输出题目本身，不在题目之前输出知识点标题、引导语或任何提示性内容（例如“本次复习的知识点是……”），避免作答前泄露答案方向；不输出菜单；不要在题目正文之前插入来源。仓库 AGENTS.md 要求的 H4 标题只使用不泄露知识点的泛化措辞（如“#### 复习题”）。把来源作为独立斜体元信息，放进题目之后的最终 attribution block：

```text
---
*Picked from <record-source> · <status> · <category>*
*Generated by practice-learning-records skill*
```

`learning` 与 `familiar` 的 `<record-source>` 使用 `learning-records`；`mastered` 使用 `mastered-learning-records`。来源行必须位于区块第一行；若本轮还有 commit notice，把它放在来源之后、skill attribution 之前。后续讲解或评价同一题组时不重复来源标注。

## 开展普通复习

根据记录设计 5 至 10 个短题，默认 6 题，按由易到难的顺序组织，并尽量参照四六级真题的命题风格，至少组合三种题型。`learning` 与 `familiar` 使用 `title`、`explanation`、`source` 和 `example`；`mastered` 的 source/example 是补齐值，只使用 `title` 与 `explanation` 并另造新语境：

- `errors`：使用新句子纠错或改写。
- `grammar`：组合造句、纠错、补全、语境选择或翻译。
- `vocabulary`、`phrases`：组合填空、搭配判断、释义辨析或造句。
- `usage`：组合语气辨析、自然度判断和场景表达。
- 可以适当加入选择题、填空题、改错题、改写题、翻译题、语境判断题和简短产出题，避免同一题型连续过多；题目应先易后难，前几题更聚焦识别和选择，后几题再逐步过渡到改写、翻译和综合运用。
- 不得出依赖「画线」「下划线」或高亮标记的题目：聊天正文呈现不了这些视觉标记，用户看不到被考查的成分。需要指定句子里的某一段时，用引号把该片段原样引用出来（例如题干写成“把 that people have to pay for shortcuts 改成不定式短语”），或者改写成不依赖标记的产出要求；只要题干出现“画线部分”这类指向不明标记的说法，该题作废并重写。

题组必须考查同一知识点的多角度迁移，而不是反复改写同一个句子。出题前先拆出 2 至 4 个可迁移子点，例如搭配冗余、时间从句结构、语义边界、语域自然度、可替换表达或真实场景使用；每道题只聚焦其中 1 至 2 个子点。除非记录本身只有一个固定短语且无法迁移，否则同一题组必须满足：

- 至少 3 道题使用全新的语境、主语或动作，不沿用 `source` 或 `example` 的完整句子骨架。
- 仅当机制的成因确非显而易见、能真正考查理解深度时，才加入“为什么错/为什么自然”的机制判断题；对可直接套用规则（如基本比较级、固定搭配）的简单知识点，不要强行安排这种题，以免显得冗余。
- 至少 1 道题要求用户主动产出，如翻译、改写、造句或短场景回复。
- 至少 1 道题引入近义表达、相邻语境或干扰项，测试用户能否区分边界。
- 不要让 4 道及以上题目的标准答案都只是同一句核心英文的微小变体；如果题目读起来像同一道题换了编号，必须重写。

### 题组内的答案隔离

一套题必须靠语境复杂度、干扰项相似度和产出自由度区分难度，绝不能靠“别处已经写出答案”让题目变成填空题式送分。出题完成后先自检下面五条，任一条不满足就重写该题：

- **题干不得泄漏他题答案**：某题的题干、选项、括号说明或示例里，不得出现另一题的标准答案成分（尤其是介词、反身代词形式、固定搭配的后半截、被考查的语法形式）。例如前题考选 `Help yourself to ...`，后题题干又写出 `... to the fruit`，前题即失效。
- **选项不得共享被考成分**：四选一的干扰项必须是语义上真实可能、但在该语境下不成立的说法，不能是同一正确短语的残形（如 `Help yourself the sandwiches` 这种缺词拼法），否则用户不看题也能凭“只有一项拼得完整”猜对。
- **一题只考一个点，相邻题不得同点**：同一子点（某一介词、某一代词形式、某一固定搭配）只在一题中作为判断核心；其余题改用不同语境、不同产出方式再测同一知识点，不能用同一结构连问两遍。
- **识别题不给结构提示**：单选题若考场景识别，选项写成场景或意图描述，而不是若干只差一个词的句子，避免“句式全同、只挑一个完整版”。
- **至少两题是无提示产出**：用户必须自己决定用哪个表达、什么结构、单复数或语气，题面只给中文意图或场景，不出现目标表达的任何一个词。

要求用户按阿拉伯数字题号集中作答，作答前不公布答案。题目板式（加粗的题号与题型行、题与题之间的 `---`、题干不加粗也不另用标题）按仓库根目录 `AGENTS.md` 的「Exercise group display format」一节执行，题型名直接取笔记固定集合中的一个，方便写入时原样复用。未作答题组是当前回复的唯一操作入口，不显示菜单。用户只回答部分题目时，确认已收到的题号并列出未答题号，不公布答案、不评分；用户补齐或明确跳过剩余题目后再综合评分。

不要根据文字回答评价实际发音。相邻两轮避免完全相同的题型组合。

## 评分与协调记录

用户完成一组可客观评价的复习后，逐题判断并给出自然答案，再综合评为 0 至 10 分（练习轮次同样按这里评分，只是落盘按「练习计分」只写笔记）：

- 9 至 10：完全正确且自然。
- 8：核心正确，有轻微问题。
- 5 至 7：部分掌握。
- 0 至 4：核心规则未掌握。

评分只衡量当前被复习记录对应的目标知识点是否掌握。执行时按下面顺序判断：

1. 先判断当前目标知识点本身是否答对。
2. 目标知识点答对时，必须按通过处理，不能因为答案里还有其他英语问题而把这个目标点判为未通过或降档。
3. 再检查答案里是否出现其他可复用英语错误；这些错误要单独写入本轮 `errors`。
4. 只有当某个错误本身就是当前目标知识点的一部分时，才把它计入当前知识点评分。

换句话说，主评分只看目标点是否掌握，附带错误只做独立记录，不互相覆盖。

在提交评分（`review-round` 的 `review` 段或单独跑的 `complete-review`）前必须执行一次「评分自检」，逐项核对全部通过后才允许写入：

1. 用一句话写出现行目标知识点，**以记录的 title（主规则）为唯一锚点**：explanation 中与 title 同一规则、支撑 title 的细则属于目标点；而 explanation 里标注为“更自然/更贴切/更口语”等次要自然度或语用偏好（例如某语境用某词更自然）**不构成目标点**，除非 title 本身就以该偏好为核心。拿不准时一律按 title 判定。
2. 逐题归因：把每道题及每个错误标记为「属于目标点」或「独立于目标点」。
3. 目标分数只由「属于目标点」的作答决定；任何「独立于目标点」的错误都只放入 `errors`，绝不降低目标分。
4. 只要答案里存在「独立于目标点」的错误，先确认它们已收录进本轮 `errors`，再提交评分。
5. 唯一允许把错误计入目标分的情形：该错误本身构成当前目标知识点的一部分。

若发现目标分曾因「独立于目标点」的错误被下调，必须先更正评分后再提交，不能把独立错误当作扣分依据。

把评分和本轮实际出现的可复用错误模式组成一个 JSON 对象，作为 `review-round` 的 `review` 段，随本轮笔记和后续菜单一次提交（见「会话效率」）：

```bash
python3 learn-from-english/scripts/learning_records.py review-round --input <JSON 文件或 ->
```

`review` 段的格式（单独跑 `complete-review --input` 的入参与此完全相同，只在只写记录、不写笔记的重试路径里单独使用它）：

```json
{
  "id": "grammar:present-perfect-experience",
  "score": 7,
  "claim_owner": "<current conversation owner>",
  "claim_token": "<token returned by next-review>",
  "errors": [
    {
      "key": "stable-semantic-error-key",
      "title": "错误模式标题",
      "explanation": "纠错说明",
      "source": "用户的错误答案",
      "example": "修正后的代表句",
      "tags": ["review-error"]
    }
  ]
}
```

完全正确时传入空 `errors`。只记录用户实际展示并已解释的错误，不推断其他弱点。整个命令先校验评分和所有错误，再在本机写锁保护下逐个原子替换受影响的分类文件：任一输入无效时不会开始写入；跨文件写入中途失败时会尽力回滚本轮已替换的文件，但这不是单次文件系统事务。

一次成功的 `complete-review` 可能同时修改当前目标所属分类文件和 `errors.json`；以命令返回成功为准确认记录已保存，再运行 `git status --short` 检查所有实际受影响的规范文件。提交时只暂存本轮确实改动的文件，但不能只暂存 `errors.json` 而遗漏目标分类文件。若工作区原本已有其他改动，先区分来源并保留它们；若用户随后要求放弃本轮结果，只撤销本轮事务产生的文件变化。

根据返回结果说明状态变化：

- `status: learning`：继续留在待巩固状态。
- `status: familiar`：本次达到 8 分及以上但尚未满足 `mastered` 条件，进入或留在已标熟状态。
- `status: mastered`：同一知识点累计第 3 次达到 10 分，进入已掌握状态，并作为完整英语考试套题素材；未满 3 次的 10 分仍显示为 `familiar`。
- `lapse_count` 增加：原已标熟或已掌握知识点出现遗忘。

命令还会返回 `next_review_at`、`status` 与 `lapse_count`，这些只用来判断记录已怎么变化，不再写进聊天回复。写入成功后按「生成本轮学习笔记」准备好本轮笔记，与评分一起用一次 `review-round` 落盘，再按「评分后的回复」输出得分行、判定表格与后续菜单。写入失败时仍完成教学反馈，说明“本轮评分与错题未能保存；本轮记录变更已回滚”，并把含 `claim_owner`、`claim_token` 的完整 payload 只保留在当前对话。此时不要输出得分行与判定表格，只显示“重试保存本轮评分”和“放弃保存并返回菜单”；重试时原样调用 `complete-review` 并复用凭据，放弃时必须确保本轮评分、状态、历史、错题和 claim 全部清除，再清除 payload。若回滚未完整成功，说明可能残留部分变更并停止后续写入。上下文丢失时说明无法重试并返回初始菜单。

如果重试仍返回“review claim does not exist”或其他领取凭据失效错误，不得暗示评分已经保存；如实说明当前 payload 无法再提交。只有用户明确选择放弃时才尝试 `release-claim`；释放成功后清除 payload 并返回初始菜单，释放失败也要如实说明，不能把失败当作已回滚。

评分后必须运行 `menu --context review-complete --focus "<本轮知识点>"`，把返回的菜单渲染在得分行与判定表格之后（见「评分后的回复」）。

## 评分后的回复

评分保存成功（或用户明确放弃保存）后，聊天回复按下面顺序输出，不追加其他内容。练习轮次（见「练习计分」）同样只输出第 1、2、3、4 部分，只是没有状态变化可写：

1. 得分行：`**得分：<x> / 10**`（套题写 `**得分：<xxx> / 710（无听力模拟折算分）**`），只写分数与满分，不加状态词、不加建议、不加下次复习时间。
2. 判定表格：固定列为「题 | 题型 | 判定 | 关键点」，**必须用表格呈现，一题一行**；判定只取 `✅ 正确` / `⚠️ 部分正确` / `❌ 错误` / `⚠️ 未作答`，「关键点」一句话点出错在哪里或答对在哪，不复述答案、不展开机制。
3. 后续菜单：运行 `menu --context review-complete --focus "<本轮知识点>"`，按返回 `options` 的 `group`、`label`、`kind` 原样渲染；菜单前一行 `➡️ 接下来可以回复数字：` 之前必须先放一个 `---`，`Popular Menus` 必须出现并排在前面，其余按 `group` 归入 `Other Menus`，编号、子项与 emoji 规则按仓库根目录 `AGENTS.md` 的英语学习菜单一节执行；`disabled: true` 的项照样渲染但不执行。
4. 最终 attribution block：本轮是题组首次展示时还需要的 `Picked from` 来源行（来源已在出题那轮写过的不重复）、`*Committed -- <message>*` 提交行、`*Generated by practice-learning-records skill*` 技能行，顺序与分隔符按仓库根目录 `AGENTS.md` 执行。

以下内容一律不写进聊天，因为它们已经落在 `learning-record-notes/` 的笔记里：

- 小结、总结、逐条解析、逐题的考点、错误机制、英语表达逻辑、正确表达（`references/error-explanation.md` 的四步模板只用于笔记的 `错题讲解` 折叠块）；
- 状态变化说明、下次复习时间、最关键建议、本轮写入的文件与字段等过程说明；
- 自检与校验过程（`note_status`、`auto_fixed`、`tracking_mismatch`）；
- 追问式收尾与下一步建议（后续动作只由第 3 部分的菜单承担）。

只有三种情况允许在得分行、判定表格与后续菜单之外加文字：写入失败时读 `references/failure-recovery.md`，只显示重试/放弃两个动作（此时不显示后续菜单）；用户随后明确要求讲某道题时，读 `references/error-explanation.md` 并按其模板补讲该题，此时不重发判定表格；`note_status` 为 `unverified` 或笔记追踪字段与记录不一致时，用一句话如实说明（不展开细节）。

`知识点讲解` 与 `错题讲解` 都是笔记（`learning-record-notes/`）里的强制折叠块，聊天里不再展开。

## 生成本轮学习笔记

每一轮有实际作答的复习、聚焦练习或套题结束后，在记录所在分类的目录里写一份笔记 `learning-record-notes/<category>/<category>-<slug>.md`。笔记的骨架、字段、锚点与索引、菜单小节写法**全部**以 `take-english-study-notes` 为准：`take-english-study-notes/references/note-format.md` 定骨架与字段，需要补写、补段或改写时看同目录 `note-format-append.md`，跑校验或修派生索引看同目录 `note-format-validation.md`；本 skill 不复述这些细则。

本 skill 只保留五条口径：

1. 写入统一走 `review-round` 的 `note` 段，一次落盘评分、笔记与菜单；`note.py` 的子命令只在组合命令不适用时单独使用。
2. 目标文件还没有文件级 `## 讲解` 时必须带上 `explain.content`；笔记只在记录首次写笔记时新建，已有笔记一律复用同一路径。
3. 只有开启新一轮（`practice` 抽题、`review` 复习、套题）才建新日期区块；菜单里继续做的习题（含隔天再做）追加到文件里最新那个区块，用 `append-section`（同一菜单项第二次被选中时编号成 ` - 01` / ` - 02` 各建一节，一节一表、题号各从 1 起），不按当天日期另建区块、也不并进既有小节。
4. 复习轮次的 `body` 写真实状态变化，练习轮次写 `<category> · 未入库`；两种都由 `note` 段承载。
5. `note_status` 为 `invalid` 时按 issue 就地修正，为 `unverified` 时在回复里说明「本轮笔记未校验」。

## 历史与统计

用户要求查看某条记录的复习过程时运行：

```bash
python3 learn-from-english/scripts/learning_records.py history --id <record id>
```

用户要求查看近期进展时运行：

```bash
python3 learn-from-english/scripts/learning_records.py stats --period 30d
```

使用 `snapshot_totals`、`daily`、`by_category`、`score_distribution`、`due_backlog`、`lapse_count` 和 `mastery_count` 说明当前规模、每日趋势、类别弱点、分数分布、积压、遗忘与掌握情况。明确说明 mastered 精简归档会清除掌握前的逐次历史，因此平均分、近期事件和分类统计只覆盖当前仍保留的事件；不要把它们描述成终身完整统计。

## 数据边界

- 菜单、查询和查看历史不增加学习或复习次数。
- `learning-record-notes/` 下的笔记是可读副本，不是规范数据源：不参与 `validate`、统计、抽题和调度，删除或缺失不影响任何评分、状态与下次复习时间；也不得从笔记反向修改 `learning-records/`、`mastered-learning-records/` 或 `exam-papers/`。
- `follow-up-learning` 的菜单选择本身不增加复习次数；只有实际引入并写入的新知识点才增加对应学习记录的 `learned_count` 或创建新记录。
- 重复学习同一知识点会增加 `learned_count`；只用更丰富的新内容补全较弱字段并合并标签，不用较弱内容覆盖完整讲解。
- 每个复习题组只调用一次 `complete-review`，不能按小题重复计分；练习轮次（`starter-practice`、`follow-up-learning`、错题聚类练习）不调用 `complete-review`，得分只写笔记，见「练习计分」。
- 数据错误时运行 `validate`；只在用户明确要求修复时运行 `repair --dry-run` 并先展示结果。
