"""Versioned dog profile shape and input validation."""

from copy import deepcopy
from datetime import date
import math
import unicodedata
import uuid

SCHEMA_VERSION = 1

# null means unknown. An empty list means the owner explicitly reported none.
PROFILE_TEMPLATE = {
    "id": None,
    "name": None,
    "breed": {
        "reported_name": None,
        "standard_name": None,
        "alias_zh": None,
        "alias_en": None,
        "reference": None,
        "mixed": None,
    },
    "expected_adult_size": None,
    "birth": {"date": None, "estimated_age_months": None, "estimated_as_of": None},
    "weight": {"kg": None, "measured_at": None},
    "bcs": {"score_9": None, "recorded_at": None},
    "sex": None,
    "neutered": None,
    "diet": {
        "type": None,
        "food_name": None,
        "life_stage_on_label": None,
        "complete_and_balanced_on_label": None,
        "kcal_per_kg": None,
        "calorie_source": None,
        "meals_per_day": None,
        "meal_times": None,
        "treat_kcal_per_day": None,
        "current_food_g_per_day": None,
        "vet_target_kcal_per_day": None,
        "vet_target_reference": None,
    },
    "activity": {
        "habit": None,
        "walks_per_day": None,
        "minutes_per_walk": None,
        "walk_distance_km_per_day": None,
        "living_conditions": None,
    },
    "medical": {
        "allergies": None,
        "history": None,
        "vet_restrictions": None,
        "red_flags": None,
    },
    "prevention": {
        "vaccinations": None,
        "parasite_prevention": None,
        "confirmed_appointments": None,
    },
    "constraints": {"caregiver_schedule": None, "budget": None},
}

TEXT_FIELDS = {
    "name", "breed.reported_name", "breed.standard_name", "breed.alias_zh",
    "breed.alias_en", "breed.reference", "expected_adult_size", "sex",
    "diet.type", "diet.food_name", "diet.life_stage_on_label",
    "diet.calorie_source", "diet.vet_target_reference", "activity.habit",
    "activity.living_conditions", "constraints.caregiver_schedule",
    "constraints.budget",
}
DATE_FIELDS = {"birth.date", "birth.estimated_as_of", "weight.measured_at", "bcs.recorded_at"}
POSITIVE_FIELDS = {
    "weight.kg", "diet.kcal_per_kg", "diet.current_food_g_per_day",
    "diet.vet_target_kcal_per_day", "activity.minutes_per_walk",
    "activity.walk_distance_km_per_day",
}
NONNEGATIVE_FIELDS = {"diet.treat_kcal_per_day", "birth.estimated_age_months"}
INTEGER_FIELDS = {"bcs.score_9", "diet.meals_per_day", "activity.walks_per_day"}
LIST_TEXT_FIELDS = {
    "medical.allergies", "medical.history", "medical.vet_restrictions",
    "medical.red_flags", "prevention.vaccinations",
    "prevention.parasite_prevention", "prevention.confirmed_appointments",
    "diet.meal_times",
}


class InputError(ValueError):
    """Invalid user-supplied data, safe to display."""


def _graphemes(value):
    """Group common Unicode extended graphemes, including emoji ZWJ sequences.

    Python's standard library has no full UAX #29 segmenter. This accepts the
    common emoji forms used in names; the length guard is conservative for any
    unrecognized non-ASCII cluster.
    """
    clusters = []
    regional_run = 0
    for char in value:
        code = ord(char)
        regional = 0x1F1E6 <= code <= 0x1F1FF
        extend = (
            unicodedata.combining(char) != 0
            or char in ("\u200d", "\u20e3")
            or 0xFE00 <= code <= 0xFE0F
            or 0x1F3FB <= code <= 0x1F3FF
            or 0xE0020 <= code <= 0xE007F
        )
        join = bool(clusters and clusters[-1].endswith("\u200d"))
        pair_flag = regional and regional_run % 2 == 1
        if clusters and (extend or join or pair_flag):
            clusters[-1] += char
        else:
            clusters.append(char)
        regional_run = regional_run + 1 if regional else 0
    return clusters


def name_units(value):
    return sum(1 if all(ord(char) < 128 for char in cluster) else 2
               for cluster in _graphemes(value))


