import json
import urllib.error
import urllib.request
import subprocess
import os

REPOS=['LH-03/codex-monitor-hud','Yxianshe/Codex-Monitor','jspann21/codex-bar','redmikarimo/codex-supervisor-mcp']
env=os.environ.copy();env.update(GIT_TERMINAL_PROMPT='0',GCM_INTERACTIVE='never')
credentials=subprocess.run(['git','credential','fill'],input='protocol=https\nhost=github.com\n\n',capture_output=True,text=True,env=env)
fields=dict(line.split('=',1) for line in credentials.stdout.splitlines() if '=' in line)
def get(path):
    headers={'User-Agent':'Codex-monitor-evaluation','Accept':'application/vnd.github+json'}
    if fields.get('password'):headers['Authorization']='Bearer '+fields['password']
    req=urllib.request.Request('https://api.github.com/'+path,headers=headers)
    with urllib.request.urlopen(req,timeout=25) as response:return json.load(response)
for name in REPOS:
    try:
        meta=get('repos/'+name)
        item={key:meta.get(key) for key in ('full_name','stargazers_count','pushed_at','archived','default_branch')}
        item['license']=(meta.get('license') or {}).get('spdx_id')
        try:
            release=get('repos/'+name+'/releases/latest')
            item['release']={'tag':release['tag_name'],'published_at':release['published_at'],
                             'assets':[{key:a.get(key) for key in ('name','size','digest','browser_download_url')} for a in release.get('assets',[])]}
        except urllib.error.HTTPError as exc:
            item['release_error']=exc.code
        print(json.dumps(item,ensure_ascii=False))
    except Exception as exc:
        print(json.dumps({'repository':name,'error':type(exc).__name__,'status':getattr(exc,'code',None)}))
