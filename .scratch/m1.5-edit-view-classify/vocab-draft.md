# 场景、任务词表初稿（待负责人过目）

Status: draft（执行线 2026-10-30 根据现有 35 个数据集第 6 项"任务与场景"起草）

用途：给算法研究员快速定位"某个场景下、某类任务"的数据。数据集信息里的"场景"单选，"任务"多选；词表放在平台配置里，以后可以增删。

## 场景（单选）

| 编码 | 名称 | 典型例子 |
|---|---|---|
| kitchen | 家居-厨房 | 洗锅、做虾、开冰箱、搅拌机、咖啡杯（aloha 系列、robocasa_target、utokyo_pr2_fridge） |
| home_living | 家居-起居 | 椅子、橱柜、毛巾、衣物、厕纸、玩具（galaxea、aloha_mobile_chair/cabinet） |
| tabletop | 桌面 | 桌面抓放、餐具摆放、方块（libero 系列、jaco_play、droid_100、tidybot、cobotmagic） |
| office | 办公室 | 文件、物品整理（EgoProStandard 部分） |
| retail | 商超零售 | 超市取物、扫码入库（agibot_world_alpha、EgoProDemo 部分） |
| logistics | 物流仓储 | 分拣区、货架（EgoProStandard 部分） |
| industrial | 工业 | 产线、设备（agibot_world_2026 Industry 子集） |
| public_space | 公共与商业空间 | 电梯、电影院、民宿（aloha_mobile_elevator、agibot_world_2026 CommercialSpaces） |
| mixed | 多场景混合 | 一个数据集覆盖多种场景（agibot_world_2026、EgoProStandard、galaxea_open_world） |
| unknown | 未知 | — |

## 任务（多选）

| 编码 | 名称 | 典型例子 |
|---|---|---|
| pick_place | 抓取放置 | 抓物放进碗、上架、转移物品 |
| articulated | 开合操作 | 开门、抽屉、柜门、冰箱、锅盖、洗碗机 |
| fold | 折叠 | 折 T 恤、折卫衣、折布、晾毛巾 |
| wipe_clean | 擦拭清洁 | 擦酒渍、擦桌面、清洁污渍、洗碗、洗锅 |
| tidy | 收纳整理 | 收撤餐桌、餐具摆放、衣物入篮、整理玩具、冷柜整理 |
| cook | 烹饪 | 煎虾、蒸饭、烧水、舀爆米花 |
| mobile_nav | 移动与导航 | 乘电梯、推椅子、移动拾取垃圾 |
| tool_use | 工具使用 | 钥匙开门、工具操作 |
| bimanual | 双臂协作 | 双手洗碗、双臂操作（robotwin、umi） |
| human_demo | 人体演示 | 人体第一视角、全身动作（EgoPro 系列） |
| long_horizon | 长程多步 | 多步骤组合任务 |
| unknown | 未知 | — |

## 说明

- 平台按编码存，页面显示中文名称。
- 一个数据集只有一个场景；任务可以多选，例如 aloha_mobile_wash_pan = 厨房 + 擦拭清洁、抓取放置。
- 现有 35 个数据集的初始标注，可以由执行线按第 6 项起草一份建议值，负责人在页面上逐个确认或修改。确认之前一律显示"未标注"，不自动写进导航层。
