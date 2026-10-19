"""Synthetic CPU regressions for row isolation and bounded admission."""
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor
import json
import os
import queue
import sys
import tempfile
import threading
import time
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'backend'))
from ocr_app.batch_generation import RowStops, compatible
from ocr_app.config import RuntimeConfig
from ocr_app.model_queues import ModelQueues
from ocr_app.model_protocol import ModelInbox
from ocr_app.runtime import ModelManager, RuntimeFailure
from ocr_app.task_scheduler import TaskScheduler
import test_task_scheduler as scheduling


class RowControlTests(unittest.TestCase):
    def test_completed_cancelled_and_expired_rows_are_independent(self):
        stops = RowStops(3, [2], 100, deadlines={1:.2})
        self.assertEqual(stops.step(1, [9,9,2], .1), ([False,False,True], [2]))
        self.assertEqual(stops.step(2, [9,9,0], .3, cancelled=[0]), ([True,True,True], [0,1]))
        self.assertEqual(stops.reasons, ['cancelled','time_limit','eos'])
        self.assertEqual(stops.step(3, [2,2,2], .4), ([True,True,True], []))

    def test_only_matching_task_and_token_ceiling_are_compatible(self):
        self.assertTrue(compatible({'task':'ocr'}, {'task':'ocr','max_new_tokens':4096}))
        self.assertFalse(compatible({'task':'ocr'}, {'task':'table'}))
        self.assertFalse(compatible({'max_new_tokens':512}, {'max_new_tokens':1024}))

    def test_config_only_admits_one_or_two_and_serial_default_stays_one(self):
        self.assertEqual(RuntimeConfig(Path('.')).model_batch_size, 1)
        for value in [0,3,True,2.0]:
            with self.assertRaises(ValueError):
                RuntimeConfig(Path('.'), model_batch_size=value)


class BoundedDocumentTests(unittest.TestCase):
    setUp = scheduling.SchedulerTests.setUp

    def test_qualified_batch_mode_admits_only_one_backlog_pair_per_lane(self):
        self.scheduler.close()
        self.manager.model_batch_size = 2
        self.remaining = [scheduling.task(name, kind) for name, kind in [
            ('cert-one','DIPLOMA'), ('cert-two','DEGREE_CERT'), ('form-one','GENERIC'),
            ('table-one','TABLE'), ('cert-three','DIPLOMA'), ('form-two','INTERVIEW_FORM'),
            ('cert-four','DIPLOMA')]]
        for row in self.remaining:
            row['_batch_safe'] = True
        self.install_guarded_claim()
        self.scheduler = TaskScheduler(self.store,self.manager,self.models,None,self.logger,self.replies.append,factory=scheduling.Child)
        self.scheduler.poll()
        self.assertEqual(len(self.scheduler.jobs), 6)
        self.assertEqual([r['id'] for r in self.remaining], ['cert-four'])
        self.scheduler.poll()
        self.assertEqual(len(self.scheduler.jobs), 6)
        self.scheduler.close()

    def install_guarded_claim(self):
        def claim(types, *, lane=None, single_page_only=False):
            row = next((r for r in self.remaining if types is None or r['doc_type'] in types), None)
            if row and single_page_only and not row.get('_batch_safe', False):
                return None
            if row:
                self.remaining.remove(row)
            return row
        self.store.claim_next.side_effect = claim

    def test_long_report_and_unknown_page_count_run_alone_without_starting_peer_budget(self):
        self.scheduler.close()
        self.manager.model_batch_size = 2
        self.remaining = [scheduling.task(name, kind) for name, kind in [
            ('long-certificate','DIPLOMA'), ('short-certificate','DIPLOMA'),
            ('long-report','MEDICAL_REPORT'), ('form','GENERIC')]]
        self.remaining[1]['_batch_safe'] = self.remaining[3]['_batch_safe'] = True
        self.install_guarded_claim()
        self.scheduler = TaskScheduler(self.store,self.manager,self.models,None,self.logger,self.replies.append,factory=scheduling.Child)
        self.scheduler.poll()
        self.scheduler.poll()
        self.assertEqual({j.task['id'] for j in self.scheduler.jobs.values()}, {'long-certificate','long-report'})
        self.assertEqual([r['id'] for r in self.remaining], ['short-certificate','form'])
        self.scheduler.close()

    def test_long_fair_head_waits_for_short_lane_to_drain_and_is_not_skipped(self):
        self.scheduler.close()
        self.manager.model_batch_size = 2
        self.remaining = [scheduling.task(name, kind) for name, kind in [
            ('short','GENERIC'), ('long','MEDICAL_REPORT'), ('later','TABLE')]]
        self.remaining[0]['_batch_safe'] = self.remaining[2]['_batch_safe'] = True
        self.install_guarded_claim()
        self.scheduler = TaskScheduler(self.store,self.manager,self.models,None,self.logger,self.replies.append,factory=scheduling.Child)
        self.scheduler.poll()
        self.assertEqual([j.task['id'] for j in self.scheduler.jobs.values()], ['short'])
        self.assertEqual([r['id'] for r in self.remaining], ['long','later'])
        job = next(iter(self.scheduler.jobs.values()))
        self.scheduler._begin_stop(job)
        job.stop_thread.join(2)
        self.scheduler.poll()
        self.assertEqual([j.task['id'] for j in self.scheduler.jobs.values()], ['long'])
        self.assertEqual([r['id'] for r in self.remaining], ['later'])
        self.scheduler.close()


