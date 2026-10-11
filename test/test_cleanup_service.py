import os
import shutil
import tempfile
import unittest
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import patch

from tool import cleanup as service
from tool.cleanup import CATEGORIES, CleanupConfig, CleanupItem, cleanup_manual

# 配置相关断言与补丁都落在同一个模块上。
cleanup_config = service

NOW = datetime(2026, 10, 10, 12, 0, 0)


def video_name(moment: datetime) -> str:
    """按录制命名规则生成视频文件名。"""
    return f"第1次轮回-1战-{moment.strftime('%Y%m%d_%H%M%S')}.mp4"


def log_name(moment: datetime) -> str:
    """按日志命名规则生成日志文件名。"""
    return f"log_{moment.strftime('%Y-%m-%d-%H-%M')}.txt"


def temp_name(moment: datetime) -> str:
    """按临时文件命名规则生成临时文件名。"""
    return f"{moment.strftime('%Y%m%d_%H%M%S')}.png"


def make_config_file(path: Path) -> None:
    cleanup_config.write_config(CleanupConfig(items={
        category: CleanupItem() for category in CATEGORIES
    }), path)


class CleanupServiceTestBase(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp_dir.cleanup)
        root = Path(self.temp_dir.name)
        self.paths = {
            "video": str(root / "video"),
            "logs": str(root / "logs"),
            "temp": str(root / "temp"),
        }
        self.config_path = root / "cleanup_config.yml"
        self.example_path = root / "cleanup_config_example.yml"

        self.addCleanup(patch.stopall)
        patch.object(service, "PATHS", self.paths).start()
        patch.object(cleanup_config, "CONFIG_PATH", self.config_path).start()
        patch.object(cleanup_config, "EXAMPLE_PATH", self.example_path).start()

        for key in ("video", "logs", "temp"):
            os.makedirs(self.paths[key], exist_ok=True)
        for name in service.TEMPDIRS:
            os.makedirs(os.path.join(self.paths["temp"], name), exist_ok=True)

    def write(self, directory, name):
        """在指定目录下造一个内容无关的文件，返回其路径。"""
        path = os.path.join(directory, name)
        Path(path).write_bytes(b"data")
        return path

    def write_blank_state(self, moment, pixels):
        """按 blank_state 的实际结构造一个带时间的调试目录。"""
        directory = os.path.join(
            self.paths["temp"], "blank_state",
            f"blank_{pixels}_{moment.strftime('%Y%m%d_%H%M%S')}")
        os.makedirs(directory, exist_ok=True)
        for name in ("minimap.png", "bwmap.png", "greymap.png"):
            Path(directory, name).write_bytes(b"image")
        Path(directory, "params.txt").write_text("threshold = 250\n", encoding="utf-8")
        return directory


class CollectFilesTests(CleanupServiceTestBase):
    def test_collects_only_program_named_files(self):
        self.write_video(video_name(NOW - timedelta(days=2)))
        self.write_video("用户自己录的视频.mp4")
        self.write_log(log_name(NOW - timedelta(days=2)))
        self.write_log("log.txt")
        self.write_log("crash_dump.txt")
        self.write_log("critical_log.log")
        self.write_log("error_log.log")
        self.write_temp(temp_name(NOW - timedelta(days=2)), category="angle")
        self.write_temp(f"{temp_name(NOW - timedelta(days=2))[:-4]}_123456.png",
                        category="unmatched_action_count")
        self.write_temp("minimap.png", category="angle")
        self.write_temp("params.txt", category="angle")
        self.write_temp(temp_name(NOW - timedelta(days=2)), category="", root=True)

        self.assertEqual(len(service.collect_files("video")), 1)
        self.assertEqual(len(service.collect_files("log")), 1)
        self.assertEqual(len(service.collect_files("temp")), 2)

    def test_filename_time_is_parsed_from_name(self):
        moment = NOW - timedelta(days=2)
        path = self.write_video(video_name(moment))
        os.utime(path, (0, 0))

        files = service.collect_files("video")

        self.assertEqual(files[0].created_at, moment)

    def test_invalid_time_in_name_is_skipped(self):
        self.write_video("第1次轮回-20261340_990000.mp4")

        self.assertEqual(service.collect_files("video"), [])

    def test_broken_temp_subdirectory_is_skipped(self):
        self.write_temp(temp_name(NOW), category="angle")
        os.rmdir(os.path.join(self.paths["temp"], "kill"))

        self.assertEqual(len(service.collect_files("temp")), 1)

    def test_collects_timestamped_blank_state_directories(self):
        moment = NOW - timedelta(days=2)
        old_dir = self.write_blank_state(moment, pixels=120)
        recent_dir = self.write_blank_state(NOW, pixels=300)
        user_dir = os.path.join(self.paths["temp"], "blank_state", "用户备份")
        os.makedirs(user_dir, exist_ok=True)

        files = service.collect_files("temp")

        collected = {collect_file.path: collect_file for collect_file in files}
        self.assertEqual(len(collected), 2)
        self.assertIn(old_dir, collected)
        self.assertIn(recent_dir, collected)
        self.assertNotIn(user_dir, collected)
        self.assertTrue(collected[old_dir].is_directory)
        self.assertEqual(collected[old_dir].created_at, moment)

    def test_unmatched_directories_are_not_collected(self):
        other_dir = os.path.join(self.paths["temp"], "angle",
                                 temp_name(NOW - timedelta(days=1))[:-4])
        os.makedirs(other_dir, exist_ok=True)
        Path(other_dir, "minimap.png").write_bytes(b"image")

        self.assertEqual(service.collect_files("temp"), [])

    def write_video(self, name, name_in_logs=False):
        root = self.paths["logs"] if name_in_logs else self.paths["video"]
        path = os.path.join(root, name)
        Path(path).write_bytes(b"video")
        return path

    def write_log(self, name):
        path = os.path.join(self.paths["logs"], name)
        Path(path).write_text("log", encoding="utf-8")
        return path

    def write_temp(self, name, category, root=False):
        directory = self.paths["temp"] if root else os.path.join(self.paths["temp"], category)
        path = os.path.join(directory, name)
        Path(path).write_bytes(b"image")
        return path


