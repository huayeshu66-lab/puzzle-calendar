# 运行能力与接口

## 先分清能力层级

| 层级 | 当前事实 | 执行方式 |
| --- | --- | --- |
| 已实现 | 公历计划；原生3类内容；扩展后端适配；一页一题的月／周／每日PDF；独立答案、规则和校准；7种editorial每日预设；2.0任务与交付记录 | 先通过当前环境、组合与实际内容检查，再调用脚本 |
| 有条件 | 扩展求解运行时、可嵌入中文字体、农历／节气／节假日数据、引文、专业排盘、用户图片或logo | 取得实际依赖／材料并记录版本、来源、适用范围 |
| 需新增实现 | 未接通的制式或组合、DOCX、任意纸幅、多题月格、复杂双面拼版、真实纸雕／刀模等 | 保留用户目标，明确缺口；本次另行实现并验收后才称支持 |

不能从目录有某题型、planner能排日期或样式名存在，推导整条生产链已可用。题型规格、独立验证和难度边界见 [backends.md](backends.md)；不把35个候选条目称为35类均稳定量产。

非方形题盘提供独立实验入口 `shape_loopy.py`、`shape_hex_cluster.py`、`shape_circular.mjs` 和矢量绘图 `shape_boards.py`，具体实例、依赖、验证与限制见 [题盘形态](puzzle-forms.md)。蜂巢默认类六边形簇，依赖Z3验证；显式选择上游矩形蜂窝／三角网格时另需版本匹配的原生库。圆形迷宫附MIT核心代码。尚未自动接入现有 job CLI 的选型与批量排程。

答案与玩法的设计选项见 [交付安排](answer-and-rules.md)。当前基线只自动处理output.answers=separate；双面拼版、随机背面映射、直接编码答案的二维码、首玩前独立插页等需要另行实现并验收。现有first_occurrence是在首题页内印规则，不是首题前另印一页。不能把这些需求改成旧默认值以绕过检查。
联网图形答案可复用 [Cloudflare 静态托管流程](qr-cloudflare.md)：使用用户账户发布答案页，再生成二维码。此流程已有单题发布和手机扫码验证经验；批量站点、日期映射与最终PDF仍须按任务实施核对，不等同于新增CLI参数或全年已验收。

## 统一任务入口

新建或长期续做推荐 [workflow.md](workflow.md) 的 `calendar_workflow.py`，以job.json为唯一需求源。prepare只导出输入并检查当前支持组合，不自动生成所有内容。

```text
PYTHON SKILL_DIR/scripts/calendar_workflow.py init --request REQUEST.json --brief BRIEF.json --output NEW_JOB
PYTHON SKILL_DIR/scripts/calendar_workflow.py prepare --job NEW_JOB
PYTHON SKILL_DIR/scripts/calendar_workflow.py status --job NEW_JOB
```

prepare生成inputs/plan.json、appearance.json，已有信息或记录时还生成information.json、records-resolved.json；inputs/prepared.json提供当前selected_page_ids与输入位置。完整plan与当前scope分开，做一月不改变全年题位，做代表页不重新推断正式首次规则。

需求在request.requirements只存一次；decisions保存origin/reason，brief保存理由与取舍。修改使用revise；文件使用attach注册，证据使用review，交付使用release。精确JSON和角色合同只在workflow.md维护，避免多个不同的“任务格式”。

## 依赖与迁移

