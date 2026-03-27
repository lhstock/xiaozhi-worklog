# xiaozhi-worklog

`xiaozhi-worklog` 是 `小志` 的技能仓库。它的目标不是保存会话副本，而是基于项目目录、AI 原始会话和个人 git 信息，帮助你快速整理可编辑的中文周报。

如果你是第一次使用，先看下面的“3 分钟快速开始”，先跑通一次，再回来看后面的说明。

## 小志能做什么

- 生成中文周报草稿
- 打开本地周报工作台进行编辑、复制和确认
- 按项目目录管理项目映射
- 查看当前索引状态和技能信息
- 支持从不同 AI 工具会话中补充周报语义，当前支持 `codex` 和 `claude-code`

## 3 分钟快速开始

### 1. 安装到本地 skills 目录

```bash
git clone git@github.com:lhstock/xiaozhi-worklog.git ~/.codex/skills/xiaozhi-worklog
cd ~/.codex/skills/xiaozhi-worklog
```

技能入口文件：

```text
~/.codex/skills/xiaozhi-worklog/SKILL.md
```

### 2. 配置会话来源

编辑 `settings.json`，至少保证 `session_providers` 可用。示例：

```json
{
  "session_providers": [
    {
      "name": "codex",
      "type": "codex",
      "root": "/Users/lh/.codex/sessions"
    },
    {
      "name": "claude-code",
      "type": "claude-code",
      "root": "/Users/lh/.claude/projects"
    }
  ]
}
```

如果你暂时只用一个来源，也可以只保留一个 provider。

### 3. 配置项目映射

周报按“项目名”汇总，因此要先把项目目录映射到项目名称。编辑 `report-mapping.json`，例如：

```json
{
  "path_map": {
    "/Users/lh/work/project-a": "项目A",
    "/Users/lh/work/project-b": "项目B"
  }
}
```

这里使用精确 `pwd` 匹配，不做前缀匹配。

### 4. 生成周报

在技能宿主里直接说：

```text
小志 提供周报
```

如果你更习惯命令行，也可以先准备周报源数据：

```bash
python3 scripts/xiaozhi_worklog.py --settings settings.json prepare-report --mapping report-mapping.json
```

### 5. 在工作台确认

推荐使用一次性本地工作台：

```bash
python3 scripts/xiaozhi_worklog.py --settings settings.json open-workbench --mapping report-mapping.json
```

默认地址：

```text
http://127.0.0.1:5555/
```

你可以在页面里：

- 查看并编辑周报草稿
- 重新生成草稿
- 一键复制内容
- 确认归档

归档完成后，本次工作台会自动结束，不会常驻。

## 一次完整演示

假设你这周在两个项目里都和 AI 有过会话，并且本周提交了个人代码：

1. 在 `report-mapping.json` 里配置项目目录和项目名
2. 在宿主里输入 `小志 提供周报`
3. 小志先静默同步本周涉及的项目目录，再结合个人 git 和原始会话准备周报源数据
4. 打开 `http://127.0.0.1:5555/`
5. 在页面中查看生成的中文草稿，按需要修改文案
6. 点击复制带走内容，或直接确认归档

你最终拿到的是可直接继续修改的周报草稿，不是原始对话摘抄，也不是 commit 列表。

## 小志常用指令

在技能宿主中，你可以直接使用这些表达：

- `小志 提供周报`
- `小志 打开周报工作台`
- `小志 查看索引状态`
- `小志 查看技能信息`
- `小志 查看项目映射`
- `小志 设置项目映射 /a/project:Alpha`
- `小志 删除项目映射 /a/project`

## 周报会是什么风格

小志生成的周报默认遵循这些规则：

- 按“项目 + 模块级事项”归纳
- 每个项目尽量控制在 `3-7` 条以内
- 优先合并重复问题域和交付目标
- 使用“完成 / 优化 / 推进 / 完善”等结果导向动词
- 避免时间线式表达，不写“先做什么、再做什么”
- 不直接复述会话原文，不直接堆 commit 信息
- 以管理视角表达成果、进度、功能、测试或调研结论

简单理解：小志会尽量把“做了哪些步骤”改写成“本周交付了什么结果”。

## 工作原理简述

为了让周报更可用，小志采用的是“轻索引 + 回查原始信息”的方式：

- 静默同步时，只记录本周哪些项目目录发生过 AI 会话
- 不额外备份整份会话记录
- 生成周报时，再按项目目录和时间回查原始会话
- git 与会话重叠时以 git 为主，会话只补充 git 不容易表达的上下文
- 周报阶段才根据 `report-mapping.json` 归并为项目名

这套方式更轻，也更方便后续扩展不同工作目录和不同 AI 工具来源。

## 常用命令

```bash
python3 scripts/xiaozhi_worklog.py --settings settings.json info
python3 scripts/xiaozhi_worklog.py --settings settings.json index-status --mapping report-mapping.json
python3 scripts/xiaozhi_worklog.py --settings settings.json prepare-report --mapping report-mapping.json
python3 scripts/xiaozhi_worklog.py --settings settings.json open-workbench --mapping report-mapping.json
python3 scripts/xiaozhi_worklog.py list-mappings --mapping report-mapping.json
python3 scripts/xiaozhi_worklog.py set-mapping --mapping report-mapping.json --pwd "/a/project" --project "Alpha"
python3 scripts/xiaozhi_worklog.py delete-mapping --mapping report-mapping.json --pwd "/a/project"
```

## 仓库结构

- `SKILL.md`: 技能入口
- `settings.json` / `report-mapping.json`: 配置文件
- `scripts/` / `agents/`: 运行逻辑
- `dev/tests/`: 开发验证用例
- `dev/docs/`: 开发过程文档

## 更新

```bash
cd ~/.codex/skills/xiaozhi-worklog
git pull
```

## 开发验证

```bash
python3 -m unittest dev.tests.test_xiaozhi_worklog -v
python3 /Users/lh/.codex/skills/.system/skill-creator/scripts/quick_validate.py .
```
