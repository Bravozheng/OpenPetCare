"""Acceptance tests for a usable, persistent Skill v0.1 core."""

from copy import deepcopy
import json
import subprocess
import sys
import tempfile
from pathlib import Path
import unittest

from openpetcare.care import daily
from openpetcare.models import InputError, name_units, new_profile
from openpetcare.service import (create_profile, update_profile, daily_care,
                                 propose_plan, confirm_plan, plan_history,
                                 restore_plan)
from openpetcare.storage import Store, StorageError


ROOT = Path(__file__).resolve().parents[1]


def complete_profile():
    return {
        "name": "豆豆 🐕‍🦺",
        "breed": {"reported_name": "混种犬", "mixed": True},
        "expected_adult_size": "中型",
        "birth": {"date": "2023-01-01"},
        "weight": {"kg": 10, "measured_at": "2026-10-01"},
        "bcs": {"score_9": 5, "recorded_at": "2026-10-01"},
        "sex": "female", "neutered": True,
        "diet": {
            "type": "dry_food", "food_name": "测试完整主粮 A",
            "life_stage_on_label": "adult", "complete_and_balanced_on_label": True,
            "kcal_per_kg": 3500, "calorie_source": "包装标注：3500 kcal/kg",
            "meals_per_day": 2, "meal_times": ["早间", "晚间"],
            "treat_kcal_per_day": 30, "current_food_g_per_day": 170,
        },
        "activity": {"habit": "常规散步", "walks_per_day": 2,
                     "minutes_per_walk": 25, "walk_distance_km_per_day": 2},
        "medical": {"allergies": [], "history": [], "vet_restrictions": [], "red_flags": []},
        "prevention": {"vaccinations": [], "parasite_prevention": [],
                       "confirmed_appointments": ["2026-11-15 复查预约"]},
        "constraints": {"caregiver_schedule": "早晚可照护", "budget": "每月约 500 元"},
    }


class ProfileAndCareTests(unittest.TestCase):
    def test_complete_healthy_adult_has_traceable_starting_estimate(self):
        profile = new_profile(complete_profile())
        result = daily(profile, "2026-10-30")
        self.assertEqual(result["feeding"]["status"], "estimated_starting_point")
        self.assertEqual(result["feeding"]["food_g_per_day"], 170)
        self.assertEqual(sum(x["food_g_approx"] for x in result["feeding"]["meals"]), 170)
        self.assertEqual(result["activity"]["track_400m_laps_equivalent"], 5)
        self.assertIn("Merck", result["feeding"]["basis"])

    def test_missing_information_never_gets_made_up_grams(self):
        profile = new_profile({"name": "小狗"})
        result = daily(profile, "2026-10-30")
        self.assertIsNone(result["feeding"]["food_g_per_day"])
        self.assertIn("diet.kcal_per_kg", result["feeding"]["missing"])
        self.assertIsNone(profile["medical"]["history"])

    def test_contradiction_and_bad_name_are_rejected(self):
        with self.assertRaises(InputError):
            new_profile({"name": "小狗", "birth": {"date": "2023-01-01",
                                              "estimated_age_months": 20,
                                              "estimated_as_of": "2026-10-01"}})
        self.assertEqual(name_units("👩🏽‍⚕️"), 2)
        self.assertEqual(name_units("🇨🇳"), 2)
        with self.assertRaises(InputError):
            new_profile({"name": "中" * 13})
        profile = complete_profile()
        profile["diet"]["treat_kcal_per_day"] = 100
        self.assertEqual(daily(new_profile(profile), "2026-10-30")["feeding"]["status"], "review_needed")

    def test_medical_risk_suppresses_routine_numbers(self):
        data = complete_profile()
        data["medical"]["red_flags"] = ["呼吸困难"]
        result = daily(new_profile(data), "2026-10-30")
        self.assertEqual(result["status"], "urgent_review")
        self.assertIsNone(result["feeding"]["food_g_per_day"])
        self.assertEqual(result["activity"]["status"], "urgent_hold")

    def test_unknown_health_blocks_generic_formula(self):
        data = complete_profile()
        data["medical"]["history"] = None
        result = daily(new_profile(data), "2026-10-30")
        self.assertEqual(result["feeding"]["status"], "insufficient_for_estimate")
        self.assertIsNone(result["feeding"]["food_g_per_day"])


class PersistenceAndPlanTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.store = Store(self.temp.name)
        self.dog = create_profile(self.store, complete_profile())["profile"]["id"]

    def test_proposal_confirmation_history_and_safe_restore(self):
        before = daily_care(self.store, self.dog)["feeding"]["food_g_per_day"]
        proposal = propose_plan(self.store, self.dog, {"diet": {
            "food_name": "测试完整主粮 B", "kcal_per_kg": 4000,
            "calorie_source": "包装标注：4000 kcal/kg"}})
        self.assertEqual(self.store.get(self.dog)["profile"]["diet"]["food_name"], "测试完整主粮 A")
        first = confirm_plan(self.store, self.dog, proposal["id"])["active_plan"]
        self.assertEqual(self.store.get(self.dog)["profile"]["diet"]["food_name"], "测试完整主粮 B")
        self.assertLess(daily_care(self.store, self.dog)["feeding"]["food_g_per_day"], before)
        p2 = propose_plan(self.store, self.dog, {"diet": {"food_name": "测试完整主粮 C"}})
        confirm_plan(self.store, self.dog, p2["id"])
        restored = restore_plan(self.store, self.dog, first["id"])
        self.assertEqual(self.store.get(self.dog)["profile"]["diet"]["food_name"], "测试完整主粮 B")
        self.assertEqual(len(plan_history(self.store, self.dog)["plans"]), 3)
        self.assertEqual(restored["active_plan"]["restored_from_plan_id"], first["id"])

    def test_restore_cannot_erase_new_vet_restriction(self):
        p = propose_plan(self.store, self.dog, {})
        first = confirm_plan(self.store, self.dog, p["id"])["active_plan"]
        update_profile(self.store, self.dog, {"medical": {"vet_restrictions": ["限制运动"]}})
        with self.assertRaises(InputError):
            restore_plan(self.store, self.dog, first["id"])

    def test_backup_export_restore_and_corruption_detection(self):
        backup = self.store.backup()
        update_profile(self.store, self.dog, {"name": "新名字"})
        self.assertEqual(self.store.import_archive(backup, replace=True), 1)
        self.assertEqual(self.store.get(self.dog)["profile"]["name"], "豆豆 🐕‍🦺")
        path = self.store._path(self.dog)
        content = json.loads(path.read_text(encoding="utf-8"))
        content["payload"]["profile"]["name"] = "篡改"
        path.write_text(json.dumps(content), encoding="utf-8")
        with self.assertRaises(StorageError):
            self.store.get(self.dog)

    def test_cli_new_process_reads_same_profile_and_plan(self):
        proposal = propose_plan(self.store, self.dog, {})
        plan_id = confirm_plan(self.store, self.dog, proposal["id"])["active_plan"]["id"]
        command = [sys.executable, str(ROOT / "scripts" / "opc.py"),
                   "--data-dir", self.temp.name, "daily", "--dog", self.dog]
        output = subprocess.run(command, text=True, capture_output=True, check=True)
        result = json.loads(output.stdout)
        self.assertEqual(result["active_plan_id"], plan_id)
        self.assertEqual(result["plan_status"], "active")
        self.assertEqual(result["feeding"]["status"], "estimated_starting_point")


if __name__ == "__main__":
    unittest.main()
