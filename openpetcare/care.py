"""Deterministic daily care calculations; uncertainty is part of the output."""

from datetime import date
import math

from .models import InputError


def _age_months(profile, on_date):
    birth = profile["birth"]
    if birth["date"]:
        born = date.fromisoformat(birth["date"])
        if born > on_date:
            return None
        return (on_date.year - born.year) * 12 + on_date.month - born.month - (on_date.day < born.day)
    if birth["estimated_age_months"] is not None:
        observed = date.fromisoformat(birth["estimated_as_of"])
        if observed > on_date:
            return None
        return round(birth["estimated_age_months"] + (on_date - observed).days / 30.4375, 1)
    return None


def _life_stage(age_months):
    if age_months is None:
        return "unknown"
    if age_months < 12:
        return "growth"
    if age_months < 24:
        return "transition_review"
    if age_months <= 84:
        return "adult_estimate_eligible_age"
    return "senior_review"


def _round_five(value):
    return int(math.floor(value / 5 + 0.5) * 5)


def _feeding(profile, stage):
    diet = profile["diet"]
    missing = []
    if profile["weight"]["kg"] is None:
        missing.append("weight.kg")
    if profile["weight"]["measured_at"] is None:
        missing.append("weight.measured_at")
    if profile["bcs"]["score_9"] is None:
        missing.append("bcs.score_9")
    for key in ("food_name", "life_stage_on_label", "kcal_per_kg", "calorie_source", "meals_per_day", "treat_kcal_per_day"):
        if diet[key] is None:
            missing.append("diet." + key)
    if stage == "unknown":
        missing.append("birth.date 或 birth.estimated_age_months + birth.estimated_as_of")
    if missing:
        return {"status": "insufficient", "missing": missing, "food_g_per_day": None,
                "basis": None, "reported_current_food_g_per_day": diet["current_food_g_per_day"]}
    target = diet["vet_target_kcal_per_day"]
    basis_kind = "vet_target"
    if target is None:
        # Merck's maintenance multipliers are starting points for healthy adult dogs.
        # Unknown health status is not treated as a healthy status.
        medical = profile["medical"]
        eligibility = []
        if stage != "adult_estimate_eligible_age":
            eligibility.append("年龄不在通用成年犬起始估算范围（24–84 月）；请提供兽医确认的日热量目标")
        if profile["bcs"]["score_9"] not in (4, 5):
            eligibility.append("BCS 不在 4–5/9；请由兽医评估热量目标")
        if profile["neutered"] is None:
            eligibility.append("neutered")
        if any(medical[key] != [] for key in ("history", "vet_restrictions", "red_flags")):
            eligibility.append("medical.history、vet_restrictions、red_flags 须明确无问题；有病史或限制请用兽医目标")
        if diet["life_stage_on_label"] not in ("adult", "all_life_stages"):
            eligibility.append("主粮须标注适用于成年期")
        if diet["complete_and_balanced_on_label"] is not True:
            eligibility.append("diet.complete_and_balanced_on_label 须从包装或可靠资料确认")
        if eligibility:
            return {"status": "insufficient_for_estimate", "missing": eligibility + ["diet.vet_target_kcal_per_day（可替代通用估算）"],
                    "food_g_per_day": None, "reported_current_food_g_per_day": diet["current_food_g_per_day"]}
        rer = 70 * profile["weight"]["kg"] ** 0.75
        multiplier = 1.6 if profile["neutered"] else 1.8
        target = rer * multiplier
        basis_kind = "adult_starting_estimate"
    treats = diet["treat_kcal_per_day"]
    if treats >= target:
        return {"status": "invalid", "reason": "零食热量达到或超过总热量目标", "food_g_per_day": None}
    if treats > target * 0.1:
        return {"status": "review_needed", "reason": "记录的零食热量超过总热量目标的 10%；先与兽医确认零食与主粮分配", "food_g_per_day": None}
    if profile["medical"]["vet_restrictions"]:
        return {"status": "review_needed", "reason": "有兽医限制，需确认当前热量目标与食物仍适用", "food_g_per_day": None}
    if diet["complete_and_balanced_on_label"] is not True:
        return {"status": "review_needed", "reason": "未确认主粮完整均衡；不能仅凭热量换算推荐克数", "food_g_per_day": None}
    label = diet["life_stage_on_label"]
    suitable = (
        label == "all_life_stages"
        or stage == "growth" and label == "growth"
        or stage == "adult_estimate_eligible_age" and label == "adult"
        or stage == "senior_review" and label in ("adult", "senior")
    )
    if not suitable:
        return {"status": "review_needed", "reason": "主粮包装生命阶段与当前年龄判断未能确认匹配；需兽医核对", "food_g_per_day": None}
    grams_exact = (target - treats) * 1000 / diet["kcal_per_kg"]
    grams = _round_five(grams_exact)
    if grams <= 0:
        return {"status": "review_needed", "reason": "计算出的主粮数量过小，需人工复核", "food_g_per_day": None}
    count = diet["meals_per_day"]
    times = diet["meal_times"] or ["请按照护人时间均匀安排"] * count
    base, extra = divmod(grams, count)
    meals = [{"time": times[i], "food_g_approx": base + (1 if i < extra else 0)} for i in range(count)]
    return {
        "status": "calculated_from_vet_target" if basis_kind == "vet_target" else "estimated_starting_point",
        "basis": ("兽医确认的每日总热量" if basis_kind == "vet_target" else "Merck 健康成年犬维护能量起始估算：70×体重kg^0.75×绝育状态系数")
                 + "，减去零食热量，再按包装热量密度换算；约取至 5 g",
        "target_kcal_per_day": round(target),
        "treat_kcal_per_day": treats,
        "treat_limit_kcal_per_day": round(target * 0.1, 1),
        "food_g_per_day": grams,
        "meals": meals,
        "reported_current_food_g_per_day": diet["current_food_g_per_day"],
        "difference_from_reported_current_g": (
            grams - diet["current_food_g_per_day"] if diet["current_food_g_per_day"] is not None else None),
        "weight_measured_at": profile["weight"]["measured_at"],
        "do_not_change_existing_ration_automatically": basis_kind == "adult_starting_estimate",
        "limitations": ["通用公式仅为起点，个体实际能量需求可与估算明显不同；随体重与 BCS 变化复核",
                        "与当前喂量比较；若差异明显，先核对称重、热量和兽医意见，不直接大幅改变",
                        "若体重记录已不能反映当前体况，先重新称重；若有疾病或兽医医嘱，以兽医要求为准"],
        "sources": [
            "https://www.merckvetmanual.com/multimedia/table/daily-maintenance-energy-requirements-for-dogs-and-cats",
            "https://vmc.vet.osu.edu/services/companion-animal-nutrition-support-service",
            "https://wsava.org/wp-content/uploads/2020/01/Frequently-Asked-Questions-and-Myths.pdf",
        ],
    }


