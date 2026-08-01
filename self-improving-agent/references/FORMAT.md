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
- 已在当前任务解决的问题，记录后立即执行 `resolve <ID> "解决说明"`。
