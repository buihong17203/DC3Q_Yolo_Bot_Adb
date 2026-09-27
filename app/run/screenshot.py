from pathlib import Path
from app.run.device import DeviceRuntime

def save_screenshot(runtime: DeviceRuntime, path: str | Path): return runtime.screenshot.save(path)
