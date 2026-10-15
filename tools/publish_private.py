"""Publish source using existing Git Credential Manager credentials, never printing them."""
import base64
import json
import os
import subprocess
import sys
import urllib.error
import urllib.request
from pathlib import Path

ROOT=Path(__file__).resolve().parent.parent
NAME='codex-desktop-monitor'


def git(*args, capture=False):
    return subprocess.run(['git',*args],cwd=ROOT,check=True,text=True,encoding='utf-8',
                          stdout=subprocess.PIPE if capture else None, env=ENV)


ENV=os.environ.copy()
ENV.update(GIT_TERMINAL_PROMPT='0',GCM_INTERACTIVE='never')


def main(check=False):
    cred=subprocess.run(['git','credential','fill'],input='protocol=https\nhost=github.com\n\n',
                        text=True,capture_output=True,env=ENV)
    fields=dict(line.split('=',1) for line in cred.stdout.splitlines() if '=' in line)
    password=fields.get('password')
    if not password:
        raise RuntimeError('现有 Git 凭据不可用于 GitHub 建库，需要通过 GitHub CLI 或浏览器登录。')
    def api(path,body=None):
        req=urllib.request.Request('https://api.github.com'+path,
             data=json.dumps(body).encode() if body is not None else None,
             headers={'Authorization':'Bearer '+password,'Accept':'application/vnd.github+json','User-Agent':'codex-desktop-monitor-setup','X-GitHub-Api-Version':'2022-11-28'})
        with urllib.request.urlopen(req,timeout=30) as response:return json.load(response)
    user=api('/user')['login']
    if check:
        print(json.dumps({'login':user,'credential_available':True}))
        return
    try:
        repo=api(f'/repos/{user}/{NAME}')
        if not repo.get('private'):raise RuntimeError('同名仓库不是私有仓库，停止上传。')
        remote=git('remote','get-url','origin',capture=True).stdout.strip() if (ROOT/'.git').exists() else ''
        if remote and remote!=repo['clone_url']:raise RuntimeError('已有仓库远程地址不同，停止上传。')
        if not remote and repo.get('size',0)>0:raise RuntimeError('同名仓库已经有内容，停止上传以免混入其他项目。')
    except urllib.error.HTTPError as exc:
        if exc.code!=404:raise RuntimeError(f'GitHub 仓库检查失败（HTTP {exc.code}）。') from None
        repo=api('/user/repos',{'name':NAME,'private':True,'description':'Codex 桌面任务监控：本地面板、独立复核与操作确认。','auto_init':False})
    if not repo.get('private'):raise RuntimeError('未确认仓库私有，停止上传。')
    if not (ROOT/'.git').exists():git('init','-b','main')
    files=['.gitignore','settings.example.json','monitor','web','tests','tools','assets','run.py','configure.py','README.md','RESEARCH.md','THIRD_PARTY.md','设计方案.md','打开监控.cmd','launch.ps1','restart.ps1','install_windows.ps1','configure_lifecycle.ps1','install_desktop.ps1','lifecycle_bootstrap.py','codex_proxy.py']
    git('add','--',*[name for name in files if (ROOT/name).exists()])
    staged=git('diff','--cached','--name-only',capture=True).stdout.splitlines()
    if any(name.startswith(('.local/','_scratch/')) or name=='settings.local.json' or name.endswith(('.sqlite','.log')) for name in staged):
        raise RuntimeError('发现不应上传的本地运行数据，停止提交。')
    if staged:git('commit','-m','Add local desktop monitor with independent review and checkpoint controls')
    remotes=git('remote',capture=True).stdout.splitlines()
    if 'origin' not in remotes:git('remote','add','origin',repo['clone_url'])
    git('push','-u','origin','main')
    verified=api(f'/repos/{user}/{NAME}')
    if not verified.get('private'):raise RuntimeError('上传后未确认私有状态。')
    print(json.dumps({'url':verified['html_url'],'private':True},ensure_ascii=False))


if __name__=='__main__':
    try:main('--check' in sys.argv)
    except Exception as exc:
        # HTTP exception bodies/credential-helper diagnostics are intentionally omitted.
        print(str(exc) if isinstance(exc,RuntimeError) else 'GitHub 发布未完成：'+type(exc).__name__,file=sys.stderr)
        sys.exit(1)
