"""验证进程统计口径、速率差分及系统计数器不可用的行为。"""

import ctypes as ct
import struct
import unittest
from unittest.mock import patch

import pywintypes

from tool.process_metrics import (
    AdapterDesc,
    CounterItem,
    CounterValue,
    ProcessMetrics,
    counter_values,
    gpu_capacities,
    performance_cores,
)


class ProcessorTopologyTests(unittest.TestCase):
    def read_cores(self, classes):
        records = bytearray(48 * len(classes))
        for index, efficiency in enumerate(classes):
            struct.pack_into("<II", records, index * 48, 0, 48)
            records[index * 48 + 8] = 1  # 即使启用超线程，一条记录也只算一个物理核。
            records[index * 48 + 9] = efficiency

        def query(relation, buffer, length):
            ct.cast(length, ct.POINTER(ct.c_uint32))[0] = len(records)
            if buffer is None:
                return 0
            ct.memmove(buffer, bytes(records), len(records))
            return 1

        with patch("tool.process_metrics.ct.WinDLL") as library, patch("tool.process_metrics.ct.get_last_error", return_value=122):
            library.return_value.GetLogicalProcessorInformationEx.side_effect = query
            return performance_cores()

    def test_hybrid_cpu_counts_only_physical_performance_cores(self):
        self.assertEqual(self.read_cores([1] * 6 + [0] * 8), 6)
        self.assertEqual(self.read_cores([10] * 4 + [20] * 2), 2)

    def test_uniform_cpu_counts_physical_cores_without_smt_duplication(self):
        self.assertEqual(self.read_cores([0] * 8), 8)

    def test_failed_topology_is_not_reported_as_an_invented_core_count(self):
        with patch("tool.process_metrics.ct.WinDLL") as library, patch("tool.process_metrics.ct.get_last_error", return_value=5):
            library.return_value.GetLogicalProcessorInformationEx.return_value = 0
            with self.assertRaises(OSError):
                performance_cores()


class GpuCapacityTests(unittest.TestCase):
    def setUp(self):
        self.descriptions = [AdapterDesc(dedicated=12 * 1024**3, shared=32 * 1024**3,
                                         luid_low=0xAB, luid_high=-1),
                             AdapterDesc(dedicated=1 << 40, flags=2)]
        self.released = []
        self.fail_description = False

        def create(iid, factory):
            ct.cast(factory, ct.POINTER(ct.c_void_p))[0] = 100
            return 0

        def enumerate_adapter(factory, index, adapter):
            if index == len(self.descriptions):
                return -2005270526  # DXGI_ERROR_NOT_FOUND。
            ct.cast(adapter, ct.POINTER(ct.c_void_p))[0] = 200 + index
            return 0

        def describe(adapter, description):
            if self.fail_description:
                return -2147467259
            ct.memmove(description, ct.byref(self.descriptions[adapter.value - 200]), ct.sizeof(AdapterDesc))
            return 0

        def method(interface, index, result, *arguments):
            return {12: enumerate_adapter, 10: describe, 2: lambda pointer: self.released.append(pointer.value)}[index]

        library = self.enterContext(patch("tool.process_metrics.ct.WinDLL"))
        library.return_value.CreateDXGIFactory1.side_effect = create
        self.enterContext(patch("tool.process_metrics.com_method", side_effect=method))

    def test_capacity_preserves_more_than_four_gb_and_excludes_software_adapter(self):
        self.assertEqual(gpu_capacities(), {"luid_0xffffffff_0x000000ab": (12 * 1024**3, 32 * 1024**3)})
        self.assertEqual(self.released, [200, 201, 100])

    def test_descriptor_failure_releases_adapter_and_factory(self):
        self.fail_description = True
        with self.assertRaises(OSError):
            gpu_capacities()
        self.assertEqual(self.released, [200, 100])


