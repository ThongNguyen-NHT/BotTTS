"""Discord TTS bot với hàng đợi phát tuần tự theo máy chủ."""
from __future__ import annotations

import asyncio
import logging
import os
import tempfile
from pathlib import Path

import discord
import edge_tts
from aiohttp import web
from discord.ext import commands

log = logging.getLogger("discord_tts")


class SpeechQueue:
    def __init__(self, bot: commands.Bot, guild_id: int, language: str):
        self.bot = bot
        self.guild_id = guild_id
        self.language = language
        self.items: asyncio.Queue[tuple[str, int] | None] = asyncio.Queue()
        self.worker: asyncio.Task | None = None

    def put(self, text: str, voice_channel_id: int) -> None:
        self.items.put_nowait((text, voice_channel_id))
        if self.worker is None or self.worker.done():
            self.worker = asyncio.create_task(self._run(), name=f"tts-queue-{self.guild_id}")

    async def _run(self) -> None:
        while True:
            item = await self.items.get()
            try:
                if item is None:
                    return
                text, voice_channel_id = item
                guild = self.bot.get_guild(self.guild_id)
                if guild is None:
                    continue
                channel = guild.get_channel(voice_channel_id)
                if not isinstance(channel, (discord.VoiceChannel, discord.StageChannel)):
                    log.warning("Kênh thoại không còn khả dụng trong guild %s", self.guild_id)
                    continue
                voice = guild.voice_client
                if voice is None or not voice.is_connected():
                    try:
                        voice = await channel.connect()
                    except (discord.DiscordException, asyncio.TimeoutError) as exc:
                        log.warning("Không thể kết nối voice: %s", exc)
                        continue
                elif voice.channel != channel:
                    try:
                        await voice.move_to(channel)
                    except discord.DiscordException as exc:
                        log.warning("Không thể chuyển voice channel: %s", exc)
                        continue

                temp_path: Path | None = None
                try:
                    with tempfile.NamedTemporaryFile(prefix="discord_tts_", suffix=".mp3", delete=False) as file:
                        temp_path = Path(file.name)
                    communicator = edge_tts.Communicate(text, self._voice_name())
                    await communicator.save(str(temp_path))
                    if not temp_path.exists() or temp_path.stat().st_size == 0:
                        raise RuntimeError("Dịch vụ TTS không tạo được âm thanh.")
                    done = asyncio.Event()
                    source = discord.FFmpegPCMAudio(str(temp_path))

                    def after_play(error: Exception | None) -> None:
                        if error:
                            log.error("Lỗi phát âm thanh: %s", error)
                        self.bot.loop.call_soon_threadsafe(done.set)

                    voice.play(source, after=after_play)
                    await done.wait()
                except (edge_tts.exceptions.EdgeTTSException, OSError, RuntimeError, discord.DiscordException) as exc:
                    log.warning("Không thể tạo/phát TTS: %s", exc)
                finally:
                    if temp_path:
                        temp_path.unlink(missing_ok=True)
            except asyncio.CancelledError:
                raise
            except Exception:
                log.exception("Lỗi xử lý mục trong hàng đợi TTS")
            finally:
                self.items.task_done()

    def _voice_name(self) -> str:
        # edge-tts yêu cầu tên voice đầy đủ; ánh xạ vài ngôn ngữ phổ biến.
        voices = {
            "vi": "vi-VN-HoaiMyNeural", "en": "en-US-AriaNeural",
            "ja": "ja-JP-NanamiNeural", "ko": "ko-KR-SunHiNeural",
            "fr": "fr-FR-DeniseNeural", "de": "de-DE-KatjaNeural",
            "es": "es-ES-ElviraNeural", "zh": "zh-CN-XiaoxiaoNeural",
        }
        return voices.get(self.language.lower().split("-")[0], "vi-VN-HoaiMyNeural")