class CleanupBehaviourTests(CleanupServiceTestBase):
    def test_manual_cleanup_deletes_only_files_past_the_limit(self):
        old_video = self.write(self.paths["video"], video_name(NOW - timedelta(days=2)))
        recent_video = self.write(self.paths["video"], video_name(NOW - timedelta(hours=2)))
        config = self.config(value=1, unit="day")

        result = cleanup_manual(config, "video", NOW)

        self.assertFalse(os.path.exists(old_video))
        self.assertTrue(os.path.exists(recent_video))
        self.assertEqual((result.success_count, result.failure_count), (1, 0))

    def test_manual_cleanup_with_zero_deletes_every_matching_file(self):
        old_video = self.write(self.paths["video"], video_name(NOW - timedelta(days=2)))
        recent_video = self.write(self.paths["video"], video_name(NOW - timedelta(hours=2)))
        config = self.config(value=0, unit="year")

        result = cleanup_manual(config, "video", NOW)

        self.assertFalse(os.path.exists(old_video))
        self.assertFalse(os.path.exists(recent_video))
        self.assertEqual(result.success_count, 2)

    def test_manual_cleanup_keeps_files_inside_the_limit(self):
        recent_video = self.write(self.paths["video"], video_name(NOW - timedelta(hours=2)))
        config = self.config(value=1, unit="day")

        result = cleanup_manual(config, "video", NOW)

        self.assertTrue(os.path.exists(recent_video))
        self.assertEqual((result.success_count, result.failure_count), (0, 0))

    def test_automatic_cleanup_uses_saving_period(self):
        old_log = self.write(self.paths["logs"], log_name(NOW - timedelta(days=4)))
        recent_log = self.write(self.paths["logs"], log_name(NOW - timedelta(days=2)))
        config = self.config(value=3, unit="day", mode="automatic")

        result = service.cleanup_expired(config, "log", NOW)

        self.assertFalse(os.path.exists(old_log))
        self.assertTrue(os.path.exists(recent_log))
        self.assertEqual(result.success_count, 1)

    def test_periodic_cleanup_removes_all_matching_files(self):
        old_temp = self.write(
            os.path.join(self.paths["temp"], "kill"), temp_name(NOW - timedelta(days=2)))
        recent_temp = self.write(
            os.path.join(self.paths["temp"], "kill"), temp_name(NOW - timedelta(hours=2)))
        config = self.config(value=100, unit="year", mode="periodic")

        result = service.cleanup_all(config, "temp", NOW)

        self.assertFalse(os.path.exists(old_temp))
        self.assertFalse(os.path.exists(recent_temp))
        self.assertEqual(result.success_count, 2)

    def test_current_log_is_not_cleaned(self):
        # 本次运行正在写入的日志，无论期限如何都不参与清理。
        current = self.write(self.paths["logs"], "log_2020-01-01-00-00.txt")
        old_log = self.write(self.paths["logs"], log_name(NOW - timedelta(days=30)))
        config = self.config(value=0, unit="day")

        with patch.object(service, "current_log_file", return_value="log_2020-01-01-00-00.txt"):
            result = cleanup_manual(config, "log", NOW)

        self.assertTrue(os.path.exists(current))
        self.assertFalse(os.path.exists(old_log))
        self.assertEqual((result.success_count, result.failure_count), (1, 0))

    def test_skip_current_log_keeps_other_objects(self):
        current = self.write(self.paths["logs"], "log_2026-10-10-12-00.txt")
        other = self.write(self.paths["logs"], "log_2026-10-09-12-00.txt")
        items = [
            service.CollectFile(path=current, created_at=NOW),
            service.CollectFile(path=other, created_at=NOW),
            service.CollectFile(
                path=os.path.join(self.paths["temp"], "kill"),
                created_at=NOW,
                is_directory=True,
            ),
        ]

        with patch.object(service, "current_log_file", return_value="log_2026-10-10-12-00.txt"):
            kept = service.skip_current_log(items)

        self.assertEqual([item.path for item in kept], [other, items[2].path])

    def test_failed_deletion_is_counted_and_does_not_stop_cleanup(self):
        files = [
            self.write(self.paths["video"], video_name(NOW - timedelta(days=index)))
            for index in range(1, 4)
        ]
        config = self.config(value=0, unit="day")
        real_remove = os.remove

        def remove_with_one_failure(path):
            if path == files[1]:
                raise PermissionError("文件被占用")
            real_remove(path)

        with patch.object(service.os, "remove", side_effect=remove_with_one_failure):
            result = cleanup_manual(config, "video", NOW)

        self.assertEqual((result.success_count, result.failure_count), (2, 1))
        self.assertTrue(os.path.exists(files[1]))
        self.assertFalse(os.path.exists(files[0]))
        self.assertFalse(os.path.exists(files[2]))

    def test_cleanup_time_is_recorded(self):
        self.assertEqual(
            cleanup_manual(self.config(), "video", NOW).cleaned_at,
            "2026-10-10 12:00:00",
        )

    def test_manual_cleanup_removes_expired_blank_state_directory(self):
        old_dir = self.write_blank_state(NOW - timedelta(days=2), pixels=120)
        recent_dir = self.write_blank_state(NOW - timedelta(hours=2), pixels=300)
        user_dir = os.path.join(self.paths["temp"], "blank_state", "用户备份")
        os.makedirs(user_dir, exist_ok=True)
        config = self.config(value=1, unit="day")

        result = cleanup_manual(config, "temp", NOW)

        self.assertFalse(os.path.exists(old_dir))
        self.assertTrue(os.path.exists(recent_dir))
        self.assertTrue(os.path.exists(user_dir))
        self.assertEqual((result.success_count, result.failure_count), (1, 0))

    def test_periodic_cleanup_removes_whole_blank_state_directory(self):
        blank_dir = self.write_blank_state(NOW - timedelta(days=2), pixels=120)
        config = self.config(value=0, unit="day", mode="periodic")

        result = service.cleanup_all(config, "temp", NOW)

        self.assertFalse(os.path.exists(blank_dir))
        self.assertEqual((result.success_count, result.failure_count), (1, 0))
        self.assertTrue(os.path.isdir(
            os.path.join(self.paths["temp"], "blank_state")))

    def test_directory_deletion_failure_is_counted_and_does_not_stop_cleanup(self):
        directories = [
            self.write_blank_state(NOW - timedelta(days=index), pixels=100 + index)
            for index in range(1, 4)
        ]
        config = self.config(value=0, unit="day")
        real_rmtree = shutil.rmtree

        def rmtree_with_one_failure(path):
            if path == directories[1]:
                raise PermissionError("目录被占用")
            real_rmtree(path)

        with patch.object(service.shutil, "rmtree", side_effect=rmtree_with_one_failure):
            result = cleanup_manual(config, "temp", NOW)

        self.assertEqual((result.success_count, result.failure_count), (2, 1))
        self.assertTrue(os.path.exists(directories[1]))
        self.assertFalse(os.path.exists(directories[0]))
        self.assertFalse(os.path.exists(directories[2]))

    def config(self, **overrides):
        base = {"mode": "manual", "trigger": "program_start", "value": 3, "unit": "day"}
        base.update(overrides)
        return CleanupConfig(items={
            category: CleanupItem(**base) for category in CATEGORIES
        })

    def write(self, directory, name):
        path = os.path.join(directory, name)
        Path(path).write_bytes(b"data")
        return path