class CounterArrayTests(unittest.TestCase):
    def test_native_array_preserves_duplicate_names_and_invalid_values(self):
        records = (CounterItem * 3)(
            CounterItem("python", CounterValue(0, 12)),
            CounterItem("python", CounterValue(1, 123)),
            CounterItem("python", CounterValue(0xC0000BBA, 0)),
        )

        def read(counter, formatting, size, count, buffer):
            ct.cast(size, ct.POINTER(ct.c_uint32))[0] = ct.sizeof(records)
            ct.cast(count, ct.POINTER(ct.c_uint32))[0] = len(records)
            if buffer is None:
                return 0x800007D2
            ct.memmove(buffer, records, ct.sizeof(records))
            return 0

        with patch("tool.process_metrics.pdh_array", side_effect=read):
            self.assertEqual(counter_values(1), [("python", 12), ("python", 123), ("python", None)])

    def test_native_counter_error_is_not_reported_as_empty_success(self):
        with patch("tool.process_metrics.pdh_array", return_value=0xC0000BB8):
            with self.assertRaises(pywintypes.error):
                counter_values(1)


class ProcessMetricsTests(unittest.TestCase):
    def setUp(self):
        self.enterContext(patch("tool.process_metrics.os.getpid", return_value=12))
        self.enterContext(patch("tool.process_metrics.performance_cores", return_value=6))
        self.enterContext(patch("tool.process_metrics.gpu_capacities", return_value={
            "luid_1": (4 * 1024**3, 8 * 1024**3),
            "luid_2": (8 * 1024**3, 8 * 1024**3),
            "luid_unused": (32 * 1024**3, 8 * 1024**3),
        }))
        self.enterContext(patch("tool.process_metrics.win32api.GlobalMemoryStatusEx", return_value={
            "TotalPhys": 16 * 1024**3, "TotalPageFile": 32 * 1024**3,
        }))
        self.enterContext(patch("tool.process_metrics.win32api.GetCurrentProcess"))
        self.enterContext(patch("tool.process_metrics.win32pdh.OpenQuery", return_value=50))
        self.enterContext(patch("tool.process_metrics.win32pdh.AddEnglishCounter", side_effect=lambda query, path: path))
        self.collect = self.enterContext(patch("tool.process_metrics.win32pdh.CollectQueryData"))
        self.close = self.enterContext(patch("tool.process_metrics.win32pdh.CloseQuery"))
        self.times = self.enterContext(patch("tool.process_metrics.win32process.GetProcessTimes", return_value={"KernelTime": 0, "UserTime": 0}))
        self.memory = self.enterContext(patch("tool.process_metrics.win32process.GetProcessMemoryInfo", return_value={"WorkingSetSize": 200 * 1024**2, "PagefileUsage": 300 * 1024**2}))
        self.io = self.enterContext(patch("tool.process_metrics.win32process.GetProcessIoCounters", return_value={"ReadTransferCount": 0, "WriteTransferCount": 0}))
        self.array = self.enterContext(patch("tool.process_metrics.counter_values", return_value=[]))
        self.metrics = ProcessMetrics()
        self.addCleanup(self.metrics.close)

    def test_rates_use_elapsed_time_and_physical_performance_core_capacity(self):
        self.times.side_effect = [{"KernelTime": 10_000_000, "UserTime": 30_000_000}, {"KernelTime": 20_000_000, "UserTime": 60_000_000}]
        self.io.side_effect = [{"ReadTransferCount": 1000, "WriteTransferCount": 500}, {"ReadTransferCount": 3048, "WriteTransferCount": 4596}]
        with patch("tool.process_metrics.time.monotonic", side_effect=[10, 12]):
            first = self.metrics.sample()
            second = self.metrics.sample()
        self.assertIsNone(first.cpu)
        self.assertIsNone(first.read)
        self.assertAlmostEqual(second.cpu, 100 / 3)
        self.assertEqual(second.cpu_usage, 2)
        self.assertEqual(second.cpu_cores, 6)
        self.assertEqual(second.read, 1024)
        self.assertEqual(second.write, 2048)
        self.assertEqual(second.memory, 200 * 1024**2)
        self.assertEqual(second.commit, 300 * 1024**2)
        self.assertEqual(second.memory_total, 16 * 1024**3)
        self.assertEqual(second.commit_limit, 32 * 1024**3)

    def test_all_threads_are_counted_even_when_big_core_equivalent_exceeds_capacity(self):
        self.times.side_effect = [{"KernelTime": 0, "UserTime": 0}, {"KernelTime": 0, "UserTime": 80_000_000}]
        with patch("tool.process_metrics.time.monotonic", side_effect=[1, 2]):
            self.metrics.sample()
            result = self.metrics.sample()
        self.assertEqual(result.cpu_usage, 8)
        self.assertAlmostEqual(result.cpu, 400 / 3)

    def test_topology_failure_keeps_raw_cpu_usage_without_using_all_logical_processors(self):
        with patch("tool.process_metrics.performance_cores", side_effect=OSError("拓扑不可用")):
            metrics = ProcessMetrics()
        self.addCleanup(metrics.close)
        with patch("tool.process_metrics.time.monotonic", side_effect=[1, 2]):
            metrics.sample()
            result = metrics.sample()
        self.assertIsNone(result.cpu)
        self.assertIsNone(result.cpu_cores)
        self.assertEqual(result.cpu_usage, 0)
        self.assertIn("拓扑不可用", result.cpu_error)

    def test_system_capacity_failure_does_not_discard_process_memory(self):
        with patch("tool.process_metrics.win32api.GlobalMemoryStatusEx", side_effect=pywintypes.error(5, "GlobalMemoryStatusEx", "拒绝访问")):
            result = self.metrics.sample()
        self.assertEqual(result.memory, 200 * 1024**2)
        self.assertIsNone(result.memory_total)
        self.assertIn("总容量读取失败", result.memory_error)

    def test_gpu_filters_exact_pid_and_uses_busiest_engine(self):
        self.array.side_effect = [
            [("pid_12_luid_1_eng_0_engtype_Copy", 15), ("pid_12_luid_1_eng_1_engtype_3D", 37), ("pid_123_luid_1_eng_0", 99)],
            [("pid_12_luid_1", 1024), ("pid_12_luid_2", 2048), ("pid_123_luid_1", 1_000_000)],
            [("pid_12_luid_1", 4096), ("pid_123_luid_1", 1_000_000)],
            [("python", 123), ("python", 12)],
            [("python", 99999), ("python", 2048)],
        ] * 2
        first = self.metrics.sample()
        self.assertIsNone(first.gpu)
        self.assertEqual(first.gpu_engine, "3D")
        result = self.metrics.sample()
        self.assertEqual(result.gpu, 37)
        self.assertEqual(result.dedicated, 3072)
        self.assertEqual(result.shared, 4096)
        self.assertEqual(result.private_memory, 2048)
        self.assertEqual(result.dedicated_total, 12 * 1024**3)
        self.assertEqual(result.shared_total, 8 * 1024**3)

    def test_gpu_capacity_matches_luid_and_does_not_count_same_adapter_twice(self):
        def read(counter):
            if "Dedicated Usage" in counter:
                return [("pid_12_luid_1_phys_0", 1024), ("pid_12_luid_1_phys_1", 2048), ("pid_123_luid_2_phys_0", 9999)]
            return []

        self.array.side_effect = read
        result = self.metrics.sample()
        self.assertEqual(result.dedicated, 3072)
        self.assertEqual(result.dedicated_total, 4 * 1024**3)
        self.assertIsNone(result.shared_total)

    def test_unknown_adapter_keeps_usage_without_inventing_a_percentage(self):
        self.array.side_effect = lambda counter: [("pid_12_luid_unknown_phys_0", 1024)] if "Dedicated Usage" in counter else []
        result = self.metrics.sample()
        self.assertEqual(result.dedicated, 1024)
        self.assertIsNone(result.dedicated_total)
        self.assertIn("未匹配", result.capacity_error)

    def test_multiple_gpus_do_not_multiply_the_shared_system_memory_limit(self):
        self.array.side_effect = lambda counter: [("pid_12_luid_1_phys_0", 1024), ("pid_12_luid_2_phys_0", 2048)] if "Shared Usage" in counter else []
        result = self.metrics.sample()
        self.assertEqual(result.shared, 3072)
        self.assertEqual(result.shared_total, 8 * 1024**3)

    def test_private_memory_matches_pid_when_process_names_repeat(self):
        def read(counter):
            if "ID Process" in counter:
                return [("python", 123), ("chrome", 20), ("python", 12)]
            if "Working Set - Private" in counter:
                return [("chrome", 99999), ("python", 1000), ("python", 2000)]
            return []

        self.array.side_effect = read
        self.assertEqual(self.metrics.sample().private_memory, 2000)

    def test_missing_gpu_context_is_not_reported_as_measured_zero(self):
        result = self.metrics.sample()
        self.assertEqual((result.gpu, result.dedicated, result.shared), (None, None, None))
        self.assertFalse(result.gpu_error)
        self.collect.side_effect = pywintypes.error(5, "CollectQueryData", "拒绝访问")
        result = self.metrics.sample()
        self.assertIsNone(result.gpu)
        self.assertIsNone(result.dedicated)
        self.assertIn("拒绝访问", result.gpu_error)
        self.assertIsNotNone(result.memory)

    def test_partial_query_creation_failure_releases_query_and_keeps_cpu_monitoring(self):
        with patch("tool.process_metrics.win32pdh.AddEnglishCounter", side_effect=pywintypes.error(2, "AddEnglishCounter", "无此计数器")):
            metrics = ProcessMetrics()
        self.assertIsNone(metrics.query)
        self.assertIn("无此计数器", metrics.sample().gpu_error)
        self.assertIsNotNone(metrics.sample().memory)
        self.close.assert_called_with(50)

    def test_one_gpu_counter_failure_does_not_discard_other_valid_readings(self):
        def read(counter):
            if "Dedicated Usage" in counter:
                raise pywintypes.error(5, "GetFormattedCounterArray", "显存计数器失败")
            if "Utilization Percentage" in counter:
                return [("pid_12_luid_1_eng_0_engtype_3D", 25)]
            if "Shared Usage" in counter:
                return [("pid_12_luid_1", 1024)]
            return []

        self.array.side_effect = read
        self.metrics.sample()
        result = self.metrics.sample()
        self.assertEqual(result.gpu, 25)
        self.assertEqual(result.shared, 1024)
        self.assertIsNone(result.dedicated)
        self.assertIn("显存计数器失败", result.gpu_error)

    def test_reset_requires_fresh_cpu_and_gpu_intervals(self):
        self.array.return_value = [("pid_12_luid_1_eng_0_engtype_3D", 10)]
        self.metrics.sample()
        self.assertEqual(self.metrics.sample().gpu, 10)
        self.metrics.reset_rates()
        result = self.metrics.sample()
        self.assertIsNone(result.cpu)
        self.assertIsNone(result.read)
        self.assertIsNone(result.gpu)

    def test_process_read_failure_does_not_reuse_stale_rates(self):
        self.metrics.sample()
        self.memory.side_effect = pywintypes.error(5, "GetProcessMemoryInfo", "拒绝访问")
        result = self.metrics.sample()
        self.assertIsNone(result.cpu)
        self.assertIsNone(result.memory)
        self.assertIn("读取失败", result.error)
        self.memory.side_effect = None
        self.assertIsNone(self.metrics.sample().cpu)

    def test_zero_elapsed_and_counter_reset_do_not_produce_invalid_rates(self):
        with patch("tool.process_metrics.time.monotonic", side_effect=[1, 1, 2]):
            self.io.return_value = {"ReadTransferCount": 100, "WriteTransferCount": 100}
            self.metrics.sample()
            self.assertIsNone(self.metrics.sample().read)
            self.io.return_value = {"ReadTransferCount": 0, "WriteTransferCount": 0}
            result = self.metrics.sample()
        self.assertEqual(result.read, 0)
        self.assertEqual(result.write, 0)


if __name__ == "__main__":
    unittest.main()
