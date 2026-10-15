"""Prepare/reversibly install the exact reviewed MCP and hook definitions."""
import argparse
import json
import os
import shutil
import sys
import time
import tomllib
from pathlib import Path

ROOT=Path(__file__).resolve().parent
BEGIN='# BEGIN CODEX DESKTOP MONITOR'
END='# END CODEX DESKTOP MONITOR'
SERVER='codex_desktop_monitor'
EVENTS=['UserPromptSubmit','PreToolUse','PostToolUse','Stop','Interrupt','PreCompact','PostCompact']


def definitions():
    hooks={}
    for event in EVENTS:
        fields=['session_id','turn_id','cwd','model','hook_event_name']
        if event=='UserPromptSubmit':fields+=['prompt']
        if event in ('PreToolUse','PostToolUse'):fields+=['tool_name','tool_input']
        if event=='PostToolUse':fields+=['tool_response']
        if event=='Stop':fields+=['last_assistant_message']
        mapping={key:'${'+key+'}' for key in fields}
        mapping['hook_event_name']=event
        hooks[event]=[{'hooks':[{'type':'mcp_tool','server':SERVER,'tool':'observe','input':{'event':mapping},'timeout':15,'statusMessage':'任务监控检查'}]}]
    return {'description':'Codex 桌面任务监控：本机采集、独立 GPT 复核、异常时在下一次操作前等待确认。','hooks':hooks}


def strip_block(text):
    if BEGIN not in text:return text
    start=text.index(BEGIN)
    stop=text.index(END,start)+len(END)
    return text[:start]+text[stop:].lstrip('\r\n')


def without_monitor(groups):
    result=[]
    for group in groups:
        remaining=[handler for handler in group.get('hooks',[]) if handler.get('server')!=SERVER]
        if remaining:
            result.append({**group,'hooks':remaining})
    return result


def prepare():
    local=ROOT/'.local';local.mkdir(exist_ok=True)
    config=ROOT/'settings.local.json'
    if not config.exists():
        data=json.loads((ROOT/'settings.example.json').read_text(encoding='utf-8'))
        data['enabled_roots']=[str(ROOT.parent)]
        data['excluded_thread_ids']=[]
        config.write_text(json.dumps(data,ensure_ascii=False,indent=2),encoding='utf-8')
    (local/'hooks.proposed.json').write_text(json.dumps(definitions(),ensure_ascii=False,indent=2),encoding='utf-8')
    block=(BEGIN+'\n'+f'[mcp_servers.{SERVER}]\ncommand = '+json.dumps(sys.executable)+'\nargs = '+json.dumps([str(ROOT/'run.py'),'mcp'])+'\nstartup_timeout_sec = 20\ntool_timeout_sec = 600\n'+END+'\n')
    (local/'config.proposed.toml').write_text(block,encoding='utf-8')
    print('本地配置与待安装定义已生成；尚未更改 Codex 配置。')


def install():
    prepare()
    home=Path(os.environ.get('CODEX_HOME') or Path.home()/'.codex')
    config=home/'config.toml';hooks=home/'hooks.json'
    original=config.read_text(encoding='utf-8-sig') if config.exists() else ''
    parsed=tomllib.loads(original)
    if SERVER in parsed.get('mcp_servers',{}) and BEGIN not in original:
        raise RuntimeError('已有同名 MCP 配置，停止安装以避免覆盖。')
    existing=json.loads(hooks.read_text(encoding='utf-8-sig')) if hooks.exists() else {'hooks':{}}
    if not isinstance(existing.get('hooks',{}),dict):raise RuntimeError('已有 hooks 配置结构无效。')
    backup=ROOT/'.local'/('backup-'+time.strftime('%Y%m%d-%H%M%S'));backup.mkdir()
    for path in (config,hooks):
        if path.exists():shutil.copy2(path,backup/path.name)
    merged=existing
    for event,groups in definitions()['hooks'].items():
        old=merged.setdefault('hooks',{}).setdefault(event,[])
        old[:]=without_monitor(old)
        old.extend(groups)
    proposed=strip_block(original).rstrip()+'\n\n'+(ROOT/'.local/config.proposed.toml').read_text(encoding='utf-8')
    tomllib.loads(proposed)
    # Prepare both before modifying either; backups allow reversal.
    home.mkdir(exist_ok=True)
    temp_config=config.with_suffix('.monitor-tmp');temp_hooks=hooks.with_suffix('.monitor-tmp')
    temp_config.write_text(proposed,encoding='utf-8')
    temp_hooks.write_text(json.dumps(merged,ensure_ascii=False,indent=2),encoding='utf-8')
    try:
        os.replace(temp_hooks,hooks)
        os.replace(temp_config,config)
    except Exception:
        for path in (config,hooks):
            saved=backup/path.name
            if saved.exists():shutil.copy2(saved,path)
            elif path.exists() and path.resolve().parent==home.resolve():path.unlink()
        raise
    print('监控定义已安装。已有配置已备份；仍需在 Codex 中审核并信任这些钩子。')


def uninstall():
    home=Path(os.environ.get('CODEX_HOME') or Path.home()/'.codex')
    config=home/'config.toml';hooks=home/'hooks.json'
    if config.exists():config.write_text(strip_block(config.read_text(encoding='utf-8-sig')),encoding='utf-8')
    if hooks.exists():
        data=json.loads(hooks.read_text(encoding='utf-8-sig'))
        for event,groups in data.get('hooks',{}).items():
            groups[:]=without_monitor(groups)
        hooks.write_text(json.dumps(data,ensure_ascii=False,indent=2),encoding='utf-8')
    print('已移除本监控定义；任务文件和其他配置保留。')


if __name__=='__main__':
    parser=argparse.ArgumentParser()
    parser.add_argument('action',choices=['prepare','install','uninstall'])
    args=parser.parse_args()
    {'prepare':prepare,'install':install,'uninstall':uninstall}[args.action]()