class PeriodCheckTests(CleanupServiceTestBase):
    def test_first_cleanup_runs_immediately(self):
        config = self.config(value=1, unit="day", last_cleanup="")

        self.assertTrue(service.needs_periodic_cleanup(config, "video", NOW))

    def test_period_not_reached_skips_cleanup(self):
        config = self.config(value=1, unit="day", last_cleanup="2026-10-10 10:00:00")

        self.assertFalse(service.needs_periodic_cleanup(config, "video", NOW))

    def test_period_reached_runs_cleanup(self):
        config = self.config(value=1, unit="day", last_cleanup="2026-10-08 10:00:00")

        self.assertTrue(service.needs_periodic_cleanup(config, "video", NOW))

    def test_zero_period_always_runs(self):
        config = self.config(value=0, unit="minute", last_cleanup="2026-10-10 11:59:59")

        self.assertTrue(service.needs_periodic_cleanup(config, "video", NOW))

    def test_unit_conversion(self):
        cases = [
            # 数值与单位表示需要等待的周期：未达到周期不清理，达到或超过周期立即清理。
            (5, "minute", "2026-10-10 11:55:01", False),
            (5, "minute", "2026-10-10 11:55:00", True),
            (2, "hour", "2026-10-10 10:00:01", False),
            (2, "hour", "2026-10-10 10:00:00", True),
            (1, "month", "2026-10-10 11:59:59", False),
            (1, "month", "2026-09-10 12:00:00", True),
            (1, "year", "2026-01-01 00:00:00", False),
            (1, "year", "2025-10-10 12:00:00", True),
        ]
        for value, unit, last_cleanup, expected in cases:
            with self.subTest(value=value, unit=unit, last_cleanup=last_cleanup):
                config = self.config(
                    value=value, unit=unit, last_cleanup=last_cleanup)
                self.assertEqual(
                    service.needs_periodic_cleanup(config, "video", NOW), expected)

    def config(self, **overrides):
        base = {"mode": "periodic", "trigger": "program_start", "value": 1, "unit": "day"}
        base.update(overrides)
        return CleanupConfig(items={
            category: CleanupItem(**base) for category in CATEGORIES
        })