扩展后端的`--types auto --difficulty challenge`按已配置profiles选择多种玩法和真实来源档位，不再依赖调用者手写固定八类；`--difficulty mixed`还可使用未标定难度的候选。实际规格、样本验证覆盖、A5测量条件及限制见[后端profiles](backends.md#已配置的多题型profiles)。显式`--types`与旧默认规格保持兼容。

planner只需Python 3.11+标准库。原生生成／PDF需要已安装的puzzle-publisher/runtime、reportlab、pypdf和可嵌入中文字体；页脚logo另需Pillow。用可用的 `load_workspace_dependencies` 找现成解释器，不把作者缓存路径当作通用命令。

先运行Publisher的doctor与capabilities。helper依次查同级puzzle-publisher和 `~/.codex/skills/puzzle-publisher`，也可显式传 `--publisher-dir`。它复用Publisher私有 `_Page/_geometry/_grid/_maze`，需记录实际版本／hash，升级后重验相关链路。doctor.ready不代表页面、难度、数据事实或实物已经通过。

扩展后端需 `--source-project` 指向实际只读来源，所需编译器产物和Z3／cspuz依赖见backends.md；当前skill包不自带全部引擎。新生成文件写当前任务的新目录，不运行会覆盖历史固定输出的旧入口。

assets附Work Sans Bold／Regular、Lora Regular、Tektur Medium及OFL许可。中文主字体由实际环境提供；eastern-book、newsprint和cyber-noir寄语需要可嵌入宋体。自动检测本机Songti SC-Regular；serif_font_path可以覆盖合格TTF／TTC，用户TTC取首字面，必须核中文覆盖与嵌入。缺失明确失败，不默换字体并保留原style标签；不打包商业中文字体。

任务迁移时用import-records复制冻结源记录与原题板，另注册信息、配置与证据，保留hash；prepare恢复已注册资产的可用路径。外部引擎与不可分发字体仍是运行依赖，缺失需补齐。可复现能力以真实续做试验说明，不只交出绝对路径清单。

## 底层脚本继续可用

以下PYTHON／SKILL_DIR／JOB均为已解析真实路径，所有输出目录需新建。新任务用prepare导出的输入；旧任务仍可直接传原有计划。旧planner接受扁平date_range等字段，不能直接读完整2.0 request／job包装。

原生示例：

```text
PYTHON SKILL_DIR/scripts/content_records.py --plan JOB/inputs/plan.json --out NEW_RECORDS.json --seed calendar-v1 --types sudoku:9,nonogram:5,maze:10 --difficulty easy
PYTHON SKILL_DIR/scripts/render_calendar.py --plan JOB/inputs/plan.json --records NEW_RECORDS.json --appearance JOB/inputs/appearance.json --paper A5 --orientation portrait --print-mode bw --instructions reference --output-dir NEW_RENDER
```

有信息时显式加 `--information JOB/inputs/information.json`；没有该文件不传。有旧记录时content helper可用 `--reuse`，renderer直接使用prepare导出的records-resolved.json；两者都需要实际重验，不信任旧的passed标签。

扩展生成与渲染示例：

```text
PYTHON SKILL_DIR/scripts/extended_job.py --plan JOB/inputs/plan.json --types lightup,hashi,slant --source-project SOURCE_PROJECT --appearance JOB/inputs/appearance.json --paper A5 --instructions reference --output-dir NEW_EXTENDED_JOB
PYTHON SKILL_DIR/scripts/extended_calendar.py --plan JOB/inputs/plan.json --records JOB/inputs/records-resolved.json --source-project SOURCE_PROJECT --appearance JOB/inputs/appearance.json --paper A5 --print-mode bw --instructions reference --output-dir NEW_RENDER
```

这些是独立CLI，不是workflow自动选择的万能命令。样页／当前scope用prepared给出的正式 `--page-ids`（逗号分隔）；信息和复用文件按实际存在与类型传入。extended_job通过 `--variants PATH` 接收精确上游规格，通过 `--reuse PATH` 接续内容记录。参数以当前脚本help与检查结果为准，不能把示例值写死到任务。

| 现有入口 | 支持范围与限制 |
| --- | --- |
| calendar_plan.py | daily／weekly／monthly与多种cadence；最多3660天；只规划，不证明能排版 |
| content_records.py | 数独／数织／迷宫；easy／normal／mixed；fresh solve、独立验解、原生评级、规范化去重与检查点 |
| render_calendar.py | A4／A5、横竖版、bw／color；每页一个题位且每题位一题 |
| extended_calendar.py | A4／A5竖版、bw／color；每页一题，保留源矢量题板；实际依赖与规格先核对 |
| extended_job.py | 整合当前扩展生成、复用和竖版渲染；现CLI没有通用orientation／print-mode选项，不等于所有renderer组合都有一条集成命令 |

任意装订预留、双面拼版或其他成品工艺不是现有renderer的任意参数；记录了binding需求仍需实际适配与工艺证据。月格每日一题、同页多题或单页年总览等不在现成一页一题链路范围，不能静默改成每月一题，也不能以当前实现限制否定用户产品目标。

## 风格探索与正式制作的边界

运行CLI前按SKILL先完成当前风格决策：未选定先少量样稿，选定或明确委托自主定稿后批量。prepare可算完整日期计划，参数通过不代表用户批准。helper没有自动判断批准的开关；记录方法见 [任务流程](workflow.md#风格决策与样稿记录)。

七个style_id是当前基础页样式。它们不自动提供任意高质量插画、题面换肤、整页铺底／反白或多层配色；accent_color只覆盖强调色。新图形、题面处理与色板需要实际实现并验证，不伪造未支持的appearance字段。

图像生成可制作原创装饰或概念PNG；正式PDF的日期、文字和谜题按结构数据排入。概念图即使看起来清楚，仍不能据此声称字形、毫米格距、线索坐标或字体嵌入已核对。题面重绘要保留原源板及哈希、冻结语义，另存derived输出与实际对照证据，见 [设计评审](design-review.md)。

## 页面与规则策略

`appearance.layout` 默认classic用于旧任务兼容；editorial当前限daily＋portrait、instructions为reference／none、show_rule_hint=false。classic接受旧theme minimal／newspaper／chinese／modern和默认style_id，不能选非默认style后降级冒充。

editorial可用warm-editorial、swiss-type、eastern-book、newsprint、botanical、geometric、cyber-noir；具体构图、字体和原型边界集中见 [style-library.md](style-library.md)。预设默认不是用户偏好，新方案按brief判断；未实现组合不得声称这些样式自动覆盖。

| instructions | 适用场景 |
| --- | --- |
| reference | 整本连续使用，guide.pdf集中完整规则；样页指南只含实际所示玩法 |
| first_occurrence | 新手逐步学习，同一规则正式首次出现放简则 |
| every_puzzle | 单张独立使用，每页完整简则 |
| none | 已熟悉玩法，必要线索与图例仍保留 |

inline规则当前需要classic或新增合格版式。提示不是完整规则的替代；规则未知时保留全部条件，放不下报冲突。first_occurrence身份考虑实际规则与版本，不能只看题型名或在每月重置。后段原生样页需要来自完整正式分配的 `--first-rules-slots`，不按样页顺序猜首次。

### 页面显示配置

`appearance.json`控制layout、style_id、accent_color、serif_font_path、book_title、show_information_titles、show_rule_hint、show_puzzle_id、show_page_number和footer。未明确设置强调色时取所选style默认色；显式值需#RRGGBB。布尔值需实际bool，未知字段或不兼容组合报错。

当前renderer默认隐藏总标题、信息标题、提示、内部ID、页码，footer留空；这些是当前显示默认，不限制用户做封面、导航或品牌设计。book_title只写PDF元数据。隐藏ID不删除内部题位映射，答案默认按日期查找。

footer可用文字或本地PNG／JPEG logo，二选一。文字9pt，最多80字符且实际宽度必须放得下；logo绝对路径可读、最多10MiB和2000万像素，高度≤8mm、宽度不超实际页脚区，保持比例，不侵入安全边界。未提供logo不自动造品牌。

cyber-noir当前原型在A5顶部预留20mm；Tektur Medium为84pt左日号，年月为中文无衬线，星期及2–5字纯汉字短题名逐字正向竖排，寄语11pt与署名9.5pt宋体横排；holiday／solar_term在日期旁。其他六样式尚未统一这一信息路由，不能自动宣称已经满足同类brief。通用日期或版式新要求应先核相应实现，不强行套本原型。

## 信息、内容与来源合同

`--information`读取page_information合同，处理正文或两栏fields、页面／日期映射、来源字段与空间，不计算历法、不查天气、不验证引文真假。source／method／verified是可追溯记录，不会自行证明事实。

fields最多6项，label≤4字符、value≤16字符；实际宽度仍必须放得下，不自动截短或缩字。quote的attribution最长50字符、只与text配合，正文和署名各占实际空间。数据细节见 [calendar-information.md](calendar-information.md)。

内容始终重新验解与检查资产hash；只接受完整唯一性证据。extended显式variant参与seed与config，复用时核raw.params，不允许换档沿用旧题；未传时保留旧默认与seed。Hard为上游程序标签，human_calibration仍可pending。预算耗尽保留incomplete，不重置历史耗时绕过限制，不用重复题凑数。

## 输出、检查与发布

renderer生成publication.pdf、answers.pdf、calibration.pdf、layout-report.json、manifest.json；reference另有guide.pdf。报告保留机器结果与pending字段，主控不能手改成视觉／实物passed。

可用workflow preview实际渲染已注册PDF并生成绑定联系表，再按 [design-review.md](design-review.md) 检查设计，按 [print-design.md](print-design.md) 检查纸面。将当前PDF、预览、源数据和实际证据attach／review到任务，再由release打包。最终命名calendar.pdf可以在角色化交付时处理，不需依赖某次work装配脚本。

content、pdf、visual支持当前scope的digital_ready；用户认可、实物试印、真人难度另记。合法pending可作为trial交付；缺少实物试印不阻止数字PDF交付，但不能声称印刷实测通过。路径／hash／范围不符要先修正，不能通过“打包成功”掩盖问题。
