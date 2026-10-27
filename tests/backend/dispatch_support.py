"""A private Root-manager stand-in; captures requests and writes only test acceptance rows."""

from __future__ import annotations

import json
import shlex
import sys
from pathlib import Path
from typing import Any

import psycopg

from backend.support import Frame

START = r'''
import json,os,sys,time
from pathlib import Path
import psycopg
launcher=Path(sys.argv.pop(1));base=launcher.parent
args=sys.argv[1:]
if args[2]!='start':
 print('{}',flush=True);sys.exit(0)
exchange=args[args.index('--exchange')+1]
path=Path(args[args.index('--request')+1])
config=json.loads((base/'start-behavior.json').read_text())
rows=[json.loads(l) for l in (base/'starts.jsonl').read_text().splitlines()] if (base/'starts.jsonl').exists() else []
attempt=sum(r['exchange']==exchange for r in rows)
options=config.get('attempts',[{}]);option=options[min(attempt,len(options)-1)]
request=json.loads(path.read_bytes())
active=base/('active-'+exchange)
try:
 fd=os.open(active,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600);os.close(fd);collision=False
except FileExistsError:collision=True
with psycopg.connect(config['database'],autocommit=True) as db:
 draft=db.execute('SELECT text,revision,sent_as,sent_request FROM drafts WHERE chat_id=%s OR folder=%s',
                  [request['chat'],request['workingFolder']]).fetchall()
record={'exchange':exchange,'attempt':attempt,'at':time.monotonic(),'args':args,'pid':os.getpid(),'pgid':os.getpgrp(),
        'home':os.environ.get('HOME'),'path':os.environ.get('PATH'),'pgOverrides':[k for k in os.environ if k.startswith('PG')],
        'request':request,'mode':path.stat().st_mode&0o777,'directoryMode':path.parent.stat().st_mode&0o777,
        'draft':[[str(v) if v is not None else None for v in row] for row in draft], 'collision':collision}
fd=os.open(base/'starts.jsonl',os.O_WRONLY|os.O_CREAT|os.O_APPEND,0o600)
os.write(fd,(json.dumps(record)+'\n').encode());os.close(fd)
time.sleep(option.get('sleep',0))
reply=option.get('reply')
status=option.get('status',1 if isinstance(reply,dict) and 'error' in reply else 0)
if reply is None and 'raw' not in option:
 with psycopg.connect(config['database'],autocommit=True) as db:
  row=db.execute('SELECT chat_id,number FROM exchanges WHERE id=%s',[exchange]).fetchone()
  duplicate=row is not None
  if row is None:
   db.execute('INSERT INTO chats(id,title,created_at) VALUES(%s,NULL,clock_timestamp()) ON CONFLICT DO NOTHING',[request['chat']])
   number=db.execute('SELECT coalesce(max(number),0)+1 FROM exchanges WHERE chat_id=%s',[request['chat']]).fetchone()[0]
   db.execute("INSERT INTO exchanges(id,chat_id,number,state,trunk,build,route,working_folder,accepted_at,ended_at) "
    "VALUES(%s,%s,%s,'completed','trivial','0',%s,%s,clock_timestamp(),clock_timestamp())",
    [exchange,request['chat'],number,psycopg.types.json.Jsonb(request['route']),request['workingFolder']])
   if 'message' in request:db.execute("INSERT INTO messages VALUES(%s,0,'user',%s)",[exchange,request['message']])
   row=(request['chat'],number)
  reply={'accepted':True,'duplicate':duplicate,'root':args[1],'exchange':exchange,'chat':str(row[0]),'number':row[1]}
if option.get('removeRequest'):path.unlink(missing_ok=True)
print(option['raw'] if 'raw' in option else json.dumps(reply),flush=True)
(base/('ended-'+exchange+'-'+str(attempt))).write_text(str(time.monotonic()))
active.unlink(missing_ok=True)
sys.exit(status)
'''


def install(frame: Frame, database: str, attempts: list[dict[str, object]]) -> None:
    frame.bin.joinpath('start-behavior.json').write_text(json.dumps({'database': database, 'attempts': attempts}))
    dependency = str(Path(psycopg.__file__).resolve().parent.parent)
    code = 'import sys;sys.path.insert(0,' + repr(dependency) + ')\n' + START
    frame.bin.joinpath('arbol-root').write_text('#!/bin/sh\nexec ' + shlex.quote(sys.executable) +
        ' -I -c ' + shlex.quote(code) + ' "$0" "$@"\n')
    frame.bin.joinpath('arbol-root').chmod(0o700)


def starts(frame: Frame) -> list[dict[str, Any]]:
    path = frame.bin / 'starts.jsonl'
    return [json.loads(line) for line in path.read_text().splitlines()] if path.exists() else []
