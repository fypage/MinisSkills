# ecom-visual · 电商视觉创作（去依赖精简版）

从 [liangdabiao/ecom-details-image](https://github.com/liangdabiao/ecom-details-image) 重写整理。
原版 1493★，方法论扎实，但有三处不适配本机：**硬绑第三方 CLI（apiz.ai）**、25 个模板**缺 hex/占比/留白**（机械填空反而违反它自己的铁律）、生图脚本**只支持单图**。

本版只留方法论，生图接到本机已有的 `image-generator` 通道。

## 目录

```
ecom-visual/
├── SKILL.md                    方法论主体（铁律 / Style Lock / 多角度 / 信息图 / 质检）
├── plan.example.json           12 张整套图清单样例（5 主图 + 7 详情）
├── references/
│   ├── render.md               生图通道适配（噜皮 / 异步 / orbitix / grok / 兜底）
│   ├── style-reverse.md        参考图反推：内容骨架/画风指纹解耦 → Style Lock
│   └── trigger-map.md          25 个场景触发词表 + 常用组合
└── scripts/
    ├── batch_render.py         按清单串行出图，逐张验证落盘
    └── analyze_ref.py          参考图粗测：主色 hex / 明暗分布 / 主体占比
```

## 与原版的差异

| 项 | 原版 | 本版 |
|---|---|---|
| 生图依赖 | apiz CLI（第三方聚合站，已换过两次后端） | 本机 `image-generator`，凭据留 App 配置 |
| 模板 | 25 个 json 当填空模板 | 压成触发词表，只做场景识别与该写字段提示 |
| 铁律落地 | 写在 SKILL.md，模板里 0 处 hex、0 处留白 | 铁律与骨架合并，模板是「维度清单」不是填空 |
| 批量 | 单图脚本，12 张靠 agent 自己循环 | `batch_render.py`：清单驱动、串行、验证、跳过已存在 |
| 参考图复刻 | 无 | `style-reverse.md`：内容骨架/画风指纹解耦 → 十项 Style Lock，配 `analyze_ref.py` 量化 |
| 比例参数 | `--aspect-ratio 1:1` | OpenAI 系只吃像素，`1:1→1024x1024` 等已内置映射 |
| 交付 | 输出文件路径 | 沿用 image-generator 六行生图信息 |
| 许可 | 无 LICENSE 文件 | 见下 |

## 用法

**写提示词**：读 `SKILL.md` → 命中场景查 `references/trigger-map.md` → 按铁律逐张写。

**出图**：

```sh
# 1. 建目录与提示词文件
mkdir -p generated-images/<slug>/prompts
# 2. 复制并改 plan.example.json
cp plan.example.json generated-images/<slug>/plan.json
# 3. 先干跑核对
python3 scripts/batch_render.py --plan generated-images/<slug>/plan.json \
    --out /var/minis/attachments/ecom/<slug> --dry-run
# 4. 分批实跑（12 张整包约 8-20 分钟，超单次调用时限，务必分批）
python3 scripts/batch_render.py --plan generated-images/<slug>/plan.json \
    --out /var/minis/attachments/ecom/<slug> --only 01,02,03
```

`plan.json` 字段：`id` / `use` / `ratio`（或 `size` 像素）/ `file` / `prompt` 或 `prompt_file` / `reference_image`（可选，顶层也可设默认）。

## 已验证与未验证

**已测（2026-10-27，桩环境）**：
- 脚本编译通过；比例映射、`--only`、`--dry-run`、已存在跳过、非法比例报错、提示词缺失报错；
- 伪图（非图片字节）被 Pillow 解码门禁拒绝，不交付；
- 失败汇总退出码 1。

**2026-10-27 真实出图实测**：
- `gpt-image-2.5-flare`（orbitix）**不可用**：返回 `Invalid API key`，两次探测（含最简提示词）均失败，与提示词无关；
- `gpt-image-2`（噜皮生图）**可用**：62 秒出图，请求 `1024x1024` 实出 `1254×1254`（复现既有记录），1.1 MB PNG；
- 探路图主体占比实测 65.8%（`analyze_ref.py`），高于白底主图 35–40% 的目标区间，说明模型有放大主体的倾向，提示词需在占比上收紧；
- 批量脚本默认模型已改为 `gpt-image-2` / `噜皮生图`。

**仍未验证**：
- 12 张整包的分批节奏与总耗时；
- 图生图（`--image` 参考产品图）通道；
- `style-reverse.md` 的闭环在真实竞品图上的效果。

## 许可

方法论文本参照原项目（Apache-2.0）重写，署名保留在 `SKILL.md` 末。本目录同样以 Apache-2.0 对待使用。
