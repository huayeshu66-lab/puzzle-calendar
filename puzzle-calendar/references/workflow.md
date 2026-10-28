# 可续做任务与交付合同

## 唯一记录源

`job.json` 是任务真值：需求、设计理由、当前范围、文件角色、证据和变更历史保存在一起。导出的inputs是可再生输入，不单独修改成另一份需求；聊天摘要与work脚本不是续做所需的唯一依据。

```text
NEW_JOB/
  job.json
  inputs/                 prepare生成，可重建
  artifacts/              attach复制并注册的文件
  inputs/prepared.json    当前支持检查与选页结果
```

`schema_version='2.0'`，顶层含job_id、正整数revision、request、brief、artifacts、reviews、history。

| request字段 | 内容 |
| --- | --- |
| requirements | 唯一实际值：date_range、calendar_form、cadence、puzzles_per_slot、week_start、audience、difficulty、print、output、instructions、information、appearance |
| decisions | 字段路径对应origin与reason；origin为user／assumed／delegated／derived，不再重复实际value |
| constraints | locked字段路径列表、excluded_types列表；锁定项变化需要实际用户授权 |
| scope | 可选start／end，当前交付子范围；省略即完整date_range，必须包含在计划范围内 |

print使用paper／orientation／mode／duplex／binding，其中binding含edge和reserve_mm。output使用formats列表和answers模式；information.kinds只记录已选类别。字段通过当前实现校验，不把记录了需求当成已支持输出。

brief包含use_case、priorities列表、rationale、regions对象、tradeoffs列表；见 [intake.md](intake.md)。这允许不同项目有不同审美和区域安排，不强制某个预设。

## 风格决策与样稿记录

默认先比较样稿、再由用户选定、再批量制作。日期计划与必要样题可先准备；普通“做整月”或“你推荐”不等于已选某个候选。已选方向或明确委托自主定稿直接沿用，不重复审批。

沿用现有合同记录，不新增CLI参数或伪造机器批准：

- 比较组与反馈保存为design制作资料并attach注册，记录候选标识、版本、整页／题面近景、artifact ID与SHA、真实PDF或概念PNG、当前状态及用户反馈来源。
- 用户选定后实际值写requirements，decisions对应字段记origin=user及真实原话、所指候选版本与确认范围；明确委托时记delegated。未选定的试色仍是探索，不覆盖原有打印要求或宣称批准。
- 图像编辑另记edit_target、detail_reference与preserved_layers，明确使用哪版整页、哪版题面；换色前先核对来源，避免旧底稿覆盖最新细节。
- 真实PDF候选用calendar等实际角色注册，PDF渲染的preview仍须绑定其当前哈希。独立生成的概念图可按design／other_private注册并作为概念图展示，不能编造source_pdf_ids或借preview角色伪装已验证PDF。

跨任务相同日期或puzzle_id未必指同一道题。选样和续做同时核对job_id、公开线索、源板哈希及答案映射；不能仅凭P20270101或文件名混用其他任务。当前任务已有冻结题时优先从中选样；临时借用其他题作视觉原型要标明来源，不覆盖正式账本。

当前helper核文件与审阅一致性，不理解“用户是否选定风格”或代替人类授权。执行skill的agent负责在批量调用前读取真实反馈与已选状态；digital_ready也不是风格确认信号。样稿可在未选定时供比较，不要求先审批才能看到候选。

## 入口与旧运行链路

以下PYTHON、SKILL_DIR、JOB等均替换为已解析的真实路径；JSON通过文件传入，不拼成shell代码。

```text
PYTHON SKILL_DIR/scripts/calendar_workflow.py init --request REQUEST.json --brief BRIEF.json --output NEW_JOB
PYTHON SKILL_DIR/scripts/calendar_workflow.py prepare --job NEW_JOB
PYTHON SKILL_DIR/scripts/calendar_workflow.py status --job NEW_JOB
```

`--job` 接受任务目录或其中的job.json。init输出必须是新目录；request文件采用上表request对象，不包整个job。prepare从job导出：

- inputs/plan.json：完整正式计划，保持日期与题位身份。
- inputs/appearance.json：当前显示配置。
- inputs/information.json：已有注册信息时导出。
- inputs/records-resolved.json：已有可复用记录时导出，按已注册资产恢复路径。
- inputs/prepared.json：能力与组合检查、当前scope对应selected_page_ids及输入位置。

prepare缺少所选信息的实际数据时返回needs_inputs；未知style、非PDF、双面拼版或未接通装订等返回needs_implementation，仍保留原需求。prepare不等于生成日历，更不是所有题型、格式的一键实现。按prepared结果调用既有planner／content／renderer或extended_job，详见 [runtime.md](runtime.md)。不支持的组合保留用户需求并明确说明，不静默降级。若在任务中另行实现，注册实现与验收证据后再声明该组合可用。

