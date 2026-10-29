"""采集当前 Windows 进程的资源数据，不包含游戏或其他进程。"""

import ctypes as ct
import os
import time
from collections import defaultdict, deque
from dataclasses import dataclass, field
from uuid import UUID

import pywintypes
import win32api
import win32pdh
import win32process


def performance_cores():
    """按 Windows EfficiencyClass 识别性能最高的一组物理核心，不重复计入超线程。"""
    query = ct.WinDLL("kernel32", use_last_error=True).GetLogicalProcessorInformationEx
    query.argtypes = [ct.c_uint32, ct.c_void_p, ct.POINTER(ct.c_uint32)]
    query.restype = ct.c_int
    size = ct.c_uint32()
    if not query(0, None, ct.byref(size)) and ct.get_last_error() != 122:
        raise ct.WinError(ct.get_last_error())
    buffer = ct.create_string_buffer(size.value)
    if not query(0, buffer, ct.byref(size)):
        raise ct.WinError(ct.get_last_error())
    classes = []
    offset = 0
    while offset < size.value:
        if offset + 32 > size.value:
            raise OSError("CPU 拓扑记录不完整")
        relation = ct.c_uint32.from_buffer(buffer, offset).value
        length = ct.c_uint32.from_buffer(buffer, offset + 4).value
        if relation != 0 or length < 32 or offset + length > size.value:
            raise OSError("CPU 拓扑记录无效")
        # 8 字节头后为 PROCESSOR_RELATIONSHIP；Flags、EfficiencyClass 各占一个字节。
        classes.append(buffer.raw[offset + 9])
        offset += length
    if not classes:
        raise OSError("未读取到物理核心信息")
    return classes.count(max(classes))


class AdapterDesc(ct.Structure):
    """DXGI_ADAPTER_DESC1；显存容量必须用 SIZE_T，不能用会截断 4 GB 的 WMI 字段。"""

    _fields_ = [("description", ct.c_wchar * 128),
                ("vendor", ct.c_uint32), ("device", ct.c_uint32),
                ("subsystem", ct.c_uint32), ("revision", ct.c_uint32),
                ("dedicated", ct.c_size_t), ("system_memory", ct.c_size_t),
                ("shared", ct.c_size_t), ("luid_low", ct.c_uint32),
                ("luid_high", ct.c_int32), ("flags", ct.c_uint32)]


def com_method(interface, index, result, *arguments):
    """按 COM vtable 契约调用 DXGI 接口，保留 Windows 调用约定。"""
    table = ct.cast(interface, ct.POINTER(ct.POINTER(ct.c_void_p))).contents
    return ct.WINFUNCTYPE(result, ct.c_void_p, *arguments)(table[index])


def gpu_capacities():
    """按适配器 LUID 返回专用/共享容量，供同一进程的显存计数器匹配。"""
    create = ct.WinDLL("dxgi").CreateDXGIFactory1
    create.argtypes = [ct.c_void_p, ct.POINTER(ct.c_void_p)]
    create.restype = ct.c_long
    # IID_IDXGIFactory1，使用 DXGI 1.1 与 Qt / DirectML 的接口版本保持一致。
    iid = (ct.c_ubyte * 16).from_buffer_copy(UUID("770aae78-f26f-4dba-a829-253c83d1b387").bytes_le)
    factory = ct.c_void_p()
    status = create(iid, ct.byref(factory))
    if status < 0:
        raise OSError(f"创建显卡查询失败：0x{status & 0xFFFFFFFF:08X}")
    capacities = {}
    try:
        enumerate_adapter = com_method(factory, 12, ct.c_long, ct.c_uint32, ct.POINTER(ct.c_void_p))
        index = 0
        while True:
            adapter = ct.c_void_p()
            status = enumerate_adapter(factory, index, ct.byref(adapter))
            if status & 0xFFFFFFFF == 0x887A0002:  # DXGI_ERROR_NOT_FOUND，已枚举完毕。
                break
            if status < 0:
                raise OSError(f"枚举显卡失败：0x{status & 0xFFFFFFFF:08X}")
            try:
                description = AdapterDesc()
                status = com_method(adapter, 10, ct.c_long, ct.POINTER(AdapterDesc))(adapter, ct.byref(description))
                if status < 0:
                    raise OSError(f"读取显卡容量失败：0x{status & 0xFFFFFFFF:08X}")
                if not description.flags & 2:  # 软件渲染器没有可供比较的硬件显存容量。
                    luid = f"luid_0x{description.luid_high & 0xFFFFFFFF:08X}_0x{description.luid_low:08X}"
                    capacities[luid.casefold()] = (description.dedicated + description.system_memory, description.shared)
            finally:
                com_method(adapter, 2, ct.c_uint32)(adapter)
            index += 1
    finally:
        com_method(factory, 2, ct.c_uint32)(factory)
    return capacities


