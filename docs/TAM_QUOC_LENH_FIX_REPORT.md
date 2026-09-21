# Tam Quốc Lệnh – bản sửa ổn định

Ngày kiểm tra: 2026-09-21

## Vấn đề đã xử lý

1. Icon Tam Quốc Lệnh trên HOME thay đổi vị trí X theo account.
2. Icon HOME có hai trạng thái: thường / có badge `!`.
3. Cửa sổ Tam Quốc Lệnh có animation; kiểm tra đúng một frame gây lỗi `que_boi tab not verified`.
4. Tab Quẻ bói / Điểm binh có nhiều trạng thái active, inactive và alert.
5. Quẻ bói có hai ảnh nút miễn phí.
6. Khi lượt miễn phí đã dùng, phải nhận nút 99/100 nhưng tuyệt đối không bấm.
7. Popup nhận thưởng phải được xác minh, đóng bằng vùng trống, rồi xác minh đã biến mất.
8. Nếu bị Ctrl+C / gián đoạn ở popup thưởng hoặc giữa module, lần sau có thể tiếp tục.
9. Sau khi đóng module phải xác minh HOME ổn định trước khi account manager chạy bước tiếp theo.

## Ảnh live đã dùng để kiểm tra

Các ảnh `temp/tql_*.png` trong project đều là 960x540 và được dùng cho test replay bằng chính TemplateMatcher của project.

Một số confidence đo trực tiếp trên ảnh live:

- HOME entry: 0.929–0.968 tùy trạng thái.
- Quẻ bói tab: 0.956–0.997.
- Điểm binh tab: 0.964–0.997.
- Quẻ bói free: 0.992.
- Quẻ bói paid/used 99: 0.991.
- Điểm binh free: 0.993.
- Điểm binh paid/used 100: 0.993.
- Reward banner: 0.993.
- Close X: 0.995–1.000.
- HOME marker sau khi đóng: ~0.999.

## Test

```text
50 passed
compileall PASS
```

Test Tam Quốc Lệnh hiện replay trực tiếp chuỗi ảnh live:

HOME -> mở module -> Quẻ bói free -> popup thưởng -> Quẻ bói done ->
Điểm binh free -> popup thưởng -> Điểm binh done -> đóng X -> HOME.

Ngoài ra có test:
- resume từ popup thưởng bị gián đoạn;
- nhận trạng thái 99/100 là đã hoàn thành mà không bấm nút trả phí.
