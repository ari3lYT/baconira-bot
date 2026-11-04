"""Visual presentation, welcome cards and owner-controlled temporary voice rooms."""
from __future__ import annotations

import asyncio
from pathlib import Path

import discord
from proposals import TOPIC as PROPOSAL_TOPIC

VERSION = 3
COLOR = 0xD4AF37
DESCRIPTION = "Baconira — наше государство в Minecraft. Строим города, развиваем фермы и заводы, создаём проекты и пишем общую историю. Здесь начинается твой путь от гостя до гражданина."
NAMES = {
    "правила": "📜・правила", "новости": "📣・новости", "лор": "📖・лор",
    "приветствие": "👋・приветствие", "общий-чат": "💬・общий-чат",
    "скриншоты": "📸・скриншоты", "координаты": "📍・координаты",
    "объявления": "🏗️・объявления", "гражданство": "🪪・гражданство",
    "тикеты": "🎫・тикеты", "сенат": "🏛️・сенат", "логи": "🤖・логи",
    "идеи": "💡・предложения", "мемы": "😂・мемы", "сми": "📰・сми",
}
TOPICS = {
    "правила": "📜 Начни отсюда: уважение к участникам, порядок в чатах и правила жизни в Baconira. Вопросы и спорные ситуации — через тикеты.",
    "новости": "📣 Официальные новости государства: важные решения, события и обновления. Публикуют Император и Регент.",
    "лор": "📖 Будущая летопись Baconira. Историю государства напишет глава; пока здесь нет записей.",
    "приветствие": "👋 Добро пожаловать в Baconira! Прочитай правила, подай анкету на гражданство и познакомься с городом.",
    "общий-чат": "💬 Главная площадь жителей: знакомства, разговоры, вопросы по Minecraft и повседневная жизнь Baconira.",
    "скриншоты": "📸 Делись красивыми видами, постройками, достижениями и забавными моментами. Добавляй короткую подпись к снимкам.",
    "координаты": "📍 Фермы, порталы и полезные места. Формат: название • измерение • X Y Z • владелец • доступ и особенности.",
    "объявления": "🏗️ Планы, стройки и проекты. Расскажи о цели, месте, нужных ресурсах и участниках; отмечай прогресс и завершение.",
    "идеи": PROPOSAL_TOPIC,
    "сми": "Официальные публикации Baconira: репортажи, интервью, события и жизнь государства. Публикуют только Император и Регент; остальные читают.",
    "мемы": "😂 Мемы, шутки и забавные моменты из Minecraft и жизни Baconira. Без спама, травли и публикации чужих личных данных.",
    "гражданство": "🪪 Стань гражданином Baconira: нажми «Подать анкету». Ответы увидят только ты, Император, Регент и администраторы.",
    "тикеты": "Выбери тип обращения в меню: вопрос или жалоба. Один активный тикет на участника; закрытые тикеты сохраняются в HTML и удаляются из списка каналов.",
    "сенат": "🏛️ Закрытый совет государства: Император, Регент и Сенаторы. Обсуждение решений, развития города и общих проектов.",
    "логи": "🤖 Журнал канцелярии: входы, выходы, изменения ролей, каналы, обращения и временные голосовые комнаты. Обычная переписка не записывается.",
}
CATEGORIES = {"ВХОД": "🏰 ВХОД", "ГОРОД": "🌆 ГОРОД", "ГОСУДАРСТВО": "⚖️ ГОСУДАРСТВО"}


def voice_overwrites(guild, owner=None, locked=False):
    result = {
        guild.default_role: discord.PermissionOverwrite(view_channel=True, connect=not locked,
                                                       speak=True, stream=True, use_voice_activation=True),
        guild.me: discord.PermissionOverwrite(view_channel=True, connect=True, manage_channels=True,
                                             move_members=True, send_messages=True),
    }
    if owner:
        result[owner] = discord.PermissionOverwrite(view_channel=True, connect=True, speak=True,
                                                   stream=True, use_voice_activation=True)
    return result


