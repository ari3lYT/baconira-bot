**English** · [Русский](development.ru.md)

# Development

Run `python -m unittest discover -s tests -v` after installing `requirements.txt`. The tests mock Discord
objects and cover privacy overwrites, repeatable setup, ticket archival failure, duplicate creation,
voice ownership and forum behavior. No bot login is needed.

Changing role names requires reviewing behavioral references as well as presentation: citizenship uses
the citizen role, and staff/senate membership determines access. The default theme lives in Python
constants rather than a universal role-layout schema. Avoid string replacement across persisted data.

To generate a safe transcript example, run `python tools/demo_transcript.py`; it uses fictional members
and messages and does not connect to Discord. Open `output/demo-transcript.html` locally.

For live validation, use a separate bot application and a disposable guild. Offline mocks do not prove
that a particular production guild has all required intents, permissions and role hierarchy.
