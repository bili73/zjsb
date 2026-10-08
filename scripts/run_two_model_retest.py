"""Offline, serial paired retest with bounded generation and sampled RAM."""
import argparse
import ctypes
import hashlib
import importlib
import importlib.metadata
import json
import os
import threading
import time
from datetime import datetime
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
os.environ.update(HF_HOME=str(ROOT/'.cache/huggingface'),HF_HUB_OFFLINE='1',TRANSFORMERS_OFFLINE='1',HF_HUB_DISABLE_TELEMETRY='1',DO_NOT_TRACK='1')

def now(): return datetime.now().astimezone().isoformat()

def save(path, data):
    temporary=path.with_suffix(path.suffix+'.tmp')
    with temporary.open('w',encoding='utf-8') as f:
        json.dump(data,f,ensure_ascii=False,indent=2)
        f.flush()
        os.fsync(f.fileno())
    temporary.replace(path)

class MemorySampler:
    def __init__(self):
        import psutil
        self.psutil=psutil
        self.process=psutil.Process()
        self.lock=threading.Lock()
        self.stop=threading.Event()
        self.reset()
        self.thread=threading.Thread(target=self.loop,daemon=True)
        self.thread.start()

    def reset(self):
        with self.lock:
            self.values={'process_rss_peak_gib':0,'host_used_peak_gib':0,'host_available_min_gib':float('inf'),'memory_sample_count':0}
        self.sample()

    def sample(self):
        m=self.psutil.virtual_memory()
        rss=self.process.memory_info().rss/1024**3
        with self.lock:
            self.values['process_rss_peak_gib']=max(self.values['process_rss_peak_gib'],rss)
            self.values['host_used_peak_gib']=max(self.values['host_used_peak_gib'],(m.total-m.available)/1024**3)
            self.values['host_available_min_gib']=min(self.values['host_available_min_gib'],m.available/1024**3)
            self.values['memory_sample_count']+=1

    def loop(self):
        while not self.stop.wait(.25): self.sample()

    def snapshot(self):
        self.sample()
        with self.lock: return dict(self.values)