def clean_name(name):
    name = " ".join(name.split()).strip()
    if not name or len(name) > 80:
        raise ValueError("Название должно содержать от 1 до 80 символов.")
    return "🔊 " + name


class Features:
    def __init__(self, client, root, read, write, allowed, log, ticket_panel, citizen_panel):
        self.client, self.root = client, Path(root)
        self.read, self.write, self.allowed, self.log = read, write, allowed, log
        self.ticket_panel, self.citizen_panel = ticket_panel, citizen_panel
        self.deletions = {}
        self.voice_panel = VoicePanel(self)

    def channel(self, guild, state, key):
        return guild.get_channel(state.get("channels", {}).get(key, 0))

    def link(self, state, key):
        return f"<#{state['channels'][key]}>"

    def embed(self, title, text, guild=None):
        card = discord.Embed(title=title, description=text, colour=COLOR)
        card.set_footer(text="BACONIRA • Канцелярия государства")
        if guild and guild.icon:
            card.set_thumbnail(url=guild.icon.url)
        return card

    def welcome(self, guild, state, member=None):
        text = DESCRIPTION
        title = "🏰 Добро пожаловать в BACONIRA"
        if member:
            title = "👋 В Baconira новый житель!"
            text = f"{member.mention}, рады видеть тебя в нашем государстве!\n\n" + DESCRIPTION
        card = self.embed(title, text, guild)
        card.add_field(name="📜 Первый шаг", value=f"Прочитай {self.link(state, 'правила')}.", inline=True)
        card.add_field(name="🪪 Гражданство", value=f"Подай анкету в {self.link(state, 'гражданство')}.", inline=True)
        card.add_field(name="💬 Знакомство", value=f"Загляни в {self.link(state, 'общий-чат')}.", inline=True)
        card.add_field(name="🔊 Своя комната", value="Зайди в «➕ Создать комнату» в разделе голосовых каналов. Бот создаст твой канал и перенесёт тебя туда.", inline=False)
        card.add_field(name="🎫 Нужна помощь?", value=f"Обратись в {self.link(state, 'тикеты')} — вопрос увидят только ты и администрация.", inline=False)
        if member:
            card.set_thumbnail(url=member.display_avatar.url)
            card.set_footer(text=f"BACONIRA • Жителей на сервере: {guild.member_count}")
        return card

    async def upsert(self, guild, state, key, channel, card, view=None, banner=False):
        mid = state.setdefault("panels", {}).get(key)
        old = None
        if mid:
            try:
                old = await channel.fetch_message(mid)
            except discord.NotFound:
                pass
        banner = banner and (self.root / "welcome-banner.png").is_file()
        if banner:
            card.set_image(url="attachment://welcome-banner.png")
        if old:
            kwargs = dict(content=None, embed=card, view=view)
            if banner:
                kwargs["attachments"] = [discord.File(self.root / "welcome-banner.png")]
            await old.edit(**kwargs)
        else:
            kwargs = dict(embed=card, view=view)
            if banner:
                kwargs["file"] = discord.File(self.root / "welcome-banner.png")
            old = await channel.send(**kwargs)
        state["panels"][key] = old.id
        self.write(guild.id, state)
        return old

    async def decorate(self, guild):
        state = self.read(guild.id)
        for key in ("мемы",):
            if not self.channel(guild, state, key):
                channel = discord.utils.get(guild.text_channels, name=NAMES[key])
                if not channel:
                    template = self.channel(guild, state, "общий-чат")
                    channel = await guild.create_text_channel(NAMES[key],
                        category=guild.get_channel(state["categories"]["ГОРОД"]), topic=TOPICS[key],
                        overwrites=template.overwrites, reason="Новый городской канал по решению администратора")
                state["channels"][key] = channel.id
                self.write(guild.id, state)
        # IDs survive name changes; a repeated setup keeps the same channels.
        for key, cid in state["categories"].items():
            category = guild.get_channel(cid)
            if key in CATEGORIES and category and category.name != CATEGORIES[key]:
                await category.edit(name=CATEGORIES[key], reason="Оформление Baconira")
        for key, name in NAMES.items():
            ch = self.channel(guild, state, key)
            if ch and (ch.name != name or ch.topic != TOPICS[key]):
                changes = {"topic": TOPICS[key], "reason": "Оформление и описание каналов Baconira"}
                if ch.name != name:
                    changes["name"] = name
                await ch.edit(**changes)
        welcome = self.channel(guild, state, "приветствие")
        flags = guild.system_channel_flags
        flags.join_notifications = False  # bot supplies the personalised welcome card
        kwargs = dict(system_channel=welcome, system_channel_flags=flags, reason="Оформление Baconira")
        if not state.get("server_icon_applied") and (self.root / "avatar.png").is_file():
            kwargs["icon"] = (self.root / "avatar.png").read_bytes()
        if "icon" in kwargs or guild.system_channel != welcome or guild.system_channel_flags.value != flags.value:
            await guild.edit(**kwargs)
        state["server_icon_applied"] = True
        self.write(guild.id, state)
        try:
            if guild.description != DESCRIPTION:
                updated = await guild.edit(description=DESCRIPTION, reason="Описание Baconira")
                state["description_applied"] = updated.description == DESCRIPTION
            else:
                state["description_applied"] = True
        except discord.HTTPException as exc:
            state["description_applied"] = False
            state["description_error"] = {"status": exc.status, "code": exc.code}
        self.write(guild.id, state)

        # Use the existing voice area and common channel instead of duplicating them.
        category = guild.get_channel(state.get("voice_category", 0))
        category = category or discord.utils.get(guild.categories, name="Голосовые каналы")
        if not category:
            category = await guild.create_category("🔊 ГОЛОСОВЫЕ", reason="Личные голосовые комнаты")
        elif category.name != "🔊 ГОЛОСОВЫЕ":
            await category.edit(name="🔊 ГОЛОСОВЫЕ", reason="Оформление Baconira")
        state["voice_category"] = category.id
        state.setdefault("voice_rooms", {})
        creator = guild.get_channel(state.get("voice_creator", 0))
        if not creator:
            creator = await guild.create_voice_channel("➕ Создать комнату", category=category,
                overwrites=voice_overwrites(guild), reason="Вход для создания голосовой комнаты")
        state["voice_creator"] = creator.id
        control = self.channel(guild, state, "управление-голосом")
        if not control:
            control = await guild.create_text_channel("🎛️・управление-комнатой", category=category,
                topic="Зайди в «➕ Создать комнату», затем управляй своей комнатой кнопками: имя, лимит, закрыть, открыть, пригласить и передать владение.",
                overwrites={guild.default_role: discord.PermissionOverwrite(view_channel=True, send_messages=False,
                    create_public_threads=False, create_private_threads=False, send_messages_in_threads=False),
                    guild.me: discord.PermissionOverwrite(view_channel=True, send_messages=True, read_message_history=True)},
                reason="Панель личных голосовых комнат")
        state["channels"]["управление-голосом"] = control.id
        self.write(guild.id, state)
        for ch in guild.voice_channels:
            if ch.id == creator.id:
                if getattr(ch, "status", None) != "Зайди сюда — получишь свою комнату":
                    await ch.edit(status="Зайди сюда — получишь свою комнату")
            elif ch.category_id == category.id and ch.id not in {int(cid) for cid in state["voice_rooms"]}:
                if ch.name == "Основной":
                    await ch.edit(name="🔊 Общая площадь", status="Общий голосовой чат жителей Baconira")
        for ch in guild.text_channels:
            if ch.name == "основной":
                await ch.edit(name="💬・гостиная", topic="Открытая гостиная Baconira: общение гостей и новичков. За гражданством — в раздел ГОСУДАРСТВО.")
        for cat in guild.categories:
            if cat.name == "Текстовые каналы":
                await cat.edit(name="🗨️ ГОСТИНАЯ")
        ordered_categories = [guild.get_channel(state["categories"][key]) for key in CATEGORIES]
        ordered_categories.append(category)
        guest_area = discord.utils.get(guild.categories, name="🗨️ ГОСТИНАЯ")
        if guest_area:
            ordered_categories.append(guest_area)
        for position, area in enumerate(ordered_categories):
            if area and area.position != position:
                await area.edit(position=position, reason="Порядок разделов Baconira")

        await self.upsert(guild, state, "welcome_board", welcome, self.welcome(guild, state), banner=True)
        rules = self.embed("📜 Правила", (self.root / "rules.txt").read_text(encoding="utf-8").removeprefix("### Правила\n").strip(), guild)
        await self.upsert(guild, state, "rules_board", self.channel(guild, state, "правила"), rules)
        await self.upsert(guild, state, "тикеты", self.channel(guild, state, "тикеты"), self.embed("🎫 Канцелярия помощи", "Вопрос администрации, техническая проблема или жалоба?\n\nНажми **«Открыть тикет»**, укажи тему и опиши ситуацию. Бот создаст приватный канал для тебя и администрации.\n\nМожно приложить скриншоты. После решения вопроса обращение закрывается, а история сохраняется.", guild), self.ticket_panel())
        await self.upsert(guild, state, "гражданство", self.channel(guild, state, "гражданство"), self.embed("🪪 Стань гражданином Baconira", "Начни свою историю в государстве.\n\nНажми **«Подать анкету»** и укажи ник в Minecraft, интересы и опыт игры. Анкета будет видна только тебе и администрации.\n\nПосле одобрения бот выдаст роль **Гражданин** и откроет возможность писать в городских каналах.", guild), self.citizen_panel())
        voice_card = self.embed("🔊 Твоя голосовая комната", f"**1.** Подключись к <#{creator.id}>.\n**2.** Бот создаст комнату и перенесёт тебя в неё.\n**3.** Управляй комнатой кнопками ниже.\n\n**Название** — переименовать комнату.\n**Лимит** — от 0 до 99; 0 означает без ограничения.\n**Закрыть / Открыть** — запретить или разрешить новые подключения. Уже вошедшие остаются в комнате.\n**Пригласить** — дать выбранному участнику доступ в закрытую комнату.\n**Передать** — назначить владельцем другого участника комнаты.\n\nОдна комната на человека. Когда все выйдут, бот удалит её через 10 секунд. Кнопками управляет только владелец своей комнаты.", guild)
        await self.upsert(guild, state, "voice_board", control, voice_card, self.voice_panel)
        for uid, role_name in state.get("leadership", {}).items():
            if state.get("leadership_applied", {}).get(uid) == role_name:
                continue
            member = await guild.fetch_member(int(uid))
            role = guild.get_role(state["roles"][role_name])
            await member.add_roles(role, reason="Распределение руководящих ролей администратором")
            state.setdefault("leadership_applied", {})[uid] = role_name
            self.write(guild.id, state)
        state["branding_version"] = VERSION
        self.write(guild.id, state)
        await self.log(guild, "🎨 Оформление обновлено: роли руководства, эмодзи, описания, приветственные карточки и личные голосовые комнаты.")

    async def send_welcome(self, member):
        state = self.read(member.guild.id)
        channel = self.channel(member.guild, state, "приветствие")
        if not channel:
            return
        card = self.welcome(member.guild, state, member)
        kwargs = {}
        if (self.root / "welcome-banner.png").is_file():
            card.set_image(url="attachment://welcome-banner.png")
            kwargs["file"] = discord.File(self.root / "welcome-banner.png")
        await channel.send(embed=card, **kwargs,
                           allowed_mentions=discord.AllowedMentions(users=[member]))

    async def cleanup_room(self, guild, cid, delay=10):
        try:
            if delay:
                await asyncio.sleep(delay)
            async with self.client.lock(guild.id):
                state = self.read(guild.id)
                if str(cid) not in state.get("voice_rooms", {}):
                    return
                room = guild.get_channel(cid)
                if room and room.members:
                    return
                if room:
                    try:
                        await room.delete(reason="Пустая временная голосовая комната")
                    except discord.NotFound:
                        pass
                state["voice_rooms"].pop(str(cid), None)
                self.write(guild.id, state)
        except discord.NotFound:
            pass
        finally:
            if self.deletions.get(cid) is asyncio.current_task():
                self.deletions.pop(cid, None)

    async def reconcile(self, guild):
        if not self.allowed(guild):
            return
        for cid in list(self.read(guild.id).get("voice_rooms", {})):
            room = guild.get_channel(int(cid))
            if not room or not room.members:
                self.schedule_cleanup(guild, int(cid))

    def schedule_cleanup(self, guild, cid):
        if cid not in self.deletions:
            self.deletions[cid] = asyncio.create_task(self.cleanup_room(guild, cid))

    async def voice_changed(self, member, before, after):
        guild = member.guild
        if not self.allowed(guild) or before.channel == after.channel:
            return
        state = self.read(guild.id)
        if after.channel and after.channel.id in self.deletions:
            self.deletions.pop(after.channel.id).cancel()
        if after.channel and after.channel.id == state.get("voice_creator") and not member.bot:
            async with self.client.lock(guild.id):
                state = self.read(guild.id)
                rooms = state.setdefault("voice_rooms", {})
                existing = next((guild.get_channel(int(cid)) for cid, x in rooms.items()
                                 if x["owner"] == member.id and guild.get_channel(int(cid))), None)
                if existing:
                    await member.move_to(existing, reason="Возврат в свою комнату")
                else:
                    room = await guild.create_voice_channel(clean_name(f"Комната {member.display_name}"[:80]),
                        category=guild.get_channel(state["voice_category"]), user_limit=0,
                        overwrites=voice_overwrites(guild, member), reason="Личная голосовая комната")
                    rooms[str(room.id)] = {"owner": member.id, "locked": False}
                    self.write(guild.id, state)
                    try:
                        await member.move_to(room, reason="Перенос в созданную комнату")
                    except discord.HTTPException:
                        self.schedule_cleanup(guild, room.id)
                        raise
                    await self.log(guild, f"🔊 Создана комната {room.id}; владелец {member.id}.")
        if before.channel and str(before.channel.id) in state.get("voice_rooms", {}):
            if not before.channel.members:
                self.schedule_cleanup(guild, before.channel.id)

    def owned_room(self, interaction):
        if not self.allowed(interaction.guild):
            raise ValueError("Эта панель работает только в Baconira.")
        voice = getattr(interaction.user, "voice", None)
        if not voice or not voice.channel:
            raise ValueError("Сначала зайди в свою голосовую комнату.")
        state = self.read(interaction.guild.id)
        record = state.get("voice_rooms", {}).get(str(voice.channel.id))
        if not record or record["owner"] != interaction.user.id:
            raise ValueError("Управлять может только владелец этой комнаты.")
        return state, voice.channel, record


