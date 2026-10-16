"""Build a tracked-source release and publish using existing GCM credentials.

No personal configuration, credentials, logs or databases are packaged.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import urllib.error
import urllib.parse
import urllib.request
import zipfile

ROOT = Path(__file__).resolve().parent.parent
REPO = '7Ambrose/codex-desktop-monitor'
VERSION = 'v0.1.0-preview'
ENV = dict(os.environ, GIT_TERMINAL_PROMPT='0', GCM_INTERACTIVE='never')


def git(*args):
    return subprocess.check_output(['git', *args], cwd=ROOT, env=ENV).decode('utf-8').strip()


def build():
    if git('status', '--porcelain'):
        raise RuntimeError('Commit all release changes before packaging.')
    out = ROOT/'_scratch/release'
    out.mkdir(parents=True, exist_ok=True)
    asset = out/f'codex-monitor-{VERSION}-windows-source.zip'
    subprocess.run(['git','archive','--format=zip','--prefix=codex-monitor/','-o',str(asset),'HEAD'],cwd=ROOT,check=True)
    with zipfile.ZipFile(asset) as package:
        names = package.namelist()
        for name in names:
            path = Path(name)
            if any(part in ('.local','.git','_scratch','__pycache__') for part in path.parts) or path.name in ('settings.local.json','auth.json') or path.suffix in ('.log','.sqlite','.db','.jsonl'):
                raise RuntimeError('Private or generated data found in package.')
        if package.testzip():
            raise RuntimeError('Release archive failed integrity check.')
        for required in ('RELEASE.md','安装.cmd','runtime.ps1','vendor/supervisor/LICENSE'):
            if 'codex-monitor/'+required not in names:
                raise RuntimeError('Required release file is missing: '+required)
    checksums = out/'SHA256SUMS.txt'
    checksums.write_text(hashlib.sha256(asset.read_bytes()).hexdigest()+'  '+asset.name+'\n',encoding='ascii')
    return asset, checksums


class GitHub:
    def __init__(self):
        result = subprocess.run(['git','credential','fill'],input='protocol=https\nhost=github.com\n\n',text=True,capture_output=True,env=ENV,check=True)
        fields = dict(line.split('=',1) for line in result.stdout.splitlines() if '=' in line)
        self.secret = fields.get('password')
        if not self.secret: raise RuntimeError('Existing GitHub credentials unavailable.')

    def call(self, path, body=None, method=None, binary=False):
        url = path if path.startswith('https://uploads.github.com/') else 'https://api.github.com'+path
        data = body if binary else json.dumps(body,ensure_ascii=False).encode('utf-8') if body is not None else None
        request = urllib.request.Request(url,data=data,method=method,headers={
            'Authorization':'Bearer '+self.secret,'Accept':'application/vnd.github+json',
            'User-Agent':'codex-monitor-release','X-GitHub-Api-Version':'2022-11-28',
            'Content-Type':'application/octet-stream' if binary else 'application/json'})
        with urllib.request.urlopen(request,timeout=40) as response:
            return json.load(response)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--publish',action='store_true')
    parser.add_argument('--inspect',action='store_true')
    args = parser.parse_args()
    if not args.publish and not args.inspect:
        files=build()
        print(json.dumps({'files':[str(p) for p in files],'bytes':files[0].stat().st_size}))
        return
    github = GitHub()
    repo = github.call('/repos/'+REPO)
    if not repo.get('private'): raise RuntimeError('Repository privacy changed; publishing stopped.')
    if args.inspect:
        releases = github.call('/repos/'+REPO+'/releases')
        print(json.dumps({'private':True,'url':repo['html_url'],'releases':[{'tag':r['tag_name'],'draft':r['draft']} for r in releases]}))
        return
    sha = git('rev-parse','HEAD')
    remote = github.call('/repos/'+REPO+'/git/ref/heads/main')['object']['sha']
    if remote != sha: raise RuntimeError('Remote main must match the verified local release commit.')
    assets = build()
    path = '/repos/'+REPO+'/releases'
    try:
        release = github.call(path+'/tags/'+VERSION)
        if not release['draft']: raise RuntimeError('This version is already published; do not replace its assets.')
    except urllib.error.HTTPError as error:
        if error.code != 404: raise
        drafts = github.call(path)
        release = next((r for r in drafts if r['tag_name']==VERSION),None)
        if release is None:
            release = github.call(path,{'tag_name':VERSION,'target_commitish':sha,
                'name':'Codex 监控 '+VERSION+' · Windows 预览版',
                'body':(ROOT/'RELEASE.md').read_text(encoding='utf-8'),
                'draft':True,'prerelease':True})
    if release['target_commitish'] not in (sha,):
        raise RuntimeError('Existing draft targets a different commit.')
    existing = github.call(path+'/'+str(release['id'])+'/assets')
    for asset in assets:
        digest = 'sha256:'+hashlib.sha256(asset.read_bytes()).hexdigest()
        old = next((a for a in existing if a['name']==asset.name),None)
        if old:
            if old.get('digest') != digest: raise RuntimeError('Existing draft asset differs; review it before replacing.')
            continue
        github.call(release['upload_url'].split('{')[0]+'?name='+urllib.parse.quote(asset.name),asset.read_bytes(),binary=True)
    verified = github.call(path+'/'+str(release['id'])+'/assets')
    for asset in assets:
        match = next((a for a in verified if a['name']==asset.name),None)
        if not match or match['size'] != asset.stat().st_size:
            raise RuntimeError('Release asset verification failed.')
    published = github.call(path+'/'+str(release['id']),{'draft':False},method='PATCH')
    print(json.dumps({'url':published['html_url'],'prerelease':published['prerelease'],'private':True,'assets':[a['name'] for a in verified]},ensure_ascii=False))


if __name__=='__main__':
    try: main()
    except Exception as error:
        # Never print request bodies, credential-helper output, or authentication headers.
        print(str(error) if isinstance(error,RuntimeError) else 'Release failed: '+type(error).__name__)
        raise SystemExit(1)
