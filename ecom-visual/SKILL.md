---
name: ecom-visual
description: 电商与营销视觉创作方法论：产品主图、详情页/PDP 图片包、场景图、社媒图、广告 Banner、直播间的视觉策略与提示词工程。含 5 张主图 + 7-9 张详情页图片包编排、Campaign Style Lock 风格锁定、多角度分配、信息图结构、Anti-AI 真实感技巧、出图后质检。当用户要写生图提示词、做电商整套图、诊断转化视觉、或直接出图时使用。
---

# 电商视觉创作

两种模式：

1. **Brief 模式**：只出视觉简报 + 最终提示词 + 负面约束 + 假设。用户只要方向、只要文案时用。
2. **Generate 模式**：用户说「生图 / 出图 / 渲染 / render」时，先出提示词，再按本机通道出图，最后报文件路径。

不内置任何 API。生图走当前环境已有的模型通道（见「生图通道」），不引入第三方 CLI，不接触密钥。

---

## 核心流程

1. 判断任务类型（见 `references/trigger-map.md` 的触发词表）。
2. 只问会实质改变画面结果的缺失项；其余按默认值假设并写明。
3. 若为商品/营销图，先做**转化驱动力诊断**（视觉 / 痛点 / 情感）。
4. 若用户给了参考图要复刻风格，先反推：见 `references/style-reverse.md`（内容骨架/画风指纹解耦 + 量化 + 转 Style Lock）。参考图只为「卖得好」而非画风好看时，只学信息结构，不学画风。
5. 若一组图 >1 张，先立 **Campaign Style Lock**。
6. 逐张写提示词（遵守下方铁律），每张单独成文，绝不一次提示词拼多屏。
7. 出图（Generate 模式），输出文件路径。
8. 按「出图后质检」逐项核对，把不合格项连提示词一起重写，不要凭手感逐张补描述。

---

## 铁律（每条提示词逐一核对）

### 1. 颜色写 hex，不写形容词
「白底」出来是淡灰，「金色」有八种金。常用：

| 用途 | hex |
|---|---|
| 纯白底 | `#FFFFFF` |
| 浅米/暖白 | `#F5F1E8`、`#FAF7F2` |
| 深灰正文 | `#2D2D2D` |
| 浅灰标注 | `#888888` |
| 金色强调 | `#D4AF37` |
| 深绿品牌底 | `#1A3A2E` |

### 2. 产品占比数字化

| 图型 | 产品占比 |
|---|---|
| 白底主图 | 35–40% |
| 卖点副图 | 25–30%（左图右文，产品在左） |
| 场景氛围图 | 20–25% |
| 信息流广告 | 40% |
| 搜索广告 | 45% |
| SKU 多规格横排 | 60–70%（整体） |
| 特写/微距 | 55–60% |

### 3. 留白必须显式声明
不写，模型一定填满。
- 白底主图 / 卖点副图 / 广告图：留白 ≥45%
- 场景氛围图：≥50%
- 详情页长图：≥50%

### 4. 否定清单不能省，要具体
结尾必带，写具体禁止项：

```
不要添加：道具、手、水印、假 logo、额外文字、装饰元素、渐变背景、投影叠加
```

### 5. 平台预留区写像素坐标
国内电商主图必写：
- 顶部中央 200×100 区域留空（平台价格叠加区）
- 左上角 200×100 像素区域完全留白（logo 区，如需要）

写「留点空间」等于没写。

### 6. 图内文字三层架构
- 主标题 ≤15 字（核心承诺）
- 关键证据 2–3 个（图标 + 短标签）
- CTA ≤8 字

单屏文字总量（标题+副标题+标注）不超过 50 字。字号：标题 28–48pt，副标题 16–20pt，标注 10–14pt。

### 7. 批量出图 > 反复调参
一次出 3 个变体让数据选，不要凭审美一张张磨。

---

## 提示词写法

默认英文，用户要求中文才换中文。结构：

1. Campaign Style Lock（多图必填，原文逐字复用）
2. 主体与场景
3. 目的与情绪意图
4. 构图、镜头、取景（含角度关键词）
5. 光线、颜色、材质纹理
6. 风格与真实感等级
7. 画幅比例与平台限制
8. 图内文字处理
9. 负面约束

**精简原则**：自然语言优于关键词堆砌；只放核心信息；材质写具体（磨砂玻璃、拉丝金属、哑光饰面、丝绸光泽）；场景图指定色温（如 5500K）；一个提示词不塞多个场景与情绪。

**中文渲染**：中文字用「」包裹（渲染准确率明显高于英文引号或无引号）；复杂笔画字（赢、鬱、餮）换简单同义字，95% 准确率不是 100%。

---

## 转化驱动力诊断

先选一个主驱动力，再决定序列：

**A 视觉驱动**（外观、质感、风格匹配、礼品属性）：一眼抓住产品 → 质感特写 → 场景匹配 → 普通 vs 升级对比 → 优惠/保障。

