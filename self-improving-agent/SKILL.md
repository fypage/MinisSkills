---
name: self-improving-agent
description: "自我改进记录与闭环：在非显然的命令/工具失败、用户纠正、知识过时、可复用更优方案、能力缺口或复发模式出现时触发；重要任务前可搜索和回顾历史经验。普通闲聊、无复用价值的小失误或用户明确要求不记录时不要触发。"
version: 3.2.0
metadata:
  language: zh-CN
  scope: minis
---

# 自我改进技能（Minis v3.2）

记录值得复用的错误、纠正和实践，并把条目推进到解决、公共提升或记忆提升，避免只积累未处理日志。

## 触发边界

应该记录：

1. 非显然的命令、权限、依赖、网络、API 或工具失败。
2. 用户纠正了事实、路径、规范、逻辑或软件实际行为。
3. 发现旧知识或既有假设已经过时。
4. 得到能显著减少返工的稳定做法。
5. 同类问题复发，或用户提出可复用的新能力。

不要记录：普通闲聊、一次性细枝末节、无复用价值的输入错误、用户明确说“不用记”，以及任何密码、Token、Cookie 或 API Key。

## 数据位置

- 默认可变数据：`/var/minis/shared/self-improving-agent/`
- 公共学习区：`/var/minis/shared/self-improving-agent/public/`
- 项目区：显式使用 `--project <path>` 后写入 `<path>/.learnings/`
- 旧版兼容区：`/var/minis/skills/self-improving-agent/data/`，只用于兼容搜索和迁移，不再作为默认写入位置。

执行入口：

```sh
sh /var/minis/skills/self-improving-agent/scripts/minis_auto_log.sh ...
```

## 核心工作流

### 1. 先搜索再记录

对疑似复发问题先搜索关键词：

```sh
sh /var/minis/skills/self-improving-agent/scripts/minis_auto_log.sh search "关键词"
```

找到同一问题时执行 `recur <ID>`，不要创建近似重复条目；不同问题可新建并在详情中引用旧 ID。

### 2. 记录

```sh
# 可复用经验或用户纠正
sh .../minis_auto_log.sh learning "摘要" "根因和正确做法" \
  --category correction --domain config --action "以后执行的预防动作" --tags "minis,path"

# 非显然失败
sh .../minis_auto_log.sh error "摘要" "实际错误" \
  --context "操作、输入和环境" --action "修复方案" --reproducible yes

# 缺失能力
sh .../minis_auto_log.sh feature "能力" "用户背景" \
  --complexity medium --frequency recurring --action "建议实现"
```

明确项目时在入口后、命令前添加 `--project /path`；自定义目录使用 `--base /path`；直接写公共区使用 `--public`。

### 3. 当前任务已解决就闭环

记录后若已经修复，立即执行：

```sh
sh .../minis_auto_log.sh resolve <ID> "具体解决办法与验证结果"
```

处理中或不处理：

```sh
sh .../minis_auto_log.sh update <ID> --status in_progress --note "当前进展"
sh .../minis_auto_log.sh update <ID> --status wont_fix --note "不处理原因"
```

### 4. 复发与公共提升

```sh
sh .../minis_auto_log.sh recur <ID>
sh .../minis_auto_log.sh promote <ID>
```

`promote` 复制到共享公共区，并把源条目与副本的独立 `提升` 字段标为 `public`；不会覆盖 `pending/resolved` 生命周期状态，重复执行不会重复追加。

### 5. 定期回顾

在重要任务前、功能完成后或进入有历史问题的领域时：

```sh
sh .../minis_auto_log.sh review
sh .../minis_auto_log.sh review --verbose
```

优先处理：高优先级 pending、信息不完整条目、重复出现条目，以及已解决但尚未闭环的记录。

## 提升到 Minis 记忆

技能日志用于保留上下文和排错过程；Minis 记忆只保存短、稳定、跨任务可复用的规则。

满足任一条件才考虑写入 `memory_write`：

- 可浓缩为一句“以后遇到 X 就做 Y”的规则；
- 30 天内复发至少 3 次且横跨至少 2 个任务；
- 用户明确要求长期记住某项偏好或约定。

实际调用 `memory_write` 成功后，再执行：

```sh
sh .../minis_auto_log.sh update <ID> --promotion memory --note "已提炼到 YYYY-MM-DD 日记忆"
```

只有用户明确要求写入全局记忆时，才可编辑 `GLOBAL.md`。

## 维护命令

```sh
# 初始化与状态
sh .../minis_auto_log.sh init
sh .../minis_auto_log.sh status

# 一次性迁移旧日志；按 ID 去重，旧文件不删除
sh .../minis_auto_log.sh migrate
```

完整字段和状态定义按需读取 `references/FORMAT.md`。
