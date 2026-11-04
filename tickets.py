"""One active ticket per person; verified private HTML archive before deletion."""
from __future__ import annotations

import asyncio
from datetime import datetime, timezone

import discord

from transcripts import export_transcript, upload_files

KINDS = {"question": "Вопрос / помощь", "report": "Жалоба", "citizen": "Гражданство", "ticket": "Вопрос / помощь"}


def now():
    return datetime.now(timezone.utc).isoformat()


class TicketService:
    def __init__(self, client, root, read, write, allowed, staff, overwrites, roles, log, safe_role):
        self.client, self.root, self.read, self.write = client, root, read, write
        self.allowed, self.staff, self.overwrites, self.roles = allowed, staff, overwrites, roles
        self.log, self.safe_role = log, safe_role

    def normalize(self, state, cid, case, channel=None):
        if "number" not in case:
            state["ticket_counter"] = state.get("ticket_counter", 0) + 1
            case["number"] = state["ticket_counter"]
        case.setdefault("status", "legacy_closed" if case.get("closed") else "open")
        case.setdefault("created_at", channel.created_at.isoformat() if channel else now())
        case.setdefault("subject", KINDS.get(case["kind"], case["kind"]))
        return case

    def active(self, guild, state, uid):
        for cid, case in state.get("cases", {}).items():
            # Applies across help, complaints AND citizenship; not one of each.
            if case["owner"] == uid and not case.get("source_deleted") and guild.get_channel(int(cid)):
                if case.get("status") != "archived" or not case.get("source_deleted"):
                    return guild.get_channel(int(cid))
        return None

    def case_embed(self, case):
        card = discord.Embed(title=f"🎫 Тикет #{case['number']:04d} · {KINDS.get(case['kind'], case['kind'])}",
            description=f"**Автор:** <@{case['owner']}>\n**Тема:** {discord.utils.escape_markdown(case.get('subject', '—'))}\n"
                        f"**Статус:** {'в работе' if case.get('claimed_by') else 'ожидает администрацию'}\n"
                        f"**Ответственный:** {('<@' + str(case['claimed_by']) + '>') if case.get('claimed_by') else 'не назначен'}",
            colour=0xD4AF37)
        for name, value in case.get("fields", []):
            card.add_field(name=name, value=discord.utils.escape_markdown(str(value))[:1024] or "—", inline=False)
        card.set_footer(text="Закрытие → приватный HTML-архив → удаление канала. Вложения сохраняются.")
        return card

    async def refresh_controls(self, guild, state, channel, case):
        old = None
        if case.get("control_message"):
            try:
                old = await channel.fetch_message(case["control_message"])
            except discord.NotFound:
                pass
        view = TicketActions(self, citizen=case["kind"] == "citizen", accepted=case.get("accepted", False))
        if old:
            await old.edit(embed=self.case_embed(case), view=view)
        else:
            old = await channel.send(embed=self.case_embed(case), view=view)
            case["control_message"] = old.id
            self.write(guild.id, state)

    async def prepare(self, guild):
        if not self.allowed(guild):
            return
        async with self.client.lock(guild.id):
            state = self.read(guild.id)
            roles = self.roles(guild, state)
            private = self.overwrites(guild, roles, "logs")
            category = guild.get_channel(state.get("tickets_category", 0))
            if not category:
                category = await guild.create_category("🎫 ОТКРЫТЫЕ ТИКЕТЫ", position=len(guild.categories), overwrites=private, reason="Система тикетов Baconira")
                state["tickets_category"] = category.id
                self.write(guild.id, state)
            archive_area = guild.get_channel(state.get("archive_category", 0))
            if not archive_area:
                archive_area = await guild.create_category("🗄 АРХИВ", position=len(guild.categories), overwrites=private, reason="Приватный архив тикетов")
                state["archive_category"] = archive_area.id
                self.write(guild.id, state)
            archive = guild.get_channel(state.get("ticket_archive", 0))
            if not archive:
                archive = await guild.create_text_channel("📁・архив-тикетов", category=archive_area,
                    topic="Закрытые тикеты: HTML-переписка с копиями вложений, автор, ответственный и причина закрытия. Только руководство и администраторы.",
                    overwrites=private, reason="Архив HTML-переписок")
                state["ticket_archive"] = archive.id
                self.write(guild.id, state)
            portal = guild.get_channel(state["channels"]["тикеты"])
            await portal.edit(topic="Выбери тип обращения в меню: вопрос или жалоба. Один активный тикет на участника; закрытые тикеты сохраняются в HTML и удаляются из списка каналов.")
            card = discord.Embed(title="🎫 Поддержка Baconira", colour=0xD4AF37,
                description="Выбери тип обращения в меню ниже и заполни форму.\n\n"
                    "**❓ Вопрос / помощь** — проблемы, просьбы и вопросы администрации.\n"
                    "**⚠️ Жалоба** — ситуация, требующая разбора; приложи факты.\n\n"
                    "**Один активный тикет на человека**, включая анкету на гражданство. Повторная заявка покажет ссылку на уже открытый тикет.\n\n"
                    "Переписку видят автор и администрация. После закрытия HTML с вложениями сохраняется в приватном архиве; канал удаляется только после проверки сохранения.")
            card.set_footer(text="Не нужно создавать отдельные обращения по одному вопросу — продолжай свой открытый тикет.")
            panel_id = state.setdefault("panels", {}).get("тикеты")
            panel = None
            if panel_id:
                try:
                    panel = await portal.fetch_message(panel_id)
                except discord.NotFound:
                    pass
            if panel:
                await panel.edit(content=None, embed=card, view=TicketPanel(self))
            else:
                panel = await portal.send(embed=card, view=TicketPanel(self))
                state["panels"]["тикеты"] = panel.id
            recovery = []
            for cid, case in state.get("cases", {}).items():
                channel = guild.get_channel(int(cid))
                if not channel:
                    continue
                self.normalize(state, cid, case, channel)
                if case.get("closed") or case["status"] in {"legacy_closed", "archiving", "archived"}:
                    recovery.append(int(cid))
                elif state.get("tickets_version") != 1:
                    await channel.edit(category=category, reason="Активный тикет в выделенном разделе")
                    await self.refresh_controls(guild, state, channel, case)
            state["tickets_version"] = 1
            self.write(guild.id, state)
        for cid in recovery:
            try:
                await self.archive_case(guild, cid, self.client.user.id, "Перенос ранее закрытого обращения в HTML-архив")
            except (discord.HTTPException, ValueError, OSError) as error:
                await self.log(guild, f"⚠️ Тикет {cid} оставлен на месте: архивирование не завершено ({type(error).__name__}).")

    async def open_case(self, interaction, kind, fields):
        guild = interaction.guild
        if not self.allowed(guild):
            return await interaction.response.send_message("Эта система работает только в Baconira.", ephemeral=True)
        await interaction.response.defer(ephemeral=True)
        async with self.client.lock(guild.id):
            state = self.read(guild.id)
            existing = self.active(guild, state, interaction.user.id)
            if existing:
                return await interaction.followup.send(f"У тебя уже есть тикет: {existing.mention}. Продолжи обсуждение там.", ephemeral=True)
            last = state.setdefault("ticket_cooldowns", {}).get(str(interaction.user.id))
            if last and (datetime.now(timezone.utc) - datetime.fromisoformat(last)).total_seconds() < 60:
                return await interaction.followup.send("Подожди минуту между созданием тикетов.", ephemeral=True)
            category = guild.get_channel(state.get("tickets_category", 0))
            if not category:
                return await interaction.followup.send("Система тикетов ещё запускается. Попробуй через несколько секунд.", ephemeral=True)
            number = state.get("ticket_counter", 0) + 1
            channel = await guild.create_text_channel(f"🎫・тикет-{number:04d}", category=category,
                overwrites=self.overwrites(guild, self.roles(guild, state), "case", interaction.user),
                topic=f"Baconira | {KINDS[kind]} | Автор {interaction.user.id} | #{number:04d}", reason="Приватный тикет")
            record = {"owner": interaction.user.id, "kind": kind, "number": number, "closed": False,
                      "status": "open", "created_at": now(), "subject": str(fields[0][1])[:100],
                      "fields": [(name, str(value)) for name, value in fields], "claimed_by": None}
            state["ticket_counter"] = number
            state.setdefault("cases", {})[str(channel.id)] = record
            state["ticket_cooldowns"][str(interaction.user.id)] = now()
            self.write(guild.id, state)
            await self.refresh_controls(guild, state, channel, record)
            await interaction.followup.send(f"Тикет **#{number:04d}** открыт: {channel.mention}", ephemeral=True)
        await self.log(guild, f"🎫 Открыт тикет #{number:04d}; автор {interaction.user.id}; тип {KINDS[kind]}.")

    def get_case(self, interaction, require_staff=False):
        if not self.allowed(interaction.guild):
            raise ValueError("Недоступно на этом сервере.")
        state = self.read(interaction.guild.id)
        case = state.get("cases", {}).get(str(interaction.channel_id))
        if not case:
            raise ValueError("Это не канал тикета.")
        if require_staff and not self.staff(interaction.user):
            raise ValueError("Действие доступно только администрации.")
        if not self.staff(interaction.user) and case["owner"] != interaction.user.id:
            raise ValueError("Доступно только автору и администрации.")
        return state, case

    async def archive_case(self, guild, cid, actor, reason, notify=None):
        async with self.client.lock(guild.id):
            state = self.read(guild.id)
            channel = guild.get_channel(cid)
            case = state.get("cases", {}).get(str(cid))
            if not channel or not case:
                raise ValueError("Тикет уже закрыт или не найден.")
            self.normalize(state, cid, case, channel)
            archive = guild.get_channel(state.get("ticket_archive", 0))
            if not archive:
                raise ValueError("Приватный архив недоступен. Канал тикета сохранён.")
            application = await self.client.application_info()
            if not (application.flags.gateway_message_content or application.flags.gateway_message_content_limited):
                raise ValueError("Message Content Intent отключён: Discord скроет текст переписки. Канал сохранён.")
            case.update(status="archiving", closed_by=case.get("closed_by") or actor,
                        close_reason=case.get("close_reason") or reason)
            self.write(guild.id, state)
            # Keep current participants' view permissions, freeze ordinary writing.
            ow = channel.overwrites
            for target, permissions in ow.items():
                if target.id != guild.me.id:
                    permissions.send_messages = False
                    permissions.send_messages_in_threads = False
                    permissions.create_public_threads = False
                    permissions.create_private_threads = False
            await channel.edit(overwrites=ow, reason="Архивирование тикета")
            result = await export_transcript(channel, case, case["closed_by"], case["close_reason"], self.root)
            payload = upload_files(result, guild.filesize_limit)
            card = discord.Embed(title=f"🗄 Тикет #{case['number']:04d} · {KINDS.get(case['kind'], case['kind'])}",
                description=f"**Тема:** {discord.utils.escape_markdown(case.get('subject', '—'))}\n"
                    f"**Автор:** <@{case['owner']}> (`{case['owner']}`)\n"
                    f"**Закрыл:** <@{case['closed_by']}>\n"
                    f"**Причина:** {discord.utils.escape_markdown(case['close_reason'])}\n"
                    f"**Сообщений:** {result['count']}\n\nHTML можно скачать и открыть в браузере. Вложения встроены в файл. Для больших архивов приложены ZIP/части и manifest.json.",
                colour=0xD4AF37, timestamp=datetime.now(timezone.utc))
            card.set_footer(text=f"Источник: {cid} • Архив доступен только администрации")
            posts = case.setdefault("archive_posts", [])
            for index in range(0, len(payload), 10):
                batch = payload[index:index + 10]
                post_index = index // 10
                existing = None
                if post_index < len(posts):
                    try:
                        existing = await archive.fetch_message(posts[post_index])
                    except discord.NotFound:
                        pass
                files = [discord.File(path) for path in batch]
                try:
                    if existing:
                        message = await existing.edit(embed=card, attachments=files)
                    else:
                        message = await archive.send(embed=card, files=files)
                        if post_index < len(posts):
                            posts[post_index] = message.id
                        else:
                            posts.append(message.id)
                        self.write(guild.id, state)
                finally:
                    for file in files:
                        file.close()
                proof = await archive.fetch_message(message.id)
                expected = {(p.name, p.stat().st_size) for p in batch}
                if not expected.issubset({(a.filename, a.size) for a in proof.attachments}):
                    raise ValueError("Discord не подтвердил все файлы архива. Исходный канал не удалён.")
            latest = [m async for m in channel.history(limit=1)]
            if (latest[0].id if latest else None) != result["last_id"]:
                raise ValueError("Во время экспорта появились новые сообщения. Канал сохранён; повтори закрытие, чтобы обновить HTML.")
            case.update(status="archived", closed=True, archive_url=f"https://discord.com/channels/{guild.id}/{archive.id}/{posts[0]}",
                        transcript_path=str(result["html"]), archived_at=now(), message_count=result["count"])
            self.write(guild.id, state)
            if notify:
                await notify(case)
            # This is the only deletion path: full local copy + confirmed Discord uploads.
            await channel.delete(reason=f"Тикет #{case['number']:04d}: HTML и вложения сохранены в архиве")
            case["source_deleted"] = True
            self.write(guild.id, state)
        await self.log(guild, f"🗄 Тикет #{case['number']:04d} архивирован; канал удалён после проверки HTML. {case['archive_url']}")
        return case


