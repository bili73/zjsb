"""CPU-only automatic layout experiment; no references or manual boxes guide detection."""
import argparse
import hashlib
import json
import math
import os
import shutil
import sys
import time
from datetime import datetime
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'.cache/layout-runtime'))
os.environ.update(HF_HOME=str(ROOT/'.cache/huggingface'),HF_HUB_OFFLINE='1',TRANSFORMERS_OFFLINE='1',HF_HUB_DISABLE_TELEMETRY='1')

HARD=['cert-020-p1','cert-023-p1','cert-026-p1','medical-01-followup-long-jpg',
      'medical-01-blood-p13','medical-02-blood-p13','medical-03-blood-p12']
CONTROLS=['cert-001-p1','medical-01-conclusion-p04']

def sha(path): return hashlib.sha256(path.read_bytes()).hexdigest()
def read(path): return json.loads(path.read_text(encoding='utf-8-sig'))
def write(path,data): path.write_text(json.dumps(data,ensure_ascii=False,indent=2),encoding='utf-8')
def union(a,b): return [min(a[0],b[0]),min(a[1],b[1]),max(a[2],b[2]),max(a[3],b[3])]
def intersection(a,b): return max(0,min(a[2],b[2])-max(a[0],b[0]))*max(0,min(a[3],b[3])-max(a[1],b[1]))

def make_regions(detections,width,height):
    """Group adjacent text, keep table boundaries; coordinates are inferred, never templated."""
    tables=[]
    texts=[]
    omitted=[]
    for d in detections:
        if d['label'] in {'image','header_image','footer_image'}:
            omitted.append(d)
            continue
        box=d['bbox']
        if box[2]<=box[0] or box[3]<=box[1]:
            raise ValueError('Invalid detector box')
        item={'bbox':box[:],'detection_ids':[d['index']], 'labels':[d['label']],
              'order':d['index'],'task':'table' if d['label']=='table' else 'ocr'}
        (tables if item['task']=='table' else texts).append(item)
    # A merged text rectangle must not cross a detected table.
    merged=[]
    for item in texts:
        for group in merged:
            a,b=group['bbox'],item['bbox']
            aw,ah,bw,bh=a[2]-a[0],a[3]-a[1],b[2]-b[0],b[3]-b[1]
            xover=max(0,min(a[2],b[2])-max(a[0],b[0]))
            yover=max(0,min(a[3],b[3])-max(a[1],b[1]))
            xgap=max(0,max(a[0],b[0])-min(a[2],b[2]))
            ygap=max(0,max(a[1],b[1])-min(a[3],b[3]))
            near=(xover>=.45*min(aw,bw) and ygap<=.025*height) or (yover>=.5*min(ah,bh) and xgap<=.08*width)
            box=union(a,b)
            if near and box[3]-box[1]<=.65*width and not any(intersection(box,t['bbox'])>0 for t in tables):
                group['bbox']=box
                group['detection_ids']+=item['detection_ids']
                group['labels']+=item['labels']
                break
        else:
            merged.append(item)
    regions=sorted(tables+merged,key=lambda x:x['order'])
    fallback=not regions
    if fallback:
        regions=[{'bbox':[0,0,width,height],'detection_ids':[],'labels':['no_text_detection_fallback'],'order':0,'task':'ocr'}]
    pad=max(4,round(.008*min(width,height)))
    for r in regions:
        a=r['bbox']
        r['unpadded_bbox']=a[:]
        r['bbox']=[max(0,math.floor(a[0])-pad),max(0,math.floor(a[1])-pad),min(width,math.ceil(a[2])+pad),min(height,math.ceil(a[3])+pad)]
    return regions,omitted,fallback

