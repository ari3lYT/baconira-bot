"""Baconira: setup, private tickets, citizenship, welcome and event log."""
from __future__ import annotations

import asyncio
import getpass
import json
import logging
import os
from pathlib import Path

import discord
from discord import app_commands
from tickets import TicketService, TicketPanel as ServiceTicketPanel, TicketActions
from proposals import ProposalService

ROOT = Path(__file__).resolve().parent
DATA = Path(os.getenv("BACONIRA_DATA", str(ROOT / "data")))
ROLE_SPECS = [
    ("Император", 0xF1C40F), ("Регент", 0x9B59B6),
    ("Сенаторы", 0xE67E22), ("Директор завода", 0x607D8B),
    ("Архитектор", 0x1ABC9C), ("Строитель", 0x2ECC71),
    ("Легионер", 0xE74C3C), ("Гражданин", 0x3498DB), ("гость", 0x95A5A6),
]
STAFF = ("Император", "Регент")
SENATE = (*STAFF, "Сенаторы")
REASON = "Настройка Baconira по поручению администратора"
LAYOUT = {
    "ВХОД": [
        ("правила", "Правила сервера. Текст публикует администрация.", "info"),
        ("новости", "Официальные новости Baconira.", "info"),
        ("лор", None, "info"),
        ("приветствие", "Добро пожаловать в Baconira!", "info"),
    ],
    "ГОРОД": [
        ("общий-чат", "Общение жителей Baconira.", "city"),
        ("скриншоты", "Скриншоты из Minecraft и жизнь города.", "city"),
        ("координаты", "Фермы и порталы: название, измерение, X Y Z, владелец.", "city"),
        ("объявления", "Планы, стройки и проекты жителей.", "city"),
        ("мемы", "Мемы и юмор жителей Baconira.", "city"),
    ],
    "ГОСУДАРСТВО": [
        ("гражданство", "Анкеты новичков. Заявка открывается приватно по кнопке.", "info"),
        ("тикеты", "Приватные жалобы и вопросы к администрации и главе.", "info"),
        ("сенат", "Закрытые заседания: Император, Регент, Сенаторы.", "senate"),
        ("логи", "События бота: входы, выходы, роли, каналы и обращения.", "logs"),
        ("сми", "Официальные публикации Baconira. Пишут Император и Регент.", "info"),
    ],
}


def allowed_guild(guild):
    gid = os.getenv("DISCORD_GUILD_ID")
    return bool(guild and gid and str(guild.id) == gid)


def read_state(guild_id):
    path = DATA / f"{guild_id}.json"
    return json.loads(path.read_text()) if path.exists() else {}


def write_state(guild_id, state):
    DATA.mkdir(exist_ok=True, mode=0o700)
    path = DATA / f"{guild_id}.json"
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(state, ensure_ascii=False, indent=2))
    tmp.chmod(0o600)
    tmp.replace(path)


def is_staff(member):
    return isinstance(member, discord.Member) and (
        member.guild_permissions.administrator or
        any(r.name in STAFF for r in member.roles))


def overwrites(guild, roles, mode, member=None):
    """Explicit per-channel access, including thread permissions."""
    read_only = discord.PermissionOverwrite(
        view_channel=True, send_messages=False, add_reactions=True,
        create_public_threads=False, create_private_threads=False,
        send_messages_in_threads=False)
    private = mode in {"senate", "logs", "case"}
    result = {guild.default_role: (discord.PermissionOverwrite(view_channel=False)
                                 if private else read_only)}
    writers = SENATE if mode == "senate" else STAFF
    if mode == "city":
        writers = tuple(name for name, _ in ROLE_SPECS if name != "гость")
    for name in writers:
        role = roles.get(name)
        if role:
            result[role] = discord.PermissionOverwrite(
                view_channel=True, send_messages=True, read_message_history=True,
                attach_files=True, embed_links=True, add_reactions=True,
                create_public_threads=True, send_messages_in_threads=True)
    result[guild.me] = discord.PermissionOverwrite(
        view_channel=True, send_messages=True, read_message_history=True,
        manage_channels=True, manage_messages=True, attach_files=True, embed_links=True)
    if member:
        result[member] = discord.PermissionOverwrite(
            view_channel=True, send_messages=True, read_message_history=True,
            attach_files=True, embed_links=True)
    return result


def get_roles(guild, state):
    return {name: guild.get_role(rid) for name, rid in state.get("roles", {}).items()
            if guild.get_role(rid)}


async def log_event(guild, text):
    if not allowed_guild(guild):
        return
    state = read_state(guild.id)
    channel = guild.get_channel(state.get("channels", {}).get("логи", 0))
    if channel:
        try:
            await channel.send(text, allowed_mentions=discord.AllowedMentions.none())
        except discord.HTTPException:
            logging.warning("Не удалось записать событие в #логи")


