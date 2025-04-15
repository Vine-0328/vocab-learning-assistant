# TOEFL & SAT Vocabulary Learning Assistant

一个简单而强大的托福和SAT词汇学习助手，帮助你每天高效记忆英语单词。

## 功能特点

- 每日学习70个精选托福/SAT词汇
- 智能复习系统，根据掌握程度调整复习频率
- 包含详细释义和例句
- 学习进度追踪
- 自动保存学习记录
- 简洁清晰的用户界面

## 安装说明

1. 克隆仓库：
```bash
git clone https://github.com/Vine-0328/vocab-learning-assistant.git
cd vocab-learning-assistant
```

2. 创建并激活虚拟环境（推荐）：
```bash
python -m venv venv
.\venv\Scripts\activate
```

3. 安装依赖：
```bash
pip install -r requirements.txt
```

## 使用方法

1. 运行程序：
```bash
python vocab_learner.py
```

2. 使用界面：
   - 点击"开始学习"显示新单词
   - 点击"显示释义"查看词义和例句
   - 根据掌握程度点击"认识"或"不认识"
   - 界面上方显示每日学习进度

## 项目结构
vocab-learning-assistant/
- vocab_learner.py # 主程序
- requirements.txt # 项目依赖
- README.md # 项目文档
- LICENSE # 开源协议
- data/ # 数据文件夹
- word_list.json # 词汇数据
- 6000 words examples.json #6000词汇数据
## 数据格式

词汇数据存储在SQLite数据库中，包含以下字段：
- 单词
- 释义
- 例句
- 难度级别
- 最后复习时间
- 掌握程度

## 贡献指南

欢迎提交 Pull Request 或创建 Issue！

主要改进方向：
1. 添加更多托福和SAT高频词汇
2. 增加词源分析功能
3. 添加发音功能
4. 增加复习计划功能
5. 添加错题本功能
6. 增加数据统计和学习分析功能

## 开源协议

本项目采用 MIT 协议开源，详见 [LICENSE](LICENSE) 文件。
