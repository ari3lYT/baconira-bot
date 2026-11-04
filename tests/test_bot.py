import os
import asyncio
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import bot


class Role:
    def __init__(self, rid, name, position=0, permissions=None):
        self.id, self.name, self.position = rid, name, position
        self.permissions = permissions or bot.discord.Permissions.none()
        self.managed = False

    def __lt__(self, other):
        return self.position < other.position


class Channel:
    def __init__(self, cid, name, category=None, **kwargs):
        self.id, self.name, self.category = cid, name, category
        self.category_id = category.id if category else None
        self.type = 'text' if category else 'category'
        self.position = kwargs.get('position', 0)
        self.topic = kwargs.get('topic')
        self.overwrites = kwargs.get('overwrites', {})
        self.messages = {}

    async def edit(self, **kwargs):
        for k, v in kwargs.items():
            if k != 'reason':
                setattr(self, k, v)
        return self

    async def send(self, *args, **kwargs):
        m = SimpleNamespace(id=len(self.messages) + 1, edit=AsyncMock())
        self.messages[m.id] = m
        return m

    async def fetch_message(self, mid):
        return self.messages[mid]


class Guild:
    def __init__(self):
        self.id, self.name = 1234, 'Сервер baconira'
        self.default_role = Role(1, '@everyone')
        self.roles = [self.default_role]
        self.categories, self.text_channels = [], []
        self.me = Role(2, 'Bot', 100)
        self.me.top_role = self.me
        self.me.guild_permissions = bot.discord.Permissions(administrator=True, manage_channels=True, manage_roles=True, send_messages=True)
        self.next_id = 10
        self.created = 0
        self.delete = AsyncMock(side_effect=AssertionError('Deletion forbidden'))

    @property
    def channels(self):
        return self.categories + self.text_channels

    def new_id(self):
        self.next_id += 1
        return self.next_id

    def get_role(self, rid):
        return next((r for r in self.roles if r.id == rid), None)

    def get_channel(self, cid):
        return next((c for c in self.channels if c.id == cid), None)

    async def create_role(self, name, **kwargs):
        r = Role(self.new_id(), name, 1, kwargs['permissions'])
        self.roles.append(r)
        self.created += 1
        return r

    async def edit_role_positions(self, positions, **kwargs):
        for r, pos in positions.items():
            r.position = pos

    async def create_category(self, name, **kwargs):
        c = Channel(self.new_id(), name, **kwargs)
        self.categories.append(c)
        self.created += 1
        return c

    async def create_text_channel(self, name, **kwargs):
        c = Channel(self.new_id(), name, **kwargs)
        self.text_channels.append(c)
        self.created += 1
        return c


class SetupTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.patch = patch.object(bot, 'DATA', Path(self.temp.name))
        self.patch.start()
        self.guild = Guild()
        self.env = patch.dict(os.environ, {'DISCORD_GUILD_ID': str(self.guild.id)})
        self.env.start()
        self.addCleanup(self.env.stop)

    async def asyncTearDown(self):
        self.patch.stop()
        self.temp.cleanup()

    async def test_complete_setup_and_idempotency(self):
        self.guild.edit_role_positions = AsyncMock(side_effect=AssertionError('Absolute role positions can cross the bot role'))
        state = await bot.configure(self.guild)
        self.assertEqual(len(state['roles']), 9)
        self.assertEqual(len(state['channels']), 14)
        self.assertEqual(len(self.guild.categories), 3)
        self.assertTrue(all(r.permissions.value == 0 for r in self.guild.roles))
        self.assertIsNone(self.guild.get_channel(state['channels']['лор']).topic)
        self.assertEqual(len(self.guild.get_channel(state['channels']['лор']).messages), 0)
        count = self.guild.created
        first_ids = state['channels'].copy()
        again = await bot.configure(self.guild)
        self.assertEqual(self.guild.created, count)
        self.assertEqual(again['channels'], first_ids)
        self.assertEqual(len(self.guild.get_channel(state['channels']['тикеты']).messages), 1)
        self.assertTrue(list(Path(self.temp.name).glob('backup-*.json')))
        self.guild.edit_role_positions.assert_not_called()

    async def test_permissions_hide_senate_and_logs(self):
        state = await bot.configure(self.guild)
        senate = self.guild.get_channel(state['channels']['сенат'])
        roles = bot.get_roles(self.guild, state)
        self.assertFalse(senate.overwrites[self.guild.default_role].view_channel)
        self.assertTrue(senate.overwrites[roles['Сенаторы']].view_channel)
        self.assertNotIn(roles['Гражданин'], senate.overwrites)
        self.assertNotIn(roles['гость'], senate.overwrites)
        logs = self.guild.get_channel(state['channels']['логи'])
        self.assertNotIn(roles['Сенаторы'], logs.overwrites)
        self.assertFalse(logs.overwrites[self.guild.default_role].view_channel)
        news = self.guild.get_channel(state['channels']['новости'])
        self.assertFalse(news.overwrites[self.guild.default_role].send_messages)
        self.assertFalse(news.overwrites[self.guild.default_role].send_messages_in_threads)

    async def test_private_case_permissions(self):
        state = await bot.configure(self.guild)
        user = Role(987, 'Applicant')
        roles = bot.get_roles(self.guild, state)
        perms = bot.overwrites(self.guild, roles, 'case', user)
        self.assertFalse(perms[self.guild.default_role].view_channel)
        self.assertTrue(perms[user].view_channel)
        self.assertNotIn(roles['Сенаторы'], perms)
        self.assertNotIn(roles['Гражданин'], perms)

    async def test_wrong_guild_and_duplicates_fail_before_changes(self):
        self.guild.id = 9999
        with self.assertRaises(ValueError):
            await bot.configure(self.guild)
        self.assertEqual(self.guild.created, 0)
        self.guild.id = 1234
        self.guild.roles += [Role(3, 'Гражданин'), Role(4, 'Гражданин')]
        with self.assertRaises(ValueError):
            await bot.configure(self.guild)
        self.assertEqual(self.guild.created, 0)

    async def test_never_autoassign_existing_admin_role(self):
        role = Role(3, 'Гражданин', 2, bot.discord.Permissions(administrator=True))
        self.assertFalse(bot.safe_citizen_role(role, self.guild))
        role.permissions = bot.discord.Permissions.none()
        self.assertTrue(bot.safe_citizen_role(role, self.guild))
        role.position = 200
        self.assertFalse(bot.safe_citizen_role(role, self.guild))


if __name__ == '__main__':
    unittest.main()
