import copy
import datetime as dt
import unittest
from daily_status import render, send_daily
from monitor import MonitorError
from state_store import StateError

NOW=dt.datetime(2026,11,24,11,17,tzinfo=dt.timezone.utc)
class Store:
    def __init__(self,data=None): self.data=data; self.fail=False
    def read(self): return copy.deepcopy(self.data)
    def save(self,data):
        if self.fail: raise StateError('save failed')
        self.data=copy.deepcopy(data)
def healthy():
    return {'last_success':NOW.isoformat(),'last_run':NOW.isoformat(),'last_result':{'status':'success'},'failures':0,'pending':None}
class DailyStatusTests(unittest.TestCase):
    def test_before_20_jst(self):
        sent=[]
        self.assertEqual(send_daily(NOW-dt.timedelta(minutes=18),Store(healthy()),Store(),sent.append),'not_due')
        self.assertEqual(sent,[])
    def test_once_per_jst_day(self):
        sent=[];report=Store()
        self.assertEqual(send_daily(NOW,Store(healthy()),report,sent.append),'sent')
        self.assertEqual(send_daily(NOW+dt.timedelta(minutes=30),Store(healthy()),report,sent.append),'already_sent')
        self.assertEqual(len(sent),1);self.assertIn('正常稼働',sent[0])
        self.assertEqual(send_daily(NOW+dt.timedelta(days=1),Store(healthy()),report,sent.append),'sent')
        self.assertEqual(len(sent),2)
    def test_stale_state(self):
        state=healthy();state['last_success']=(NOW-dt.timedelta(hours=2)).isoformat()
        self.assertIn('要確認',render(state,NOW));self.assertNotIn('✅',render(state,NOW))
    def test_unhealthy_state(self):
        for fields in [{'pending':'123'},{'failures':1},{'provider_blocked':True},{'last_result':{'status':'fetching'}}]:
            state=healthy();state.update(fields);self.assertIn('要確認',render(state,NOW))
    def test_missing_state(self):
        sent=[];send_daily(NOW,Store(),Store(),sent.append)
        self.assertIn('正常とは判定できません',sent[0])
    def test_save_failure_prevents_post(self):
        sent=[];report=Store();report.fail=True
        with self.assertRaises(StateError):send_daily(NOW,Store(healthy()),report,sent.append)
        self.assertEqual(sent,[])
    def test_unknown_delivery_not_repeated(self):
        report=Store();calls=[]
        def uncertain(text):calls.append(text);raise MonitorError('timeout')
        with self.assertRaises(MonitorError):send_daily(NOW,Store(healthy()),report,uncertain)
        with self.assertRaises(StateError):send_daily(NOW,Store(healthy()),report,uncertain)
        self.assertEqual(len(calls),1)
    def test_definite_refusal(self):
        report=Store()
        def refused(text):raise MonitorError('HTTP 429',status=429)
        with self.assertRaises(MonitorError):send_daily(NOW,Store(healthy()),report,refused)
        self.assertIsNone(report.data['pending_date'])
        sent=[];send_daily(NOW,Store(healthy()),report,sent.append);self.assertEqual(len(sent),1)
    def test_bad_timestamp(self):
        state=healthy();state['last_success']='broken';self.assertIn('判定できません',render(state,NOW))