class QueueManager:
    model_batch_size = 2
    def __init__(self):
        self.calls, self.entered = [], queue.Queue()
        self.release = threading.Event()
    def recognize_batch(self, model, requests, deliver):
        self.calls.append([r['context']['task_id'] for r in requests])
        self.entered.put(self.calls[-1])
        if len(self.calls) == 1:
            self.release.wait(2)
        for index, request in enumerate(requests):
            deliver(index, {'text':request['context']['task_id']}, None)
    def stop_run(self, *identity):
        pass
    def close(self):
        self.release.set()


class BatchQueueTests(unittest.TestCase):
    def make(self):
        manager = QueueManager()
        queues = ModelQueues(manager)
        self.addCleanup(queues.close)
        return manager, queues
    def submit(self, queues, name, task='ocr'):
        return queues.submit('glm_ocr',dict(image='synthetic',task=task),task_id=name,run_id=name,
                             deadline=time.monotonic()+5)

    def test_single_starts_immediately_then_existing_backlog_pairs_without_wait(self):
        manager, queues = self.make()
        first = self.submit(queues,'first')
        self.assertEqual(manager.entered.get(timeout=1), ['first'])
        others = [self.submit(queues,name) for name in ['a','b','c']]
        manager.release.set()
        self.assertEqual(first.result(1)['text'],'first')
        self.assertEqual([f.result(1)['text'] for f in others],['a','b','c'])
        self.assertEqual(manager.calls,[['first'],['a','b'],['c']])

    def test_incompatible_head_is_not_skipped_and_cancelled_pending_never_runs(self):
        manager, queues = self.make()
        first = self.submit(queues,'first')
        manager.entered.get(timeout=1)
        a=self.submit(queues,'a'); b=self.submit(queues,'b','table'); c=self.submit(queues,'c')
        removed=self.submit(queues,'removed')
        queues.stop_run('removed','removed')
        manager.release.set()
        for future in [first,a,b,c]: future.result(1)
        with self.assertRaisesRegex(RuntimeFailure,'CANCELLED'): removed.result(1)
        self.assertEqual(manager.calls,[['first'],['a'],['b'],['c']])


class BatchFactory:
    def __init__(self, fault=None):
        self.clients, self.fault = {}, fault
    def __call__(self, key, config, phase):
        factory=self
        class Client:
            def __init__(self):
                self.entered=threading.Event(); self.dead=False
                self.release=[threading.Event(),threading.Event()]
                self.cancelled=set(); self.rows=[]
            def call(self, op, timeout, **payload):
                if op=='load': return {'revision':'synthetic'}
                self.rows=payload['rows']; delivered=set()
                payload['on_started'](1)
                self.entered.set(); end=time.monotonic()+timeout
                while len(delivered)<len(self.rows):
                    if self.dead: raise RuntimeFailure('MODEL_PROCESS_EXITED')
                    if time.monotonic()>=end: raise RuntimeFailure('MODEL_REQUEST_TIMEOUT')
                    for index,row in enumerate(self.rows):
                        if index in delivered: continue
                        if row['row_id'] in self.cancelled:
                            value=dict(ok=False,error_code='CANCELLED')
                        elif self.release[index].is_set():
                            value=dict(ok=True,result=dict(text=row.get('image','synthetic'),termination_reason='eos',batch_size=len(self.rows)))
                        else: continue
                        message=dict(id=1,event='row_result',row_id=row['row_id'],**value)
                        payload['on_row'](message); delivered.add(index)
                        if factory.fault=='duplicate': payload['on_row'](message)
                        if factory.fault=='unknown': payload['on_row']({**message,'row_id':'wrong'})
                    time.sleep(.001)
                return {'completed':len(self.rows)}
            def cancel_rows(self, identity, rows):
                if factory.fault != 'ignore_cancel': self.cancelled.update(rows)
            def poll(self): return 1 if self.dead else None
            def close(self): self.dead=True
        client=Client(); self.clients[key]=client; return client


