"""Profile and plan workflows with explicit confirmation and history."""

from copy import deepcopy
from datetime import date
import uuid

from .care import daily as calculate_daily
from .models import InputError, SCHEMA_VERSION, merge_profile, new_profile
from .storage import Store, StorageError, now_iso


def _event(kind, details):
    return {"at": now_iso(), "type": kind, "details": details}


def create_profile(store, fields):
    profile = new_profile(fields)
    record = {
        "schema_version": SCHEMA_VERSION,
        "profile_revision": 1,
        "profile": profile,
        "active_plan_id": None,
        "plans": [], "proposals": [],
        "events": [_event("profile_created", {"revision": 1})],
    }
    store.save(record, create=True)
    return {"profile": profile, "profile_revision": 1}


def update_profile(store, dog_id, patch):
    record = store.get(dog_id)
    old_revision = record["profile_revision"]
    record["profile"] = merge_profile(record["profile"], patch)
    record["profile_revision"] += 1
    record["events"].append(_event("profile_updated", {"revision": record["profile_revision"], "patch": patch}))
    store.save(record, expected_revision=old_revision)
    return {"profile": record["profile"], "profile_revision": record["profile_revision"],
            "active_plan_needs_review": record["active_plan_id"] is not None}


def active_plan(record):
    for plan in record["plans"]:
        if plan["id"] == record["active_plan_id"]:
            return plan
    return None


def daily_care(store, dog_id, on_date=None):
    record = store.get(dog_id)
    result = calculate_daily(record["profile"], on_date)
    plan = active_plan(record)
    if plan:
        result["active_plan_id"] = plan["id"]
        result["plan_status"] = (
            ("active" if plan.get("status") == "complete" else "active_limited")
            if plan["profile_revision"] == record["profile_revision"]
            else "stale_profile_changed"
        )
        if result["plan_status"] == "active" and plan["care_snapshot"].get("life_stage_assessment") != result.get("life_stage_assessment"):
            result["plan_status"] = "needs_life_stage_review"
        if result["plan_status"] != "active":
            result["safety"] += " 当前有效计划需复核，不应照搬旧数量。"
    else:
        result["active_plan_id"] = None
        result["plan_status"] = "no_confirmed_plan"
    return result


def _diff(old, new, prefix=""):
    changes = []
    for key, value in new.items():
        path = prefix + key
        previous = old.get(key)
        if isinstance(value, dict) and isinstance(previous, dict):
            changes.extend(_diff(previous, value, path + "."))
        elif value != previous:
            changes.append({"field": path, "before": previous, "after": value})
    return changes


def propose_plan(store, dog_id, patch):
    record = store.get(dog_id)
    candidate = merge_profile(record["profile"], patch)
    care = calculate_daily(candidate)
    proposal = {
        "id": str(uuid.uuid4()),
        "created_at": now_iso(),
        "base_revision": record["profile_revision"],
        "patch": patch,
        "candidate_profile": candidate,
        "candidate_daily": care,
        "changes": _diff(record["profile"], candidate),
        "status": "pending",
    }
    current = active_plan(record)
    proposal["before_feeding"] = (
        current["care_snapshot"].get("feeding")
        if current else calculate_daily(record["profile"]).get("feeding")
    )
    proposal["after_feeding"] = care.get("feeding")
    record["proposals"].append(proposal)
    record["events"].append(_event("plan_proposed", {"proposal_id": proposal["id"]}))
    store.save(record, expected_revision=record["profile_revision"])
    return proposal


