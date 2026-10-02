"""CLI cấu hình, kiểm tra và chạy Discord TTS bot."""
from __future__ import annotations

import argparse
import getpass
import logging
import os
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
ENV_FILE = ROOT / ".env"


def find_ffmpeg() -> str | None:
    found = shutil.which("ffmpeg")
    if found:
        return found
    winget_link = Path.home() / "AppData" / "Local" / "Microsoft" / "WinGet" / "Links" / "ffmpeg.exe"
    # Some Windows builds expose this command as a reparse point that pathlib
    # cannot follow even though the Windows shell can execute it.
    return str(winget_link) if os.path.lexists(winget_link) else None


def read_token() -> str:
    # Trên Render, secret được truyền bằng Environment Variables; local dùng .env.
    configured = os.environ.get("DISCORD_TOKEN", "").strip()
    if configured:
        return configured
    if not ENV_FILE.exists():
        return ""
    for line in ENV_FILE.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if stripped.startswith("DISCORD_TOKEN="):
            value = stripped.split("=", 1)[1].strip()
            if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
                value = value[1:-1]
            return value
    return ""


def check_environment() -> int:
    print("Kiểm tra môi trường Discord TTS Bot")
    ffmpeg = find_ffmpeg()
    if ffmpeg:
        print(f"[OK] FFmpeg: {ffmpeg}")
    else:
        print("[THIẾU] Không tìm thấy FFmpeg trong PATH.")
        print("Windows: cài FFmpeg (ví dụ: winget install Gyan.FFmpeg), rồi mở terminal mới.")
        print("macOS: brew install ffmpeg | Ubuntu/Debian: sudo apt install ffmpeg")
    if read_token():
        print("[OK] Đã có DISCORD_TOKEN trong .env")
    else:
        print("[THIẾU] Chưa có DISCORD_TOKEN. Chạy: python cli.py setup")
    return 0 if ffmpeg else 1


def setup() -> int:
    print("Nhập Discord Bot Token (nội dung sẽ không hiển thị).")
    try:
        token = getpass.getpass("DISCORD_TOKEN: ").strip()
    except (EOFError, KeyboardInterrupt):
        print("\nĐã hủy.")
        return 1
    if not token:
        print("Token không được để trống.", file=sys.stderr)
        return 1

    lines = ENV_FILE.read_text(encoding="utf-8").splitlines() if ENV_FILE.exists() else []
    replacement = f'DISCORD_TOKEN="{token.replace(chr(34), chr(92) + chr(34))}"'
    found = False
    for index, line in enumerate(lines):
        if line.lstrip().startswith("DISCORD_TOKEN="):
            lines[index] = replacement
            found = True
            break
    if not found:
        lines.append(replacement)
    ENV_FILE.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")
    print(f"Đã lưu token vào {ENV_FILE}. Không chia sẻ hoặc commit file này.")
    return 0


def run_bot(args: argparse.Namespace) -> int:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    ffmpeg = find_ffmpeg()
    if not ffmpeg:
        print("Không tìm thấy FFmpeg. Chạy `python cli.py check` để xem hướng dẫn.", file=sys.stderr)
        return 1
    ffmpeg_dir = str(Path(ffmpeg).parent)
    os.environ["PATH"] = ffmpeg_dir + os.pathsep + os.environ.get("PATH", "")
    try:
        from bot import create_bot
    except ImportError as exc:
        print(f"Thiếu dependency: {exc}. Chạy `python -m pip install -r requirements.txt`.", file=sys.stderr)
        return 1

    token = read_token()
    if not token:
        print("Chưa cấu hình token. Chạy `python cli.py setup`.", file=sys.stderr)
        return 1
    try:
        bot = create_bot(prefix=args.prefix, language=args.lang, auto_read_channel=args.auto_read_channel)
        bot.run(token, log_handler=None)
    except KeyboardInterrupt:
        print("Bot đã dừng.")
    except Exception as exc:
        print(f"Không thể chạy bot: {exc}", file=sys.stderr)
        return 1
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="CLI cấu hình và khởi chạy Discord TTS bot")
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("check", help="Kiểm tra FFmpeg và cấu hình token")
    commands.add_parser("setup", help="Nhập/cập nhật Discord Bot Token")
    run_parser = commands.add_parser("run", help="Khởi chạy bot")
    run_parser.add_argument("--prefix", default="!", help="Prefix lệnh (mặc định: !)")
    run_parser.add_argument("--lang", default="vi", help="Mã ngôn ngữ đọc mặc định (mặc định: vi)")
    run_parser.add_argument("--auto-read-channel", type=int, metavar="CHANNEL_ID", help="Đọc tin nhắn văn bản trong channel này")
    args = parser.parse_args()
    if args.command == "check":
        return check_environment()
    if args.command == "setup":
        return setup()
    return run_bot(args)


if __name__ == "__main__":
    # Tránh lỗi in dấu tiếng Việt trên một số Windows dùng code page ANSI.
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")
    raise SystemExit(main())
