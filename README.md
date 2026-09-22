# DC3Q PATCH 2026-09-22 v4

Bản vá cho `DC3Q_YOLO_BOT_ADB`.

## Điểm danh v4

- Không dùng quầng sáng/glow để chọn ô.
- Tìm template/text **Báo danh bù / Được báo danh bù** từ assets hiện có trong project.
- Nếu tìm thấy: xác định ô kế bên bằng hình học thực tế của bảng, không hard-code tọa độ.
- Nếu không tìm thấy: tìm dấu `✓` cuối cùng rồi chọn ô kế bên.
- Nếu chưa có `✓`: tìm ô ngày `1` động cho tháng mới.
- Sau khi click phải xác nhận post-condition trước khi ghi `CLAIMED`.

Code tự quét thư mục `assets/templates/.../Điểm-Danh/` để tìm template có tên liên quan `bao_danh_bu`, `duoc_bao_danh`, `claimable` và các biến thể tên file.

## Cô lập lỗi theo function

### Hoạt động / Phúc lợi
- Lễ bao quốc vận
- Quà online
- Điểm danh
- Trưng thu thuế

Mỗi mục có lỗi riêng. Lỗi một mục không dừng các mục phía sau. Sau lỗi, bot phải recovery về HOME trước khi tiếp tục.

### Tam Quốc Lệnh
- Quẻ bói
- Điểm binh

Hai nhánh chạy độc lập. Một nhánh lỗi không làm mất nhánh còn lại.

### Account
- Login/prepare là critical.
- Function nhiệm vụ lỗi nhưng recovery thành công → account vẫn tiếp tục.
- Recovery không thành công → chỉ account hiện tại FAILED; worker lấy account tiếp theo.
- Logout lỗi → account vẫn được tính đã xử lý; account kế tiếp tự kiểm tra session cũ.

## PowerShell

`Ctrl+C` và lỗi ngoài cùng được cleanup rồi trả exit code để PowerShell nhận lại prompt hiện tại.

## Cài patch

Đặt thư mục patch ngay dưới project:

```text
DC3Q_YOLO_BOT_ADB/
├── app/
├── scripts/
├── PATCH/
│   └── ...
└── apply_patch.ps1
```

Chạy:

```powershell
powershell -ExecutionPolicy Bypass -File .pply_patch.ps1
```

Script sẽ backup file cũ vào:

```text
.patch_backup\DC3Q_2026-09-22```

Sau đó kiểm tra:

```powershell
python -m compileall app
python -m app.main --validate-scenario scripts/multi_account_manager.yaml
```