class NewTicket(discord.ui.Modal):
    def __init__(self, service, kind):
        super().__init__(title=KINDS[kind])
        self.service, self.kind = service, kind
        self.subject = discord.ui.TextInput(label="Тема", max_length=100)
        self.details = discord.ui.TextInput(label="Опиши ситуацию и нужную помощь", style=discord.TextStyle.paragraph, max_length=1000)
        self.add_item(self.subject)
        self.add_item(self.details)

    async def on_submit(self, interaction):
        await self.service.open_case(interaction, self.kind, [("Тема", self.subject.value), ("Описание", self.details.value)])


class TicketKind(discord.ui.Select):
    def __init__(self, service):
        self.service = service
        super().__init__(placeholder="Выбери тип тикета…", custom_id="baconira:ticket:kind", options=[
            discord.SelectOption(label="Вопрос / помощь", value="question", emoji="❓"),
            discord.SelectOption(label="Жалоба", value="report", emoji="⚠️")])

    async def callback(self, interaction):
        state = self.service.read(interaction.guild.id)
        existing = self.service.active(interaction.guild, state, interaction.user.id)
        if existing:
            return await interaction.response.send_message(f"Твой активный тикет: {existing.mention}", ephemeral=True)
        await interaction.response.send_modal(NewTicket(self.service, self.values[0]))