def confirm_plan(store, dog_id, proposal_id):
    record = store.get(dog_id)
    proposal = next((p for p in record["proposals"] if p["id"] == proposal_id), None)
    if proposal is None:
        raise InputError("找不到提案")
    if proposal["status"] != "pending":
        raise InputError("提案已经处理")
    if proposal["base_revision"] != record["profile_revision"]:
        raise InputError("提案基于旧档案；请重新生成")
    candidate = merge_profile(record["profile"], proposal["patch"])
    changes = _diff(record["profile"], candidate)
    if candidate != proposal["candidate_profile"] or changes != proposal["changes"]:
        raise InputError("提案内容与变更记录不一致；请重新生成")
    fresh_care = calculate_daily(candidate)
    if fresh_care != proposal["candidate_daily"] or fresh_care.get("feeding") != proposal["after_feeding"]:
        raise InputError("提案的日期或照护计算已变化；请重新生成后再确认")
    old_revision = record["profile_revision"]
    record["profile"] = candidate
    feeding_status = fresh_care["feeding"]["status"]
    if fresh_care["status"] == "urgent_review" or feeding_status == "invalid":
        raise InputError("提案含紧急健康风险或无效热量分配，不能确认为有效计划")
    record["profile_revision"] += 1
    plan = {
        "id": str(uuid.uuid4()), "created_at": now_iso(),
        "status": "complete" if feeding_status in ("calculated_from_vet_target", "estimated_starting_point") else "limited",
        "profile_revision": record["profile_revision"],
        "profile_snapshot": deepcopy(record["profile"]),
        "care_snapshot": fresh_care,
        "confirmed_from_proposal_id": proposal_id,
        "restored_from_plan_id": None,
    }
    record["plans"].append(plan)
    record["active_plan_id"] = plan["id"]
    proposal["status"] = "confirmed"
    for other in record["proposals"]:
        if other["status"] == "pending":
            other["status"] = "obsolete"
    record["events"].append(_event("plan_confirmed", {"plan_id": plan["id"], "proposal_id": proposal_id}))
    store.save(record, expected_revision=old_revision)
    return {"active_plan": plan, "profile_revision": record["profile_revision"]}


def plan_history(store, dog_id):
    record = store.get(dog_id)
    return {"active_plan_id": record["active_plan_id"], "plans": record["plans"],
            "proposals": record["proposals"], "events": record["events"]}


def restore_plan(store, dog_id, plan_id):
    record = store.get(dog_id)
    source = next((p for p in record["plans"] if p["id"] == plan_id), None)
    if source is None:
        raise InputError("找不到历史计划")
    previous = source["profile_snapshot"]
    current = record["profile"]
    protected = ("birth", "weight", "bcs", "medical", "prevention")
    if any(previous[key] != current[key] for key in protected):
        raise InputError("历史版本的年龄、体况或医疗/预防资料已变化；请基于当前档案重新提案，不能直接回滚")
    if (previous["diet"]["vet_target_kcal_per_day"] != current["diet"]["vet_target_kcal_per_day"]
            or previous["diet"]["vet_target_reference"] != current["diet"]["vet_target_reference"]):
        raise InputError("兽医热量目标已变化；请基于当前医嘱重新提案")
    old_revision = record["profile_revision"]
    record["profile"] = deepcopy(source["profile_snapshot"])
    record["profile_revision"] += 1
    fresh_care = calculate_daily(record["profile"])
    feeding_status = fresh_care["feeding"]["status"]
    if fresh_care["status"] == "urgent_review" or feeding_status == "invalid":
        raise InputError("历史版本在当前条件下含紧急健康风险或无效热量分配，不能恢复为有效计划")
    restored = {
        "id": str(uuid.uuid4()), "created_at": now_iso(),
        "status": "complete" if feeding_status in ("calculated_from_vet_target", "estimated_starting_point") else "limited",
        "profile_revision": record["profile_revision"],
        "profile_snapshot": deepcopy(record["profile"]),
        "care_snapshot": fresh_care,
        "confirmed_from_proposal_id": None,
        "restored_from_plan_id": plan_id,
    }
    record["plans"].append(restored)
    record["active_plan_id"] = restored["id"]
    for proposal in record["proposals"]:
        if proposal["status"] == "pending":
            proposal["status"] = "obsolete"
    record["events"].append(_event("plan_restored", {"new_plan_id": restored["id"], "from_plan_id": plan_id}))
    store.save(record, expected_revision=old_revision)
    return {"active_plan": restored, "profile_revision": record["profile_revision"]}