def snapshot(guild):
    return {
        "roles": [{"id": r.id, "name": r.name, "permissions": r.permissions.value,
                   "position": r.position} for r in guild.roles],
        "channels": [{"id": c.id, "name": c.name, "type": str(c.type),
                      "category_id": c.category_id, "position": c.position,
                      "topic": getattr(c, "topic", None),
                      "overwrites": [{"id": t.id, "kind": type(t).__name__,
                                      "allow": p.pair()[0].value,
                                      "deny": p.pair()[1].value}
                                     for t, p in c.overwrites.items()]}
                     for c in guild.channels],
    }


async def configure(guild):
    if not allowed_guild(guild):
        raise ValueError("Это не сервер Baconira. Укажи его ID в DISCORD_GUILD_ID.")
    needed = guild.me.guild_permissions
    if not (needed.manage_channels and needed.manage_roles and needed.send_messages):
        raise ValueError("Боту нужны права управления каналами, ролями и отправки сообщений.")
    # Reject ambiguous names before making any change.
    for name, _ in ROLE_SPECS:
        if len([r for r in guild.roles if r.name == name]) > 1:
            raise ValueError(f"Несколько ролей «{name}»: сначала устрани совпадение имён.")
    for category, specs in LAYOUT.items():
        if len([c for c in guild.categories if c.name == category]) > 1:
            raise ValueError(f"Несколько категорий «{category}».")
        for name, _, _ in specs:
            if len([c for c in guild.text_channels if c.name == name]) > 1:
                raise ValueError(f"Несколько каналов #{name}.")
    DATA.mkdir(exist_ok=True, mode=0o700)
    from datetime import datetime, timezone
    backup = DATA / f"backup-{guild.id}-{datetime.now(timezone.utc):%Y%m%d-%H%M%S-%f}.json"
    backup.write_text(json.dumps(snapshot(guild), ensure_ascii=False, indent=2))
    backup.chmod(0o600)
    state = read_state(guild.id)
    state.setdefault("roles", {})
    state.setdefault("channels", {})
    state.setdefault("categories", {})
    state.setdefault("panels", {})
    roles = {}
    for name, color in ROLE_SPECS:
        role = guild.get_role(state["roles"].get(name, 0))
        role = role or discord.utils.get(guild.roles, name=name)
        if not role:
            role = await guild.create_role(name=name, colour=discord.Colour(color),
                                           permissions=discord.Permissions.none(),
                                           hoist=name != "гость", mentionable=False, reason=REASON)
        roles[name] = role
        state["roles"][name] = role.id
        write_state(guild.id, state)
    # Roles are created in rank order. Do not assign absolute positions:
    # Discord can give the bot and new roles position=1, with ID tie-breaking.
    # Explicit positions 1..9 would then move roles above the bot and fail.
    for position, (name, specs) in enumerate(LAYOUT.items()):
        category = guild.get_channel(state["categories"].get(name, 0))
        category = category or discord.utils.get(guild.categories, name=name)
        if not category:
            category = await guild.create_category(name, position=position, reason=REASON)
        state["categories"][name] = category.id
        write_state(guild.id, state)
        for channel_position, (channel_name, topic, mode) in enumerate(specs):
            channel = guild.get_channel(state["channels"].get(channel_name, 0))
            channel = channel or discord.utils.get(guild.text_channels, name=channel_name)
            kwargs = dict(category=category, overwrites=overwrites(guild, roles, mode),
                          position=channel_position, reason=REASON)
            if topic is not None:
                kwargs["topic"] = topic
            if channel:
                await channel.edit(**kwargs)
            else:
                channel = await guild.create_text_channel(channel_name, **kwargs)
            state["channels"][channel_name] = channel.id
            write_state(guild.id, state)
    for name, message, view in [
        ("тикеты", "Нужна помощь или хочешь подать жалобу? Нажми кнопку. Обращение увидят только ты и администрация.", TicketPanel()),
        ("гражданство", "Хочешь стать гражданином Baconira? Заполни анкету. Её увидят только ты и администрация.", CitizenPanel()),
    ]:
        channel = guild.get_channel(state["channels"][name])
        previous = state["panels"].get(name)
        if previous:
            try:
                panel = await channel.fetch_message(previous)
                await panel.edit(content=message, view=view)
                continue
            except discord.NotFound:
                pass
        panel = await channel.send(message, view=view)
        state["panels"][name] = panel.id
        write_state(guild.id, state)
    await log_event(guild, "✅ Структура Baconira настроена. Снимок прежних настроек сохранён на компьютере бота.")
    state["configured"] = True
    write_state(guild.id, state)
    return state


