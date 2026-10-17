# OCR 设备选择

部分双显卡机器上，ONNX Runtime 的自动设备排序可能把核显排在独显前面，使文字识别变慢。可在主窗口的 **进阶设置 → OCR 设备设置** 中选择显卡或 CPU，保存后重启程序。

- **自动选择**：保持项目当前 ONNX Runtime 1.20.1 的 DXCore 高性能排序规则，不保证它在每台机器上都选择最快显卡。窗口会显示自动选择的设备名称和当前 LUID。
- **指定显卡**：按名称选择。相同名称的设备通过 DXGI 编号和 LUID 区分，不使用任务管理器 GPU0/GPU1 编号推断设备身份。
- **CPU**：文字检测和文字识别都使用 CPU；个别功能自身明确要求 CPU 时仍遵守该要求。

设置保存在 `user/gui_settings.json` 的 `ocr_device` 字段，旧配置缺少该字段时使用 `"auto"`。显卡优先按 Windows 设备接口路径保存，启动时重新映射到当前 DXGI 索引，避免显卡排序改变后误用另一块设备。无法取得接口路径的设备使用 `luid:` 标识；LUID 只在当前系统会话有效，系统重启后可能需要重新选择。设备被移除或标识失效时明确报错，不静默改用另一块显卡。

模型会话创建成功后，诊断日志记录所用设备名称、DXGI 索引及 LUID；CPU 会话记录 CPU。检测和文字识别共用一次解析出的设备，设置界面的设备信息也可用于排查选卡问题。DirectML 初始化失败时不会把 CPU 回退报告为 GPU 成功。

独立调用 OCR 时可覆盖全局设置：

```python
from tool.onnxocr.onnx_paddleocr import ONNXPaddleOcr

ocr = ONNXPaddleOcr(gpu_id=0)  # 本机 DXGI 索引，仅用于本次调用。
ocr = ONNXPaddleOcr(cpu=True)  # 强制 CPU。
ocr = ONNXPaddleOcr(use_gpu=False)  # 同样强制 CPU。
```

显式 `cpu=True` 或 `use_gpu=False` 优先于显卡设置。`gpu_id` 省略时读取全局设置；提供时必须是可用硬件适配器的非负 DXGI 索引。不要假定索引 0 一定是独显。

设备选择依据见 [ORT 1.20.1 DirectML 选卡实现](https://github.com/microsoft/onnxruntime/blob/v1.20.1/onnxruntime/core/providers/dml/dml_provider_factory.cc#L199)：自动模式走 DXCore，指定 `device_id` 走 DXGI，两者不是同一套顺序。本实现按 DXCore 规则取得 LUID 后映射到 DXGI，并显式传入设备索引，使创建会话时使用的设备与日志一致；没有按显存容量或集成显卡标志猜测性能，也没有引入首次启动测速。
