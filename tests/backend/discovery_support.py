"""An explicit-Root private manager records real child starts and finishes."""

from __future__ import annotations

import json
import shlex
import sys
from typing import Any

from backend.support import Frame

MANAGER = r'''
import json,os,sys,time
from pathlib import Path
launcher=Path(sys.argv.pop(1));base=launcher.parent;args=sys.argv[1:]
root,kind=args[1],args[2]
all=json.loads((base/'manager-behavior.json').read_text());option=all.get(root,{}).get(kind,{})
record={'root':root,'kind':kind,'args':args,'pid':os.getpid(),'pgid':os.getpgrp(),'phase':'start','at':time.monotonic()}
def log(value):
 fd=os.open(base/'manager-calls.jsonl',os.O_WRONLY|os.O_CREAT|os.O_APPEND,0o600)
 os.write(fd,(json.dumps(value)+'\n').encode());os.close(fd)
log(record)
time.sleep(option.get('sleep',0))
if kind=='list':value={'root':root,'exchanges':[],'unreadable':[]}
elif kind=='settle':value={'root':root,'results':[]}
else:value={'root':root,'exchange':args[-1],'ended':'cancelled','forced':'--force' in args}
value=option.get('output',value)
if option.get('stateBytes') and isinstance(value,dict) and value.get('exchanges'):
 value['exchanges'][0]['state']='future-'+('x'*option['stateBytes'])
if option.get('rootEcho'):value['root']=root
print(option.get('raw',json.dumps(value)),flush=True)
log({**record,'phase':'finish','at':time.monotonic()})
sys.exit(option.get('status',0))
'''


def install(frame: Frame, behavior: dict[str, Any]) -> None:
    configure(frame, behavior)
    path = frame.bin / "arbol-root"
    path.write_text("#!/bin/sh\nexec "+shlex.quote(sys.executable)+" -I -c "+shlex.quote(MANAGER)+' "$0" "$@"\n')
    path.chmod(0o700)


def configure(frame: Frame, behavior: dict[str, Any]) -> None:
    (frame.bin / "manager-behavior.json").write_text(json.dumps(behavior))


def calls(frame: Frame, *, kind: str | None = None, root: str | None = None, phase: str = "start") -> list[dict[str, Any]]:
    path = frame.bin / "manager-calls.jsonl"
    rows = [json.loads(line) for line in path.read_text().splitlines()] if path.exists() else []
    return [row for row in rows if row["phase"] == phase and (kind is None or row["kind"] == kind)
            and (root is None or row["root"] == root)]
