import asyncio
import copy
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import test_bot
import discord
import proposals
from proposals import ProposalService, proposal_permissions, forum_tags


class Forum(test_bot.Channel):
    def __init__(self, cid, name):
        super().__init__(cid, name)
        self.available_tags = []

    async def edit(self, **kwargs):
        for key, value in kwargs.items():
            setattr(self, key, value)
        return self


class ProposalTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.guild = test_bot.Guild()
        self.guild.features = ['COMMUNITY']
        self.guild.forums = []
        self.guild.edit = AsyncMock()
        self.state = {'channels': {}, 'categories': {'ГОРОД': 11, 'ГОСУДАРСТВО': 12}}
        self.lock = asyncio.Lock()
        self.create_forum = AsyncMock(side_effect=self.make_forum)
        self.guild.create_forum = self.create_forum
        self.service = ProposalService(SimpleNamespace(lock=lambda gid: self.lock),
            lambda gid: copy.deepcopy(self.state), self.write, lambda g: True, lambda m: False,
            lambda *a: {}, lambda *a: {}, AsyncMock())
        self.patcher = patch.object(proposals.discord, 'ForumChannel', Forum)
        self.patcher.start()
        self.addCleanup(self.patcher.stop)

    def write(self, gid, state): self.state = copy.deepcopy(state)

    async def make_forum(self, name, **kwargs):
        forum = Forum(800, name)
        await forum.edit(**kwargs)
        self.guild.forums.append(forum)
        # Fake Guild.get_channel searches this collection (real Guild caches all channel types).
        self.guild.text_channels.append(forum)
        return forum

    def test_residents_create_native_posts_and_only_staff_manage_tags(self):
        names = ['Гражданин', 'гость', 'Император', 'Регент', 'Сенаторы']
        roles = {name: test_bot.Role(90+i, name) for i, name in enumerate(names)}
        perms = proposal_permissions(self.guild, roles)
        self.assertFalse(perms[self.guild.default_role].send_messages)
        self.assertFalse(perms[self.guild.default_role].manage_threads)
        self.assertNotIn(roles['гость'], perms)
        for name in ['Гражданин', 'Сенаторы']:
            self.assertTrue(perms[roles[name]].send_messages)
            self.assertTrue(perms[roles[name]].send_messages_in_threads)
            self.assertFalse(perms[roles[name]].manage_threads)
        for name in ['Император', 'Регент']:
            self.assertTrue(perms[roles[name]].manage_threads)

    def test_decision_tags_moderated_and_ids_survive_reconfiguration(self):
        tags = forum_tags()
        for idx, tag in enumerate(tags): tag.id = 100+idx
        tags[1].moderated = False
        updated = forum_tags(tags)
        self.assertEqual([tag.id for tag in updated], [100,101,102])
        self.assertEqual([tag.moderated for tag in updated], [False,True,True])
        extra = discord.ForumTag(name='Фермы'); extra.id=800
        self.assertEqual(forum_tags(tags+[extra])[-1].id, 800)

    async def test_native_forum_replaces_legacy_without_deleting_history(self):
        old = test_bot.Channel(700, 'old')
        self.guild.text_channels.append(old)
        self.state['channels']['идеи'] = old.id
        forum = await self.service.prepare(self.guild)
        self.assertEqual(self.state['proposal_legacy_channel'], 700)
        self.assertEqual(self.state['channels']['идеи'], forum.id)
        self.assertTrue(forum.require_tag)
        self.assertEqual(forum.default_layout, discord.ForumLayoutType.gallery_view)
        self.assertIn(old, self.guild.text_channels)
        self.create_forum.assert_awaited_once()
        await self.service.prepare(self.guild)
        self.create_forum.assert_awaited_once()
        self.assertEqual(self.state['proposals_version'], 2)

    async def test_missing_state_reuses_existing_native_forum(self):
        forum = await self.make_forum(proposals.NAME)
        await self.service.prepare(self.guild)
        self.create_forum.assert_not_awaited()
        self.assertEqual(self.state['channels']['идеи'], forum.id)

    async def test_community_preserves_stronger_verification_and_existing_channels(self):
        self.guild.features = []
        self.guild.verification_level = discord.VerificationLevel.high
        self.guild.explicit_content_filter = discord.ContentFilter.disabled
        self.guild.rules_channel = self.guild.public_updates_channel = None
        rules = test_bot.Channel(20,'rules'); logs = test_bot.Channel(21,'logs')
        self.guild.text_channels.extend([rules,logs])
        self.state['channels'].update({'правила':20, 'логи':21})
        await self.service.prepare(self.guild)
        args = self.guild.edit.call_args.kwargs
        self.assertTrue(args['community'])
        self.assertIs(args['rules_channel'], rules)
        self.assertIs(args['public_updates_channel'], logs)
        self.assertEqual(args['verification_level'], discord.VerificationLevel.high)
        self.assertEqual(args['explicit_content_filter'], discord.ContentFilter.all_members)
        self.assertEqual(self.state['community_before']['features'], [])
        self.assertNotIn('discoverable', args)


if __name__=='__main__': unittest.main()
