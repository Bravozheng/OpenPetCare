"""Acceptance tests for a usable, persistent Skill v0.1 core."""

import json
import subprocess
import sys
import tempfile
from pathlib import Path
import unittest
from unittest import mock

from openpetcare.care import daily
from openpetcare.models import InputError, name_units, new_profile
from openpetcare.service import (create_profile, update_profile, daily_care,
                                 propose_plan, confirm_plan, plan_history,
                                 restore_plan)
from openpetcare.storage import Store, StorageError, validate_record


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

    def test_confirmed_vet_target_takes_priority_over_generic_formula(self):
        data = complete_profile()
        data["diet"]["vet_target_kcal_per_day"] = 800
        data["diet"]["vet_target_reference"] = "兽医于 2026-10-20 确认"
        result = daily(new_profile(data), "2026-10-30")
        self.assertEqual(result["feeding"]["status"], "calculated_from_vet_target")
        self.assertEqual(result["feeding"]["target_kcal_per_day"], 800)
        self.assertEqual(result["feeding"]["food_g_per_day"], 220)
        self.assertIn("兽医确认", result["feeding"]["basis"])


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
        self.assertEqual(proposal["before_feeding"]["food_g_per_day"], before)
        self.assertLess(proposal["after_feeding"]["food_g_per_day"], before)
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

    def test_confirmation_rederives_candidate_from_the_confirmed_patch(self):
        proposal = propose_plan(self.store, self.dog, {"diet": {"food_name": "测试完整主粮 B"}})
        record = self.store.get(self.dog)
        record["proposals"][0]["candidate_profile"]["name"] = "未展示的名字"
        self.store.save(record, expected_revision=record["profile_revision"])

        with self.assertRaises(InputError):
            confirm_plan(self.store, self.dog, proposal["id"])
        self.assertEqual(self.store.get(self.dog)["profile"]["name"], "豆豆 🐕‍🦺")

    def test_restore_reclassifies_plan_from_current_calculation(self):
        proposal = propose_plan(self.store, self.dog, {})
        source = confirm_plan(self.store, self.dog, proposal["id"])["active_plan"]
        limited_care = daily(self.store.get(self.dog)["profile"], "2026-10-30")
        limited_care["feeding"] = {"status": "review_needed", "food_g_per_day": None}

        with mock.patch("openpetcare.service.calculate_daily", return_value=limited_care):
            restored = restore_plan(self.store, self.dog, source["id"])
        self.assertEqual(restored["active_plan"]["status"], "limited")
        self.assertEqual(restored["active_plan"]["care_snapshot"]["feeding"]["status"],
                         "review_needed")

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

    def test_record_validation_rejects_malformed_history(self):
        record = self.store.get(self.dog)
        record["events"].append({"unexpected": "shape"})
        with self.assertRaises(StorageError):
            validate_record(record)

    def test_failed_multi_record_import_rolls_back_all_writes(self):
        with tempfile.TemporaryDirectory() as source_dir, tempfile.TemporaryDirectory() as target_dir:
            source = Store(source_dir)
            first = create_profile(source, complete_profile())["profile"]["id"]
            second_data = complete_profile()
            second_data["name"] = "第二只测试犬"
            second = create_profile(source, second_data)["profile"]["id"]
            archive = source.export(Path(source_dir) / "export.json")

            target = Store(target_dir)
            target.import_archive(archive)
            update_profile(target, first, {"name": "本地第一只"})
            update_profile(target, second, {"name": "本地第二只"})
            original_save = target.save
            calls = 0

            def fail_second_write(record, **kwargs):
                nonlocal calls
                calls += 1
                if calls == 2:
                    raise OSError("simulated write failure")
                return original_save(record, **kwargs)

            with mock.patch.object(target, "save", side_effect=fail_second_write):
                with self.assertRaises(StorageError):
                    target.import_archive(archive, replace=True)
            self.assertEqual(target.get(first)["profile"]["name"], "本地第一只")
            self.assertEqual(target.get(second)["profile"]["name"], "本地第二只")

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


class SkillPackageTests(unittest.TestCase):
    def test_installed_bundle_runs_in_a_new_process(self):
        with tempfile.TemporaryDirectory() as temp:
            base = Path(temp)
            skill = base / "openpetcare"
            data = base / "data"
            subprocess.run(
                [sys.executable, str(ROOT / "scripts" / "install.py"),
                 "codex", "--target", str(skill)],
                text=True, capture_output=True, check=True,
            )
            self.assertTrue((skill / "SKILL.md").is_file())
            self.assertTrue((skill / "agents" / "openai.yaml").is_file())
            self.assertTrue((skill / "docs" / "SCIENCE_SOURCES.md").is_file())
            script = skill / "scripts" / "opc.py"

            def command(*arguments):
                result = subprocess.run(
                    [sys.executable, str(script), "--data-dir", str(data), *arguments],
                    text=True, capture_output=True, check=True,
                )
                return json.loads(result.stdout)

            created = command("profile", "create", "--json",
                              json.dumps(complete_profile(), ensure_ascii=False))
            dog_id = created["profile"]["id"]
            care = command("daily", "--dog", dog_id, "--date", "2026-10-30")
            self.assertEqual(care["feeding"]["status"], "estimated_starting_point")

            patch = {"diet": {"food_name": "安装测试主粮 B", "kcal_per_kg": 4000,
                              "calorie_source": "包装标注：4000 kcal/kg"}}
            proposal = command("plan", "propose", "--dog", dog_id, "--patch",
                               json.dumps(patch, ensure_ascii=False))
            self.assertEqual(proposal["status"], "pending")
            self.assertEqual(command("profile", "get", "--dog", dog_id)["profile"]["diet"]["food_name"],
                             "测试完整主粮 A")

            confirmed = command("plan", "confirm", "--dog", dog_id,
                                "--proposal", proposal["id"])
            loaded = command("profile", "get", "--dog", dog_id)
            history = command("plan", "history", "--dog", dog_id)
            self.assertEqual(loaded["profile"]["diet"]["food_name"], "安装测试主粮 B")
            self.assertEqual(loaded["active_plan_id"], confirmed["active_plan"]["id"])
            self.assertEqual(history["active_plan_id"], confirmed["active_plan"]["id"])


if __name__ == "__main__":
    unittest.main()