**B 痛点驱动**（摩擦、风险、时间损失、反复烦恼）：痛点快照 → 解决机制 → 利益证明 → 信任画面 → 优惠 + CTA。顺序不可打乱。

**C 情感价值驱动**（身份、信心、归属、地位、关怀、新奇）：情绪钩子 → 身份表达 → 产品作为实现方式 → 社交信号 → 情绪强化优惠。

---

## 图片包编排

用户提到详情页 / PDP / A+ / 主图堆栈 / 整套商品图时，默认输出 **5 张主图（1:1）+ 7–9 张详情页（2:3）**，共 12–14 张，每张独立提示词文件。

### 主图 5 张
1. 首图卖点（一眼可懂的视觉主张）
2. 机制/功能
3. 利益证明
4. 对比或场景
5. 优惠/物流/保障 + CTA

### 详情页 7–9 张
1. 首屏承接：为谁解决什么问题
2. 痛点放大：当前的不便、损失、反复烦恼
3. 机制解释：结构可视化，不虚构数据
4. 核心利益：2–4 个利益做易扫读信息图
5. 使用步骤：3–4 步
6. 场景覆盖：适用对象 / 使用前后
7. 对比选择：普通方案 vs 本产品
8. 信任背书：材料、质检、包装、保障、真实评价；无证据就写 `proof placeholder`，不编造认证
9. FAQ / 风险逆转 / CTA

---

## Campaign Style Lock（多图专用）

整套图的视觉合同，不是灵感描述。10 项必填：

1. 视觉方向（如 premium tech ecommerce）
2. 固定色板：2–3 主色 + 1 强调色，写明背景/文字/强调 hex
3. 冷暖调：warm / cool / neutral，全套一致
4. 字体系统：一种字体风格，禁混衬线+手写+复古+卡通
5. 背景系统：统一材质、空间、深浅
6. 光线系统：光源方向、阴影强度、反光质感
7. 布局系统：留白、圆角、分栏、标签、编号
8. 图标系统：线宽、形状、颜色、复杂度
9. 产品呈现规则：角度、比例、材质、是否居中
10. 禁止漂移项

**默认锁（用户无品牌规范时用）**：

```
Campaign Style Lock: consistent premium ecommerce visual system across the entire image set; fixed palette of clean off-white background (#F5F1E8), deep charcoal text (#2D2D2D), one product-matched accent color, and one soft secondary accent; neutral-cool studio lighting at 5500K; modern geometric sans-serif headline placeholders only; consistent rounded rectangular info labels; consistent thin-line icon style; clean high-end product photography mixed with minimal infographic elements; stable product scale and placement; generous whitespace; no color palette changes, no mixed fonts, no random backgrounds, no inconsistent lighting, no mismatched icon styles.
```

**强制规则**：
- 每张提示词第一段原文照抄，不改写、不缩写、不换同义词。
- 单张只能改：画面目的、主体动作、局部构图、短文案。
- 单张不能改：色板、冷暖、字体、背景、光线、图标、标签样式。
- 重生成某一张，必须复用原锁。
- 出图风格已漂移时，重写整个提示词包，不要逐张补。

---

## 详情页 = 信息图，不是多角度产品照

**错误**：`Side profile view of the product on white background. Product occupies 38%.` —— 只是换个角度，没有转化元素。

**正确**：

```
E-commerce infographic benefits screen on #FAF7F2 background.
Top headline in #2D2D2D at 28pt reading 「核心利益」.
Left side: the product shown from an elevated overhead angle.
Right side: four benefit rows stacked vertically with thin-line icons:
  (1) icon + 「卖点一」 in #7A9E7E
  (2) icon + 「卖点二」 in #8B6F47
  ...
Clean two-column layout. Product occupies 35%. Whitespace 48%+.
```

每张详情页提示词以 `E-commerce infographic [screen type]` 开头，必须含：
1. 布局关键词（`two-column layout` / `structured grid` / `timeline` / `comparison layout`）
2. 标题与文案（含 hex 与 pt）
3. 信息图元素（`feature callout icons`、`thin connecting lines`、`numbered circles`、`trust badges`、`CTA button placeholder`）
4. 产品角度（为信息图内容服务）

---

## 多角度与景别分配

AI 默认爱出正面 3/4，不显式指定就整套雷同。每张都要写角度关键词。

**角度**：正面 3/4（`slight 3/4 angle showing full front`）、正上俯视（`90-degree overhead angle`）、侧面 90°（`clean 90-degree side profile`）、后侧 45°（`45-degree rear angle`）、仰视低角度（`very low angle looking upward`）、高角度俯视（`high 45-degree angle looking down`）。

**景别**：全景（35–40%）、中景（45–50%）、特写（55–60%，`tight zoom on ...`）、微距（`extreme close-up macro, shallow depth of field`）、局部。

