# DC3Q YOLO BOT ADB

Hệ thống automation Android qua ADB, hỗ trợ nhiều giả lập chạy đồng thời, Template Matching bằng OpenCV, YOLO, kịch bản YAML, State Machine, Recovery và hàng đợi tài khoản.

## 1. Kiến trúc hiện tại

```text
app/
├── main.py                 # CLI / điểm khởi chạy
├── core/
│   ├── config.py           # config.yaml + biến môi trường
│   └── logger.py
├── adb/
│   ├── client.py           # subprocess ADB tập trung
│   ├── device.py           # thao tác một Android device
│   └── device_manager.py   # discovery / ADB multi-device
├── vision/
│   ├── screenshot.py
│   ├── template_matcher.py
│   ├── yolo_detector.py
│   └── vision_engine.py
├── automation/
│   ├── engine.py
│   ├── state_machine.py
│   ├── actions.py
│   ├── conditions.py
│   └── recovery.py
├── accounts/
│   ├── repository.py       # XLSX / CSV / JSON
│   └── manager.py          # claim/lock/status account
└── devices/
    ├── worker.py           # một worker cho một giả lập
    └── manager.py          # điều phối nhiều worker
```

Luồng chạy nhiều tài khoản:

```text
ADB discovery
    -> DeviceManager
        -> DeviceWorker A -> claim account 1 -> scenario -> DONE/FAILED -> account tiếp theo
        -> DeviceWorker B -> claim account 2 -> scenario -> DONE/FAILED -> account tiếp theo
        -> DeviceWorker C -> ...
```

Một account không thể được hai worker claim cùng lúc.

## 2. Cài môi trường trên PowerShell

Không dùng `&&` trên Windows PowerShell cũ. Chạy từng lệnh hoặc dùng dấu `;`.

```powershell
python --version
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
pip install -r requirements.txt
```

`.venv` chỉ là môi trường Python local. Không sửa code trong đó và không cần đưa `.venv` vào Git/archive dự án.

## 3. Kiểm tra ADB

```powershell
python -m app.main --adb-version
python -m app.main --list
python -m app.main --serial emulator-5554
```

Thứ tự tìm ADB:

1. Biến môi trường `ADB_PATH` nếu có.
2. `%LOCALAPPDATA%\Android\Sdk\platform-tools\adb.exe`.
3. `adb.executable` trong `config/config.yaml` nếu file đó tồn tại.
4. Lệnh `adb` trong PATH.

## 4. Kiểm tra scenario không cần thiết bị

```powershell
python -m app.main --validate-scenario scripts/self_check.yaml
python -m app.main --validate-scenario scripts/account_flow.example.yaml
```

## 5. Chạy scenario trên thiết bị

Đăng nhập rồi đăng xuất tuần tự nhiều tài khoản DC3Q trên một giả lập:

```powershell
python -m app.main --run scripts/multi_account_manager.yaml --accounts data/accounts/accounts.json --max-workers 1
```

Tách trách nhiệm:

```text
scripts/auth/login.yaml          đăng nhập và xác minh Home
scripts/auth/logout.yaml         đăng xuất và xác minh form đăng nhập
scripts/multi_account_manager.yaml gọi login → nhiệm vụ → logout; worker lấy account tiếp theo
```

Mỗi account cần `id, username, password, status`; chỉ account `READY` được chạy. Một account thất bại sẽ dừng batch để tránh chạy account tiếp theo trên trạng thái thiết bị chưa được chứng minh. Google/CAPTCHA/OTP cần người vận hành, không được tự động vượt qua.

Không dùng danh sách tài khoản; mỗi thiết bị online chạy đúng một lần:

```powershell
python -m app.main --run scripts/self_check.yaml --no-accounts
```

Dùng hàng đợi account:

```powershell
python -m app.main --run scripts/account_flow.example.yaml --accounts data/accounts/accounts.xlsx
```

Giới hạn số giả lập chạy song song:

```powershell
python -m app.main --run scripts/account_flow.example.yaml --accounts data/accounts/accounts.xlsx --max-workers 4
```

Nếu không truyền `--accounts`, chương trình đọc đường dẫn `accounts.source_file` trong `config/config.yaml`. Nếu file mặc định chưa tồn tại, hệ thống chuyển sang chế độ chạy một lần trên mỗi device.

## 6. File tài khoản

Hỗ trợ `.xlsx`, `.csv`, `.json`.

Các cột chính:

```text
id, username, password, status, attempts
```

`id` và `status` có thể bỏ trống. Các cột khác được giữ trong `account.metadata` và có thể gọi trong scenario, ví dụ `${account.server}`.

Trạng thái account:

- `READY`: sẵn sàng được worker lấy.
- `IN_USE`: đang bị một worker khóa.
- `DONE`: scenario hoàn thành.
- `FAILED`: thất bại quá số lần retry.
- `DISABLED`: không được sử dụng.

Có file mẫu: `examples/accounts.example.csv`.

## 7. Biến account trong scenario

Khi worker claim account, scenario có thể dùng:

```yaml
- action: input_text
  text: "${account.username}"

- action: input_text
  text: "${account.password}"
```

Các biến mặc định khác:

```text
${account.id}
${account.attempts}
${device.serial}
${worker.id}
```

## 8. Actions hiện có

```text
tap / click
swipe
input_text
keyevent
back
home
sleep / wait
start_app
stop_app
tap_template
tap_yolo
set_variable
delete_variable
log
```

## 9. Conditions hiện có

```text
always
never
template_exists
template_not_exists
yolo_exists
yolo_not_exists
variable_equals
variable_not_equals
variable_truthy
variable_falsy
variable_exists
```

Conditions hỗ trợ tổ hợp `all`, `any`, `not`.

## 10. Vision

Template Matching đọc ảnh từ `assets/templates/`. Scenario có thể truyền `threshold`, `roi`, `scales`.

YOLO mặc định đọc `models/yolo/best.pt`. Nếu `best.pt` chưa tồn tại, worker tự tắt nhánh YOLO và vẫn sử dụng Template Matching; chương trình không chết chỉ vì thiếu model.

## 11. Test

```powershell
python -m pytest -q
```

Bộ test hiện kiểm tra ADB parser/command/device manager, account repository/locking/retry, Automation account variables, DeviceWorker account queue và Template Matching.

## 12. Các thư mục không cần đưa vào source/archive

```text
.venv/
__pycache__/
.pytest_cache/
logs/
temp/
data/ runtime
models/ model thật nếu quá lớn
```

Các thư mục này đã được đưa vào `.gitignore` phù hợp.
