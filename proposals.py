"""Native Discord forum: member-created posts and moderator-only decision tags."""
from __future__ import annotations

import discord

NAME = "💡・предложения"
TOPIC = """Одна идея — одна публикация. Перед созданием посмотри, не предлагали ли это раньше.

В заголовке коротко назови идею. В описании расскажи:
• что предлагаешь;
• чем это полезно Baconira;
• как реализовать, какие нужны ресурсы и участники.
Можно прикреплять картинки и обсуждать идею в комментариях.

При создании выбери тег 🟡 «На рассмотрении». Император, Регент и администраторы меняют его на ✅ «Принято» или ❌ «Отклонено» через встроенное меню «Изменить теги».
Предлагать и обсуждать могут граждане и старшие роли. Гости читают."""
MEDIA_NAME = "📰・сми"
MEDIA_TOPIC = "Официальные публикации Baconira: репортажи, интервью, события и жизнь государства. Публикуют только Император и Регент; остальные читают."
STATUSES = {"review": ("🟡", "На рассмотрении"), "accepted": ("✅", "Принято"), "rejected": ("❌", "Отклонено")}


def forum_tags(existing=()):
    # Reuse IDs so reconnects and /настроить preserve tags already applied to posts.
    by_name = {tag.name: tag for tag in existing}
    result = []
    for key, (emoji, name) in STATUSES.items():
        tag = by_name.pop(name, None) or discord.ForumTag(name=name)
        tag.emoji = discord.PartialEmoji.from_str(emoji)
        tag.moderated = key != "review"
        result.append(tag)
    result.extend(by_name.values())
    return result


def proposal_permissions(guild, roles):
    result = {guild.default_role: discord.PermissionOverwrite(view_channel=True,
        send_messages=False, create_public_threads=False, create_private_threads=False,
        send_messages_in_threads=False, manage_threads=False, add_reactions=True,
        read_message_history=True)}
    for name, role in roles.items():
        if name != "гость":
            # In forums SEND_MESSAGES grants native Create Post; thread replies are separate.
            result[role] = discord.PermissionOverwrite(view_channel=True, send_messages=True,
                create_public_threads=True, create_private_threads=False,
                send_messages_in_threads=True, manage_threads=name in ("Император", "Регент"),
                attach_files=True, embed_links=True, add_reactions=True, read_message_history=True)
    result[guild.me] = discord.PermissionOverwrite(view_channel=True, send_messages=True,
        create_public_threads=True, send_messages_in_threads=True, manage_threads=True,
        read_message_history=True, attach_files=True, embed_links=True, add_reactions=True)
    return result


class ProposalService:
    def __init__(self, client, read, write, allowed, staff, roles, core_overwrites, log):
        self.client, self.read, self.write = client, read, write
        self.allowed, self.staff, self.roles = allowed, staff, roles
        self.core_overwrites, self.log = core_overwrites, log

    async def prepare(self, guild):
        if not self.allowed(guild):
            return
        async with self.client.lock(guild.id):
            state = self.read(guild.id)
            roles = self.roles(guild, state)
            if "COMMUNITY" not in guild.features:
                state.setdefault("community_before", {
                    "features": list(guild.features),
                    "verification_level": guild.verification_level.value,
                    "explicit_content_filter": guild.explicit_content_filter.value,
                    "rules_channel_id": guild.rules_channel.id if guild.rules_channel else None,
                    "public_updates_channel_id": guild.public_updates_channel.id if guild.public_updates_channel else None,
                })
                self.write(guild.id, state)
                await guild.edit(community=True,
                    rules_channel=guild.get_channel(state["channels"]["правила"]),
                    public_updates_channel=guild.get_channel(state["channels"]["логи"]),
                    verification_level=discord.VerificationLevel(max(1, guild.verification_level.value)),
                    explicit_content_filter=discord.ContentFilter.all_members,
                    reason="Штатный форум предложений: требования Community")
            channel = guild.get_channel(state["channels"].get("идеи", 0))
            if channel and not isinstance(channel, discord.ForumChannel):
                state.setdefault("proposal_legacy_channel", channel.id)
                self.write(guild.id, state)
                channel = None
            channel = channel or discord.utils.get(guild.forums, name=NAME)
            kwargs = dict(topic=TOPIC, overwrites=proposal_permissions(guild, roles),
                category=guild.get_channel(state["categories"]["ГОРОД"]),
                default_auto_archive_duration=10080, default_thread_slowmode_delay=5,
                default_sort_order=discord.ForumOrderType.latest_activity,
                default_layout=discord.ForumLayoutType.gallery_view,
                default_reaction_emoji="👍", reason="Штатный форум с карточками и тегами решений")
            if channel:
                kwargs.update(available_tags=forum_tags(channel.available_tags), require_tag=True)
                if channel.name != NAME:
                    kwargs["name"] = NAME
                channel = await channel.edit(**kwargs)
            else:
                channel = await guild.create_forum(NAME, available_tags=forum_tags(), **kwargs)
                # Persist the ID before the next request, so recovery never duplicates the forum.
                state["channels"]["идеи"] = channel.id
                self.write(guild.id, state)
                channel = await channel.edit(require_tag=True)
            state["channels"]["идеи"] = channel.id
            state["proposals_version"] = 2
            self.write(guild.id, state)
            # Forum posts and status changes use Discord's native UI even while the bot is offline.
            media = guild.get_channel(state["channels"].get("сми", 0))
            media_kwargs = dict(topic=MEDIA_TOPIC, overwrites=self.core_overwrites(guild, roles, "info"),
                                reason="СМИ: публикации Императора и Регента")
            media = media or discord.utils.get(guild.text_channels, name=MEDIA_NAME)
            if media:
                await media.edit(**media_kwargs)
            else:
                media = await guild.create_text_channel(MEDIA_NAME,
                    category=guild.get_channel(state["categories"]["ГОСУДАРСТВО"]), **media_kwargs)
            state["channels"]["сми"] = media.id
            self.write(guild.id, state)
            return channel
