"""Run in a model environment: exact row-control path with CPU fake generation."""
import base64
from io import BytesIO
from pathlib import Path
from types import SimpleNamespace
import sys
import threading
import time
import unittest
from unittest.mock import patch

try:
    import torch
except ImportError:
    torch = None

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'backend'))
from ocr_app.batch_generation import generate_rows


@unittest.skipIf(torch is None,'Run explicitly in model environment; no app Torch dependency')
class GenerationRowsTests(unittest.TestCase):
    def make(self):
        from PIL import Image
        target=BytesIO();Image.new('RGB',(20,20),'white').save(target,format='PNG')
        encoded=base64.b64encode(target.getvalue()).decode()
        rows=[dict(row_id=name,image_base64=encoded,task='ocr',max_new_tokens=8,
            generation_timeout_seconds=2,deadline=time.monotonic()+30) for name in ['a','b']]
        controls={name:threading.Event() for name in ['a','b']};trace=[]
        class Inputs(dict):
            def to(self,device): return self
        class Processor:
            tokenizer=SimpleNamespace(padding_side='right',pad_token_id=0,eos_token_id=2)
            def apply_chat_template(self,messages,**kwargs):
                return Inputs(input_ids=torch.zeros((len(messages),3),dtype=torch.long))
            def decode(self,tokens,**kwargs): return ','.join(map(str,tokens.tolist()))
        class Model:
            generation_config=SimpleNamespace(eos_token_id=2)
            def generate(self,input_ids,stopping_criteria,**kwargs):
                plans=[[7,2,0,0],[9,9,9,2]]
                for step in range(4):
                    if hasattr(self,'before_step'): self.before_step(step)
                    input_ids=torch.cat([input_ids,torch.tensor([[plans[i][step]] for i in range(input_ids.shape[0])])],dim=1)
                    mask=stopping_criteria[0](input_ids,None)
                    if bool(mask.all()): break
                trace.append('returned')
                return input_ids
        engine=SimpleNamespace(torch=torch,name='paddleocr-vl',processor=Processor(),model=Model())
        return engine,rows,controls,trace

    def run_rows(self,engine,rows,controls,trace):
        results=[]
        with patch.object(torch.cuda,'synchronize'),patch.object(torch.cuda,'reset_peak_memory_stats'),\
             patch.object(torch.cuda,'max_memory_allocated',return_value=0),\
             patch.object(torch.cuda,'max_memory_reserved',return_value=0),patch.object(torch.cuda,'empty_cache'):
            def completed(*value): trace.append(value[0]);results.append(value)
            final=generate_rows(engine,rows,controls,completed)
        self.assertEqual(final['completed'],len(rows))
        return results

    def test_short_row_is_emitted_before_peer_finishes_without_mixing_tokens(self):
        engine,rows,controls,trace=self.make()
        results=self.run_rows(engine,rows,controls,trace)
        self.assertEqual(trace,['a','b','returned'])
        self.assertEqual([r[1]['text'] for r in results],['7,2','9,9,9,2'])
        self.assertEqual([r[1]['output_tokens'] for r in results],[2,4])
        self.assertTrue(all(r[1]['batch_size']==2 for r in results))

    def test_row_soft_deadline_does_not_stop_peer(self):
        engine,rows,controls,trace=self.make();rows[0]['generation_timeout_seconds']=1e-9
        engine.model.before_step=lambda step: time.sleep(.02) if step==0 else None
        results=self.run_rows(engine,rows,controls,trace)
        self.assertEqual([r[1]['termination_reason'] for r in results],['time_limit','eos'])
        self.assertEqual(results[1][1]['text'],'9,9,9,2')

    def test_cancel_before_generation_and_bad_image_only_affect_their_row(self):
        for failure in ['cancel','bad']:
            with self.subTest(failure=failure):
                engine,rows,controls,trace=self.make()
                if failure=='cancel': controls['a'].set()
                else: rows[0]['image_base64']='invalid image'
                results=self.run_rows(engine,rows,controls,trace)
                self.assertEqual(results[0][2],'CANCELLED' if failure=='cancel' else 'INPUT_INVALID')
                self.assertIsNone(results[0][1])
                self.assertEqual(results[1][1]['termination_reason'],'eos')
                self.assertEqual(results[1][1]['batch_size'],1)