def _activity(profile, stage):
    medical = profile["medical"]
    if medical["red_flags"]:
        return {"status": "urgent_hold", "advice": "先处理可能紧急的健康问题，暂停常规运动建议"}
    if medical["vet_restrictions"]:
        return {"status": "vet_restriction", "advice": "遵守已记录的兽医活动限制，不自行增加次数或时长",
                "restrictions": medical["vet_restrictions"]}
    if medical["history"] is None or medical["history"]:
        return {"status": "health_review", "advice": "健康史未明确排除活动限制；先核对病史和兽医意见，不沿用固定运动时长"}
    activity = profile["activity"]
    if activity["walks_per_day"] is None or activity["minutes_per_walk"] is None:
        return {"status": "needs_baseline", "advice": "提供当前遛狗次数和每次时长后，再讨论可执行的日程；可安排温和嗅闻与互动"}
    result = {
        "status": "continue_reported_baseline",
        "walks_per_day": activity["walks_per_day"],
        "minutes_per_walk": activity["minutes_per_walk"],
        "advice": "暂以主人已报告的日常活动为讨论起点，留意体况、意愿和疲劳；增加嗅闻与互动。此数值不是权威运动处方。",
    }
    if activity["walk_distance_km_per_day"] is not None:
        result["track_400m_laps_equivalent"] = round(activity["walk_distance_km_per_day"] / 0.4, 1)
        result["distance_note"] = "仅把主人提供的距离换算成 400 米跑道圈数，不推算步速或建议里程"
    if stage == "growth":
        result["caution"] = "幼犬活动应按个体发育与兽医意见调整，避免把当前时长视为标准"
    return result


def daily(profile, on_date=None):
    if on_date is None:
        on_date = date.today()
    elif isinstance(on_date, str):
        try:
            on_date = date.fromisoformat(on_date)
        except ValueError:
            raise InputError("日期必须是 YYYY-MM-DD")
    stage_months = _age_months(profile, on_date)
    stage = _life_stage(stage_months)
    risk = profile["medical"]["red_flags"]
    if risk:
        return {
            "date": on_date.isoformat(), "dog_id": profile["id"], "name": profile["name"],
            "status": "urgent_review", "red_flags": risk,
            "safety": "出现可能紧急的症状时，应立即联系兽医或急诊；本工具不能诊断或给药。",
            "feeding": {"status": "withheld_for_urgent_review", "food_g_per_day": None},
            "activity": _activity(profile, stage),
        }
    return {
        "date": on_date.isoformat(), "dog_id": profile["id"], "name": profile["name"],
        "status": "routine",
        "age_months": stage_months, "age_is_estimated": profile["birth"]["estimated_age_months"] is not None,
        "life_stage_assessment": stage,
        "life_stage_note": "犬只成熟和老年阶段因体型及个体而异；24–84 月龄仅作为通用成年犬估算的保守程序边界，并非权威生命阶段定义。",
        "feeding": _feeding(profile, stage),
        "water": {"numeric_ml_per_day": None,
                  "advice": "持续提供清洁饮水；饮水量受饮食含水量、天气、活动与疾病影响，当前不据体重给单一目标。"},
        "activity": _activity(profile, stage),
        "care": ["观察体重与 BCS 的变化", "按已经确认的免疫、驱虫和兽医日程安排护理"],
        "confirmed_appointments": profile["prevention"]["confirmed_appointments"],
        "safety": "一般照护参考，不替代兽医诊断或已给出的医嘱；无后台自动提醒。",
    }
