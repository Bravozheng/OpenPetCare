# OpenPetCare

OpenPetCare v0.1 是免费开源的犬只照护 Agent Skill。它让支持本地 Skill 执行的 AI 客户端调用确定性 Python 工具，保存犬只档案，生成有条件的每日饮食与活动建议，并通过提案、明确确认和历史版本管理变更。它不是兽医诊断工具，也不提供后台推送、账号或云同步。

**代码免费开源；你使用的 Codex、Claude Code 或其他第三方 AI 服务可能收费或有额度限制。** 本项目不会为你支付宿主服务费用。

## 运行要求

- Python 3.9 或更新版本；核心工具只使用标准库。
- 可在本机运行命令、保留本机文件的兼容 AI 客户端。云端临时沙箱的跨会话持久化未经验证。
- 首版仅支持犬。资料不足时会返回缺失项；不会凭体重单独编造主粮克数。

## 在 Codex 安装

在本仓库目录运行：

```bash
python3 scripts/install.py codex
```

这会把最小 Skill 包复制到 `~/.agents/skills/openpetcare`。安装后重新打开本地 Codex 会话，输入 `$openpetcare` 或在 `/skills` 中选择 OpenPetCare。也可在某个项目内安装：

```bash
python3 scripts/install.py codex --scope project --project /你的/项目目录
```

更新同一个普通目录安装时使用 `--replace`；安装脚本只替换 Skill 代码，不触碰犬只数据。若目标已经是符号链接，脚本会拒绝覆盖。

可先验证安装包中的工具：

```bash
python3 "$HOME/.agents/skills/openpetcare/scripts/opc.py" --help
python3 "$HOME/.agents/skills/openpetcare/scripts/opc.py" where
```

本机已验证 Codex CLI 能发现放在技能目录的 `SKILL.md`；**尚未把一次完整的自然语言建档、换粮和重启会话流程标为已通过宿主验收**。首次使用请观察 AI 是否确实调用了 `scripts/opc.py`，并检查命令输出。

## 亲自体验

在本地 Codex 中按顺序说：

1. “使用 `$openpetcare`，帮我建立一只狗的档案。”提供真实资料；不知道的字段直接说不知道。
2. “告诉我它今天应该怎么吃、怎么运动。”缺少包装热量、体况等资料时，Skill 应列出缺口；不会给主粮克数。
3. “我最近换了狗粮，需要调整吗？”提供新粮包装上的热量、完整均衡声明和适用生命阶段。AI 应先生成**待确认提案**并说明前后变化。
4. 检查提案后明确说“确认更新这个方案”。AI 才能执行确认并保存有效计划。
5. 关闭并重新打开本地客户端，再询问档案、今日照护和计划历史，核对仍可读取。

如需不依赖 AI 地检查工具，可运行 `python3 scripts/opc.py --help`。例如 `profile create --json '{"name":"小狗"}'` 仅建空白档案，其他未知字段会保存为 `null`。`profile list` 查看 ID，`daily --dog <UUID>` 查看程序的结构化结果。命令都可从已安装包的 `scripts/opc.py` 运行。

## 数据与隐私

真实档案不在仓库或 Skill 文件夹。默认位置：macOS `~/Library/Application Support/OpenPetCare`，Windows `%APPDATA%/OpenPetCare`，Linux `${XDG_DATA_HOME:-~/.local/share}/openpetcare`。`where` 命令可查看本机实际路径。每犬一份版本化、带 SHA-256 校验和的 JSON；写入时先写临时文件再原子替换。校验和能发现意外损坏，**不加密**。

`data backup` 在应用数据目录创建备份；`data export --path <路径>` 导出；`data import --path <路径>` 导入。已有同 ID 档案需显式加 `--replace`，此前应先备份当前数据。备份可能包含宠物健康及主人的时间、预算信息，不要提交到 Git 或公开传播。宿主 AI 在处理自然语言时可能接收相关档案内容；没有 OpenPetCare 云数据库不等于资料绝不会离开设备。

## 科学与安全边界

在确认为健康、成年、BCS 4–5/9、主粮适龄且完整均衡等条件下，工具可依据 Merck 的维护能量公式提供**起始估算**，并与当前喂量比较；个体实际需求可能明显不同。若有兽医确认的日热量目标，会优先用该目标换算，但仍需确认食品和零食信息。其他情况不给精确克数。饮水始终应有清洁水可用；当前版本不给单一的毫升配额。运动建议不会编造固定里程或时长；有危险信号或兽医限制时按 [安全政策](docs/SAFETY_POLICY.md)处理。依据和适用地区见 [科学资料](docs/SCIENCE_SOURCES.md)。

## Claude Code 与其他宿主

按 [Claude Code 官方 Skills 文档](https://code.claude.com/docs/en/skills)，可运行 `python3 scripts/install.py claude` 安装到 `~/.claude/skills/openpetcare`，并用 `/openpetcare` 调用。本机已确认安装了 Claude Code，但尚未运行可能产生服务费用的完整 AI 调用；其实际 Skill 发现、Python 执行与跨会话持久化仍待人工验证。其他宿主需要支持 `SKILL.md`、本地命令和持久文件系统；当前未逐一验证。

## 项目文档与开发

从 [产品需求](docs/PRODUCT_SPEC.md)、[决策](docs/DECISIONS.md)、[架构](docs/ARCHITECTURE.md)、[数据结构](docs/DATA_SCHEMA.md)、[测试计划](docs/TEST_PLAN.md)和 [路线图](docs/ROADMAP.md)开始阅读。开发规则见 [AGENTS.md](AGENTS.md)。运行测试：

```bash
python3 -m unittest discover -s tests -v
```

许可证：[MIT](LICENSE)。引用的机构资料仍归原作者所有；仓库只列链接和简述，不转载受版权保护的图表或大段原文。
