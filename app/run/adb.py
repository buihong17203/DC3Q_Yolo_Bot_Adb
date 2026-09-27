from app.adb import AdbClient, AdbResolver

def create_adb(path: str = "adb") -> tuple[AdbClient, AdbResolver]:
    client=AdbClient(path); return client, AdbResolver(client)
