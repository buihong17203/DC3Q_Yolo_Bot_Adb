from app.adb import AdbClient, AdbResolver
from app.devices import DeviceManager

def create_device_manager(adb_path: str = "adb") -> DeviceManager:
    adb=AdbClient(adb_path); resolver=AdbResolver(adb); resolver.ensure_server(); return DeviceManager(adb,resolver)
