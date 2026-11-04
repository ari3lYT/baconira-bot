"""Offline, escaped HTML transcripts with preserved attachment bytes."""
from __future__ import annotations

import base64
import hashlib
import html
import json
import re
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo


def esc(value):
    return html.escape(str(value), quote=True)


def when(value):
    if isinstance(value, str):
        value = datetime.fromisoformat(value)
    return value.astimezone(ZoneInfo("Europe/Moscow")).strftime("%d.%m.%Y %H:%M:%S МСК")


def render_html(records, metadata):
    title = f"Baconira · Тикет #{metadata['number']:04d}"
    rows = []
    for message in records:
        content = esc(message["content"])
        embeds = []
        for embed in message["embeds"]:
            fields = "".join(f"<h4>{esc(f['name'])}</h4><p>{esc(f['value'])}</p>" for f in embed.get("fields", []))
            embeds.append(f"<section class='embed'><h3>{esc(embed.get('title', ''))}</h3><p>{esc(embed.get('description', ''))}</p>{fields}</section>")
        attachments = []
        for file in message["attachments"]:
            uri = "data:application/octet-stream;base64," + file["base64"]
            preview = ""
            if file["content_type"] in {"image/png", "image/jpeg", "image/gif", "image/webp"}:
                preview = f"<img class='attachment' src='data:{file['content_type']};base64,{file['base64']}' alt='{esc(file['filename'])}'>"
            attachments.append(f"<div class='file'>{preview}<a download='{esc(file['filename'])}' href='{uri}'>📎 {esc(file['filename'])}</a> · {file['size']} байт</div>")
        reply = f"<a href='#m{int(message['reply_to'])}'>↪ Ответ на сообщение {int(message['reply_to'])}</a>" if message.get("reply_to") else ""
        edited = f" · изменено {when(message['edited_at'])}" if message.get("edited_at") else ""
        reactions = " · ".join(esc(r) for r in message.get("reactions", []))
        rows.append(f"<article id='m{int(message['id'])}'><header><b>{esc(message['author_name'])}</b> <span>{esc(message['author_id'])} {'· БОТ' if message['bot'] else ''}</span><time>{when(message['created_at'])}{edited}</time></header>{reply}<p class='content'>{content}</p>{''.join(embeds)}{''.join(attachments)}<small>{reactions}</small><footer>Сообщение {int(message['id'])}</footer></article>")
    info = "".join(f"<dt>{esc(k)}</dt><dd>{esc(v)}</dd>" for k, v in {
        "Тип": {"citizen": "Гражданство", "question": "Вопрос / помощь", "ticket": "Вопрос / помощь", "report": "Жалоба"}.get(metadata["kind"], metadata["kind"]), "Тема": metadata.get("subject", "—"),
        "Автор": metadata.get("owner_label") or metadata["owner"], "Закрыл": metadata.get("closed_by_label") or metadata["closed_by"],
        "Причина": metadata["close_reason"], "Создан": when(metadata["created_at"]),
        "Экспортирован": when(metadata["exported_at"]), "Сообщений": len(records),
        "Источник": metadata["channel_id"], "Ответственный": metadata.get("claimed_by") or "—",
        "Гражданство": "одобрено" if metadata.get("accepted") else "—",
    }.items())
    return f"""<!doctype html><html lang="ru"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><meta http-equiv="Content-Security-Policy" content="default-src 'none'; style-src 'unsafe-inline'; img-src data:; base-uri 'none'; form-action 'none'"><title>{esc(title)}</title><style>
    *{{box-sizing:border-box}}body{{margin:0;background:#111827;color:#e5e7eb;font:15px/1.6 system-ui,sans-serif}}main{{max-width:1000px;margin:auto;padding:28px 18px}}h1{{color:#e7c56e;margin-bottom:4px}}.intro{{color:#9ca3af}}dl{{display:grid;grid-template-columns:160px 1fr;background:#1f2937;border:1px solid #374151;border-radius:12px;padding:20px;gap:6px 16px}}dt{{color:#9ca3af}}dd{{margin:0;overflow-wrap:anywhere;white-space:pre-wrap}}article{{padding:20px;margin:16px 0;background:#1f2937;border:1px solid #374151;border-radius:12px;scroll-margin:12px}}header{{display:flex;gap:10px;align-items:baseline;flex-wrap:wrap}}header b{{color:#f0cd76}}header span,time,footer,small{{font-size:12px;color:#9ca3af}}time{{margin-left:auto}}p{{white-space:pre-wrap;overflow-wrap:anywhere}}.content:empty{{display:none}}.embed{{border-left:4px solid #d4af37;background:#111827;padding:10px 16px;margin:12px 0;border-radius:4px}}.embed h3,.embed h4{{margin:5px 0}}a{{color:#93c5fd;overflow-wrap:anywhere}}.attachment{{display:block;max-width:100%;max-height:600px;border-radius:8px;margin-bottom:8px}}.file{{margin:12px 0}}@media(max-width:600px){{dl{{grid-template-columns:1fr}}time{{margin-left:0}}}}
    </style></head><body><main><h1>{esc(title)}</h1><p class="intro">Приватный архив переписки. Текст и вложения сохранены в этом файле; подключение к Discord для просмотра не требуется.</p><dl>{info}</dl>{''.join(rows)}<p class="intro">Содержит сообщения, доступные боту на момент экспорта. Сообщения, удалённые до экспорта, восстановить нельзя. Ссылки и код из переписки не исполняются.</p></main></body></html>"""


