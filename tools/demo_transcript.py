#!/usr/bin/env python3
"""Produce a real offline export from fictional records, without a Discord login."""
from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from transcripts import render_html

records=[]
for index,(name,text) in enumerate([
    ('DemoBuilder','Здравствуйте! Как предложить общественную стройку?'),
    ('DemoHelper','Привет! Создай предложение на форуме: цель, материалы и примерные сроки.'),
    ('DemoBuilder','Спасибо! Добавлю эскиз и список ресурсов. Вопрос решён.'),
],1):
    records.append({'id':index,'author_name':name,'author_id':str(100+index),'bot':False,
                    'content':text,'created_at':f'2026-11-04T12:0{index}:00+00:00',
                    'edited_at':None,'embeds':[],'attachments':[],'reactions':[]})
metadata={'number':1,'kind':'question','subject':'Как предложить стройку — демонстрация',
          'owner':'DemoBuilder','owner_label':'DemoBuilder','closed_by':'DemoHelper','closed_by_label':'DemoHelper',
          'close_reason':'Ответ получен. Все имена и сообщения вымышлены.',
          'created_at':'2026-11-04T12:00:00+00:00','exported_at':'2026-11-04T12:05:00+00:00',
          'channel_id':'demo-ticket','claimed_by':'DemoHelper'}
out=Path(__file__).resolve().parents[1]/'output';out.mkdir(exist_ok=True)
target=out/'demo-transcript.html';target.write_text(render_html(records,metadata));print(target)