def merge_profile(base, patch):
    if not isinstance(patch, dict):
        raise InputError("资料必须是 JSON 对象")
    result = deepcopy(base)

    def merge(target, changes, prefix=""):
        for key, value in changes.items():
            path = prefix + key
            if key not in target or path == "id":
                raise InputError("未知或不可修改字段: " + path)
            if isinstance(target[key], dict):
                if not isinstance(value, dict):
                    raise InputError(path + " 必须是对象")
                merge(target[key], value, path + ".")
            else:
                target[key] = value

    merge(result, patch)
    validate_profile(result)
    return result


def new_profile(data):
    result = deepcopy(PROFILE_TEMPLATE)
    result["id"] = str(uuid.uuid4())
    return merge_profile(result, data)


def validate_profile(profile):
    def check_shape(value, template, path="profile"):
        if not isinstance(value, dict) or set(value) != set(template):
            raise InputError(path + " 字段结构不完整或包含未知字段")
        for key, expected in template.items():
            if isinstance(expected, dict):
                check_shape(value[key], expected, path + "." + key)

    check_shape(profile, PROFILE_TEMPLATE)
    if not isinstance(profile.get("id"), str):
        raise InputError("档案 ID 无效")
    try:
        uuid.UUID(profile["id"])
    except ValueError:
        raise InputError("档案 ID 无效")

    def walk(obj, prefix=""):
        for key, value in obj.items():
            path = prefix + key
            if isinstance(value, dict):
                walk(value, path + ".")
            elif value is None or path == "id":
                continue
            elif path in TEXT_FIELDS:
                if not isinstance(value, str) or not value.strip():
                    raise InputError(path + " 必须是非空文本")
            elif path in DATE_FIELDS:
                if not isinstance(value, str):
                    raise InputError(path + " 必须是 YYYY-MM-DD")
                try:
                    parsed = date.fromisoformat(value)
                except ValueError:
                    raise InputError(path + " 必须是有效日期")
                if parsed > date.today():
                    raise InputError(path + " 不能是未来日期")
            elif path in POSITIVE_FIELDS or path in NONNEGATIVE_FIELDS:
                if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
                    raise InputError(path + " 必须是数字")
                if value <= 0 if path in POSITIVE_FIELDS else value < 0:
                    raise InputError(path + " 超出允许范围")
            elif path in INTEGER_FIELDS:
                if isinstance(value, bool) or not isinstance(value, int) or value < 0:
                    raise InputError(path + " 必须是非负整数")
            elif path in LIST_TEXT_FIELDS:
                if not isinstance(value, list) or any(not isinstance(x, str) or not x.strip() for x in value):
                    raise InputError(path + " 必须是文本数组")
            elif path in ("neutered", "breed.mixed", "diet.complete_and_balanced_on_label"):
                if not isinstance(value, bool):
                    raise InputError(path + " 必须是布尔值")
            else:
                raise InputError("无法验证字段: " + path)

    walk(profile)
    if not profile["name"]:
        raise InputError("请填写犬只名称")
    if name_units(profile["name"]) > 24:
        raise InputError("名称超过 24 单位（ASCII 计 1，其他字符簇计 2）")
    birth = profile["birth"]
    if birth["date"] is not None and birth["estimated_age_months"] is not None:
        raise InputError("出生日期和估计年龄只能填写一种")
    if (birth["estimated_age_months"] is None) != (birth["estimated_as_of"] is None):
        raise InputError("估计年龄必须同时填写参考日期")
    if profile["bcs"]["score_9"] is not None and not 1 <= profile["bcs"]["score_9"] <= 9:
        raise InputError("BCS 必须为 1–9")
    if profile["diet"]["meals_per_day"] == 0:
        raise InputError("每日餐次必须大于 0")
    label = profile["diet"]["life_stage_on_label"]
    if label is not None and label not in ("growth", "adult", "all_life_stages", "senior"):
        raise InputError("主粮生命阶段请使用 growth、adult、all_life_stages 或 senior")
    if profile["diet"]["meal_times"] is not None and profile["diet"]["meals_per_day"] is not None:
        if len(profile["diet"]["meal_times"]) != profile["diet"]["meals_per_day"]:
            raise InputError("已确认用餐时间数量须与每日餐次一致")
    if profile["activity"]["walks_per_day"] == 0 and profile["activity"]["minutes_per_walk"] not in (None, 0):
        raise InputError("遛狗次数为 0 时每次时长不能大于 0")
    if profile["breed"]["standard_name"] and not profile["breed"]["reference"]:
        raise InputError("标准犬种名须附参考来源；不确定时只填 reported_name")
    if profile["diet"]["vet_target_kcal_per_day"] is not None and not profile["diet"]["vet_target_reference"]:
        raise InputError("兽医热量目标须记录医嘱来源")