async def export_transcript(channel, case, actor_id, reason, root, before=None):
    folder = Path(root) / "transcripts" / str(channel.guild.id) / f"{case['number']:04d}-{channel.id}"
    folder.mkdir(parents=True, exist_ok=True, mode=0o700)
    assets = folder / "assets"
    assets.mkdir(exist_ok=True, mode=0o700)
    records = []
    async for message in channel.history(limit=None, oldest_first=True, before=before):
        files = []
        for attachment in message.attachments:
            safe = re.sub(r"[^\w. -]", "_", Path(attachment.filename).name)[:120] or "attachment"
            path = assets / f"{attachment.id}-{safe}"
            if not path.exists() or path.stat().st_size != attachment.size:
                await attachment.save(path)
                path.chmod(0o600)
            data = path.read_bytes()
            if len(data) != attachment.size:
                raise ValueError("Не удалось полностью сохранить вложение. Канал оставлен на месте.")
            files.append({"id": attachment.id, "filename": attachment.filename, "size": len(data),
                          "content_type": attachment.content_type or "application/octet-stream",
                          "sha256": hashlib.sha256(data).hexdigest(),
                          "base64": base64.b64encode(data).decode("ascii")})
        records.append({"id": message.id, "author_id": message.author.id,
            "author_name": getattr(message.author, "display_name", str(message.author)),
            "bot": message.author.bot, "content": message.clean_content or message.system_content or "",
            "created_at": message.created_at.isoformat(),
            "edited_at": message.edited_at.isoformat() if message.edited_at else None,
            "reply_to": message.reference.message_id if message.reference else None,
            "embeds": [embed.to_dict() for embed in message.embeds], "attachments": files,
            "reactions": [f"{reaction.emoji} × {reaction.count}" for reaction in message.reactions]})
    metadata = {**{key: case.get(key) for key in ("number", "kind", "owner", "subject", "claimed_by", "accepted")}, "channel_id": channel.id, "guild_id": channel.guild.id,
                "closed_by": actor_id, "close_reason": reason,
                "created_at": case.get("created_at") or channel.created_at.isoformat(),
                "exported_at": datetime.now(timezone.utc).isoformat()}
    for key, uid in (("owner_label", case["owner"]), ("closed_by_label", actor_id)):
        member = channel.guild.get_member(uid)
        metadata[key] = f"{member.display_name} · {uid}" if member else str(uid)
    html_path = folder / f"ticket-{case['number']:04d}.html"
    html_path.write_text(render_html(records, metadata), encoding="utf-8")
    html_path.chmod(0o600)
    json_path = folder / "messages.json"
    json_path.write_text(json.dumps({"metadata": metadata, "messages": records}, ensure_ascii=False, indent=2), encoding="utf-8")
    json_path.chmod(0o600)
    return {"html": html_path, "json": json_path, "folder": folder,
            "count": len(records), "last_id": records[-1]["id"] if records else None}


def upload_files(result, limit):
    """HTML first; for large transcripts, a zip or lossless numbered zip parts."""
    size = max(1024, int(limit) - 64 * 1024)
    path = result["html"]
    if path.stat().st_size > size:
        path = result["folder"] / (path.stem + ".zip")
        with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as archive:
            archive.write(result["html"], result["html"].name)
            archive.write(result["json"], "messages.json")
        path.chmod(0o600)
    if path.stat().st_size <= size:
        payload = [path]
    else:
        payload = []
        with path.open("rb") as source:
            while block := source.read(size):
                part = path.with_name(path.name + f".part{len(payload) + 1:03d}")
                part.write_bytes(block)
                part.chmod(0o600)
                payload.append(part)
    manifest = result["folder"] / "manifest.json"
    manifest.write_text(json.dumps({"html": result["html"].name, "archive": path.name,
        "archive_sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
        "message_count": result["count"],
        "parts": [{"name": p.name, "size": p.stat().st_size,
                   "sha256": hashlib.sha256(p.read_bytes()).hexdigest()} for p in payload],
        "restore": "Если есть .part001 и далее: объедините части по номеру в один .zip, затем распакуйте. HTML содержит копии вложений."}, ensure_ascii=False, indent=2))
    manifest.chmod(0o600)
    return payload + [manifest]
