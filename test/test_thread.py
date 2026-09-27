"""ThreadWithException 应保留调用方指定的线程属性。"""

import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

from tool.thread import ThreadWithException


class ThreadConfigurationTests(unittest.TestCase):
    def test_daemon_configuration_survives_initialization(self):
        daemon_thread = ThreadWithException(target=lambda: None, daemon=True)
        foreground_thread = ThreadWithException(target=lambda: None, daemon=False)

        self.assertTrue(daemon_thread.daemon)
        self.assertFalse(foreground_thread.daemon)

    def test_failure_without_gui_preserves_original_exception(self):
        error = ValueError("worker failed")
        logger = Mock()
        emitter = SimpleNamespace(show_error_signal=Mock())
        worker = ThreadWithException(target=Mock(side_effect=error))
        with (
            patch("tool.thread.get_globals", return_value=None),
            patch("tool.thread.get_logger", return_value=(logger, emitter)),
        ):
            worker.run()
        self.assertIs(worker.error, error)
        logger.exception.assert_called_once()
        self.assertIn("worker failed", emitter.show_error_signal.emit.call_args.args[1])


if __name__ == "__main__":
    unittest.main()
