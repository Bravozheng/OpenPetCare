# OpenPetCare 开发规则

本文件供后续 Codex 和其他代码代理持续遵守。唯一项目根目录是 `/Users/zhengwang/Documents/Codex/OpenPetCare`。当前产品冻结基线见 [`docs/PRODUCT_SPEC.md`](docs/PRODUCT_SPEC.md)。

## 工作原则

1. 编码前明确输入、输出、关键假设和可验证的成功标准；真正歧义才询问，不默默编造科学结论。
2. 用最少的代码解决当前需求，不为尚未开发的云同步、UI、其他物种添加抽象。
3. 只改与任务直接相关的行；清理自身产生的孤儿代码，不顺手重构相邻模块。
4. 先写能复现问题的测试，再修复；运行相关测试并报告实际结果，不声称未经执行的宿主验收或科学核验。
5. 健康风险和资料不足时保守处理。不得诊断、开药、覆盖兽医医嘱或凭体重猜喂食克数。
6. 用户真实档案只能进入系统应用数据目录，不能提交到 Git、示例或测试日志。测试必须使用临时目录。

## 长期产品文档同步规则（2026-10-30 确认）

`docs/PRODUCT_SPEC.md`、`docs/DECISIONS.md`、`docs/ARCHITECTURE.md`、`docs/ROADMAP.md` 和 `docs/CHANGELOG.md` 是 OpenPetCare 的长期开发依据。每次开发前先读取与任务相关的要求及最新变更记录，不得擅自改变已确认的产品方向；科学、安全和数据变更还要读取对应专题文档。

ChatGPT 中的讨论**不会自动同步**到本仓库。只有项目负责人明确提交为已确认的「OpenPetCare 产品变更单」或其他明确确认的产品决定，才可写入正式需求与决策。未确认的讨论、模型推测和外部材料只能作为待核查信息，不能覆盖现有基线。

收到产品变更单时：

1. 核对确认状态、日期、影响范围和可验证的验收标准；缺少关键内容时指出缺口，不自行补成已确认决策。
2. 先比对现有需求、决策、架构、路线与变更日志，列出与旧版本的差异和冲突；最新**明确确认**的决策优先，保留旧决定的历史记录。
3. 只更新受影响的正式文档，在 `docs/CHANGELOG.md` 追加记录，标注日期、来源、影响范围、旧版差异、验收标准、代码与测试影响。不要改写历史条目来掩盖变化。
4. 检查已实现代码是否受影响；需要实施时精准修改并更新相关测试。尚未实施的要求标明状态，不把文档更新写成代码已通过验收。
5. 用 Git 记录本次修改。不得未经项目负责人确认删除重要历史内容，不能把真实犬只档案或备份加入提交。

## UI 任务的附加规则

目前 v0.1 不开发 UI。若未来明确提出 UI、UX、网站、App、小程序、PWA 或其他数字界面任务，先研究目标用户和场景，再探索有实质差异的设计方向；避免模板化卡片堆叠和无意义装饰。建立统一的字体、颜色、间距、组件与状态，保留已确认的品牌素材和设计。正式设计优先可编辑、可实施的工具，开发后用真实视口截图验证；只修改用户指定范围。不得因存在设计工具就扩大当前产品范围。

## 文档索引

- [`README.md`](README.md)：安装、使用、费用和限制。
- [`docs/PRODUCT_SPEC.md`](docs/PRODUCT_SPEC.md)：产品范围与验收路径。
- [`docs/DECISIONS.md`](docs/DECISIONS.md)：关键决策及冲突记录。
- [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md)：模块和运行边界。
- [`docs/DATA_SCHEMA.md`](docs/DATA_SCHEMA.md)：持久化数据结构与迁移。
- [`docs/SCIENCE_SOURCES.md`](docs/SCIENCE_SOURCES.md)：核验过的来源与适用条件。
- [`docs/INTAKE_GUIDE.md`](docs/INTAKE_GUIDE.md)：中文 BCS 自评和狗粮官方资料补全流程。
- [`docs/SAFETY_POLICY.md`](docs/SAFETY_POLICY.md)：医疗风险分流。
- [`docs/TEST_PLAN.md`](docs/TEST_PLAN.md)：自动测试和人工验收。
- [`docs/ROADMAP.md`](docs/ROADMAP.md)：首发及后续计划。
- [`docs/CHANGELOG.md`](docs/CHANGELOG.md)：正式产品变更与冲突记录。
