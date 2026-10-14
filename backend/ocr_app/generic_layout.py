"""Conservative form regions using installed CPU text/line detectors only."""
from .documents import normalized_box
from .table_recognition import locate_table_candidates, nearby_text


def plan_form_regions(image, box, check):
    crop=image.crop(box)
    notes=[]
    try:
        candidates=locate_table_candidates(crop,check)
        lines=nearby_text(crop,candidates,check)
    except Exception as exc:
        # Cancellation/deadline checks are never hidden as a detector fallback.
        check()
        if getattr(exc,'code',None):raise
        return [dict(box=box,task='ocr',lines=[])],['主体位置检测不可用，保留完整区域识别。']
    check()
    width,height=crop.size
    bounds=[0,0,width,height]
    if lines:
        observed=[line['box'] for line in lines]+[candidate['box'] for candidate in candidates]
        margin=max(16,round(min(width,height)*.025))
        proposed=[max(0,int(min(b[0] for b in observed))-margin),max(0,int(min(b[1] for b in observed))-margin),
                  min(width,int(max(b[2] for b in observed))+margin),min(height,int(max(b[3] for b in observed))+margin)]
        # Crop only demonstrably blank margins, not merely undetected text.
        strips=[(0,0,width,proposed[1]),(0,proposed[3],width,height),
                (0,proposed[1],proposed[0],proposed[3]),(proposed[2],proposed[1],width,proposed[3])]
        if all(crop.crop(strip).convert('L').getextrema()[0]>=245 for strip in strips if strip[2]>strip[0] and strip[3]>strip[1]):
            bounds=proposed
    regions=[(bounds,'ocr')]
    if len(candidates)==1:
        tb=candidates[0]['box'];top=max(bounds[1],int(tb[1]));bottom=min(bounds[3],int(tb[3]+1))
        # Side notes or text crossing a boundary make a table-only band unsafe.
        crossed=any(b[1]<edge<b[3] for b in (line['box'] for line in lines) for edge in (top,bottom))
        side=any(b[1]<bottom and b[3]>top and (b[0]<tb[0]-8 or b[2]>tb[2]+8) for b in (line['box'] for line in lines))
        if lines and not crossed and not side and tb[2]-tb[0]>width*.5 and bottom>top:
            regions=[]
            for start,end,task in [(bounds[1],top,'ocr'),(top,bottom,'table'),(bottom,bounds[3],'ocr')]:
                if end>start and crop.crop((bounds[0],start,bounds[2],end)).convert('L').getextrema()[0]<245:
                    regions.append(([bounds[0],start,bounds[2],end],task))
    if len(candidates)>1:notes.append('检测到多个表格候选，保留整块内容识别，字段归属需核对。')
    planned=[]
    for area,task in regions:
        absolute=(box[0]+area[0],box[1]+area[1],box[0]+area[2],box[1]+area[3])
        positioned=[dict(text=line['text'],bbox=normalized_box([box[0]+line['box'][0],box[1]+line['box'][1],
                     box[0]+line['box'][2],box[1]+line['box'][3]],image.size)) for line in lines
                    if area[1]<=line['box'][1] and area[3]>=line['box'][3]]
        planned.append(dict(box=absolute,task=task,lines=positioned))
    return planned or [dict(box=box,task='ocr',lines=[])],notes
