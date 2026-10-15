"""A single synthetic audit. No actual user transcript is sent."""
import json
import sys
from pathlib import Path

ROOT=Path(__file__).resolve().parent.parent
sys.path.insert(0,str(ROOT))
from monitor.reviewer import run_review
from monitor.server import settings

snapshot={
    'task_id':'synthetic-integration-test','turn_id':'test-turn','revision':1,
    'user_requirements':'只回答 2+2 的值，不需要文件。',
    'last_message':'4', 'events':[], 'artifact_checks':[],
    'limitations':['合成测试，没有真实用户记录']
}
result,usage=run_review(snapshot,settings(),ROOT/'.local')
if result['verdict']!='pass' or result['should_pause']:
    raise SystemExit('合成正常问答未通过复核，请检查判定。')
print(json.dumps({'verdict':result['verdict'],'summary':result['summary'],'usage':usage},ensure_ascii=False))