status的configuration_preflight汇总当前prepare的state、issues与needed_inputs；需求或brief改变后标为stale，提示重新prepare。它是配置预检状态，与最终文件和审阅的digital_ready分别呈现。

## 自定义样页接入

文件名为`job.json`不代表满足本helper合同。历史样页或专用绘图器的自定义schema不能直接用于status／review／release；先新建`schema_version='2.0'`任务，保留原始样页记录与哈希，将当前需求、brief和真实范围写入新任务。

1. 使用attach注册实际PDF、答案、规则与design资料；预览必须从注册PDF渲染并绑定对应哈希。
2. 原始题板、准确结构、答案映射、绘图脚本、字体／素材依赖和实际核验报告随私有制作资料注册。可复用记录只有符合import-records合同才走该入口；异形图结构等自定义数据可用other_private保存并注明消费它的绘图器，不能假称已转换为原生records。
3. prepare仍可能提示needs_implementation，因为预置能力表不认识自定义组合。保留这个基线提示，在design资料说明本次实现及其证据；不更换用户要求来让预检变绿，也不把一次实现登记为所有任务的内置能力。
4. 依据当前PDF与当前brief重新登记content／pdf／visual检查。历史报告是依据，不能改schema或搬路径就升级为新版通过。只迁移当前需要续做的范围，不批量改写旧样页。

正式批量前仍执行风格选定与题目冻结要求；自定义样页接入不改变用户授权。配置预检、特定任务实现、数字交付与真人验收分别说明。

## 注册文件：attach

```text
PYTHON SKILL_DIR/scripts/calendar_workflow.py attach --job JOB --spec ARTIFACTS.json
```

ARTIFACTS.json是数组，path指向现有源文件。工具复制入任务artifacts并记录相对path、sha256、bytes、revision、active=true；实际PDF另记录page_count。任务记录不能引用外部路径或`..`逃出任务根。

```json
[
  {"id": "calendar-v1", "role": "calendar", "path": "/absolute/render/publication.pdf"},
  {"id": "answers-v1", "role": "answers", "path": "/absolute/render/answers.pdf"},
  {"id": "preview-v1", "role": "preview", "path": "/absolute/previews/overview.png", "source_pdf_ids": ["calendar-v1"]}
]
```

preview额外保存source_pdf_ids及source_pdf_sha256映射，绑定生成它的当前PDF；给旧PNG改文件名不等于新预览。新增或实际更换records、board、information、plan数据时，未在同批替换的旧渲染产物会设为inactive，不能让新数据沿用旧PDF和预览。

| 角色 | 交付去向 |
| --- | --- |
| calendar、rules、calibration、punch_guide、print_notes、sources | 可公开的题本资料，仍检查其内容不含完整答案 |
| preview | 只绑定公开PDF时进题本包；只绑定answers时进答案包；混合或私有来源进私有包 |
| answers | 独立答案包与私有包；不得进入player.zip |
| request_data、plan、records、board、information、renderer_manifest、layout_report、qa、design、other_private | 私有制作包，保留续做与来源 |

role表示内容用途，不只看扩展名。含答案的题板、源记录不能改称sources混进题本。注册原题板及对应hash，以便换目录或机器后恢复；不可搬迁字体或外部求解运行时仍要声明依赖，不能假称包里自带。

## 导入冻结记录与生成预览

```text
PYTHON SKILL_DIR/scripts/calendar_workflow.py import-records --job JOB --records SOURCE_RECORDS.json
PYTHON SKILL_DIR/scripts/calendar_workflow.py preview --job JOB --pdf-ids calendar-v1,answers-v1 --pdftoppm PDFTOPPM_PATH
```

import-records读取已有记录envelope或列表，核对board_sha256，将原题板复制入artifacts，并注册含任务相对题板路径的canonical记录；prepare再导出供底层renderer使用的绝对working路径。未打包的外部生成／验解依赖仍按runtime补齐，不因导入而变成已随包安装。

preview实际渲染已注册的PDF，每16页形成一张联系表并注册绑定。pdf-ids使用真实artifact ID；pdftoppm可传已解析路径，省略时查可用程序。它生成机器可核对的当前预览，不自动写visual=passed；放大细查仍应实际查看对应页，不能把联系表当成细节证据。

## 注册实际检查：review

```text
PYTHON SKILL_DIR/scripts/calendar_workflow.py review --job JOB --report REVIEW.json
```