class RoomModal(discord.ui.Modal):
    def __init__(self, features, mode):
        super().__init__(title={"name": "Название комнаты", "limit": "Лимит участников", "invite": "Доступ в закрытую комнату", "transfer": "Передать комнату"}[mode])
        self.features, self.mode = features, mode
        label = {"name": "Новое название", "limit": "Число от 0 до 99", "invite": "ID или @упоминание участника", "transfer": "ID или @упоминание нового владельца"}[mode]
        self.value = discord.ui.TextInput(label=label, max_length=80)
        self.add_item(self.value)

    async def on_submit(self, interaction):
        await interaction.response.defer(ephemeral=True)
        try:
            async with self.features.client.lock(interaction.guild.id):
                state, room, record = self.features.owned_room(interaction)
                raw = self.value.value.strip()
                if self.mode == "name":
                    await room.edit(name=clean_name(raw), reason="Владелец переименовал комнату")
                elif self.mode == "limit":
                    if not raw.isdecimal() or not 0 <= int(raw) <= 99:
                        raise ValueError("Введи целое число от 0 до 99.")
                    await room.edit(user_limit=int(raw), reason="Владелец изменил лимит")
                else:
                    uid = raw.removeprefix("<@").removeprefix("!").removesuffix(">")
                    if not uid.isdecimal():
                        raise ValueError("Укажи ID участника или его @упоминание.")
                    target = await interaction.guild.fetch_member(int(uid))
                    if target.bot:
                        raise ValueError("Выбери участника, а не бота.")
                    if self.mode == "transfer":
                        if target not in room.members:
                            raise ValueError("Новый владелец должен находиться в этой комнате.")
                        if any(r["owner"] == target.id for cid, r in state["voice_rooms"].items() if int(cid) != room.id):
                            raise ValueError("У участника уже есть своя комната.")
                    await room.set_permissions(target, view_channel=True, connect=True, speak=True, stream=True,
                                               reason="Владелец выдал доступ к комнате")
                    if self.mode == "transfer":
                        record["owner"] = target.id
                        self.features.write(interaction.guild.id, state)
            await interaction.followup.send("Готово ✅", ephemeral=True)
        except (ValueError, discord.NotFound) as exc:
            await interaction.followup.send(str(exc) if isinstance(exc, ValueError) else "Участник не найден.", ephemeral=True)
        except discord.HTTPException:
            await interaction.followup.send("Discord не применил изменение. Если переименовывал недавно, подожди несколько минут.", ephemeral=True)


