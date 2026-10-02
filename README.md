# Discord TTS Bot CLI

CLI Python để cấu hình token, kiểm tra FFmpeg và chạy bot đọc văn bản trong Discord bằng `edge-tts`.

## Cài đặt

1. Cài Python 3.10 trở lên và FFmpeg; đảm bảo lệnh `ffmpeg -version` chạy được trong terminal.
2. Tạo bot tại [Discord Developer Portal](https://discord.com/developers/applications). Bật **Message Content Intent** trong phần Bot; mời bot vào server với quyền đọc tin nhắn, gửi tin nhắn, Connect và Speak.
3. Trong thư mục dự án chạy:

   ```powershell
   python -m venv .venv
   .\.venv\Scripts\Activate.ps1
   python -m pip install -r requirements.txt
   python cli.py setup
   python cli.py check
   ```

   Nếu PowerShell chặn kích hoạt môi trường, có thể dùng `\.venv\Scripts\python.exe` thay cho `python`.

## Lệnh CLI

```powershell
python cli.py check
python cli.py setup
python cli.py run
python cli.py run --prefix ? --lang vi
python cli.py run --prefix "!" --lang en --auto-read-channel 123456789012345678
```

`setup` nhập token ẩn và lưu vào `.env` (đã được loại khỏi Git bằng `.gitignore`). `check` kiểm tra FFmpeg và token. `run` khởi chạy bot; thay `123456789012345678` bằng ID channel văn bản thật. Bật Developer Mode trong Discord để sao chép ID channel.

## Lệnh trong Discord

- `!join`: bot vào voice channel hiện tại của bạn.
- `!s Xin chào`: xếp nội dung vào hàng đợi để đọc tuần tự.
- `!leave`: bot rời voice channel.

Với `--auto-read-channel`, nội dung tin nhắn thường trong channel chỉ định được đưa vào cùng hàng đợi; người gửi cần đang ở voice channel. Lệnh bot không bị đọc hai lần. Hàng đợi hoạt động riêng cho mỗi server. Mỗi file MP3 tạm được xóa sau lượt phát, kể cả khi có lỗi.

## Lưu ý

Bot cần quyền **Connect** và **Speak** ở voice channel, cùng **View Channel/Read Message History** ở channel văn bản. Mã ngôn ngữ phổ biến như `vi`, `en`, `ja`, `ko`, `fr`, `de`, `es`, `zh` được ánh xạ sang voice tương ứng; mã khác dùng giọng tiếng Việt mặc định. `edge-tts` cần kết nối Internet tới dịch vụ giọng nói.

## Deploy lên Render bằng Docker

1. Đẩy mã nguồn lên GitHub, tạo **New → Web Service** trên Render và kết nối repository.
2. Chọn **Docker** làm runtime. Render sẽ build từ `Dockerfile` ở thư mục gốc.
3. Trong **Environment**, thêm `DISCORD_TOKEN` với token bot. Không commit `.env`.
4. Deploy. HTTP server và bot chạy cùng event loop; các route `GET /` và `GET /ping` trả `200` cùng nội dung `Bot is alive!`, bind `0.0.0.0` trên cổng `$PORT` (mặc định `8080`). Có thể cấu hình **Health Check Path** là `/ping`.
5. Trong **Environment**, bảo đảm `DISCORD_TOKEN` là token mới nhất. Bật **Message Content Intent** trong Discord Developer Portal. Xem logs để xác nhận có dòng `Đã đăng nhập` và `HTTP server đang nghe`.

HTTP ping chỉ xác nhận web process còn phục vụ request; nó không xác nhận Discord Gateway đang kết nối và không phải bảo đảm uptime. Web Service Free có thể spin down khi không nhận traffic inbound. Uptime ping có thể đánh thức dịch vụ, nhưng không thay thế gói chạy liên tục và không bảo đảm bot luôn Online. Nếu dashboard Render báo Live mà bot Offline, kiểm tra logs quanh thời điểm mất kết nối (Gateway close code, lỗi xác thực/token, reconnect hoặc giới hạn session). Để chạy bot liên tục, dùng compute không spin down hoặc Background Worker phù hợp.
