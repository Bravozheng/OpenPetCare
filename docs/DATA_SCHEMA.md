# 本地数据结构 v1

当前可执行结构以 [`openpetcare/models.py`](../openpetcare/models.py)、[`openpetcare/service.py`](../openpetcare/service.py) 和 [`openpetcare/storage.py`](../openpetcare/storage.py) 为准。本文件描述磁盘格式与约束，便于后续兼容性维护。

## 存放位置与文件封装

每只狗一份 `dogs/<UUID>.json`，位于系统持久应用数据目录，和 Skill 安装目录分离：macOS 为 `~/Library/Application Support/OpenPetCare`，Windows 为 `%APPDATA%/OpenPetCare`，Linux 为 `${XDG_DATA_HOME:-~/.local/share}/openpetcare`。仅测试或用户明确指定时使用 `OPENPETCARE_DATA_DIR` 覆盖。

磁盘文件为 UTF-8 JSON：

```json
{
  "payload": {"schema_version": 1, "profile_revision": 1, "profile": {}, "active_plan_id": null, "plans": [], "proposals": [], "events": []},
  "sha256": "该 payload 规范化 JSON 的 SHA-256 十六进制摘要"
}
```

校验和用于发现意外损坏，不提供加密、真实性认证或访问控制。写入使用同目录临时文件、`fsync` 与原子替换；应用数据和备份可能包含健康及私人信息，应仅由用户控制，并避免提交到代码仓库。

## `profile`：犬只当前资料

`id` 为系统生成的 UUID，`name` 为非空昵称。未知值统一为 JSON `null`；数组的 `[]` 表示主人明确报告“无”，与未知不同。初次建档不预填演示犬只。完整字段树由 `PROFILE_TEMPLATE` 定义：

| 分组 | 字段 |
| --- | --- |
| `breed` | `reported_name`、`standard_name`、`alias_zh`、`alias_en`、`reference`、`mixed` |
| `birth` | `date`，或 `estimated_age_months` 加 `estimated_as_of` |
| `weight`、`bcs` | `kg`、`measured_at`；`score_9`、`recorded_at` |
| 身份 | `expected_adult_size`、`sex`、`neutered` |
| `diet` | `type`、`food_name`、`life_stage_on_label`、`complete_and_balanced_on_label`、`kcal_per_kg`、`calorie_source`、`meals_per_day`、`meal_times`、`treat_kcal_per_day`、`current_food_g_per_day`、`vet_target_kcal_per_day`、`vet_target_reference` |
| `activity` | `habit`、`walks_per_day`、`minutes_per_walk`、`walk_distance_km_per_day`、`living_conditions` |
| `medical` | `allergies`、`history`、`vet_restrictions`、`red_flags` |
| `prevention` | `vaccinations`、`parasite_prevention`、`confirmed_appointments` |
| `constraints` | `caregiver_schedule`、`budget` |

`birth.date` 与估计年龄二选一；估计年龄必须同时记录参考日期。标准犬种名必须附参考来源；无法核实时只填主人报告名。兽医热量目标必须带医嘱来源。`complete_and_balanced_on_label` 只记录包装或可靠资料是否明确标注完整均衡，不由品牌名推断；未知为 `null`。`life_stage_on_label` 使用 `growth`、`adult`、`all_life_stages`、`senior`。热量密度统一存为 kcal/kg，若包装使用 kcal/杯等单位，先取得可靠的克数换算，不能猜测。BCS 用 1–9 分制；档案更新采用字段补丁并递增 `profile_revision`。

通用健康成年犬热量起始估算要求：当日年龄 24–84 月（程序保守适用边界，并非权威生命阶段定义）、BCS 4–5/9、绝育状态已知、`medical.history`、`medical.vet_restrictions` 和 `medical.red_flags` 都是主人明确确认的 `[]`，主粮标签生命阶段为 `adult` 或 `all_life_stages`，`complete_and_balanced_on_label` 为 `true`，且体重、主粮名、包装热量及来源、餐次、零食 kcal 均已填写。若有兽医确认的目标，可用于其他年龄，但仍须满足其余必需输入与安全检查；危险信号出现时直接暂缓常规计算。

昵称采用显示字符簇计数，ASCII 簇计 1，其他簇计 2，总计最多 24；组合 emoji 作为一个簇。实现对常见组合形式做处理，完整 Unicode 分段能力见测试边界。

## 计划、提案与事件

- `active_plan_id` 指向 `plans` 中当前有效版本的 UUID，尚未确认时为 `null`。
- `plans[]` 含 `id`、`created_at`、`profile_revision`、`profile_snapshot`、`care_snapshot`、`confirmed_from_proposal_id`、`restored_from_plan_id`。确认或恢复都生成新版本，不覆盖旧版本。
- `proposals[]` 含 `id`、`created_at`、`base_revision`、`patch`、`candidate_profile`、`candidate_daily`、`changes`（字段前后差异）、`before_feeding`、`after_feeding`、`status`。状态为 `pending`、`confirmed` 或 `obsolete`；候选数据在确认前不改变当前档案和有效计划。
- `events[]` 每项含 UTC `at`、`type`、`details`。事件覆盖建档、直接档案更新、提案、确认及恢复；事件详情和提案补丁都可能包含敏感资料。

提案的 `base_revision` 必须与当前档案版本相同才能确认。直接改动档案会使旧有效计划标记为需复核；日期导致生命阶段变化时也应重算。历史恢复会创建新有效版本并保留来源计划 ID。若历史快照与当前档案的出生/年龄、体重、BCS、医疗、预防资料或兽医热量目标不同，程序拒绝直接回滚，须基于当前资料重新提案，以免抹掉后来的安全信息。

## 备份、导出、导入与版本

备份与导出采用同样的校验封装，其 `payload` 为 `{"archive_version":1,"created_at":UTC时间,"records":[...]}`。内置备份写入应用数据目录的 `backups/`；外部导出由用户指定路径。导入应先检查校验和、版本、全体档案结构与重复 ID；同 ID 冲突须显式允许替换。

`schema_version` 和 `archive_version` 是迁移锚点。v0.1 首次定义版本 1，没有既存旧版数据可迁移；遇到未知未来版本必须保留原文件并拒绝静默降级。新增格式时应实现显式迁移、保留原备份并添加跨版本测试，不能靠直接改 JSON 字段。当前导入多犬备份若写入中途发生系统故障，可能需要从原备份重新恢复；该操作不等同数据库事务。
