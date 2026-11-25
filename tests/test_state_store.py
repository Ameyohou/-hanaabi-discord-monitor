import base64
import copy
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from state_store import GitHubStore, StateError, HTTPFailure, encode


class Server:
    def __init__(self, state=None):
        self.state, self.sha = state, 'old' if state else None
        self.puts = 0
        self.fail_before = 0
        self.fail_after = False
        self.conflict = False
        self.gets = 0
    def request(self, method, url, token, body=None):
        if method == 'GET':
            self.gets += 1
            if self.state is None:
                raise HTTPFailure(404)
            return {'sha':self.sha,'content':base64.b64encode(encode(self.state)).decode()}
        self.puts += 1
        if self.conflict:
            self.state={'other_writer':True};self.sha='changed';raise HTTPFailure(409)
        if self.fail_before:
            self.fail_before-=1;raise HTTPFailure(503)
        if body.get('sha') != self.sha:
            raise HTTPFailure(409)
        self.state=json.loads(base64.b64decode(body['content']))
        self.sha='new' + str(self.puts)
        if self.fail_after:
            raise HTTPFailure(0)
        return {'content':{'sha':self.sha}}


class StateStoreTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.old=os.getcwd();os.chdir(self.tmp.name)
    def tearDown(self):
        os.chdir(self.old);self.tmp.cleanup()
    def store(self,server):
        return GitHubStore('user/repo','monitor-state','state/bbcnews.json','secret',server.request,lambda s:None)
    def test_initial_write_and_round_trip(self):
        server=Server();store=self.store(server)
        self.assertIsNone(store.read());store.save({'version':1})
        self.assertEqual(store.read(),{'version':1})
    def test_retry_transient_save_without_changing_base(self):
        server=Server({'seen':['1']});store=self.store(server);store.read()
        server.fail_before=2;store.save({'seen':['1','2']})
        self.assertEqual(server.puts,3)
    def test_lost_put_response_is_reconciled_without_rewrite(self):
        server=Server({'seen':['1']});store=self.store(server);store.read();server.fail_after=True
        store.save({'seen':['1','2']})
        self.assertEqual(server.puts,1);self.assertEqual(store.sha,server.sha)
    def test_conflicting_writer_is_never_overwritten(self):
        server=Server({'seen':['1']});store=self.store(server);store.read();server.conflict=True
        with self.assertRaises(StateError):store.save({'seen':['1','2']})
        self.assertEqual(server.state,{'other_writer':True});self.assertEqual(server.puts,1)
    def test_permanent_failure_stops_and_keeps_journal(self):
        server=Server({'seen':['1']});store=self.store(server);store.read();server.fail_before=99
        with self.assertRaises(StateError):store.save({'seen':['1','2']})
        self.assertEqual(server.puts,3)
        self.assertEqual(json.loads(Path('work/runtime/bbcnews.json').read_text()),{'seen':['1','2']})
    def test_delayed_visibility_of_committed_put_is_reconciled(self):
        class DelayedServer(Server):
            remaining=3
            def request(self,method,url,token,body=None):
                if method=='GET' and self.puts and self.remaining:
                    self.remaining-=1
                    return {'sha':'old','content':base64.b64encode(encode({'seen':['1']})).decode()}
                return super().request(method,url,token,body)
        server=DelayedServer({'seen':['1']});store=self.store(server);store.read();server.fail_after=True
        store.save({'seen':['1','2']})
        self.assertEqual(store.sha,server.sha)
        self.assertEqual(server.state,{'seen':['1','2']})
    def test_save_requires_initial_read(self):
        with self.assertRaises(StateError):self.store(Server()).save({})
    def test_corrupt_state_is_not_reinitialized(self):
        def request(*a,**kw):return {'content':base64.b64encode(b'not JSON').decode(),'sha':'x'}
        store=GitHubStore('user/repo','monitor-state','state/bbcnews.json','secret',request,lambda s:None)
        with self.assertRaises(StateError):store.read()
    def test_error_never_echoes_token(self):
        def request(*a,**kw):raise HTTPFailure(403)
        store=GitHubStore('user/repo','monitor-state','state/bbcnews.json','secret',request,lambda s:None)
        with self.assertRaises(StateError) as e:store.read()
        self.assertNotIn('secret',str(e.exception))

class DeliveryDurabilityTests(unittest.TestCase):
    setUp = StateStoreTests.setUp
    tearDown = StateStoreTests.tearDown
    store = StateStoreTests.store
    def test_ack_lost_after_actual_put_does_not_duplicate_webhook(self):
        import monitor as m
        from test_monitor import NOW, post
        state=m.initial_state();state.update(initialized=True,seen=['1'])
        server=Server(state);store=self.store(server);state=store.read();sent=[]
        server.fail_after=True
        self.assertEqual(m.run(state,lambda:[post('2')],sent.append,store.save,NOW),0)
        second=self.store(server);state=second.read()
        self.assertEqual(m.run(state,lambda:[post('2')],sent.append,second.save,NOW),0)
        self.assertEqual(len(sent),1);self.assertIsNone(server.state['pending'])
    def test_durable_pending_prevents_blind_retry_after_save_outage(self):
        import monitor as m
        from test_monitor import NOW,post
        state=m.initial_state();state.update(initialized=True,seen=['1'])
        server=Server(state);store=self.store(server);state=store.read();sent=[]
        def deliver(text):
            sent.append(text)
            server.fail_before=99
        with self.assertRaises(StateError):m.run(state,lambda:[post('2')],deliver,store.save,NOW)
        self.assertEqual(server.state['pending'],'2')
        server.fail_before=0
        second=self.store(server);state=second.read()
        self.assertEqual(m.run(state,lambda:[post('2')],sent.append,second.save,NOW),1)
        self.assertEqual(len(sent),1)
    def test_save_failure_before_delivery_sends_nothing(self):
        import monitor as m
        from test_monitor import NOW,post
        state=m.initial_state();state.update(initialized=True,seen=['1'])
        server=Server(state);store=self.store(server);state=store.read();sent=[];server.fail_before=99
        with self.assertRaises(StateError):m.run(state,lambda:[post('2')],sent.append,store.save,NOW)
        self.assertEqual(sent,[])