class VoicePanel(discord.ui.View):
    def __init__(self, features):
        super().__init__(timeout=None)
        self.features = features

    async def interaction_check(self, interaction):
        try:
            self.features.owned_room(interaction)
            return True
        except ValueError as exc:
            await interaction.response.send_message(str(exc), ephemeral=True)
            return False

    @discord.ui.button(label="Название", emoji="✏️", style=discord.ButtonStyle.secondary, custom_id="baconira:voice:name", row=0)
    async def rename(self, interaction, button):
        await interaction.response.send_modal(RoomModal(self.features, "name"))

    @discord.ui.button(label="Лимит", emoji="👥", style=discord.ButtonStyle.secondary, custom_id="baconira:voice:limit", row=0)
    async def limit(self, interaction, button):
        await interaction.response.send_modal(RoomModal(self.features, "limit"))

    async def set_locked(self, interaction, locked):
        await interaction.response.defer(ephemeral=True)
        async with self.features.client.lock(interaction.guild.id):
            state, room, record = self.features.owned_room(interaction)
            ow = room.overwrites_for(interaction.guild.default_role)
            ow.connect = not locked
            await room.set_permissions(interaction.guild.default_role, overwrite=ow, reason="Владелец изменил доступ")
            record["locked"] = locked
            self.features.write(interaction.guild.id, state)
        await interaction.followup.send("🔒 Комната закрыта для новых подключений." if locked else "🔓 Комната открыта.", ephemeral=True)

    @discord.ui.button(label="Закрыть", emoji="🔒", style=discord.ButtonStyle.secondary, custom_id="baconira:voice:lock", row=0)
    async def lock(self, interaction, button):
        await self.set_locked(interaction, True)

    @discord.ui.button(label="Открыть", emoji="🔓", style=discord.ButtonStyle.success, custom_id="baconira:voice:unlock", row=0)
    async def unlock(self, interaction, button):
        await self.set_locked(interaction, False)

    @discord.ui.button(label="Пригласить", emoji="➕", style=discord.ButtonStyle.secondary, custom_id="baconira:voice:invite", row=1)
    async def invite(self, interaction, button):
        await interaction.response.send_modal(RoomModal(self.features, "invite"))

    @discord.ui.button(label="Передать", emoji="👑", style=discord.ButtonStyle.secondary, custom_id="baconira:voice:transfer", row=1)
    async def transfer(self, interaction, button):
        await interaction.response.send_modal(RoomModal(self.features, "transfer"))

    async def on_error(self, interaction, error, item):
        text = "Комната недоступна или Discord отклонил действие. Попробуй ещё раз."
        if interaction.response.is_done():
            await interaction.followup.send(text, ephemeral=True)
        else:
            await interaction.response.send_message(text, ephemeral=True)
