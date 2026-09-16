# 条目格式与字段

三类日志分别写入 `LEARNINGS.md`、`ERRORS.md`、`FEATURE_REQUESTS.md`。

## 通用字段

- ID：`LRN|ERR|FEAT-YYYYMMDD-XXXXXX`
- 优先级：`low | medium | high | critical`
- 生命周期状态：`pending | in_progress | resolved | wont_fix`
- 提升状态：`none | public | memory | public,memory`
- 领域：建议使用 `frontend | backend | infra | tests | docs | config | security`
- 元数据：来源、作用域、基础路径、项目路径、关联文件、标签

## 状态语义

- `pending`：尚未处理。
- `in_progress`：正在处理。
- `resolved`：问题或改进已落实。
- `wont_fix`：明确决定不处理，更新记录中注明原因。
生命周期与提升是正交维度：条目可同时为 `resolved` 和 `public`。

- `public`：已复制到共享公共学习区。
- `memory`：已提炼写入 Minis 记忆；只有实际写入记忆后才能使用。
- `public,memory`：两个提升动作均已完成。

旧版 `promoted_public/promoted_memory` 仅作读取兼容，新写入不得再使用。

## 高质量记录最低要求

- 摘要描述可观察事实，不只写“失败了”。
- 详情包含根因或当前最可信判断。
- 建议动作必须可执行；未知时保留待补充并在 review 中跟进。
- 不写入密码、API Key、Cookie、Token 或其他秘密。
- 摘要、详情和元数据中的控制字段会被转义；不要手工制造重复状态、提升或复发字段。
- 旧 `data/` 目录只读，修改旧条目前先执行 `migrate`。
- 已在当前任务解决的问题，记录后立即执行 `resolve <ID> "解决说明"`。

## v3.4 行为约定

- 重复 promote 合并提升标记，保留 `public,memory`；兼容旧提升状态转换时不丢原标记。
- 有效但无变化的 update 返回0；空 update、空摘要或空搜索词拒绝。
- search匹配返回0，无匹配返回1；参数语法错误返回2。结构、冲突、IO错误非零；中断不保证固定退出码。
- `--base/--project/--public` 限定按ID修改的源目录；已有同ID公共副本仍同步。手工复制ID到不同项目存在归属歧义，应避免。
- migrate仅从旧区顶层三类日志迁到选定base；同ID不同规范化内容拒绝。忽略条目末尾空白及更新/提升记录时间戳的签名差异，不作三方合并。旧自由文本、旧public目录不会自动搬迁，原文件保留。

## 路径环境变量

- `SELF_IMPROVING_BASE`：默认可变数据目录。
- `SELF_IMPROVING_PUBLIC`：公共副本目录。
- `SELF_IMPROVING_LEGACY`：只读旧日志目录。
- `SELF_IMPROVING_WORKSPACE`：项目 `.learnings` 发现根目录。

测试四者全部设置到临时目录。新日志0600、新建目录0700；已有目录权限不自动收紧。

## 一致性边界

单文件原子写不等于多文件崩溃原子性。跨文件更新以协调锁和异常回滚保护；SIGKILL、断电、外部并发编辑仍可能需人工恢复。仅按CLI锁协议协调，不保证跨文件读快照或嵌入多线程调用。手工Markdown中的裸条目标题仍可能被识别为条目，勿把任意未经转义文本直接拼入日志。
