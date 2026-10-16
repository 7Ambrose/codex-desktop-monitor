"""Exercise the real relay transport without network access or model calls."""
import io
import json
import sys
import unittest

from codex_proxy import read_allowance


class HudProxyTests(unittest.TestCase):
    def relay(self, mode):
        script = '''
import sys,json
mode=sys.argv[1]
count=0
for line in sys.stdin:
 r=json.loads(line)
 if r['method']=='initialize':
  print(json.dumps({'id':1,'result':{}}),flush=True)
 elif r['method']=='account/rateLimits/read':
  count+=1
  if mode=='auth' or mode=='always' or count==1:
   response={'error':{'code':-1,'message':'authentication required' if mode=='auth' else 'temporary connection failure'}}
  else:
   response={'result':{'rateLimits':{'secondary':{'usedPercent':13,'windowDurationMins':10080}}}}
  response.update(id=r['id'],attempts=count)
  print(json.dumps(response),flush=True)
'''
        source = io.StringIO(''.join(json.dumps(r)+'\n' for r in [
            {'id':1,'method':'initialize','params':{}},
            {'method':'initialized','params':{}},
            {'id':2,'method':'account/rateLimits/read','params':{}}]))
        target = io.StringIO()
        code = read_allowance([sys.executable,'-u','-c',script,mode],source,target,timeout=3)
        responses = [json.loads(line) for line in target.getvalue().splitlines()]
        return code, responses

    def test_transient_failure_recovers_with_single_final_response(self):
        code, responses = self.relay('recover')
        self.assertEqual(code,0)
        self.assertEqual([r['id'] for r in responses],[1,2])
        self.assertEqual(responses[-1]['attempts'],2)
        self.assertEqual(responses[-1]['result']['rateLimits']['secondary']['usedPercent'],13)

    def test_persistent_failure_stops_after_three_reads(self):
        code, responses = self.relay('always')
        self.assertEqual(code,1)
        self.assertEqual(responses[-1]['attempts'],3)
        self.assertIn('error',responses[-1])

    def test_authentication_failure_is_not_retried(self):
        code, responses = self.relay('auth')
        self.assertEqual(code,1)
        self.assertEqual(responses[-1]['attempts'],1)


if __name__=='__main__':
    unittest.main()