class ScheduledCleanupTests(CleanupServiceTestBase):
    def setUp(self):
        super().setUp()
        make_config_file(self.config_path)

    def test_never_and_manual_modes_are_skipped(self):
        self.write(self.paths["video"], video_name(NOW - timedelta(days=2)))
        self.write(self.paths["logs"], log_name(NOW - timedelta(days=2)))

        results = service.run_scheduled_cleanup("program_start", now=NOW)

        self.assertEqual(results, [])

    def test_only_matching_trigger_runs(self):
        video = self.write(self.paths["video"], video_name(NOW - timedelta(days=2)))
        config = self.replace_items(video=CleanupItem(
            mode="automatic", trigger="task_end", value=0, unit="day"))
        cleanup_config.write_config(config, self.config_path)

        results = service.run_scheduled_cleanup("program_start", now=NOW)

        self.assertEqual(results, [])
        self.assertTrue(os.path.exists(video))
        reloaded = cleanup_config.load_cleanup_config(self.config_path)
        self.assertEqual(reloaded.item("video").last_cleanup, "")

    def test_automatic_cleanup_records_last_cleanup(self):
        self.write(self.paths["logs"], log_name(NOW - timedelta(days=2)))
        config = self.replace_items(log=CleanupItem(
            mode="automatic", trigger="program_start", value=1, unit="day"))
        cleanup_config.write_config(config, self.config_path)

        results = service.run_scheduled_cleanup("program_start", now=NOW)

        self.assertEqual(len(results), 1)
        self.assertEqual(results[0].category, "log")
        self.assertEqual(results[0].success_count, 1)
        reloaded = cleanup_config.load_cleanup_config(self.config_path)
        self.assertEqual(reloaded.item("log").last_cleanup, "2026-10-10 12:00:00")
        self.assertEqual(reloaded.item("log").mode, "automatic")

    def test_periodic_cleanup_not_reached_keeps_last_cleanup(self):
        config = self.replace_items(video=CleanupItem(
            mode="periodic",
            trigger="task_end",
            value=1,
            unit="day",
            last_cleanup="2026-10-10 10:00:00",
        ))
        cleanup_config.write_config(config, self.config_path)

        results = service.run_scheduled_cleanup("task_end", now=NOW)

        self.assertEqual(results, [])
        reloaded = cleanup_config.load_cleanup_config(self.config_path)
        self.assertEqual(reloaded.item("video").last_cleanup, "2026-10-10 10:00:00")

    def test_all_matching_categories_run(self):
        self.write(self.paths["video"], video_name(NOW - timedelta(days=2)))
        self.write(self.paths["logs"], log_name(NOW - timedelta(days=2)))
        config = CleanupConfig(items={
            "video": CleanupItem(
                mode="automatic", trigger="task_end", value=1, unit="day"),
            "log": CleanupItem(
                mode="periodic", trigger="task_end", value=0, unit="day"),
            "temp": CleanupItem(
                mode="manual", trigger="task_end", value=1, unit="day"),
        })
        cleanup_config.write_config(config, self.config_path)

        results = service.run_scheduled_cleanup("task_end", now=NOW)

        self.assertEqual([result.category for result in results], ["video", "log"])
        reloaded = cleanup_config.load_cleanup_config(self.config_path)
        self.assertEqual(reloaded.item("video").last_cleanup, "2026-10-10 12:00:00")
        self.assertEqual(reloaded.item("log").last_cleanup, "2026-10-10 12:00:00")
        self.assertEqual(reloaded.item("temp").last_cleanup, "")

    def test_last_cleanup_is_recorded_even_without_deletable_files(self):
        config = self.replace_items(temp=CleanupItem(
            mode="automatic", trigger="task_end", value=1, unit="day"))
        cleanup_config.write_config(config, self.config_path)

        results = service.run_scheduled_cleanup("task_end", now=NOW)

        self.assertEqual(len(results), 1)
        self.assertEqual((results[0].success_count, results[0].failure_count), (0, 0))
        reloaded = cleanup_config.load_cleanup_config(self.config_path)
        self.assertEqual(reloaded.item("temp").last_cleanup, "2026-10-10 12:00:00")

    def replace_items(self, **overrides):
        items = {category: CleanupItem() for category in CATEGORIES}
        items.update(overrides)
        return CleanupConfig(items=items)