class BatchOwnershipTests(unittest.TestCase):
    def make(self, fault=None):
        temporary=tempfile.TemporaryDirectory();self.addCleanup(temporary.cleanup)
        factory=BatchFactory(fault)
        manager=ModelManager(RuntimeConfig(Path(temporary.name),model_batch_size=2),factory=factory)
        manager.start(); self.addCleanup(manager.close)
        return manager,factory.clients['glm_ocr']
    def requests(self):
        return [dict(payload=dict(image=name,task='ocr'),context=dict(task_id=name,run_id=name),
            submitted_at=time.monotonic(),deadline=time.monotonic()+5) for name in ['first','second']]

    def test_first_result_returns_before_peer_and_cancel_does_not_unload_shared_model(self):
        manager,client=self.make();results=queue.Queue()
        with ThreadPoolExecutor(1) as pool:
            pending=pool.submit(manager.recognize_batch,'glm_ocr',self.requests(),lambda *value:results.put(value))
            self.assertTrue(client.entered.wait(1));client.release[0].set()
            index,result,error=results.get(timeout=1)
            self.assertEqual((index,result['text'],error),(0,'first',None))
            self.assertFalse(pending.done())
            manager.stop_run('second','second')
            index,result,error=results.get(timeout=1)
            self.assertEqual((index,result,error.code),(1,None,'CANCELLED'))
            pending.result(1)
        self.assertFalse(client.dead)
        self.assertEqual(manager.snapshot()['models']['glm_ocr'],'ready')
        self.assertTrue(all('text' not in metric for metric in manager.metrics))

    def test_stopped_before_dispatch_does_not_start_a_row_or_cancel_its_peer(self):
        manager,client=self.make();results=[]
        manager.stop_run('first','first');client.release[0].set()
        manager.recognize_batch('glm_ocr',self.requests(),lambda *value:results.append(value))
        self.assertEqual(len(client.rows),1)
        self.assertEqual(results[0][2].code,'CANCELLED')
        self.assertEqual(results[1][1]['text'],'second')
        self.assertFalse(client.dead)

    def test_duplicate_or_unknown_row_fails_pending_peer_and_keeps_completed_result(self):
        for fault in ['duplicate','unknown']:
            with self.subTest(fault=fault):
                manager,client=self.make(fault);results=[];client.release[0].set()
                manager.recognize_batch('glm_ocr',self.requests(),lambda *value:results.append(value))
                self.assertEqual(results[0][1]['text'],'first')
                self.assertEqual(results[1][2].code,'MODEL_LOAD_FAILED')
                self.assertTrue(client.dead)

    def test_unconfirmed_cancel_fails_shared_process_and_does_not_invent_peer_success(self):
        manager,client=self.make('ignore_cancel');results=queue.Queue()
        with ThreadPoolExecutor(1) as pool:
            pending=pool.submit(manager.recognize_batch,'glm_ocr',self.requests(),lambda *value:results.put(value))
            self.assertTrue(client.entered.wait(1))
            with patch('ocr_app.runtime.ROW_CANCEL_WAIT_SECONDS',.02): manager.stop_run('first','first')
            pending.result(1)
        rows=[results.get(timeout=1) for _ in range(2)]
        self.assertTrue(all(row[1] is None for row in rows))
        self.assertEqual(rows[0][2].code,'CANCELLED')
        self.assertEqual(rows[1][2].code,'MODEL_PROCESS_EXITED')
        self.assertTrue(client.dead)
        self.assertEqual(manager.snapshot()['models']['paddleocr_vl'],'ready')

    def test_expired_row_is_not_dispatched_while_peer_keeps_original_deadline(self):
        manager,client=self.make();requests=self.requests();results=[]
        requests[0]['deadline']=time.monotonic()-1;client.release[0].set()
        manager.recognize_batch('glm_ocr',requests,lambda *value:results.append(value))
        self.assertEqual(results[0][2].code,'EXTRACT_TIMEOUT')
        self.assertEqual(results[1][1]['text'],'second')
        self.assertEqual(client.rows[0]['deadline'],requests[1]['deadline'])


