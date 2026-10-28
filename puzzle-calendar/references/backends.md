# 可扩展题型库

## 选择原则

三种题型只是已有原生后端，不能作为长期混合日历的全部选项。先发现本机可用后端，再按受众、玩法复杂度、难度证据和实际纸面筛选。用户授权混合题型时，较长日历可从8–12类开始推荐，全年可在足够适配的前提下采用12–18类轮换；这是推荐，不覆盖用户指定的单题型、比例或受众约束。

保存 `variety_policy`：启用题型、配额、最大连续同类次数、重复检测覆盖、程序／上游难度依据、未启用原因。不为凑题型数而采用难以书写、缺规则或未验解的题。

## 后端分层

非方形题盘另见 [题盘形态](puzzle-forms.md)：蜂巢／三角数回、圆形迷宫和无框桥梁已有独立样例入口；真实结构变化须由相应图模型验解。它们不通过给原方格题加外框实现，当前也未加入自动题型轮换。

| 后端 | 题型 | 实际接口与限制 |
| --- | --- | --- |
| 原生Publisher | 数独、数织、迷宫 | content_records.py＋render_calendar.py；有easy/normal程序评级和D4规范化去重 |
| Tatham生成＋独立Z3验解 | 下表24类 | extended_backend.py；每个新题独立验证公共题面与答案，并阻断玩家答案证明无第二解；使用记录规格；难度与去重覆盖另记 |
| cspuz／本地约束生成 | 下表8类 | 需要核查当前实际接口、公开题面fresh重验和时间预算；小规格实验能力不外推全年稳定性 |

候选题型：

| 组 | 中文题型与技术字段 |
| --- | --- |
| 数字逻辑 | 数独 sudoku、独数 hitori、不等式 futoshiki、数和 kakuro、算术笼 keen、摩天楼 towers、分割数 fillomino、二进制网格 unruly |
| 连线与路径 | 迷宫 maze、数回 slitherlink、桥梁 hashi、珍珠 masyu、连数 numberlink、网络连线 net、斜线 slant、方向序列 signpost、铁路 tracks |
| 涂格与观察 | 数织 nonogram、数墙 nurikabe、点灯 lightup、帐篷 tents、战舰 battleship、黑格视距 range、马赛克 mosaic、磁铁 magnets |
| 分区与空间 | 星战 star_battle、四格涂色 lits、部屋 heyawake、海岬 nurimisaki、矩形分区 rect、多米诺配对 dominosa、地图着色 map、银河 galaxies、围栏分区 palisade、镜面怪物 undead |

扩展24类：slitherlink、hashi、hitori、masyu、tents、fillomino、slant、futoshiki、net、rect、dominosa、lightup、map、galaxies、keen、towers、magnets、signpost、range、unruly、tracks、palisade、undead、mosaic。

另8类：star_battle、nurikabe、kakuro、battleship、numberlink、lits、heyawake、nurimisaki。

## 当前本机的扩展来源

现有多题型源码项目：

`/Users/huahua/Documents/Codex/2026-09-29/referenced-chatgpt-conversation-this-is-an`

通过 `--source-project` 指定该目录；路径不存在时询问新位置或报告缺失，不能声称skill包自带所有二进制与求解依赖。该源码是**外部只读依赖**，调用时只把新生成物写进当前任务的新job目录，不运行固定输出路径的旧main()，不覆盖历史样册。

所需组件包括 `scripts/sample35/upstream.py`、`eight.py`、`verify_upstream.py`，`work/paper-probe/build/`中的编译生成器，Z3／cspuz依赖及相应来源代码。桥接器检查真实组件、版本／哈希及生成后的唯一性证据；只列目录不算支持。

旧35类样册证明了当时每类一道题，不代表任意规格、种子或日历排版都已验证。旧wrapper固定seed和缓存路径，直接重复调用会复用同一题；扩展桥接器使用题位派生的新seed、新目录并重新验解，不靠复制旧样题填充日历。

独立checker也需要适配检查。例如桥梁描述相邻的单字符数字不能误解成一个多位数；本机freshseed测试暴露过此问题。保留解码规则与回归证据，checker异常或UNKNOWN都不能记为唯一。

## 扩展运行

```text
PYTHON SKILL_DIR/scripts/extended_backend.py capabilities --source-project SOURCE_PROJECT
PYTHON SKILL_DIR/scripts/extended_backend.py generate --type futoshiki --seed unique-slot-seed --output-dir NEW_RECORD_DIRECTORY --source-project SOURCE_PROJECT
PYTHON SKILL_DIR/scripts/extended_job.py --plan FULL_PLAN.json --types futoshiki,lightup,hitori,mosaic,towers,rect,keen,unruly --source-project SOURCE_PROJECT --output-dir NEW_JOB --paper A4 --seed calendar-v1
```

