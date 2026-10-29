# 先生成一张 PDF

这个入门示例只使用仓库自带的圆形迷宫代码和字体，生成一页 A5 日历、独立答案、独立玩法。它不需要 puzzle-publisher 或外部多题型源码。它不是全套日历的自动生成入口。

准备 Python 3.11+ 和 Node.js。在下载并解压的仓库根目录运行：

```bash
python3 -m pip install -r examples/requirements.txt
python3 examples/first_calendar.py --date 2027-07-02 --output ./my-first-calendar
```

Windows 可把 `python3` 换成 `py`。如系统找不到 Node，追加 `--node` 指定可执行文件。

输出包含 `calendar.pdf`、`answer.pdf`、`rules.pdf`。默认用英文，避免新环境缺少中文字体而无法开始。已有可嵌入中文字体时，增加参数：

```bash
python3 examples/first_calendar.py --date 2027-07-02 --output ./my-first-calendar-zh --font "/absolute/path/to/ChineseFont.ttf"
```

不要覆盖已有输出目录。换日期只改变日期；需要另一道题时追加不同的正整数 `--seed`。输入相同 seed 将得到同一道迷宫，不能当作全年不同题目。

`production-private/` 是本次生成过程的结构数据与证明，包含答案资料，不应混进只含题面的玩家文件。

此示例输出用独立 BFS 检查通路与迷宫引擎一致。正式使用仍检查纸笔体验；新机器的安装、字体及打印情况请反馈。完整技能另见上级使用说明，扩展题型仍有额外依赖。