**规则**：
- 主图 5 张：≥3 种角度，其中 1 张特写或微距
- 详情页 7–9 张：≥4 种角度，其中 2 张特写/微距
- 不得连续 3 张同角度
- 全景 ≤ 整套 40%
- 仰视、俯视各 ≥1 张

**视觉节奏**：相邻多张背景色不要完全相同，交替 2–3 种（`#FFFFFF` 主图 / `#F5F1E8` 成分质地 / 品牌深色促销）。

**字体搭配**：主标题衬线（Didot 类），副标题正文无衬线（SF Pro Display 类）；整套只用 2 种字体。

---

## Anti-AI 真实感（UGC / 直播 / 社媒专用）

- 指定具体机型：`iPhone 14 Pro` / `iPhone 15 Pro`
- 加可见瑕疵：毛孔、轻微噪点、暖色偏移、构图不完美
- 真实环境：略凌乱、真实物品、水渍、用过的毛巾
- 胶片色感：`Kodak Portra 400 color feel`
- 显式否定：`NOT professional photography`、`NOT AI-generated look`、`NOT retouched, NOT smoothed`
- 禁用词：不用 `perfect`、`flawless`、`stunning`、`hyper-realistic`——这些词反而把图推向塑料感

---

## 生图通道

优先用当前环境已有的图片模型通道。调用方式见 `references/render.md`。

> ★ 2026-10-27 实测：`gpt-image-2.5-flare`（orbitix）返回 `Invalid API key`，两次探测均失败；可用通道为 `gpt-image-2`（噜皮生图）。批量脚本默认已改为该模型，orbitix 修好后再切回。

- 单张：提示词走 `--prompt`；长提示词写文件后传文件。
- 多张：每张一个提示词文件，命名 `01-hero.txt`、`02-pain.txt`…，输出到 `generated-images/<产品slug>/`。
- 有产品实拍图时，用参考图/编辑模式传入原图，比文字描述一致性高一个量级。
- 批量前先报「Image Pack Plan」：张数、比例、预计耗时与费用，经确认再跑。
- 通道不可用时不要阻塞：完整交出提示词包 + 出图指引。

---

## 出图后质检

**逐张看**：
- 产品占比是否落在目标区间（拿不准就目测面积）
- 留白是否真的 ≥45%
- 背景是否真纯白（不是淡灰）
- 平台预留区（顶部 200×100）是否被占
- 角度是否按分配执行，有无连续 3 张雷同
- 中文标题**放大 200% 逐字核对笔画**，错字复杂字换简单同义字
- logo 区、水印、多余道具是否被擅自添加

**整包看**：
- 同屏并排，色板/冷暖/字体/光线/图标是否漂移
- 全景占比是否 ≤40%
- 信息图屏是否真有标题+图标+标签，而不是普通产品照

不合格 → 改提示词重出，不靠后期修。

---

## 红线

- 不虚构认证、实验数据、评分、销量、真实评价、品牌授权。没有证据只写占位表达。
- 医疗/功效承诺必须有据；化妆品不得写「治疗」类表述。
- 名人肖像、他人品牌 logo、有版权的角色形象，不生成。
- 不提交、不硬编码、不回显任何 API key。

---

## 翻车速查

| 翻车 | 原因 | 防护 |
|---|---|---|
| 中文字笔画错 | 中文准确率约 95% | 200% 放大核对；复杂字换同义字 |
| 品牌色漂移 | 写「金色」有八种金 | 全部 hex |
| logo 区被填满 | 只说「留空间」 | 写像素坐标 200×100 |
| 背景不是纯白 | 只说「白底」 | 写 `#FFFFFF` |
| 产品太大或太小 | 没写占比 | 写具体百分比 |
| 画面塞满 | 没写留白 | 写 ≥45%/50% |
| 连续多张疲劳 | 背景色全一样 | 交替 2–3 种背景 |
| 角度雷同 | 不指定就是正面 3/4 | 每张显式写角度；主图 ≥3 种，详情 ≥4 种 |
| 详情页变成纯产品图 | 只有角度没有信息图结构 | 以 `E-commerce infographic` 开头 |
| 衣服/3C 不稳 | 面料垂坠、人体比例、接口细节要求高 | 先测护肤/家居/食品；服装必带参考图 |
| 图看着假 | 用了 perfect/flawless 一类词 | 换 Anti-AI 写法，加瑕疵与机型 |

---

## 输出格式

**Brief 模式**：匹配场景 → 视觉简报 → 最终提示词 → 负面约束 → 假设。
商品/营销任务追加：转化驱动力诊断 → Campaign Style Lock（多图）→ 主图序列 → 详情页序列 → 图内文案 → 测试优先级。

**Generate 模式**：Image Pack Plan（编号/用途/比例/短文案）→ Campaign Style Lock → 各张提示词 → 生成文件路径 → 假设与备注。

---

> 方法论参照 liangdabiao/ecom-details-image（Apache-2.0）重写整理，去除了第三方 CLI 依赖与冗余模板层，并修正了原版「铁律与模板脱节」的问题。