class InputStream:
    def __init__(self): self.lines=queue.Queue()
    def __iter__(self): return self
    def __next__(self):
        value=self.lines.get()
        if value is None: raise StopIteration
        return json.dumps(value)+'\n'


class ModelControlProtocolTests(unittest.TestCase):
    def test_controls_are_scoped_to_rpc_and_late_controls_cannot_touch_next_call(self):
        stream=InputStream();inbox=ModelInbox(stream)
        for identity in [1,2]:
            stream.lines.put(dict(id=identity,op='recognize_batch',rows=[dict(row_id='same')]))
        first=inbox.messages.get(timeout=1)[1]['same'];second=inbox.messages.get(timeout=1)[1]['same']
        stream.lines.put(dict(op='cancel_rows',target_id=1,row_ids=['same']))
        self.assertTrue(first.wait(1));self.assertFalse(second.is_set())
        inbox.finish(1)
        stream.lines.put(dict(op='cancel_rows',target_id=1,row_ids=['same']))
        stream.lines.put(dict(id=3,op='load'))
        inbox.messages.get(timeout=1)
        self.assertFalse(second.is_set())
        stream.lines.put(None);inbox.thread.join(1)
        self.assertTrue(second.is_set())

    def test_duplicate_row_ids_fail_without_registering_ambiguous_controls(self):
        stream=InputStream();inbox=ModelInbox(stream)
        stream.lines.put(dict(id=1,op='recognize_batch',rows=[dict(row_id='x'),dict(row_id='x')]))
        self.assertTrue(inbox.messages.get(timeout=1)[0]['protocol_error'])
        inbox.thread.join(1);self.assertEqual(inbox.controls,{})


@unittest.skipUnless(os.name=='nt','Windows Job supervision')
class RealBatchProtocolTests(unittest.TestCase):
    def test_actual_worker_imports_numerical_libraries_before_blocking_control_reader(self):
        class CPUConfig(RuntimeConfig):
            def model_command(self,key):
                return [sys.executable,'-u',str(Path(__file__).parent/'fixtures/startup_import_worker.py'),'--model','glm-ocr']
        with tempfile.TemporaryDirectory() as directory:
            manager=ModelManager(CPUConfig(Path(directory),mode='single_resident',load_timeout=3))
            self.addCleanup(manager.close)
            manager.start()
            self.assertEqual(manager.snapshot()['state'],'ready')
            self.assertEqual(manager.recognize('glm_ocr',image='synthetic')['text'],'synthetic')

    def test_stream_and_targeted_cancel_keep_both_owned_processes_alive(self):
        class CPUConfig(RuntimeConfig):
            def model_command(self,key):
                return [sys.executable,'-u',str(Path(__file__).parent/'fixtures/batch_model_worker.py')]
        with tempfile.TemporaryDirectory() as directory:
            manager=ModelManager(CPUConfig(Path(directory),model_batch_size=2))
            manager.start();self.addCleanup(manager.close)
            requests=[dict(payload=dict(image=name,task='ocr'),context=dict(task_id=name,run_id=name),
                submitted_at=time.monotonic(),deadline=time.monotonic()+5) for name in ['fast','slow']]
            results=queue.Queue()
            with ThreadPoolExecutor(1) as pool:
                pending=pool.submit(manager.recognize_batch,'glm_ocr',requests,lambda *value:results.put(value))
                first=results.get(timeout=2)
                self.assertEqual(first[1]['text'],'fast');self.assertFalse(pending.done())
                manager.stop_run('slow','slow')
                self.assertEqual(results.get(timeout=1)[2].code,'CANCELLED')
                pending.result(1)
            self.assertTrue(all(client.poll() is None for client in manager.clients.values()))
            self.assertEqual(len(manager.clients),2)
