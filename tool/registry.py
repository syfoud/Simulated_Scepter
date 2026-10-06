"""通过模块描述发现内核，并在运行或打开配置时加载 Python。"""

import configparser
from dataclasses import dataclass
from importlib import import_module
from pathlib import Path

from route import PATHS


@dataclass(frozen=True)
class KernelSpec:
    id: str
    folder: Path
    name: str
    description: str
    parent: str
    entry: str
    factory: str
    settings: str
    button: str
    button_order: int
    order: int
    tray: bool
    calibration: bool
    scriptable: bool = False

    def import_entry(self, entry):
        module, symbol = entry.split(":")
        return getattr(import_module(f"core.{self.folder.name}.{module}"), symbol)


class KernelRegistry:
    """发现有效的依赖树；损坏模块与它的子类不阻止其它内核使用。"""

    def __init__(self, root=None):
        self.root = Path(root or PATHS["core"])
        self.specs = {}
        self.errors = {}
        self.classes = {}
        for path in sorted(self.root.glob("*/module.ini")):
            try:
                parser = configparser.ConfigParser(interpolation=None)
                parser.read_string(path.read_text(encoding="utf-8"))
                module = parser["module"]
                if not path.parent.name.isidentifier():
                    raise ValueError("模块目录必须是 Python 标识符")
                spec = KernelSpec(
                    module["id"], path.parent, module["name"],
                    module["description"], module.get("parent", ""),
                    module["entry"], module.get("factory", ""),
                    module.get("settings", ""), module.get("button", ""),
                    module.getint("button_order", 0),
                    module.getint("order", 0), module.getboolean("tray", False),
                    module.getboolean("calibration", False),
                    module.getboolean("scriptable", False),
                )
                if not spec.id.isidentifier():
                    raise ValueError("模块 ID 必须是标识符")
                for entry in (spec.entry, spec.factory, spec.settings):
                    if entry and (entry.count(":") != 1 or not all(
                        part.isidentifier() for part in entry.replace(":", ".").split(".")
                    )):
                        raise ValueError(f"非法 Python 入口：{entry}")
                if spec.id in self.specs:
                    self.specs.pop(spec.id)
                    self.errors[spec.id] = f"模块 ID 重复：{spec.id}"
                    raise ValueError(f"模块 ID 重复：{spec.id}")
                if spec.id in self.errors:
                    raise ValueError(f"模块 ID 不可用：{spec.id}")
                if spec.factory and not spec.settings:
                    raise ValueError("可运行内核必须声明独立配置界面")
                if (spec.button or spec.tray) and not spec.factory:
                    raise ValueError("运行按钮必须声明内核工厂")
                self.specs[spec.id] = spec
            except (OSError, ValueError, KeyError, configparser.Error) as error:
                self.errors[f"目录 {path.parent.name}"] = str(error)

        for kernel_id in tuple(self.specs):
            try:
                self.validate_parents(kernel_id, [])
            except ValueError as error:
                self.errors[kernel_id] = str(error)
        for kernel_id in self.errors:
            self.specs.pop(kernel_id, None)

    def validate_parents(self, kernel_id, chain):
        if kernel_id in chain:
            raise ValueError(f"继承关系形成循环：{' → '.join(chain + [kernel_id])}")
        if kernel_id not in self.specs:
            raise ValueError(f"缺少父内核：{kernel_id}")
        parent = self.specs[kernel_id].parent
        if parent:
            self.validate_parents(parent, chain + [kernel_id])

    def runnable(self):
        return sorted((spec for spec in self.specs.values() if spec.factory),
                      key=lambda spec: (spec.order, spec.id))

    def load_class(self, kernel_id):
        if kernel_id not in self.classes:
            spec = self.specs[kernel_id]
            parent = self.load_class(spec.parent) if spec.parent else None
            cls = spec.import_entry(spec.entry)
            if not isinstance(cls, type) or (parent and not issubclass(cls, parent)):
                raise ValueError(f"{kernel_id} 的 Python 类与 INI 继承关系不一致")
            self.classes[kernel_id] = cls
        return self.classes[kernel_id]

    def create_engine(self, kernel_id, *, script=False):
        spec = self.specs[kernel_id]
        cls = self.load_class(kernel_id)
        engine = spec.import_entry(spec.factory)(script=script)
        if not isinstance(engine, cls):
            raise TypeError(f"{kernel_id} 的工厂返回了错误的内核类型")
        return engine

    def create_settings(self, kernel_id, parent=None):
        return self.specs[kernel_id].import_entry(self.specs[kernel_id].settings)(parent)