class TicketPanel(discord.ui.View):
    def __init__(self, service):
        super().__init__(timeout=None)
        self.service = service
        self.add_item(TicketKind(service))

    @discord.ui.button(label="Мой тикет", emoji="🎫", style=discord.ButtonStyle.secondary, custom_id="baconira:ticket:mine", row=1)
    async def mine(self, interaction, button):
        state = self.service.read(interaction.guild.id)
        room = self.service.active(interaction.guild, state, interaction.user.id)
        await interaction.response.send_message(f"Твой тикет: {room.mention}" if room else "Открытого тикета нет. Выбери тип обращения в меню.", ephemeral=True)


class CloseTicket(discord.ui.Modal, title="Закрыть и сохранить в архив"):
    reason = discord.ui.TextInput(label="Причина закрытия / итог", style=discord.TextStyle.paragraph, max_length=300)

    def __init__(self, service):
        super().__init__()
        self.service = service

    async def on_submit(self, interaction):
        self.service.get_case(interaction)
        await interaction.response.defer(ephemeral=True)

        async def notify(case):
            await interaction.followup.send(f"Тикет #{case['number']:04d}: HTML и вложения сохранены в приватном архиве. Канал закрывается.", ephemeral=True)
        try:
            await self.service.archive_case(interaction.guild, interaction.channel_id, interaction.user.id, self.reason.value, notify)
        except (ValueError, OSError, discord.HTTPException) as error:
            text = str(error) if isinstance(error, ValueError) else "Архивирование не завершено. Канал не удалён; сообщи администрации и повтори закрытие."
            await interaction.followup.send(text, ephemeral=True)