class BaconiraClient(discord.Client):
    def __init__(self):
        intents = discord.Intents.default()
        intents.members = True
        intents.message_content = True
        super().__init__(intents=intents, allowed_mentions=discord.AllowedMentions.none())
        self.tree = app_commands.CommandTree(self)
        self.locks = {}
        self.synced = set()

    def lock(self, guild_id):
        return self.locks.setdefault(guild_id, asyncio.Lock())

    async def setup_hook(self):
        for view in (TicketPanel(), CitizenPanel(), CaseActions()):
            self.add_view(view)
        self.add_view(features.voice_panel)

    async def sync_guild(self, guild):
        if allowed_guild(guild) and guild.id not in self.synced:
            self.tree.copy_global_to(guild=guild)
            await self.tree.sync(guild=guild)
            self.synced.add(guild.id)

    async def on_ready(self):
        print(f"Бот подключён: {self.user}", flush=True)
        permissions = discord.Permissions(view_channel=True, send_messages=True, embed_links=True, attach_files=True, read_message_history=True, manage_channels=True, manage_roles=True, move_members=True, connect=True, manage_threads=True, send_messages_in_threads=True).value
        print(f"Приглашение бота (проверь разрешения): https://discord.com/oauth2/authorize?client_id={self.user.id}&permissions={permissions}&scope=bot%20applications.commands", flush=True)
        avatar = ROOT / "bot-avatar.png"
        if not avatar.exists():
            avatar = ROOT / "avatar.png"
        if avatar.exists():
            import hashlib
            digest = hashlib.sha256(avatar.read_bytes()).hexdigest()
            marker = DATA / "avatar-applied.txt"
            if not marker.exists() or marker.read_text() != digest:
                await self.user.edit(avatar=avatar.read_bytes())
                DATA.mkdir(exist_ok=True, mode=0o700)
                marker.write_text(digest)
                print("Minecraft-аватар установлен.", flush=True)
        for guild in self.guilds:
            await self.prepare_guild(guild)
            await features.reconcile(guild)
            await tickets.prepare(guild)
            await proposals.prepare(guild)

    async def on_guild_join(self, guild):
        await self.prepare_guild(guild)
        await tickets.prepare(guild)
        await proposals.prepare(guild)

    async def prepare_guild(self, guild):
        await self.sync_guild(guild)
        if allowed_guild(guild) and os.getenv("BACONIRA_AUTO_SETUP") == "1":
            async with self.lock(guild.id):
                if not read_state(guild.id).get("configured"):
                    try:
                        await configure(guild)
                        print(f"Структура настроена на сервере {guild.name} ({guild.id}).", flush=True)
                    except (ValueError, discord.HTTPException) as error:
                        print(f"Настройка прервана: {type(error).__name__}. Повтори /настроить после проверки прав.", flush=True)
                if read_state(guild.id).get("configured") and read_state(guild.id).get("branding_version", 0) < 3:
                    await features.decorate(guild)
                    print("Оформление и голосовые комнаты Baconira настроены.", flush=True)

    async def on_member_join(self, member):
        if not allowed_guild(member.guild) or member.bot:
            return
        state = read_state(member.guild.id)
        guest = member.guild.get_role(state.get("roles", {}).get("гость", 0))
        if safe_citizen_role(guest, member.guild):
            try:
                await member.add_roles(guest, reason="Новый житель Baconira")
            except discord.HTTPException:
                await log_event(member.guild, "⚠️ Не удалось выдать роль гостя. Проверь иерархию ролей.")
        await features.send_welcome(member)
        await log_event(member.guild, f"📥 Вход: {member} ({member.id})")

    async def on_member_remove(self, member):
        await log_event(member.guild, f"📤 Выход: {member} ({member.id})")

    async def on_member_update(self, before, after):
        if before.roles != after.roles:
            old, new = set(before.roles), set(after.roles)
            added = ", ".join(r.name for r in new - old) or "—"
            removed = ", ".join(r.name for r in old - new) or "—"
            await log_event(after.guild, f"🎭 Роли {after.id}: добавлены {added}; сняты {removed}")

    async def on_guild_channel_create(self, channel):
        await log_event(channel.guild, f"➕ Канал создан: #{channel.name} ({channel.id})")

    async def on_guild_channel_delete(self, channel):
        await log_event(channel.guild, f"➖ Канал удалён: #{channel.name} ({channel.id})")

    async def on_voice_state_update(self, member, before, after):
        try:
            await features.voice_changed(member, before, after)
        except discord.HTTPException:
            await log_event(member.guild, "⚠️ Не удалось создать комнату или перенести участника. Проверь права подключения и перемещения.")


client = BaconiraClient()


async def open_case(interaction, kind, fields):
    return await tickets.open_case(interaction, kind, fields)