def create_bot(prefix: str = "!", language: str = "vi", auto_read_channel: int | None = None) -> commands.Bot:
    intents = discord.Intents.default()
    intents.message_content = True
    intents.voice_states = True
    class TTSBot(commands.Bot):
        http_runner: web.AppRunner | None = None

        async def setup_hook(self) -> None:
            app = web.Application()

            async def health(_request: web.Request) -> web.Response:
                # 200 xác nhận process/web server còn sống; trạng thái Discord
                # được trả về để quan sát, tránh health check tạo vòng restart.
                return web.json_response({
                    "status": "ok",
                    "discord_connected": self.is_ready(),
                })

            app.router.add_get("/health", health)
            self.http_runner = web.AppRunner(app)
            await self.http_runner.setup()
            port = int(os.environ.get("PORT", "10000"))
            site = web.TCPSite(self.http_runner, host="0.0.0.0", port=port)
            await site.start()
            log.info("Health server đang nghe tại 0.0.0.0:%s", port)

        async def close(self) -> None:
            if self.http_runner is not None:
                await self.http_runner.cleanup()
                self.http_runner = None
            await super().close()

    bot = TTSBot(command_prefix=prefix, intents=intents, help_command=None)
    queues: dict[int, SpeechQueue] = {}

    def queue_for(guild_id: int) -> SpeechQueue:
        if guild_id not in queues:
            queues[guild_id] = SpeechQueue(bot, guild_id, language)
        return queues[guild_id]

    async def enqueue_from_context(ctx: commands.Context, text: str) -> bool:
        if ctx.guild is None:
            await ctx.reply("Lệnh này chỉ dùng được trong server.", mention_author=False)
            return False
        member = ctx.author
        if not isinstance(member, discord.Member) or member.voice is None or member.voice.channel is None:
            await ctx.reply("Bạn cần vào một voice channel trước.", mention_author=False)
            return False
        queue_for(ctx.guild.id).put(text, member.voice.channel.id)
        return True

    @bot.event
    async def on_ready() -> None:
        log.info("Đã đăng nhập: %s (ID: %s)", bot.user, bot.user.id if bot.user else "?")
        if auto_read_channel:
            log.info("Tự đọc tin nhắn tại channel ID %s", auto_read_channel)

    @bot.command(name="join")
    async def join(ctx: commands.Context) -> None:
        if ctx.guild is None:
            await ctx.reply("Lệnh này chỉ dùng được trong server.", mention_author=False)
            return
        member = ctx.author
        if not isinstance(member, discord.Member) or member.voice is None or member.voice.channel is None:
            await ctx.reply("Bạn cần vào một voice channel trước.", mention_author=False)
            return
        try:
            if ctx.voice_client and ctx.voice_client.is_connected():
                await ctx.voice_client.move_to(member.voice.channel)
            else:
                await member.voice.channel.connect()
            await ctx.reply(f"Đã vào **{member.voice.channel.name}**.", mention_author=False)
        except (discord.DiscordException, asyncio.TimeoutError) as exc:
            log.warning("Lệnh join thất bại: %s", exc)
            await ctx.reply("Không thể vào voice channel. Hãy kiểm tra quyền Connect/Speak của bot.", mention_author=False)

    @bot.command(name="leave")
    async def leave(ctx: commands.Context) -> None:
        if ctx.voice_client and ctx.voice_client.is_connected():
            try:
                await ctx.voice_client.disconnect()
                await ctx.reply("Đã rời voice channel.", mention_author=False)
            except discord.DiscordException as exc:
                log.warning("Lệnh leave thất bại: %s", exc)
                await ctx.reply("Mất kết nối khi đang rời voice channel.", mention_author=False)
        else:
            await ctx.reply("Bot hiện không ở trong voice channel.", mention_author=False)

    @bot.command(name="s")
    async def speak(ctx: commands.Context, *, text: str) -> None:
        text = text.strip()
        if not text:
            await ctx.reply("Hãy nhập nội dung cần đọc: `!s xin chào`", mention_author=False)
            return
        if len(text) > 1000:
            await ctx.reply("Nội dung tối đa 1000 ký tự.", mention_author=False)
            return
        await enqueue_from_context(ctx, text)

    @bot.event
    async def on_message(message: discord.Message) -> None:
        if message.author.bot:
            return
        # Lệnh vẫn được xử lý bình thường và không bị đọc lặp trong auto-read channel.
        ctx = await bot.get_context(message)
        if ctx.valid:
            await bot.invoke(ctx)
            return
        if (auto_read_channel and message.channel.id == auto_read_channel
                and message.guild and message.content.strip()):
            member = message.author
            if isinstance(member, discord.Member) and member.voice and member.voice.channel:
                content = message.content.strip()
                if len(content) <= 1000:
                    queue_for(message.guild.id).put(content, member.voice.channel.id)

    @bot.event
    async def on_voice_state_update(member: discord.Member, before: discord.VoiceState, after: discord.VoiceState) -> None:
        # Nếu kênh voice bị xóa/ngắt kết nối, worker sẽ tự kết nối lại khi có mục mới.
        voice = member.guild.voice_client
        if voice and voice.is_connected() and voice.channel is None:
            try:
                await voice.disconnect()
            except discord.DiscordException:
                log.exception("Lỗi dọn voice connection")

    return bot


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