class TicketActions(discord.ui.View):
    def __init__(self, service, citizen=False, accepted=False):
        super().__init__(timeout=None)
        self.service = service
        if citizen:
            button = discord.ui.Button(label="Гражданство выдано" if accepted else "Принять и архивировать", emoji="🪪",
                style=discord.ButtonStyle.success, custom_id="baconira:accept", disabled=accepted)
            button.callback = self.accept
            self.add_item(button)

    async def interaction_check(self, interaction):
        try:
            self.service.get_case(interaction)
            return True
        except ValueError as error:
            await interaction.response.send_message(str(error), ephemeral=True)
            return False

    @discord.ui.button(label="Взять / снять", emoji="🙋", style=discord.ButtonStyle.secondary, custom_id="baconira:claim")
    async def claim(self, interaction, button):
        try:
            self.service.get_case(interaction, require_staff=True)
        except ValueError as error:
            return await interaction.response.send_message(str(error), ephemeral=True)
        await interaction.response.defer(ephemeral=True)
        async with self.service.client.lock(interaction.guild.id):
            state, case = self.service.get_case(interaction, require_staff=True)
            if case.get("claimed_by") not in (None, interaction.user.id):
                return await interaction.followup.send(f"Тикетом уже занимается <@{case['claimed_by']}>.", ephemeral=True)
            case["claimed_by"] = None if case.get("claimed_by") else interaction.user.id
            self.service.write(interaction.guild.id, state)
            await self.service.refresh_controls(interaction.guild, state, interaction.channel, case)
        await interaction.followup.send("Назначение обновлено.", ephemeral=True)

    @discord.ui.button(label="Закрыть и архивировать", emoji="🗄", style=discord.ButtonStyle.danger, custom_id="baconira:close")
    async def close(self, interaction, button):
        await interaction.response.send_modal(CloseTicket(self.service))

    async def accept(self, interaction):
        try:
            self.service.get_case(interaction, require_staff=True)
        except ValueError as error:
            return await interaction.response.send_message(str(error), ephemeral=True)
        await interaction.response.defer(ephemeral=True)
        async with self.service.client.lock(interaction.guild.id):
            state, case = self.service.get_case(interaction, require_staff=True)
            if case["kind"] != "citizen" or case.get("status") != "open":
                return await interaction.followup.send("Это не открытая анкета на гражданство.", ephemeral=True)
            guild = interaction.guild
            role = guild.get_role(state["roles"]["Гражданин"])
            if not self.service.safe_role(role, guild):
                return await interaction.followup.send("Проверь права и положение роли Гражданин.", ephemeral=True)
            member = await guild.fetch_member(case["owner"])
            await member.add_roles(role, reason=f"Анкета #{case['number']:04d} принята")
            guest = guild.get_role(state["roles"]["гость"])
            if guest and guest in member.roles:
                await member.remove_roles(guest, reason="Получено гражданство")
            case["accepted"] = True
            self.service.write(guild.id, state)
            await interaction.channel.send(f"✅ Анкета принята. <@{member.id}> получил роль «Гражданин». Решение: <@{interaction.user.id}>.")
        async def notify(record):
            await interaction.followup.send("Гражданство выдано. Анкета сохранена в HTML-архиве; канал закрывается.", ephemeral=True)
        await self.service.archive_case(guild, interaction.channel_id, interaction.user.id, "Гражданство одобрено", notify)

    async def on_error(self, interaction, error, item):
        text = "Действие не завершено. Канал сохраняется; проверь права и доступность архива."
        if interaction.response.is_done():
            await interaction.followup.send(text, ephemeral=True)
        else:
            await interaction.response.send_message(text, ephemeral=True)
