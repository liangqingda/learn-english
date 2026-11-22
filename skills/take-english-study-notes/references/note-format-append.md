> 本文件是 `skills/take-english-study-notes/references/note-format.md` 的分支参考，讲追加、追加小节、补段与改写这些写入动作的规则。只在手动追加、补写或改写笔记时读取；普通一轮的写入由 `learning_records.py review-round` 的 `note` 段完成，不需要读本文件。

## 追加与修正

统一入口是本 skill 自带的
`skills/take-english-study-notes/scripts/note.py`：写入由本 skill 的 `note_store.py` 完成（排他锁 + 原子替换），校验由同目录的
`check_note.py` 完成，不需要装其他 skill 就能写。唯一跨 skill 依赖是只读的记录事实：追踪表比对通过
`learning_records.py record-tracking --id <id>` 取回期望值（先看 `$LEARN_ENGLISH_CLI`，再看仓库内同级目录与安装位），
取不到时返回 `tracking_skipped`，不阻断写入。

1. 用 heredoc 把本轮区块通过标准输入传给命令，**不要**先写固定路径的临时文件（如 `/tmp/note-block.md`）；
   确需文件时用 `mktemp`。区块第一行必须是 `# <YYYY-MM-DD HH:MM> · <复习|练习|套题>`，一个区块只能有一个标题行。
   `· 讲解` 不是合法区块：讲解写文件级 `## 讲解` 小节（见下一条）。
2. 追加：
   ```bash
   python3 skills/take-english-study-notes/scripts/note.py append \
     --file learning-record-notes/<category>/<category>-<slug>.md \
     --content-file - --check <<'EOF'
   # <YYYY-MM-DD HH:MM> · 复习
   …本轮区块全文…
   EOF
   ```
3. 命令在 `learning-record-notes/.notes.lock` 上取排他锁，锁内完成「读现有文件 → 把本轮区块插到 `## 讲解` 之后、所有旧区块之前并补 `---` 分隔 → 原子替换」。
4. 返回值语义：
   - `appended: true, heading_adjusted: false`：正常写入。
   - `appended: true, heading_adjusted: true`：这一分钟已被另一轮占用，或直接写入会打乱最新在前的顺序，
     **本轮已用顺延后的分钟保存**，`heading` 是实际写入的标题，`requested_heading` 是原请求；
     两轮内容都保留，按 `heading` 继续后续修正。
   - `appended: false, duplicate: true`：该标题的**同样内容**已存在（重试或并发冲突的产物），按已写入处理，
     不要重试、不要手工补写。
5. 追加菜单小节：**先判断这一项属于讲解区还是日期区块**（见「何时写、写到哪」）：
   - 讲解型（讲解要点、对比、场景对话、小故事）：用**文件级小节**命令，锁内把这一节插到 `## 讲解` 之后、所有日期区块之前。
     ```bash
     python3 skills/take-english-study-notes/scripts/note.py append-explain-section \
       --file learning-record-notes/<category>/<category>-<slug>.md \
       --content-file - --check <<'EOF'
     ## <菜单项原文>
     **讲解要点**：
     - …
     EOF
     ```
     - 内容必须以 `## ` 开头、不能含一级标题；`appended_section: true` 表示已写入。
       `note.py sections --file <笔记>` 的 `explain_sections` 列出讲解区已有标题，写之前先看它就知道这一项是否已记录过。
       讲解要点要改、要补，都用同一个命令加 `--rewrite` 就地整节替换该小节（别的小节与日期区块不动），
       不要新建同名小节绕过去。这条规则对三类文件级小节一视同仁：带习题菜单项的 `**讲解要点**`、
       场景对话小节（要点 + `场景对话原文 · <标题>` 折叠块）、小故事小节（要点 + `故事原文 · <标题>` 折叠块，收尾三列表也在块内）。
       `--rewrite` 是整节替换，原有的场景对话 / 故事原文必须一并带上，漏掉已有原文的重写会被直接拒绝；
       只是再多一段原文时仍用 `append-explain-part` 追加，不做整节重写。
     - `duplicate: true`（同标题小节已存在）：说明这一项已经记录过，**不要按新内容再记录第二次**（返回里带同样的 `hint`）；
       确需修正或补充讲解要点时，改用上面那条 `--rewrite`。
     - 同一个菜单项第二次出场景对话 / 小故事时，用 `append-explain-part` 往同一小节末尾追加一段原文：
       命令会自动把第一段的 summary 改成 `<base> 1 · <标题>`，其余按顺序编号，标题逐段保留；缺标题的折叠块会被写入命令直接拒绝。
     ```bash
     python3 skills/take-english-study-notes/scripts/note.py append-explain-part \
       --file learning-record-notes/<category>/<category>-<slug>.md \
       --section "## <文件级小节标题>" --content-file - --check <<'EOF'
     <details>
     <summary>场景对话原文 2 · 九点那间会议室</summary>
     …
     </details>
     EOF
     ```
   - 带习题的菜单项：先定位目标区块——同一轮的所有习题都进文件里**最新那个日期区块**（本轮开始那天），隔天再练也不新建区块；
      `--heading` 用这个区块的真实标题，不要用今天的日期拼一个新标题。日期区块里用**追加小节**命令，锁内只把这一节插到既有区块最前（`## 本轮习题` 之后、既有菜单项小节之前），区块内小节按落盘时间倒序（新的在前），区块其余内容一字不动；
     **不要**为了加一节而整块 `replace`。小节内只写 `### <n>. <题型>` 习题，不重复 `**讲解要点**：`。
     写日期区块小节时，命令会自动在 `## 讲解` 之后补一份同名文件级骨架小节：讲解要点已写过就复用既有那一节；
     当轮没有讲解内容时，骨架小节只留标题，正文由索引重建挂上「复习历史」`practice-index`，不需要手工再写一节。
     ```bash
     python3 skills/take-english-study-notes/scripts/note.py append-section \
       --file learning-record-notes/<category>/<category>-<slug>.md \
       --heading "# <目标区块标题>" \
       --content-file - --check <<'EOF'
     ## <菜单项原文>
     ### 1. <题型>
     …
     EOF
     ```
     - 内容必须以 `## ` 开头、不能含一级标题；目标标题必须与文件里已有区块完全一致。
     - `appended_section: true`：已追加。`duplicate: true`：同一标题同一内容已经在区块里，按已写入处理，不要重试。
     - 报 `section … already exists in this block` 时说明同标题小节已存在且内容不同：改用 `replace` 修正整块，
       不要追加第二个同标题小节。
