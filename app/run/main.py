from app.run.setup import create_device_manager

def discover(adb_path="adb"):
    return create_device_manager(adb_path).refresh()
