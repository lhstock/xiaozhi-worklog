# xiaozhi-worklog

`xiaozhi-worklog` 是一个可直接放入 `~/.codex/skills` 的 Codex skills 仓库。

## 安装

将仓库直接克隆到本地 skills 目录：

```bash
git clone git@github.com:lhstock/xiaozhi-worklog.git ~/.codex/skills/xiaozhi-worklog
```

安装完成后，技能目录为：

```text
~/.codex/skills/xiaozhi-worklog
```

## 仓库结构

- `xiaozhi-worklog/`: 实际技能目录，包含 `SKILL.md`、脚本和配置
- `tests/`: 本地验证用例
- `docs/`: 过程文档

## 更新

```bash
cd ~/.codex/skills/xiaozhi-worklog
git pull
```

## 开发验证

```bash
python3 -m unittest tests.test_xiaozhi_worklog -v
python3 /Users/lh/.codex/skills/.system/skill-creator/scripts/quick_validate.py xiaozhi-worklog
```
