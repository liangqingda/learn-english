> 本文件是 `practice-learning-records/SKILL.md` 的分支参考。写入失败后的重试 / 放弃处理。只在某个写操作失败时读取。 文中的「小节名」都指 `practice-learning-records/SKILL.md` 里的同名小节。

## 失败恢复矩阵

所有写操作的失败处理都落到同一套动作，不再按命令分别发明流程：

| 场景 | 立即动作 | 聊天输出 | payload | 回滚不完整时 |
|---|---|---|---|---|
| `batch-upsert` 保存知识点失败 | 继续发送教学正文 | 只显示「重试保存本轮记录」「放弃保存并继续」 | 只留在当前对话 | 说明可能残留部分记录变更并停止后续写入，不得说“已回滚” |
| `complete-review` 保存评分失败 | 继续发送批改正文 | 只显示「重试保存本轮评分」「放弃保存并返回菜单」 | 只留在当前对话，重试原样携带 `claim_owner` / `claim_token` | 同上；领取凭据失效的提示语见“评分与协调记录” |
| `paper-complete` 保存套题评分失败 | 继续发送批改正文 | 只显示「重试保存本次试卷评分」「放弃评分保存并保留进行中作答」 | 只留在当前对话 | 同上；放弃时不得删除已保存答案 |
| `append` / `append-explain-section` / `append-explain-part` / `append-section` / `append-part` / `replace` 写入失败（路径不合规、区块缺标题、文件被占用、目标小节不存在等） | 继续发送当天正文；命令报错原样说明原因 | 只输出得分行、判定表格与后续菜单 | 修正后的区块只留在当前对话 | 不得改用 `Write` 直接改写笔记文件来绕过失败；`append-section` 对同标题小节不再报错：它会把这一份按当天序号编号成 `## <选项原文> - 01` / ` - 02` 各建一节，所以同一菜单项再选一次照常 `append-section`，不要改用 `append-part` 把第二轮并进既有小节；`append-section` 返回 `duplicate: true` 说明这份内容已经在区块里，不要重写一遍；确属同一个小节要多补几道题时才用 `append-part`；故事 / 对话原文再生成一份要走 `append-explain-part`；`append-part` 报小节不存在时改用 `append-section` 新建；`append-explain-section` 返回 `duplicate: true` 说明这一项已记录过，不要按新内容重复记录、也不改名绕过；确需修正或补充讲解要点时用同一命令加 `--rewrite` 整节重写，并把已有的 `场景对话原文` / `故事原文` 一起带上；`append-explain-part` 报小节不存在时改用 `append-explain-section` 新建 |
| `replace` 报「一次只改一个小节」 | 说明这次替换同时重写了多个既有小节 | 只输出得分行、判定表格与后续菜单 | 修正后的区块只留在当前对话 | 一次只改一节；批量迁移逐节加 `--rewrite-section`，并同轮跑 `check --all` |
| `replace` 返回非空 `preserved_sections` | 写入成功，这些小节是别的对话的成果，已被自动保留在区块末尾 | 只输出得分行、判定表格与后续菜单 | 不涉及 | 不要手工删掉它们；确实要删时用 `--drop-section` 明确列出 |
| `append` 返回 `duplicate: true`（同标题同内容） | 按已写入处理，不再追加 | 只输出得分行、判定表格与后续菜单 | 不涉及 | 不重试、不手工补写；内容有实质修改才用替换命令 |
| `append` 返回 `heading_adjusted: true` | 按返回的 `heading` 继续，两轮内容都已保留 | 只输出得分行、判定表格与后续菜单 | 不涉及 | 不要用原请求时间再追加一遍 |
| `note_status: invalid`（校验失败，退出码 1） | 写入已成功，用替换命令修正本轮区块后重跑 | 只输出得分行、判定表格与后续菜单 | 不涉及 | 不得把退出码 1 当成写入失败去重试；第二次仍失败时正文如实说明并留待下一轮修正 |
| `note_status: unverified`（校验器不可用） | 正常发送正文 | 只输出得分行、判定表格与后续菜单 | 不涉及 | 正文如实说明「本轮笔记未校验」，不得当作已通过 |
| 返回 `tracking_mismatch`（追踪表与记录不符） | 先看 `basic_info_synced`：顶部 `累计复习次数` / `下次复习` 已自动回填；剩下的身份行或本轮字段按 `tracking_expected` 改完本轮区块，用 `replace` 重写并复检。历史笔记顶部是旧值时用 `note.py sync --file <笔记文件>` 修复 | 只输出得分行、判定表格与后续菜单 | 不涉及 | 不要改记录数据去迁就手抄值；`题量与错题数` 不在比对范围内 |
| `note.py` 找不到 `learning_records.py`（只装了复习 skill） | 说明缺少写入命令的位置，先跑 `note.py check --all` 确认校验可用 | 只输出得分行、判定表格与后续菜单 | 不涉及 | 不得改用 `Write` 直接落盘；按报错里的 `probed` 路径提示安装 learn-from-english 或设置 `LEARN_ENGLISH_CLI` |
| `complete-review` / `review-round` 返回 `deleted: true`（记录已自动删除，笔记 md 保留） | 不再重试评分：记录已经不在库里。得分与判定照常输出，另加一句说明它已退出复习库、笔记保留 | 得分行、判定表格、一句说明与后续菜单 | 不涉及 | 不得重建记录，也不得删掉那篇笔记；之后按笔记路径练习的走法见 `note-path-entry.md` |
| `menu` / `next-review` / 查询类命令失败 | 说明命令失败原因，按上下文退回初始菜单或直接回答 | 初始菜单 | 不涉及 | 不适用 |

跨文件写入由脚本的事务日志兜底：写入前把目标文件的原始内容备份到 `learning-records/.txn/` 并记录 `.txn-journal.json`；中途失败会立即回滚，进程被杀时下一次任意写操作或 `validate` 会先恢复再继续。看到 `.txn-recovery.log` 记录时，如实说明“上次未完成的写入已自动回滚”，不要描述成“已回滚本轮”。
