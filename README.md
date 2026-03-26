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