def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--model',choices=['glm-ocr','paddleocr-vl'],required=True)
    parser.add_argument('--run-dir',type=Path,required=True)
    args=parser.parse_args()
    out=args.run_dir/args.model
    out.mkdir(exist_ok=False)
    manifest=json.loads((args.run_dir/'inputs/manifest.json').read_text(encoding='utf-8'))
    checkpoint=ROOT/'models'/args.model
    # The lock is shared by both model environments; unrelated user processes are not touched.
    lock=(ROOT/'output/two-model-retest-gpu.lock').open('a+b')
    if lock.tell()==0:
        lock.write(b'1')
        lock.flush()
    lock.seek(0)
    if os.name=='nt':
        import msvcrt
        msvcrt.locking(lock.fileno(),msvcrt.LK_NBLCK,1)
    else:
        import fcntl
        fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
    sleep_guard=False
    monitor=MemorySampler()
    process_start=time.perf_counter()
    try:
        if os.name=='nt':
            sleep_guard=bool(ctypes.windll.kernel32.SetThreadExecutionState(0x80000001))
        import torch
        from PIL import Image
        from transformers import AutoModelForCausalLM,AutoModelForImageTextToText,AutoProcessor,StoppingCriteria,StoppingCriteriaList
        torch.set_num_threads(4)
        if not torch.cuda.is_available(): raise RuntimeError('CUDA unavailable')
        versions={k:importlib.metadata.version(k) for k in ['torch','torchvision','transformers','accelerate','psutil']}
        session={'model':args.model,'started_at':now(),'pid':os.getpid(),'python':os.sys.version,'versions':versions,
            'gpu':torch.cuda.get_device_name(),'gpu_total_gib':torch.cuda.get_device_properties(0).total_memory/1024**3,
            'host_total_gib':monitor.psutil.virtual_memory().total/1024**3,'sleep_prevention_active':sleep_guard,
            'revision':json.loads((checkpoint/'download_manifest.json').read_text())['revision']}
        save(out/'session.json',session)
        print(json.dumps({'event':'loading','model':args.model}),flush=True)
        started=time.perf_counter()
        kwargs=dict(local_files_only=True,torch_dtype=torch.bfloat16,attn_implementation='sdpa',device_map={'':0})
        if args.model=='paddleocr-vl':
            model=AutoModelForCausalLM.from_pretrained(checkpoint,trust_remote_code=True,**kwargs).eval()
            module=importlib.import_module(model.__class__.__module__)
            original=module.create_causal_mask
            def compatible_create_causal_mask(*,inputs_embeds,**other):
                return original(input_embeds=inputs_embeds,**other)
            module.create_causal_mask=compatible_create_causal_mask
            processor=AutoProcessor.from_pretrained(checkpoint,trust_remote_code=True,local_files_only=True)
            session['compatibility_patch']='create_causal_mask inputs_embeds -> input_embeds'
        else:
            model=AutoModelForImageTextToText.from_pretrained(checkpoint,**kwargs).eval()
            processor=AutoProcessor.from_pretrained(checkpoint,local_files_only=True)
        torch.cuda.synchronize()
        session.update(load_seconds=time.perf_counter()-started,load_memory=monitor.snapshot(),load_peak_allocated_gib=torch.cuda.max_memory_allocated()/1024**3,load_peak_reserved_gib=torch.cuda.max_memory_reserved()/1024**3)
        save(out/'session.json',session)
        print(json.dumps({'event':'loaded','model':args.model,'seconds':session['load_seconds']}),flush=True)

        class Guard(StoppingCriteria):
            def __init__(self,length):
                self.length=length
                self.started=time.perf_counter()
                self.reason=None
            def __call__(self,input_ids,scores,**kwargs):
                count=input_ids.shape[1]-self.length
                if time.perf_counter()-self.started>180:
                    self.reason='generation_timeout'
                    return True
                if count>=192 and count%32==0:
                    tokens=input_ids[0,-192:].tolist()
                    if tokens[:48]==tokens[48:96]==tokens[96:144]==tokens[144:]:
                        self.reason='repetition_stop'
                        return True
                return False

        samples=[{**manifest[0],'id':'warmup-'+manifest[0]['id'],'phase':'warmup'}]+manifest
        for index,sample in enumerate(samples):
            phase=sample.get('phase','measurement')
            sid=sample['id']
            path=Path(sample['image'])
            assert hashlib.sha256(path.read_bytes()).hexdigest()==sample['input_sha256']
            record={'model':args.model,'sample_id':sid,'parent_id':sample['parent_id'],'variant':sample['variant'],
                'repeat':sample['repeat'],'phase':phase,'started_at':now(),'max_new_tokens':4096,
                'input_sha256':sample['input_sha256'],'model_revision':session['revision'],'versions':versions}
            monitor.reset()
            torch.cuda.reset_peak_memory_stats()
            request_start=time.perf_counter()
            inputs=generated=new_tokens=None
            guard=None
            print(json.dumps({'event':'start','model':args.model,'sample':sid,'index':index,'of':len(samples)-1}),flush=True)
            try:
                with Image.open(path) as original_image:
                    image=original_image.convert('RGB')
                    image.thumbnail((1600,1600))
                prompt='Table Recognition:' if sample['task']=='table' else ('Text Recognition:' if args.model=='glm-ocr' else 'OCR:')
                record.update(prompt=prompt,input_size=list(image.size))
                messages=[{'role':'user','content':[{'type':'image','image':image},{'type':'text','text':prompt}]}]
                torch.cuda.synchronize()
                recognition_start=time.perf_counter()
                inputs=processor.apply_chat_template(messages,tokenize=True,add_generation_prompt=True,return_dict=True,return_tensors='pt').to('cuda')
                torch.cuda.synchronize()
                preprocessed=time.perf_counter()
                guard=Guard(inputs['input_ids'].shape[1])
                with torch.inference_mode():
                    generated=model.generate(**inputs,max_new_tokens=4096,do_sample=False,use_cache=True,stopping_criteria=StoppingCriteriaList([guard]))
                torch.cuda.synchronize()
                recognition_end=time.perf_counter()
                new_tokens=generated[0,inputs['input_ids'].shape[1]:]
                raw=processor.decode(new_tokens,skip_special_tokens=True)
                (out/(sid+'.txt')).write_text(raw,encoding='utf-8')
                reason=guard.reason or ('token_limit' if len(new_tokens)>=4096 else 'eos')
                record.update(status='ok' if raw.strip() else 'empty',termination_reason=reason,hit_token_limit=len(new_tokens)>=4096,
                    seconds=recognition_end-recognition_start,preprocess_seconds=preprocessed-recognition_start,
                    generation_seconds=recognition_end-preprocessed,output_tokens=len(new_tokens),characters=len(raw),
                    output_sha256=hashlib.sha256(raw.encode('utf-8')).hexdigest())
            except Exception as error:
                record.update(status='error',termination_reason=guard.reason if guard and guard.reason else 'exception',error_type=type(error).__name__,error=str(error))
            record.update(request_wall_seconds=time.perf_counter()-request_start,finished_at=now(),
                peak_allocated_gib=torch.cuda.max_memory_allocated()/1024**3,peak_reserved_gib=torch.cuda.max_memory_reserved()/1024**3,
                **monitor.snapshot())
            save(out/(sid+'.metrics.json'),record)
            print(json.dumps({'event':'done','model':args.model,'sample':sid,'seconds':record.get('seconds'),
                'termination':record['termination_reason'],'rss_gib':record['process_rss_peak_gib'],'gpu_gib':record['peak_reserved_gib']}),flush=True)
            del inputs,generated,new_tokens
            torch.cuda.empty_cache()
        session.update(finished_at=now(),session_wall_seconds=time.perf_counter()-process_start,status='finished')
        save(out/'session.json',session)
    finally:
        monitor.stop.set()
        monitor.thread.join(timeout=2)
        if sleep_guard: ctypes.windll.kernel32.SetThreadExecutionState(0x80000000)
        lock.close()

if __name__=='__main__': main()
