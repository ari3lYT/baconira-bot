**English** · [Русский](configuration.ru.md)

# Configuration

| Setting | Purpose |
| --- | --- |
| `DISCORD_GUILD_ID` | Required numeric ID of the one guild allowed to use setup |
| `DISCORD_BOT_TOKEN` | Optional environment token; otherwise prompted or read from `.token` |
| `BACONIRA_DATA` | Persistent state directory; defaults to `data/` beside the code |
| `avatar.png` | Optional community icon |
| `bot-avatar.png` | Optional bot icon, falling back to `avatar.png` |
| `welcome-banner.png` | Optional welcome image |

The bot needs View Channels, Send Messages, Embed Links, Attach Files, Read Message History,
Manage Channels, Manage Roles, Move Members, Connect, Manage Threads and Send Messages in Threads.
Check the actual permission plan for your server. Global Administrator is not required. Member and
Message Content intents must be enabled. Native forum proposals require a Community server.

The administrator command may change channel overwrites and create roles/categories. Test the chosen
layout on a disposable guild first. Setup reuses existing named resources; duplicate names are rejected.
Do not remove the persistent directory during updates: it contains live case state and transcript recovery.