class TicketModal(discord.ui.Modal, title="Вопрос или жалоба"):
    subject = discord.ui.TextInput(label="Тема", max_length=100)
    details = discord.ui.TextInput(label="Что случилось?", style=discord.TextStyle.paragraph, max_length=1000)

    async def on_submit(self, interaction):
        await open_case(interaction, "ticket", [("Тема", self.subject.value), ("Описание", self.details.value)])


class CitizenModal(discord.ui.Modal, title="Гражданство Baconira"):
    nickname = discord.ui.TextInput(label="Ник в Minecraft", max_length=100)
    experience = discord.ui.TextInput(label="Чем хочешь заниматься?", style=discord.TextStyle.paragraph, max_length=1000)
    about = discord.ui.TextInput(label="Расскажи о себе и опыте игры", style=discord.TextStyle.paragraph, max_length=1000)

    async def on_submit(self, interaction):
        await open_case(interaction, "citizen", [("Ник", self.nickname.value), ("Занятие", self.experience.value), ("О себе", self.about.value)])


class TicketPanel(ServiceTicketPanel):
    def __init__(self):
        super().__init__(tickets)


class CitizenPanel(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label="Подать анкету", emoji="📜", style=discord.ButtonStyle.success, custom_id="baconira:citizen")
    async def citizen(self, interaction, button):
        await interaction.response.send_modal(CitizenModal())


def safe_citizen_role(role, guild):
    dangerous = ("administrator", "manage_guild", "manage_roles", "manage_channels",
                 "ban_members", "kick_members", "manage_webhooks", "moderate_members",
                 "manage_messages", "manage_threads", "mention_everyone", "view_audit_log")
    return bool(role and not role.managed and role < guild.me.top_role and
                not any(getattr(role.permissions, p) for p in dangerous))


class CaseActions(TicketActions):
    def __init__(self):
        super().__init__(tickets, citizen=True)


@client.tree.command(name="настроить", description="Создать роли и структуру Baconira, настроить доступ и панели")
@app_commands.guild_only()
@app_commands.default_permissions(manage_guild=True)
async def setup_command(interaction: discord.Interaction):
    if not isinstance(interaction.user, discord.Member) or not all(
        getattr(interaction.user.guild_permissions, p)
        for p in ("manage_guild", "manage_channels", "manage_roles")):
        return await interaction.response.send_message("Нужны права управления сервером, каналами и ролями.", ephemeral=True)
    await interaction.response.defer(ephemeral=True, thinking=True)
    async with client.lock(interaction.guild.id):
        state = await configure(interaction.guild)
        await features.decorate(interaction.guild)
    await tickets.prepare(interaction.guild)
    await proposals.prepare(interaction.guild)
    await interaction.followup.send(
        f"✅ Созданы/настроены {len(state['roles'])} ролей и {len(state['channels'])} каналов. "
        "Сенат закрыт, лор оставлен для тебя. Подними роль бота выше созданных ролей для выдачи гражданства и гостей. "
        "Администраторы Discord всегда видят закрытые каналы.", ephemeral=True)


@client.tree.error
async def command_error(interaction, error):
    error = getattr(error, "original", error)
    if isinstance(error, discord.Forbidden):
        text = "Discord отказал в доступе. Проверь права и положение роли бота, затем повтори /настроить."
    elif isinstance(error, ValueError):
        text = str(error)
    else:
        text = f"Не удалось завершить действие ({type(error).__name__}). Можно повторить /настроить; созданное сохранено."
    if interaction.response.is_done():
        await interaction.followup.send(text, ephemeral=True)
    else:
        await interaction.response.send_message(text, ephemeral=True)


def main():
    if not os.getenv("DISCORD_GUILD_ID", "").isdigit():
        raise SystemExit("Set DISCORD_GUILD_ID to your server ID before starting.")
    token_path = ROOT / ".token"
    token = os.getenv("DISCORD_BOT_TOKEN") or (token_path.read_text().strip() if token_path.exists() else None)
    token = token or getpass.getpass("Токен бота (ввод скрыт): ").strip()
    if not token:
        raise SystemExit("Токен не указан.")
    try:
        client.run(token, log_level=logging.WARNING)
    except discord.PrivilegedIntentsRequired:
        raise SystemExit("В Developer Portal → Bot включи Server Members Intent и запусти снова.")
    except discord.LoginFailure:
        raise SystemExit("Discord не принял токен. Проверь .token или DISCORD_BOT_TOKEN.")


from features import Features
features = Features(client, ROOT, read_state, write_state, allowed_guild, log_event, TicketPanel, CitizenPanel)
tickets = TicketService(client, DATA, read_state, write_state, allowed_guild, is_staff, overwrites, get_roles, log_event, safe_citizen_role)
proposals = ProposalService(client, read_state, write_state, allowed_guild, is_staff, get_roles, overwrites, log_event)


if __name__ == "__main__":
    main()
