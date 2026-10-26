# 场景触发词表

> 本表只做「场景识别 + 该写哪些字段」的索引，**不是填空模板**。
> 原版 25 个 json 模板缺 hex、缺占比、缺留白，机械填空会直接违反铁律；
> 用法：命中场景 → 取「该写字段」作为提示词的骨架维度 → 按 SKILL.md 铁律自行补齐约束。

| # | 场景 | 触发词 | 风格变体 | 该写字段 | 参考图 | Anti-AI |
|---|---|---|---|---|---|---|
| 01 | 白底/纯色底产品主图 | 产品主图、白底图、白背景产品、hero image、电商主图、纯色背景 | luxury/fresh/tech/color | background, lighting, composition, quality | ✓ | — |
| 02 | 场景化生活图 | 场景图、生活图、使用场景图、lifestyle photo、产品场景、生活化展示 | morning/cozy/outdoor/luxury | setting, lighting, composition, mood, quality | ✓ | — |
| 03 | 平铺图 | 平铺图、flat lay、俯拍、top-down view、产品平铺 | luxury/minimal/seasonal | props, background, color_palette, lighting, quality | ✓ | — |
| 04 | 细节微距图 | 细节图、微距图、产品特写、材质特写、detail shot、macro photography | texture/formula/craftsmanship | detail, lighting, camera, quality | ✓ | ✓ |
| 05 | 促销海报/Banner | 促销海报、banner、广告图、活动海报、促销图、campaign poster | luxury/minimal/festive/flash-sale | background, headline, subtitle, price, cta, style | ✓ | — |
| 06 | 社交媒体素材 | 社交媒体图、小红书图、Instagram、TikTok、种草图、社媒素材 | xiaohongshu/instagram/tiktok | platform, composition, lighting, overlay, quality | ✓ | ✓ |
| 07 | UGC风格/买家秀 | UGC图、买家秀、用户图、真实买家、GRWM、user-generated | mirror-selfie/ccd-retro/grwm/unboxing | style, environment, lighting, imperfection, quality | ✓ | ✓ |
| 08 | 模特展示图 | 模特图、真人展示、人物图、model photo、模特展示、人物展示图 | beauty-closeup/fashion-full/candid | camera, lighting, skin_detail, expression, quality | ✓ | ✓ |
| 09 | 使用前后对比图 | 对比图、前后对比、before after、效果展示、使用效果、transformation | clinical/cinematic/simple | before_state, after_state, metrics, divider, quality | ✓ | — |
| 10 | 包装设计展示 | 包装设计、包装展示、礼盒图、packaging design、开箱图、gift box | luxury-gift/minimal-eco/unboxing | display, surface, decorative, lighting, quality | ✓ | — |
| 11 | 信息图/A+Content | 信息图、产品信息图、详情页图、A+Content、卖点图、infographic | amazon-a-plus/feature-grid/story-flow | features, layout, data_vis, color_scheme, quality | ✓ | — |
| 12 | 创意概念广告图 | 创意广告、概念图、品牌广告、创意素材、品牌宣传、creative concept | splash-dynamic/surreal/minimal-art | concept, effects, color_palette, art_direction, quality | ✓ | — |
| 13 | 尺寸规格+使用步骤图 | 尺寸图、规格图、使用步骤图、尺寸标注、how to use、使用指南 | premium-editorial/technical/ritual-guide | dimensions, steps, extras, style, quality | ✓ | — |
| 14 | 多产品套装/组合展示 | 套装图、多产品展示、产品组合、bundle image、礼盒展示、系列图 | gift-set/routine-set/lineup | arrangement, background, decorative, quality | ✓ | — |
| 15 | 电商直播间场景 | 直播图、直播间截图、电商直播、livestream、抖音直播、带货图 | douyin/taobao/setup | host, product_action, background, ui_overlay, lighting, quality | ✓ | ✓ |
| 16 | 虚拟试穿/产品融入场景 | 虚拟试穿、产品融入场景、try on、场景融合、产品植入、场景化融入 | interior-luxury/outdoor-natural/studio-editorial | setting, atmosphere, integration, quality | ✓ | — |
| 17 | 技术拆解/爆炸图 | 产品拆解、爆炸图、内部结构、技术拆解、exploded view、产品组件 | blueprint/minimal/apple-style/editorial | components, arrangement, background, labels, quality | ✓ | — |
| 18 | 隐形模特 | 隐形模特、ghost mannequin、3D服装展示、无人穿着展示、服装立体展示、invisible mannequin | white-clean/editorial/editorial-detail/lifestyle | form, details, background, lighting, quality | ✓ | — |
| 19 | 产品多角度网格 | 多角度展示、产品网格、多面展示、颜色对比、multi-angle、grid layout | angle-view/colorway/feature-grid/comparison | grid, variation, background, separators, quality | ✓ | — |
| 20 | 杂志大片/封面 | 杂志封面、杂志大片、时尚大片、editorial、magazine cover、品牌大片 | beauty-cover/fashion-cover/fragrance-editorial/minimal-editorial | model, makeup_hair, background, lighting, layout, quality | ✓ | ✓ |
| 21 | 季节主题网格 | 季节主题、四季展示、seasonal campaign、年度campaign、春夏秋冬、季节变体 | four-seasons/holiday-series/day-to-night/travel-series | layout, spring, summer, autumn, winter, quality | ✓ | — |
| 22 | 奢华氛围渲染 | 奢华氛围、高端渲染、梦幻效果、luxury campaign、氛围渲染、高端广告 | floral-dream/smoke-mystique/golden-luxe/ice-crystal | surface, atmosphere, lighting, background, quality | ✓ | — |
| 23 | 设备界面模型 | 设备模型、界面展示、mockup、APP展示、网站展示、SaaS展示 | single-laptop/multi-device/phone-only/office-lifestyle | device, screen_content, desk_accessories, lighting, quality | ✓ | — |
| 24 | 店铺门面/空间摄影 | 店铺门面、店面摄影、空间摄影、零售空间、咖啡店外观、实体店 | exterior/interior/corner-detail/aerial-plan | exterior, interior, lighting, quality | ✓ | — |
| 25 | 运动/健身广告 | 运动广告、健身广告、sports campaign、运动品牌、运动大片、健身推广 | product-hero/athlete-action/triptych/gym-power | athlete, props, background, typography, quality | ✓ | — |

无匹配 → 默认按 01 白底主图处理。

## 常用组合

| 任务 | 建议场景序列 |
|---|---|
| 亚马逊 / 淘宝主图堆栈 | 01 主图 → 04 微距细节 → 02 场景 → 13 尺寸/步骤 → 09 对比 |
| Shopify PDP 图片包 | 01 → 11 信息图 ×4~6 → 04 微距 → 13 → 10 包装 |
| 小红书种草 | 07 UGC ×2 → 03 平铺 → 06 社媒 → 09 前后对比 |
| TikTok / 短视频封面 | 06 社媒（9:16）→ 15 直播 → 25 运动 |
| 服装 | 18 隐形模特 → 08 模特 → 16 试穿 → 19 多角度网格 → 03 平铺 |
| 直播间 | 15 直播 → 22 奢华氛围 → 05 海报 |
| 官网 / SaaS | 23 设备样机 → 12 创意概念 → 20 杂志感 |