6. 本轮区块刚写错时才用替换命令（同样走 stdin，标题行必须与追加时返回的 `heading` 完全一致）；
   写入命令会自动把 `笔记更新时间` 刷成本次写入的分钟（追加、区块替换、追加小节都算），不要手工改这一行：
   ```bash
   python3 skills/take-english-study-notes/scripts/note.py replace \
     --file learning-record-notes/<category>/<category>-<slug>.md \
     --heading "# <本轮标题>" \
     --content-file - --check <<'EOF'
   # <本轮标题>
   …修正后的本轮区块全文…
   EOF
   ```
   替换是整块覆盖，但命令在锁内做了兜底：凡是新内容没有带上、而文件里已经存在的 `## ` 小节，都会被原样保留在
   替换内容之后，并在返回值 `preserved_sections` 里列出（这些是别的对话的成果，不要手工删）；保留小节的先后
   顺序随后由校验器 `--fix` 按落盘时间倒序归一化。只有用
   `--drop-section "## <小节标题>"`（可重复）显式列出的小节才允许真的删除。
   替换一次只允许改**一个**小结：新内容同时改了两个及以上既有小节时命令直接拒绝（避免范围写宽的替换吃掉整段内容），批量迁移要对每个小节逐个加 `--rewrite-section "## <小节标题>"`，返回值 `modified_sections` 列出实际被改写的小节。
   只改一个日期区块，其他日期区块原样保留；不要在标题重复或指向不明时替换。
   改小节正文时必须用锚点收边（下一个 `##` / `###` / `</details>`），并核对 `<details>` / `</details>` 成对、原有小节一个没少；写完同一轮跑 `check --all`。