class CounterValue(ct.Structure):
    """PDH_FMT_DOUBLE 对应的状态与数值，保留 Windows 的八字节对齐。"""

    _fields_ = [("status", ct.c_uint32), ("number", ct.c_double)]


class CounterItem(ct.Structure):
    _fields_ = [("name", ct.c_wchar_p), ("value", CounterValue)]


pdh_array = ct.WinDLL("pdh").PdhGetFormattedCounterArrayW
pdh_array.argtypes = [ct.c_void_p, ct.c_uint32, ct.POINTER(ct.c_uint32), ct.POINTER(ct.c_uint32), ct.c_void_p]
pdh_array.restype = ct.c_uint32


def counter_values(counter):
    """读取有序实例，保留同名进程；字典接口会丢掉重名的 python/发布程序实例。"""
    for _ in range(3):
        size = ct.c_uint32()
        count = ct.c_uint32()
        status = pdh_array(counter, win32pdh.PDH_FMT_DOUBLE, ct.byref(size), ct.byref(count), None)
        if status == 0 and count.value == 0:
            return []
        if status == 0x800007D1:  # PDH_CSTATUS_NO_INSTANCE，当前没有实例。
            return []
        if status != 0x800007D2:  # PDH_MORE_DATA，第一次调用正常返回所需字节数。
            break
        buffer = ct.create_string_buffer(size.value)
        status = pdh_array(counter, win32pdh.PDH_FMT_DOUBLE, ct.byref(size), ct.byref(count), buffer)
        if status == 0:
            items = ct.cast(buffer, ct.POINTER(CounterItem))
            return [(items[index].name,
                     items[index].value.number if items[index].value.status in (0, 1) else None)
                    for index in range(count.value)]
        if status != 0x800007D2:
            break
        # 进程在两次读取间增多会让缓冲区变小；重新获取尺寸，最多重试三次。
    raise pywintypes.error(status, "PdhGetFormattedCounterArrayW", f"性能计数器返回 0x{status:08X}")


@dataclass
class ResourceSample:
    """一次采样；None 表示尚未取得数据，速率单位为字节/秒。"""

    cpu: float | None = None
    cpu_usage: float | None = None
    cpu_cores: int | None = None
    memory: int | None = None
    memory_total: int | None = None
    private_memory: int | None = None
    commit: int | None = None
    commit_limit: int | None = None
    read: float | None = None
    write: float | None = None
    gpu: float | None = None
    dedicated: int | None = None
    dedicated_total: int | None = None
    shared: int | None = None
    shared_total: int | None = None
    gpu_engine: str = ""
    sample_time: float = field(default_factory=time.time)
    error: str = ""
    cpu_error: str = ""
    gpu_error: str = ""
    capacity_error: str = ""
    memory_error: str = ""


