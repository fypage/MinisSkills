# RSS 订阅源

教程基线：mgz0227《订阅源规则：从入门到再入门》，2024-02-27。教程存在字段笔误，需与目标源码核对。

## 与书源严格分离

RSS 使用 `sourceUrl/sourceName`，不是 `bookSourceUrl/bookSourceName`。不要把书源骨架或校验器直接套给 RSS。

## 三种链路

1. 标准 RSS：填写 `sourceUrl`、`sourceName`，`ruleArticles` 为空，客户端默认解析。
2. 自定义列表 + 描述：列表后解析标题、链接、描述；描述存在时通常到此结束。
3. 自定义列表、无描述：可继续使用 `ruleContent`，否则打开文章网页。

## 常见字段

`sourceUrl`、`sourceName`、`sourceIcon`、`sourceGroup`、`header`、`ruleArticles`、`ruleTitle`、`rulePubDate`、`ruleDescription`、`ruleImage`、`ruleLink`、`ruleContent`、`sortUrl`。

教程把“列表下一页规则”也写成 `ruleArticles`，这是笔误。MD3 基线 `RssSource.kt` 确认真实字段为 `ruleNextPage`；其他客户端版本仍应按对应源码核对。

## 分页

教程说明 RSS 上拉分页不提供书源式 `{{page}}`，需要规则/JS 自行推进。验证至少覆盖首次加载、一次上拉、末端停止与文章去重。

## 验证

- 标准 RSS：验证标题、链接、日期、描述。
- 自定义源：验证列表数量、标题/链接一一对应、链接唯一。
- `ruleDescription` 与 `ruleContent` 的分支按目标客户端解析顺序确认。
- RSS 成品应使用独立 RSS 校验，不以书源校验器 PASS 代替。