def main():
    ap=argparse.ArgumentParser()
    ap.add_argument('--reference-run',type=Path,default=ROOT/'output/two-model-retest-20260929-152421')
    ap.add_argument('--output',type=Path,required=True)
    args=ap.parse_args()
    out=args.output.resolve()
    out.mkdir(exist_ok=False)
    for sub in ['inputs','layout','previews']: (out/sub).mkdir()
    started=time.perf_counter()
    from run_two_model_retest import MemorySampler
    monitor=MemorySampler()
    import torch
    import cv2
    import transformers
    from PIL import Image,ImageOps,ImageDraw,ImageFont
    from transformers import AutoImageProcessor,AutoModelForObjectDetection
    torch.set_num_threads(4)
    checkpoint=ROOT/'models/pp-doclayout-v3'
    protocol={'created_at':datetime.now().astimezone().isoformat(),'layout_model':read(checkpoint/'download_manifest.json'),
        'layout_device':'cpu','layout_dtype':'float32','threshold':.5,'padding_fraction':.008,
        'direction':'EXIF only; no sample-specific rotation or perspective correction',
        'groups':{'difficult':HARD,'controls':CONTROLS},'reference_run':str(args.reference_run.resolve()),
        'region_policy':'one region per table; geometric grouping of adjacent non-image text; exclude image/header_image/footer_image with explicit records; whole page OCR if no text detected',
        'scope':'layout and OCR experiment on cached rasters, not production PDF text routing or full application',
        'inference':'existing OCR runner, 4096 tokens, 180s cooperative generation stop, one GPU model at a time',
        'versions':{'torch':torch.__version__,'transformers':transformers.__version__,'opencv':cv2.__version__},
        'script_sha256':sha(Path(__file__)),'reference_sha256':sha(args.reference_run/'references.json')}
    write(out/'protocol.json',protocol)
    begin=time.perf_counter()
    processor=AutoImageProcessor.from_pretrained(checkpoint,local_files_only=True)
    model=AutoModelForObjectDetection.from_pretrained(checkpoint,local_files_only=True).cpu().eval()
    session={'load_seconds':time.perf_counter()-begin,'load_memory':monitor.snapshot(),'started_at':datetime.now().astimezone().isoformat()}
    baseline={r['id']:r for r in read(args.reference_run/'inputs/manifest.json') if r['variant']=='baseline' and r['repeat']==1}
    manifests=[]
    parents=[]
    font_path=Path('C:/Windows/Fonts/arial.ttf')
    for sid in HARD+CONTROLS:
        source=baseline[sid]
        pdf=Path(source['source']).suffix.lower()=='.pdf'
        raster=ROOT/'output/medical-expansion-20260929/review-images'/(sid+'.png') if pdf else Path(source['source'])
        monitor.reset()
        begin=time.perf_counter()
        with Image.open(raster) as im:
            exif=im.getexif().get(274,1)
            image=ImageOps.exif_transpose(im).convert('RGB')
        width,height=image.size
        t=time.perf_counter()
        tensors=processor(images=image,return_tensors='pt')
        with torch.inference_mode(): prediction=model(**tensors)
        result=processor.post_process_object_detection(prediction,target_sizes=[(height,width)],threshold=.5)[0]
        detection_seconds=time.perf_counter()-t
        detections=[]
        for i,(score,label,box) in enumerate(zip(result['scores'],result['labels'],result['boxes'])):
            b=box.tolist()
            b=[max(0,min(width,b[0])),max(0,min(height,b[1])),max(0,min(width,b[2])),max(0,min(height,b[3]))]
            detections.append({'index':i,'label':model.config.id2label[int(label)],'score':float(score),'bbox':b})
        regions,omitted,fallback=make_regions(detections,width,height)
        for i,region in enumerate(regions,1):
            crop=image.crop(region['bbox'])
            crop.thumbnail((1600,1600),Image.Resampling.LANCZOS)
            rid=f'auto--{sid}--r{i:02d}'
            path=out/'inputs'/(rid+'.png')
            crop.save(path)
            manifests.append({**source,'id':rid,'parent_id':sid,'variant':'automatic','repeat':1,'image':str(path),
                'task':region['task'],'input_sha256':sha(path),'region_index':i,'bbox':region['bbox'],'input_size':list(crop.size),
                'bbox_coordinate_system':'pixels after EXIF transpose; right/bottom exclusive','layout_labels':region['labels']})
        preparation_seconds=time.perf_counter()-begin
        parent={'parent_id':sid,'group':source['group'],'cohort':'difficult' if sid in HARD else 'control',
            'source':source['source'],'raster':str(raster),'raster_sha256':sha(raster),'source_sha256':sha(Path(source['source'])),
            'source_size':[width,height],'exif_orientation':exif,'region_count':len(regions),'detections':detections,'regions':regions,
            'omitted_image_regions':omitted,'whole_page_fallback':fallback,'pdf_render_reused':pdf,
            'detection_seconds':detection_seconds,'preparation_seconds':preparation_seconds,**monitor.snapshot()}
        write(out/'layout'/(sid+'.json'),parent)
        parents.append(parent)
        preview=image.copy()
        draw=ImageDraw.Draw(preview)
        font=ImageFont.truetype(str(font_path),max(16,round(width/65)))
        for i,r in enumerate(regions,1):
            box=r['bbox']; color='#c23616' if r['task']=='table' else '#0056b3'
            draw.rectangle(box,outline=color,width=max(3,round(width/300)))
            draw.text((box[0]+3,box[1]+3),f'{i}: {r["task"]}',fill='white',stroke_width=2,stroke_fill=color,font=font)
        preview.thumbnail((1000,1600))
        preview.save(out/'previews'/(sid+'.png'))
        print(json.dumps({'parent':sid,'detections':len(detections),'regions':len(regions),'omitted_images':len(omitted),'fallback':fallback,'seconds':preparation_seconds}),flush=True)
        del tensors,prediction,result,image,preview
    session.update(finished_at=datetime.now().astimezone().isoformat(),total_seconds=time.perf_counter()-started,
        process_rss_peak_gib=max([session['load_memory']['process_rss_peak_gib']]+[p['process_rss_peak_gib'] for p in parents]),parents=len(parents),regions=len(manifests))
    write(out/'layout/session.json',session)
    write(out/'inputs/manifest.json',manifests)
    write(out/'layout/parents.json',parents)
    shutil.copyfile(args.reference_run/'references.json',out/'references.json')
    monitor.stop.set(); monitor.thread.join(timeout=2)
    print(json.dumps({'output':str(out),'parents':len(parents),'regions':len(manifests),'rss_gib':session['process_rss_peak_gib']}))

if __name__=='__main__': main()
