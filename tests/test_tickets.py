import asyncio
import copy
import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import test_bot
import bot
from tickets import TicketService
from transcripts import render_html, upload_files


def stream(items):
    async def iterator():
        for item in items:
            yield item
    return iterator()


class TicketTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.guild = test_bot.Guild()
        self.guild.filesize_limit = 10_000_000
        self.source = test_bot.Channel(901, 'ticket', overwrites={self.guild.default_role: bot.discord.PermissionOverwrite(view_channel=False)})
        self.source.created_at = bot.discord.utils.utcnow()
        self.source.history = lambda **kwargs: stream([SimpleNamespace(id=100)])
        self.source.delete = AsyncMock()
        self.archive = test_bot.Channel(902, 'archive')
        self.archive.send = AsyncMock(return_value=SimpleNamespace(id=500))
        self.archive.fetch_message = AsyncMock(return_value=SimpleNamespace(id=500, attachments=[SimpleNamespace(filename='ticket.html', size=5)]))
        self.guild.text_channels.extend([self.source, self.archive])
        self.state = {'ticket_archive': 902, 'cases': {'901': {'owner': 77, 'kind': 'question', 'number': 1, 'status': 'open', 'closed': False, 'subject': 'Помощь'}}}
        lock = asyncio.Lock()
        client = SimpleNamespace(user=SimpleNamespace(id=2), lock=lambda gid: lock,
            application_info=AsyncMock(return_value=SimpleNamespace(flags=SimpleNamespace(
                gateway_message_content=False, gateway_message_content_limited=True))))
        self.service = TicketService(client, self.root, lambda gid: copy.deepcopy(self.state), self.write,
            lambda g: True, lambda m: m.id == 99, lambda *a: {}, lambda *a: {}, AsyncMock(), lambda *a: True)
        self.file = self.root / 'ticket.html'
        self.file.write_text('12345')
        self.result = {'html': self.file, 'json': self.file, 'folder': self.root, 'count': 1, 'last_id': 100}

    def write(self, gid, state):
        self.state = copy.deepcopy(state)

    async def asyncTearDown(self):
        self.temp.cleanup()

    async def run_archive(self):
        with patch('tickets.export_transcript', AsyncMock(return_value=self.result)), patch('tickets.upload_files', return_value=[self.file]):
            return await self.service.archive_case(self.guild, 901, 99, 'Решено')

    async def test_upload_verified_before_source_deleted(self):
        order = []
        async def proof(mid):
            order.append('verified')
            return SimpleNamespace(id=500, attachments=[SimpleNamespace(filename='ticket.html', size=5)])
        async def delete(**kwargs):
            order.append('deleted')
        self.archive.fetch_message.side_effect = proof
        self.source.delete.side_effect = delete
        result = await self.run_archive()
        self.assertEqual(order, ['verified', 'deleted'])
        self.assertTrue(result['source_deleted'])
        self.assertTrue(self.state['cases']['901']['closed'])

    async def test_failed_upload_never_deletes_source(self):
        self.archive.send.side_effect = OSError('network unavailable')
        with self.assertRaises(OSError): await self.run_archive()
        self.source.delete.assert_not_awaited()

    async def test_incomplete_upload_never_deletes_source(self):
        self.archive.fetch_message.return_value.attachments = []
        with self.assertRaises(ValueError): await self.run_archive()
        self.source.delete.assert_not_awaited()

    async def test_new_messages_during_export_prevent_deletion(self):
        self.source.history = lambda **kwargs: stream([SimpleNamespace(id=101)])
        with self.assertRaises(ValueError): await self.run_archive()
        self.source.delete.assert_not_awaited()

    async def test_retry_reuses_archive_message_instead_of_duplicate(self):
        self.state['cases']['901']['archive_posts'] = [500]
        message = SimpleNamespace(id=500, attachments=[SimpleNamespace(filename='ticket.html', size=5)])
        message.edit = AsyncMock(return_value=message)
        self.archive.fetch_message.return_value = message
        await self.run_archive()
        self.archive.send.assert_not_awaited()
        message.edit.assert_awaited_once()

    async def test_one_active_ticket_across_all_kinds(self):
        self.state['cases']['901']['kind'] = 'citizen'
        self.assertEqual(self.service.active(self.guild, self.state, 77), self.source)
        self.assertIsNone(self.service.active(self.guild, self.state, 88))

    async def test_failed_attachment_export_never_deletes_source(self):
        with patch('tickets.export_transcript', AsyncMock(side_effect=OSError('attachment missing'))):
            with self.assertRaises(OSError):
                await self.service.archive_case(self.guild, 901, 99, 'Решено')
        self.archive.send.assert_not_awaited()
        self.source.delete.assert_not_awaited()

    async def test_missing_content_permission_prevents_empty_archive_and_deletion(self):
        self.service.client.application_info.return_value.flags.gateway_message_content_limited = False
        with self.assertRaises(ValueError): await self.run_archive()
        self.archive.send.assert_not_awaited()
        self.source.delete.assert_not_awaited()


class HtmlTests(unittest.TestCase):
    def test_html_escapes_user_content_and_embeds_attachment_bytes(self):
        metadata = {'number': 1, 'kind': 'question', 'owner': 77, 'closed_by': 99, 'close_reason': '<script>x</script>',
            'channel_id': 901, 'created_at': '2026-10-23T10:00:00+00:00', 'exported_at': '2026-10-23T10:00:00+00:00'}
        messages = [{'id': 100, 'author_name': '<b>bad</b>', 'author_id': 77, 'bot': False,
            'content': '<script>alert(1)</script>', 'created_at': '2026-10-23T10:00:00+00:00', 'embeds': [],
            'attachments': [{'filename': 'x".txt', 'content_type': 'text/plain', 'size': 5, 'base64': 'aGVsbG8='}]}]
        page = render_html(messages, metadata)
        self.assertNotIn('<script>', page)
        self.assertIn('&lt;script&gt;', page)
        self.assertIn('data:application/octet-stream;base64,aGVsbG8=', page)
        self.assertIn('13:00:00 МСК', page)

    def test_large_archives_split_losslessly(self):
        import os
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            source = root / 'ticket.html'
            source.write_bytes(os.urandom(8000))
            data = root / 'messages.json'
            data.write_text('{}')
            result = {'html': source, 'json': data, 'folder': root, 'count': 1}
            files = upload_files(result, 1000)
            manifest = json.loads(files[-1].read_text())
            self.assertGreater(len(manifest['parts']), 1)
            joined = b''.join(path.read_bytes() for path in files[:-1])
            self.assertEqual(joined, (root / 'ticket.zip').read_bytes())


if __name__ == '__main__': unittest.main()