参数以脚本help为准。先做真实代表页；后续用相同正式计划、规则位置和已批准记录恢复／复用。日历制作通过extended_calendar.py将两页矢量题面／答案板分别排入日期版式，保留中文规则和物理最小尺寸，不能把带答案的整块PDF嵌入题页。

每类标明可用规格、来源、生成档、独立证明方式、尝试耗时、页面适配和去重覆盖。缺少统一难度评级时标为 `unrated` 并安排样张试做，不能冒称easy/normal或专家档已经校准。部分规格很小且玩法受限，例如2×2白区数和、4×4全覆盖连数；向用户推荐时用真实规格说明。

扩展后端默认精确公共题面摘要去重，不自动继承原生的D4与数独重编号结论。更严格的视觉／同构要求需逐类实现筛查并记录。新题面、版式与实际PDF都验证通过才进入本次交付可用集合；软件可生成不等于能在A5下写得清楚。

第三方许可随制作包保留，玩家默认只拿日历题页、独立答案、校准与打印说明。不要把源记录中的完整答案隐藏进玩家题本。


## 挑战档

以下是审读上游源代码后接通的Hard规格。每道仍须新种子、独立规则验解和完整唯一性证明，物理适配另测；不是把Easy改一个中文标签。

| type_id | 精确规格 | 说明 |
| --- | --- | --- |
| slitherlink | 10x10t0dh | 数回10×10 Hard |
| hashi | 7x7i30e10m2d2 | 桥梁7×7 Hard |
| slant | 8x8dh | 斜线8×8 Hard |
| lightup | 7x7b20s4d2 | 点灯7×7 Hard |
| towers | 5dh | 摩天楼5×5 Hard |
| dominosa | 6dh | 多米诺Hard，规则按实际骨牌范围 |
| tracks | 8x8dh | 铁路8×8 Hard |
| keen | 5dh | 算术笼5×5 Hard，数字范围1–5，规则同步 |

通过 `generate_extended(..., variant=...)` 或 `extended_job(..., variants={...})` 按任务选择；CLI分别为 `--variant` 与 `--variants JSON_PATH`。不接受未审读任意字符串，native实际返回params须与请求一致；复用若与任务规格不同直接拒绝。变体参与种子和配置，保留记录的source_params/upstream_difficulty；人类未标定时label仍为unrated、human_calibration=pending。来源档位不能跨玩法等同；下述profiles补充其他真实档位，仍不把Tricky、Extreme、Unreasonable统称Hard。

## 已配置的多题型profiles

`data/puzzle-profiles.json`保存32类扩展候选的明确规格、玩法类别、来源代码哈希、真实档位、试生成状态及本次A5题区适配记录；`data/profile-evidence.json`保存每类两组新种子的独立验解与物理尺寸证据。2026-10-15的测试共64个不同实例，不能据此外推全年所有种子稳定或真人难度已校准。原生3类沿用原生链路。

挑战候选共16类：原有8类Hard，加独数6×6 Tricky、珍珠8×8 Tricky、帐篷8×8 Tricky、不等式5×5 Extreme、地图着色12×9/18区 Hard、银河7×7 Unreasonable、磁铁6×5 Tricky、镜面怪物4×4 Tricky。每题继续保存原始档位，统一难度仍为unrated。

另16类保留为mixed或显式选择候选；星战、四格、部屋、海岬接入6×6规格。数墙6×6虽有两个有效样本，但安装后另外三个种子在20–30秒内均超时，自动默认退回4×4；6×6仅供显式实验选择，已验证的旧记录仍可重新验解。数和仍为2×2白区、战舰为5×5、连数为4×4实验规格，不能因有题型名称就推荐为成人挑战。分割数7×7的两次第二解证明超时，当前配置5×5；失败记录保留，不把UNKNOWN写成UNIQUE。

```text
PYTHON SKILL_DIR/scripts/extended_backend.py select --source-project SOURCE_PROJECT --difficulty challenge
PYTHON SKILL_DIR/scripts/extended_job.py --plan PLAN.json --types auto --difficulty challenge --source-project SOURCE_PROJECT --output-dir NEW_JOB --paper A5 --instructions reference
```

`auto`按多种玩法交错安排，并把选中规格、真实档位与排除原因写进config.json的variety_policy。`mixed`允许难度未标定的候选，不代表所有题都难；用户指定题型时保持其选择。旧默认规格与旧8类Hard记录继续可复用；放大后的cspuz记录复用须核对实际size，不能沿用4×4旧题。

A5测量对应114×92毫米题区，格距至少7毫米、实际文字至少12pt；镜面怪物与马赛克只在当前工作进程提高题板字号，外部源码保持只读。调整日历信息、孔区或题区后重新计算适配。新生成实例仍完整验解、证明唯一性与全局去重；配置证据不替代逐题检查。来源文件哈希改变时停止使用相应已审读规格，重新检查参数语义。
