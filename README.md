# xiaozhi-worklog

`xiaozhi-worklog` 是一个可直接放入 `~/.codex/skills` 的 Codex skills 仓库。

## 安装

将仓库直接克隆到本地 skills 目录：

```bash
git clone git@github.com:lhstock/xiaozhi-worklog.git ~/.codex/skills/xiaozhi-worklog
```

安装完成后，仓库根目录就是技能目录，入口文件位于：

```text
~/.codex/skills/xiaozhi-worklog/SKILL.md
```

## 仓库结构

- `SKILL.md`: 技能入口
- `settings.json` / `report-mapping.json`: 配置
- `scripts/` / `agents/`: 技能运行文件
- `dev/tests/`: 开发验证用例
- `dev/docs/`: 开发过程文档

## 设计说明

- 静默同步不再备份每周 `records/worklog.jsonl`
- 同步只维护轻量索引：按周记录 `项目绝对路径 -> [{provider, session_id}]`
- 支持多会话源 provider，当前包含 `codex` 和 `claude-code`
- 生成周报时，以个人 git 提交和未提交改动为主，再回查原始 session 补充语义
- 项目归属只在周报阶段依据 `report-mapping.json` 做精确 `pwd` 匹配
- `小志` 是统一 skill 入口，不只用于 `提供周报`
- 支持一次性本地工作台页面，用于编辑、复制、重新生成草稿和确认归档
- 周报草稿会按项目与模块级事项做中文归纳，偏“领导周报版本”表达
- 周报文风按成果聚合，不按时间线或原始会话逐条转述

## Provider 配置

`settings.json` 通过 `session_providers` 配置会话源，例如：

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

说明：

- `name` 是持久化到索引里的 provider 标识
- `type` 决定解析器
- `root` 是 transcript 根目录
- 旧配置里的 `session_root` 仍兼容，等价于单一 `codex` provider

## 常用命令

```bash
python3 scripts/xiaozhi_worklog.py --settings settings.json info
python3 scripts/xiaozhi_worklog.py --settings settings.json index-status --mapping report-mapping.json
python3 scripts/xiaozhi_worklog.py --settings settings.json prepare-report --mapping report-mapping.json
python3 scripts/xiaozhi_worklog.py --settings settings.json open-workbench --mapping report-mapping.json
```

## 周报工作台

`小志 周报` / `小志 提供周报` 的推荐形态是一次性本地页面，而不是常驻服务。

工作流：

1. 启动一次性工作台
2. 在页面中查看并编辑周报草稿
3. 通过“复制”快速带走内容，或直接“确认归档”
4. 归档完成后，本次工作台服务自动结束

默认地址：

```text
http://127.0.0.1:5555/
```

页面能力：

- 编辑周报草稿
- 重新生成中文汇总稿
- 复制草稿
- 确认归档
- 页面仅保留草稿编辑与确认区域，不展示右侧信息面板

当前周报生成规则：

- 仅保留个人 git 提交
- 会话与 git 重叠时以 git 为主
- 会话中的额外有效信息可补充到周报
- 输出按“项目 + 模块级事项”归纳，不写具体技术点、commit 或会话原文
- 每个项目控制在 3-7 条以内，优先合并重复问题域和交付目标
- 使用“完成 / 优化 / 推进 / 完善”等结果导向动词
- 删除重复表达，避免流水线描述，整体文风偏管理视角并弱化技术细节

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
