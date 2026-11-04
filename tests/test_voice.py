import asyncio
import copy
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock

import test_bot
import bot
from features import Features, clean_name, voice_overwrites


class Voice(test_bot.Channel):
    def __init__(self, cid, name, category=None, **kwargs):
        super().__init__(cid, name, category, **kwargs)
        self.members = []
        self.user_limit = kwargs.get('user_limit', 0)
        self.delete = AsyncMock()

    def overwrites_for(self, target):
        return copy.copy(self.overwrites.get(target, bot.discord.PermissionOverwrite()))

    async def set_permissions(self, target, overwrite=None, **kwargs):
        self.overwrites[target] = overwrite


class VoiceGuild(test_bot.Guild):
    def __init__(self):
        super().__init__()
        self.voice_channels = []

    @property
    def channels(self):
        return super().channels + self.voice_channels

    async def create_voice_channel(self, name, **kwargs):
        room = Voice(self.new_id(), name, **kwargs)
        self.voice_channels.append(room)
        return room


class Member:
    def __init__(self, guild, uid):
        self.guild, self.id = guild, uid
        self.display_name, self.bot = 'Игрок', False
        self.move_to = AsyncMock()
        self.voice = None


class VoiceTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.guild = VoiceGuild()
        self.cat = test_bot.Channel(800, 'Voice')
        self.guild.categories.append(self.cat)
        self.creator = await self.guild.create_voice_channel('Create', category=self.cat)
        self.state = {'voice_category': self.cat.id, 'voice_creator': self.creator.id, 'voice_rooms': {}}
        self.client = SimpleNamespace(lock=lambda gid: self.lock)
        self.lock = asyncio.Lock()
        self.features = Features(self.client, '.', lambda gid: copy.deepcopy(self.state),
            self.write, lambda g: True, AsyncMock(), bot.TicketPanel, bot.CitizenPanel)
        self.member = Member(self.guild, 77)

    def write(self, gid, state):
        self.state = copy.deepcopy(state)

    async def asyncTearDown(self):
        for task in list(self.features.deletions.values()):
            task.cancel()
        await asyncio.sleep(0)

    async def test_join_creates_only_one_room_and_moves_member(self):
        event = (self.member, SimpleNamespace(channel=None), SimpleNamespace(channel=self.creator))
        await self.features.voice_changed(*event)
        self.assertEqual(len(self.state['voice_rooms']), 1)
        room = self.guild.voice_channels[-1]
        self.member.move_to.assert_awaited_with(room, reason='Перенос в созданную комнату')
        await self.features.voice_changed(*event)
        self.assertEqual(len(self.guild.voice_channels), 2)
        self.member.move_to.assert_awaited_with(room, reason='Возврат в свою комнату')

    async def test_only_owner_can_control_room(self):
        room = await self.guild.create_voice_channel('Room', category=self.cat)
        self.state['voice_rooms'][str(room.id)] = {'owner': 77, 'locked': False}
        self.member.voice = SimpleNamespace(channel=room)
        interaction = SimpleNamespace(guild=self.guild, user=self.member)
        self.assertEqual(self.features.owned_room(interaction)[1], room)
        stranger = Member(self.guild, 88)
        stranger.voice = SimpleNamespace(channel=room)
        with self.assertRaises(ValueError):
            self.features.owned_room(SimpleNamespace(guild=self.guild, user=stranger))

    async def test_lock_and_unlock_persist_and_preserve_view_access(self):
        room = await self.guild.create_voice_channel('Room', category=self.cat,
            overwrites=voice_overwrites(self.guild, self.member))
        self.state['voice_rooms'][str(room.id)] = {'owner': 77, 'locked': False}
        self.member.voice = SimpleNamespace(channel=room)
        interaction = SimpleNamespace(guild=self.guild, user=self.member,
            response=SimpleNamespace(defer=AsyncMock()), followup=SimpleNamespace(send=AsyncMock()))
        await self.features.voice_panel.set_locked(interaction, True)
        self.assertFalse(room.overwrites[self.guild.default_role].connect)
        self.assertTrue(room.overwrites[self.guild.default_role].view_channel)
        self.assertTrue(room.overwrites[self.member].connect)
        self.assertTrue(self.state['voice_rooms'][str(room.id)]['locked'])
        await self.features.voice_panel.set_locked(interaction, False)
        self.assertTrue(room.overwrites[self.guild.default_role].connect)

    async def test_cleanup_never_deletes_untracked_or_occupied_channels(self):
        room = await self.guild.create_voice_channel('Room', category=self.cat)
        await self.features.cleanup_room(self.guild, room.id, delay=0)
        room.delete.assert_not_awaited()
        self.state['voice_rooms'][str(room.id)] = {'owner': 77}
        room.members = [self.member]
        await self.features.cleanup_room(self.guild, room.id, delay=0)
        room.delete.assert_not_awaited()
        room.members = []
        await self.features.cleanup_room(self.guild, room.id, delay=0)
        room.delete.assert_awaited_once()
        self.assertNotIn(str(room.id), self.state['voice_rooms'])

    async def test_return_cancels_pending_empty_room_cleanup(self):
        room = await self.guild.create_voice_channel('Room', category=self.cat)
        self.state['voice_rooms'][str(room.id)] = {'owner': 77}
        self.features.schedule_cleanup(self.guild, room.id)
        await self.features.voice_changed(self.member, SimpleNamespace(channel=None), SimpleNamespace(channel=room))
        self.assertNotIn(room.id, self.features.deletions)
        room.delete.assert_not_awaited()

    def test_name_sanitization(self):
        self.assertEqual(clean_name('  Моя\n  комната  '), '🔊 Моя комната')
        for name in (' ', 'a' * 81):
            with self.assertRaises(ValueError): clean_name(name)


if __name__ == '__main__':
    unittest.main()