class RunCleanupTests(CleanupServiceTestBase):
    def test_overlapping_trigger_is_skipped(self):
        self.write(self.paths["logs"], log_name(NOW - timedelta(days=2)))
        cleanup_config.write_config(self.config(value=1, unit="day", mode="automatic"),
                                    self.config_path)

        with patch.object(service, "_cleanup_running", True):
            results = service.run_cleanup("program_start")

        self.assertEqual(results, [])
        self.assertFalse(service._cleanup_running)

    def test_results_are_logged_and_emitted(self):
        self.write(self.paths["logs"], log_name(NOW - timedelta(days=2)))
        cleanup_config.write_config(self.config(value=1, unit="day", mode="automatic"),
                                    self.config_path)
        emitted = []
        service.log_emitter.cleanup_finished_signal.connect(emitted.append)

        try:
            results = service.run_cleanup("program_start")
        finally:
            service.log_emitter.cleanup_finished_signal.disconnect(emitted.append)

        self.assertEqual([result.category for result in results], list(CATEGORIES))
        self.assertEqual(emitted, [results])

    def test_running_flag_is_cleared_after_failure(self):
        def raise_error(trigger):
            raise RuntimeError("扫描失败")

        with patch.object(service, "run_scheduled_cleanup", side_effect=raise_error):
            with self.assertRaises(RuntimeError):
                service.run_cleanup("program_start")

        self.assertFalse(service._cleanup_running)

    def config(self, **overrides):
        base = {"mode": "manual", "trigger": "program_start", "value": 3, "unit": "day"}
        base.update(overrides)
        return CleanupConfig(items={
            category: CleanupItem(**base) for category in CATEGORIES
        })


class CleanupSectionWidgetTests(CleanupServiceTestBase):
    """界面控件读取：UI.ui 与代码版本不一致时必须给出明确错误。"""

    def test_missing_widget_reports_widget_names(self):
        from PyQt5.QtWidgets import QWidget

        import new_gui

        original_find_child = QWidget.findChild

        def find_child(widget, widget_type, name=None):
            if name == "Cleanup_video_value_input":
                return None
            return original_find_child(widget, widget_type, name)

        with patch.object(QWidget, "findChild", find_child):
            with self.assertRaises(RuntimeError) as raised:
                new_gui.CleanupSettingsSection(QWidget())

        self.assertIn("Cleanup_video_value_input", str(raised.exception))
        self.assertIn("UI.ui", str(raised.exception))


if __name__ == "__main__":
    unittest.main()
