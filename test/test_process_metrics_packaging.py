"""实际冻结并运行资源采样入口，覆盖 pywin32 C 扩展的隐藏依赖。"""

import json
import os
import subprocess
import sys
import tempfile
import textwrap
import unittest
from pathlib import Path


@unittest.skipUnless(sys.platform == "win32", "资源采样仅支持 Windows")
class MetricsPackagingTests(unittest.TestCase):
    def test_frozen_metrics_keep_native_timezone_dependency(self):
        root = Path(__file__).resolve().parents[1]
        (root / "temp").mkdir(exist_ok=True)
        with tempfile.TemporaryDirectory(prefix="metrics-freeze-", dir=root / "temp") as folder:
            work = Path(folder)
            entry = work / "metrics_probe.py"
            # 不直接导入 win32timezone，否则会掩盖打包钩子遗漏 C 扩展动态依赖的问题。
            entry.write_text(textwrap.dedent("""\
                import json
                import time

                import win32api
                import win32process

                from tool.process_metrics import ProcessMetrics

                times = win32process.GetProcessTimes(win32api.GetCurrentProcess())
                assert times["CreationTime"].tzinfo is not None
                metrics = ProcessMetrics()
                try:
                    metrics.sample()
                    time.sleep(0.1)
                    sample = metrics.sample()
                    assert not sample.error, sample.error
                    assert sample.cpu_usage is not None
                    assert sample.memory > 0
                    assert sample.read is not None and sample.write is not None
                    print(json.dumps({"cpu_usage": sample.cpu_usage, "memory": sample.memory,
                                      "read": sample.read, "write": sample.write}))
                finally:
                    metrics.close()
                """), encoding="utf-8")
            build = subprocess.run([
                "uv", "run", "--no-sync", "--offline", "python", "-m", "PyInstaller",
                "--noconfirm", "--clean", "--noupx", "--onedir", "--console",
                "--additional-hooks-dir", str(root / "packaging/hooks"),
                "--add-data", f"{root / 'LICENSE'}{os.pathsep}.",
                "--paths", str(root), "--distpath", str(work / "dist"),
                "--workpath", str(work / "build"), "--specpath", str(work), str(entry),
            ], cwd=root, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=180)
            self.assertEqual(build.returncode, 0, build.stdout + build.stderr)
            environment = os.environ.copy()
            environment.pop("PYTHONPATH", None)
            environment.pop("PYTHONHOME", None)
            # 从产物目录运行，确保不能借用工作区或虚拟环境里的 win32timezone。
            result = subprocess.run([str(work / "dist/metrics_probe/metrics_probe.exe")],
                                    cwd=work / "dist", env=environment, capture_output=True,
                                    text=True, encoding="utf-8", errors="replace", timeout=30)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            sample = json.loads(result.stdout.splitlines()[-1])
            self.assertGreater(sample["memory"], 0)
            self.assertGreaterEqual(sample["cpu_usage"], 0)


if __name__ == "__main__":
    unittest.main()
