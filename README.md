# 词间 Vocab · 托福 / SAT 词汇学习助手

沿用原项目「每日词汇 + 掌握程度反馈 + 学习记录」的思路，补全为离线桌面程序。

## 立即使用

Windows 用户直接运行交付目录中的 **VocabAssistant.exe**，无需安装 Python、注册账号或配置密钥。当前成品为 Windows x64。

源码需要 Python 3.10 或以上版本（包含 Tkinter），双击 `启动词间.bat`，或者运行：

```powershell
python vocab_learner.py
```

运行时只使用标准库，不需要第三方包。Linux 可能需要安装系统包 `python3-tk`。其他平台请从源码运行。

## 功能

- 今日概览：新词目标、待复习、连续学习、累计词数和近 14 天趋势。
- 学习空间：每日学习、到期复习、拼写练习、错词巩固、收藏练习。
- 间隔复习：忘记、模糊、记得、熟悉四档反馈，显示预计间隔，到期优先。
- 每日计划：默认每天 70 个新词，每轮 20 张卡，可调整数量和词库。
- 自动保存：每次评分立即写入 SQLite，同一天重启可继续未完成的一轮。
- 词库管理：按英文、中文释义和笔记搜索，按词库和学习状态筛选。
- 词汇维护：添加、编辑、例句、笔记、收藏、归档和恢复；归档保留历史。
- 数据交换：JSON / CSV 导入、CSV 导出筛选结果、完整 JSON 备份及恢复。
- 旧版兼容：导入原版 vocabulary.db，不修改原文件，重复迁移不重复记账。
- 离线发音：Windows 系统英语语音；macOS 系统 say；Linux 暂未接入发音。
- 双语翻译：拼写复习和学习新词可以查看中英双译。
- 小窗口支持：页面、长文本和词汇列表可滚动。
- 页面和列表采用无箭头圆角细滚动条，悬停加深，无需滚动时隐藏；进度条采用无边框细线。

## 第一次学习

1. 在「计划与数据」选择「核心词库」熟悉流程，也可使用全部词汇。
2. 点击「开始今日学习」。先安排到期复习，再补足新词。
3. 回想词义，按空格或点击「显示释义」，再阅读释义和例句。
4. 用 1–4 或按钮选择掌握程度。程序保存后进入下一词。
5. 拼写练习中输入单词，Enter 检查，再次 Enter 进入下一词。
6. 退出重开后，今日数量和记录保留，未完成的一轮可继续。

在输入框中空格和数字正常输入。切换模式会重新安排该模式的一轮，未评分的词不计为已学习。

## 词库情况

首次启动得到 **6,014 个去重词条**：

| 词库 | 数量 | 内容 |
| --- | ---: | --- |
| 核心词库（TOEFL / SAT 分类） | 100 | 中文释义、词性及原创英文例句 |
| 扩展词库 | 5,914 | 原项目英文释义，不含例句 |

原 6000 words examples.json 有 6,000 条，实际只有 word 和 def，没有例句。清理空格及去重后为 5,995 个不同词，其中 81 个与核心词重合，优先保留核心版本；新增 19 个核心词后总数为 6,014。

TOEFL / SAT 是学习分类，不是官方考试必考词表。

## 复习与统计

- 忘记：约 10 分钟后复习，连续成功次数归零，记录一次遗忘。
- 模糊：至少 1 天，之后间隔约为原来的 1.2 倍。
- 记得：首次 1 天，第二次 3 天，此后按记忆系数延长。
- 熟悉：首次 4 天，之后进一步延长。
- 提前练习记录正确率，不重复拉长原定间隔；再次忘记会缩短间隔。
- 已掌握：连续成功回想至少 3 次，且间隔达到 21 天。这是程序内的操作性指标。
- 错词本保留所有曾经忘记或拼写错误的词，便于长期巩固。
- 新词目标统计当天首次评分的不同词数，到期复习不占目标。错词、收藏和额外练习可按需进行。
- 今日练习显示不同词数量和练习次数。正确率按次数统计，模糊、记得、熟悉算成功回想。
- 统一使用运行设备的本地日期及时间，跨日重置新词数量。

采用可解释的间隔规则，未使用 FSRS，不把间隔或掌握指标视为考试效果保证。

## 导入与导出

支持 UTF-8 JSON、带或不带 BOM 的 UTF-8 CSV。JSON 示例：

```json
[
  {
    "word": "resilient",
    "definition": "adj. 有韧性的；能迅速恢复的",
    "example": "A resilient ecosystem can recover after a disturbance.",
    "deck": "自定义",
    "note": "与 resilience 一起记忆"
  }
]
```

兼容原项目的分组格式以及 def 释义字段。CSV 表头：

```csv
word,definition,example,deck,difficulty,note
```

单词和释义必填。先校验整份文件，任何条目不合法都取消本次导入。重复词跳过，不覆盖已有释义、笔记或进度，已归档词也视为存在。文件上限 30 MB，最多 100,000 条。

CSV 只导出词汇内容，以公式字符开头的字段加单引号，防止表格软件执行公式。保留进度、收藏和评分记录请使用「完整备份」。

## 数据与恢复

默认数据库位置：

- Windows：%LOCALAPPDATA%\VocabLearningAssistant\vocabulary.db
- macOS：~/Library/Application Support/VocabLearningAssistant/vocabulary.db
- Linux：$XDG_DATA_HOME/VocabLearningAssistant/vocabulary.db，未设置时使用 ~/.local/share/。

可以指定独立数据目录（可执行文件支持相同参数）：

```powershell
python vocab_learner.py --data-dir D:\MyVocabulary
```

数据在程序目录之外，更新程序不覆盖记录，程序不上传学习数据。

完整备份包含词库、笔记、收藏、评分记录和设置。恢复会替换现有数据，界面会确认；校验通过后先自动把当前数据库副本存入数据目录 backups/，再恢复。损坏备份不会写入当前数据。


## 开发与验证

```powershell
# 全部测试，需要桌面 / 图形显示环境
python -m unittest discover -s tests -v

# 无图形环境只运行数据层测试
python -m unittest discover -s tests -p test_core.py -v

# 检查词库及数据库完整性
python vocab_learner.py --self-check --data-dir .\check-data
```

self-check 会在数据目录写入 self-check.json，便于验证无控制台的成品。

```text
vocab_learner.py       桌面入口
vocab/app.py          界面、交互、发音
vocab/core.py         数据、间隔复习、备份及迁移
vocab/widgets.py      圆角细滚动条与进度条
data/core_words.json  100 个完整核心词
data/6000 words examples.json   原始扩展数据
tests/test_core.py    数据与学习规则测试
tests/test_ui.py      真实 Tk 交互测试
build_windows.ps1    打包脚本
启动词间.bat          源码启动入口
```

## Windows 打包

在 Windows x64 上运行：

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements-build.txt
.\build_windows.ps1 -Python .\.venv\Scripts\python.exe
```

输出 dist/VocabAssistant.exe。固定使用 PyInstaller 6.22.3，其支持范围见[官方说明](https://pyinstaller.org/en/stable/)。运行程序本体无第三方依赖。

当前成品在 Windows 11 x64 / Python 3.14.5 / Tk 8.6 上验证。

## 版本与协议

2.0.0 基于 [Vine-0328/vocab-learning-assistant](https://github.com/Vine-0328/vocab-learning-assistant) 的 main 分支 3e4b49d 扩展，保留原 MIT 协议，见 [LICENSE](LICENSE)。