输入含唯一id、kind、status、scope、criteria、notes、reviewer；工具绑定当前artifact_sha256、revision、delivery_scope及request＋brief的basis_sha256，阻止手改需求后沿用旧审阅。kind为content／pdf／visual／user_acceptance／physical_print／human_difficulty，status为passed／failed／pending／not_requested。

机器与visual证据须覆盖当前calendar和answers。检查对象是实际文件，不能只根据spec或renderer返回exit0写passed。content说明逐题验解、完整唯一性、去重及日期映射的实际依据；pdf说明页幅、字体、边界等检查；visual说明画面判断和覆盖，不由机器测试推导。

visual的criteria需要hierarchy、readability、style、spacing、writing_space五项，各为带status与notes的对象；notes再说明整本节奏和已见例外。必须存在至少一个绑定当前PDF的preview，并用coverage记录每个PDF的page_count、reviewed_pages、method、enlarged_pages。逐页缩略图扫查和放大检查分别记，不把看过4页写成31页细查。

```json
{
  "id": "visual-current-scope",
  "kind": "visual",
  "status": "passed",
  "scope": ["calendar-v1", "answers-v1"],
  "criteria": {
    "hierarchy": {"status": "passed", "notes": "日期、题面和次要文字主次清楚"},
    "readability": {"status": "passed", "notes": "已放大检查当前字体、题外线索及长署名"},
    "style": {"status": "passed", "notes": "与brief的桌面阅读目标一致"},
    "spacing": {"status": "passed", "notes": "各区域与装订区有净空"},
    "writing_space": {"status": "passed", "notes": "题板保持实测可写格距"}
  },
  "coverage": {
    "calendar-v1": {"page_count": 2, "reviewed_pages": [1, 2], "method": "逐页渲染扫查并放大边界页", "enlarged_pages": [1, 2]},
    "answers-v1": {"page_count": 2, "reviewed_pages": [1, 2], "method": "逐页渲染扫查并核对答案可见性", "enlarged_pages": [1, 2]}
  },
  "notes": "仅示例结构；实际记录必须填写真实范围与发现。整本节奏按当前scope检查。",
  "reviewer": "实际审阅者"
}
```

示例不是现成通过证明。用户认可只来自真实反馈；用户未要求审批且授权直接制作时可记not_requested，不伪造passed。实物试印与真人试玩同样独立记录，没有证据就pending，不作为普通数字版必经审批。

## 修改：revise

```text
PYTHON SKILL_DIR/scripts/calendar_workflow.py revise --job JOB --patch PATCH.json --reason "修改原因" --origin derived
```

PATCH只在根接收request与brief；request内按requirements、decisions、constraints、scope等作合并补丁。不能通过revise直接注入artifacts或reviews。origin可用user／derived，默认derived；改locked项或解除既有锁定需要已有用户授权并用user记录；derived不能通过移除锁定绕过限制，不以工具参数自行创造授权。

```json
{"request": {"requirements": {"appearance": {"style_id": "swiss-type"}}}, "brief": {"rationale": "按用户反馈加强日期与留白"}}
```

工具递增revision、记录原因和影响，使受影响文件／证据失效。status同时核实际SHA、active状态、预览绑定与证据覆盖；只改文件没有更新记录也不能沿用旧检查。未改变的源题与hash绑定证明可复用；旧审阅仍受当前需求／brief与输出hash约束，新输出的日期映射和画面需对应记录。依据影响重做，不一律重出所有题目。

仅修订brief.rationale的解释文字时保留既有PDF和预览，返回design_review／release；新理由的审阅依据需要复核，不能自动升级旧结论。真正改变字体、版式、信息或内容时仍停用受影响的渲染产物。

## 交付：release

```text
PYTHON SKILL_DIR/scripts/calendar_workflow.py release --job JOB --output NEW_RELEASE
PYTHON SKILL_DIR/scripts/calendar_release.py --job JOB/job.json --output OTHER_NEW_RELEASE
```

workflow的--job可用目录或job.json；独立calendar_release.py的--job只接受具体job.json路径，省略--output则只评估。release核哈希、角色、scope、证据覆盖和preview绑定，新建交付目录，不修改原job或renderer报告。题本、答案、私有制作资料分包；最终manifest记录文件大小与hash，清单排除自身以免自指。

`digital_ready` 只表示当前scope的内容、PDF和视觉证据完整。用户认可、实物打印、真人难度状态单列，不能由打包升级。合法pending可交付trial，README与manifest必须如实标明digital_ready=false及未完成项；路径、哈希、范围或角色错误则拒绝打包。

已有交付迁入2.0时，新建任务，保留原成品与原SHA，注册原记录、题板、布局和有效证据；不要为了迁移重做题面，也不要把历史报告改写成新版已经通过。复现试验的范围、输入版本和当前输出另记。