7. 讲解笔记用讲解命令创建（只有 `基础信息 + ## 讲解`，没有日期区块；后续复习再 `append` 追加）：
   ```bash
   python3 skills/take-english-study-notes/scripts/note.py explain      --file learning-record-notes/<category>/<category>-<slug>.md      --content-file - --check <<'EOF'
   ## 基础信息
   …追踪表…
   ## 讲解
   **英文原文**：…
   EOF
   ```
   - 内容必须含 `## 基础信息` 与 `## 讲解`，且不得含任何一级（日期）标题，否则直接拒绝。
   - `appended: true`：创建成功。`duplicate: true`：该文件已有 `## 讲解`，按已写入处理，不要重试。
   - 文件已存在但没有 `## 讲解` 时不要改用 `append` 或 `Write` 补：加 `--update` 再跑一次，命令会把这一节插到
     `## 基础信息` 表之后、所有日期区块之前（返回 `inserted: true`），已有内容一字不动。
   - 讲解正文暂时没内容时写占位提示，但仍须满足讲解版式：至少两栏 `**<栏目>**：`，其中一栏是本分类必写栏
     （`vocabulary`/`phrases` → `核心含义`、`grammar` → `语法机制`、`usage` → `语气与语域`、`errors` → `错误机制`），
     每栏下面至少一条列表项；不要留空的 `## 讲解`，也不要写成一句散文。占位提示固定写法：
     ```markdown
     **<本分类必写栏>**：
     - 本条为历史知识点补建笔记：建笔记时还没有生成过讲解，正文留空待补。

     **待补充**：
     - 下次讲解或复习这条知识点时，按本记录的分类补写本节；补全后用 `note.py explain --update` 替换这段占位内容。
     ```
   - 每份笔记都必须有 `## 讲解`。任何写笔记的 skill 在 `append` / `append-explain-section` / `append-explain-part` / `append-section` / `append-part` / `replace` 之前先确认它存在，
     缺了就先按上一条补（没有正文就写占位），再写本轮区块。校验器允许缺讲解，所以这只能靠写入路径保证。
   - 该记录若已存在于其他笔记文件，命令拒绝另建新文件并给出应复用的路径。
8. 新建文件同样走追加命令：第一个区块**必须**在标题行之前带上 `## 基础信息` 与追踪表，命令会把它写到文件最顶部；
   写入已有文件时同一次调用里多带的 `## 基础信息` 会被自动忽略，不会重复落地。缺这一段时创建新文件会被直接拒绝。
   文件里已有 `## 讲解` 时，本轮区块插在整个文件级讲解区（`## 讲解` 与只讲解的菜单小节）之后；若文件已有日期区块，本轮与旧区块之间写一行 `---`。
9. 只修顶部 `累计复习次数` / `下次复习` 两行（记录级字段）用同步命令，不要用 `replace` 去改整个区块：
   ```bash
   python3 skills/take-english-study-notes/scripts/note.py sync --file learning-record-notes/<category>/<category>-<slug>.md [--check]
   ```
   - 值来自 `record-tracking`，只改「基础信息」表里的这两行，日期区块里的同名行一个字都不动，返回 `synced`。
   - `append` / `replace` 写完后也会自动回填这两行（`basic_info_synced`），所以日常复习不需要额外跑这一条；
     它用于修复历史笔记，或另一条记录改了复习计划后笔记顶部停在旧值的情况。
   - 记录库不可用时返回 `tracking_skipped`，不阻断操作。
10. `--check` 的结果在返回 JSON 的 `check` 字段，同时给出 `check_ok` 与 `note_status`：
   - `note_status: "valid"`：笔记合规。
   - `note_status: "invalid"`：写入已成功但笔记不合规（进程退出码 1）。按 issue 的 `line` / `message` 用替换命令就地修正，
     再重跑一次；**不要**把退出码 1 当成写入失败去重试追加。
   - `note_status: "unverified"`：校验器不可用，未执行校验；在回复里如实说明「本轮笔记未校验」，不要当作通过。

## 写入前预校验与最小改写

大块区块（多题题组，正文超过约 3000 字）不要写完就赌校验器通过：写入之后才发现 `invalid` 再整块重写，是最慢的一步，
而且整块重写容易顺手改坏没出问题的小节。

1. 先在 `mktemp` 出来的草稿上装配并预校验（`check` 接受仓库外路径，不会碰仓库里的笔记）：
   ```bash
   DRAFT=$(mktemp -t note-draft.XXXXXX)
   # 把本轮区块写进 $DRAFT
   python3 skills/take-english-study-notes/scripts/note.py check "$DRAFT"    # 约 0.1s
   ```
   仍不要用固定路径的临时文件（如 `/tmp/note-block.md`），必须走 `mktemp`。
2. 预校验要在写入前清零的装配错误：`- 1.` / `- 2.` 这类缩进编号、`**<栏目>**：` 或折叠块步骤标签只写标签不带内容、
   题与小节之间缺 `---`、`<details>` 与 `</details>` 不成对、`题量与错题数` 与实际题数 / `错题讲解` 块数不符。
3. 草稿 `ok: true` 后再把同一份内容交给 `append` / `replace` / `review-round` 的 `note` 段：`review-round` 的 `body`
   直接复用草稿正文，不要重新生成一遍。
4. 已经落盘之后才发现要改一两处时，先 `Edit` 草稿，再用 `replace --rewrite-section "## <小节标题>"` 只替换那一个小节；
   不要为了改一句措辞重新生成整块正文，也不要用 `replace` 去动第二个小节（一次一个，见上一条）。