class ProcessMetrics:
    """持有性能查询，在后台线程按实际时间差计算速率。"""

    def __init__(self):
        self.process = win32api.GetCurrentProcess()
        self.pid = os.getpid()
        self.cores = None
        self.cpu_error = ""
        try:
            self.cores = performance_cores()
        except OSError as error:
            self.cpu_error = f"大核数量读取失败：{error}"
        self.adapters = {}
        self.capacity_error = ""
        try:
            self.adapters = gpu_capacities()
        except OSError as error:
            self.capacity_error = f"显存总容量读取失败：{error}"
        self.prefix = f"pid_{self.pid}_"
        self.previous = None
        self.query = None
        self.counters = {}
        self.counter_errors = {}
        self.gpu_instances = set()
        try:
            self.query = win32pdh.OpenQuery()
        except pywintypes.error as error:
            self.counter_errors["query"] = f"系统性能查询不可用：{error}"
            return
        for name, path in (
            ("gpu", r"\GPU Engine(*)\Utilization Percentage"),
            ("dedicated", r"\GPU Process Memory(*)\Dedicated Usage"),
            ("shared", r"\GPU Process Memory(*)\Shared Usage"),
            ("pid", r"\Process(*)\ID Process"),
            ("private", r"\Process(*)\Working Set - Private"),
        ):
            try:
                # 英文计数器入口不受 Windows 显示语言影响，通配实例支持运行后新建的 GPU 引擎。
                self.counters[name] = win32pdh.AddEnglishCounter(self.query, path)
            except pywintypes.error as error:
                self.counter_errors[name] = str(error)
        if not self.counters:
            self.close()
            return
        try:
            win32pdh.CollectQueryData(self.query)
        except pywintypes.error as error:
            self.counter_errors["query"] = str(error)

    def reset_rates(self):
        """恢复采样时清除速率基线，隐藏期间的数据不伪装成当前占用。"""
        self.previous = None
        self.gpu_instances.clear()

    def sample(self):
        """读取当前进程；CPU 按物理大核数折算，显存用量与容量按相同适配器汇总。"""
        result = ResourceSample(cpu_cores=self.cores, cpu_error=self.cpu_error, capacity_error=self.capacity_error)
        try:
            capacity = win32api.GlobalMemoryStatusEx()
            result.memory_total = capacity["TotalPhys"]
            result.commit_limit = capacity["TotalPageFile"]
        except pywintypes.error as error:
            result.memory_error = f"内存总容量读取失败：{error}"
        try:
            timestamp = time.monotonic()
            times = win32process.GetProcessTimes(self.process)
            memory = win32process.GetProcessMemoryInfo(self.process)
            io = win32process.GetProcessIoCounters(self.process)
            # GetProcessTimes 含 Python / Rust 全部线程，返回 100 纳秒计数。
            cpu_time = (times["KernelTime"] + times["UserTime"]) / 10_000_000
            result.memory = memory["WorkingSetSize"]
            result.commit = memory["PagefileUsage"]
            if self.previous is not None:
                elapsed = timestamp - self.previous[0]
                if elapsed > 0:
                    result.cpu_usage = max(0.0, (cpu_time - self.previous[1]) / elapsed)
                    if self.cores is not None:
                        # 这是程序总 CPU 时间的大核容量折算，不改变系统调度，也不声称只采到大核线程。
                        result.cpu = result.cpu_usage / self.cores * 100
                    result.read = max(0.0, (io["ReadTransferCount"] - self.previous[2]) / elapsed)
                    result.write = max(0.0, (io["WriteTransferCount"] - self.previous[3]) / elapsed)
            self.previous = (timestamp, cpu_time, io["ReadTransferCount"], io["WriteTransferCount"])
        except pywintypes.error as error:
            result.error = f"进程资源读取失败：{error}"
            self.previous = None

        arrays = {}
        errors = self.counter_errors.copy()
        if self.query is not None:
            try:
                win32pdh.CollectQueryData(self.query)
                errors.pop("query", None)
                for name, counter in self.counters.items():
                    try:
                        arrays[name] = counter_values(counter)
                    except pywintypes.error as error:
                        errors[name] = str(error)
            except pywintypes.error as error:
                errors["query"] = str(error)

        # 任务管理器的默认“内存”是专用工作集；进程总工作集还包含共享页，不能直接混用。
        # 同一查询快照中，同名实例的顺序一致；不能用进程名作为唯一键覆盖重复实例。
        private_values = defaultdict(deque)
        for instance, value in arrays.get("private", []):
            private_values[instance].append(value)
        for instance, pid in arrays.get("pid", []):
            values = private_values[instance]
            value = values.popleft() if values else None
            if pid == self.pid and value is not None:
                result.private_memory = int(value)
                break
        if result.private_memory is None:
            reason = "; ".join(
                errors[name] for name in ("query", "pid", "private") if name in errors
            )
            result.memory_error = "\n".join(filter(None, [result.memory_error,
                f"专用工作集暂不可用：{reason or '该 PID 暂无有效实例'}"]))

        matches = {instance: value for instance, value in arrays.get("gpu", [])
                   if instance.startswith(self.prefix)}
        if matches:
            # 新实例的首个速率值没有完整差分区间，Windows 可能返回 0；等待下一次而非报零。
            ready = [value for instance, value in matches.items() if instance in self.gpu_instances and value is not None]
            if ready:
                result.gpu = min(100.0, max(0.0, max(ready)))
            busiest = max(matches, key=lambda name: matches[name] or 0)
            result.gpu_engine = busiest.rsplit("_engtype_", 1)[-1] if "_engtype_" in busiest else "GPU"
        self.gpu_instances = set(matches)
        for name in ("dedicated", "shared"):
            own_values = [(instance, value) for instance, value in arrays.get(name, [])
                          if instance.startswith(self.prefix) and value is not None]
            if own_values:
                setattr(result, name, int(sum(value for _, value in own_values)))
                # 只汇总本进程涉及的显卡；空闲独显、核显和其他进程不能稀释当前占比。
                luids = {instance[len(self.prefix):].split("_phys_", 1)[0].casefold() for instance, _ in own_values}
                if all(luid in self.adapters for luid in luids):
                    if name == "dedicated":
                        total = sum(self.adapters[luid][0] for luid in luids)
                    else:
                        # 多张显卡借用同一池系统内存，共享上限不能按显卡张数重复累加。
                        total = max(self.adapters[luid][1] for luid in luids)
                    setattr(result, name + "_total", total)
                elif not result.capacity_error:
                    result.capacity_error = "当前 GPU 计数器未匹配到显卡总容量"
        result.gpu_error = "; ".join(f"{name}: {errors[name]}" for name in ("query", "gpu", "dedicated", "shared") if name in errors)
        return result

    def close(self):
        """释放性能查询，包含初始化中途失败的情况。"""
        if self.query is not None:
            win32pdh.CloseQuery(self.query)
            self.query = None
        self.counters.clear()
