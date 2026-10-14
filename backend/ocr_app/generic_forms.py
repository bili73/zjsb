"""Dynamic form pairs grounded in observed text and cell geometry, never a field dictionary."""
import re
from collections import Counter
from uuid import uuid4

from bs4 import BeautifulSoup
from .table_format import table_html
from .table_recognition import decode_table_output

LABEL = re.compile(r'(?:^|[\t \u3000]+)([^\s:：，,。；;!?！？]{1,40})\s*[:：](?![/\\])')


def compact(text):
    return re.sub(r'\s+', '', text)


def is_label(text):
    value=text.strip().rstrip(':：').strip()
    return bool(value and len(value)<=40 and any(c.isalpha() for c in value)
                and not re.search(r'[\n。；;!?！？/\\]',value))


def source(block, raw, bbox=None, kind=None):
    result={k:block[k] for k in ('page','region_id','bbox','extraction_method') if k in block}
    result.update(raw_text=raw,bbox_kind=kind or 'region')
    if bbox is not None:result['bbox']=bbox
    return result


def pair(key,value,origin,basis):
    return dict(pair_id=str(uuid4()),key=key.strip().rstrip(':：').strip(),value=value.strip() or None,
                source=origin,basis=basis,confidence=None,confidence_method='unavailable')


def contains(outer,inner):
    return all([outer[0]<=inner[0]+.002,outer[1]<=inner[1]+.002,
                outer[2]>=inner[2]-.002,outer[3]>=inner[3]-.002])


def text_records(block, text):
    """Use CPU line boxes only if their text is actually present in the model output."""
    lines=block.get('_layout_lines',[])
    observed=compact(text)
    counts=Counter(compact(line['text']) for line in lines if compact(line['text']))
    matched=[line for line in lines if compact(line['text']) and
             observed.count(compact(line['text']))>=counts[compact(line['text'])]]
    # Partial line matches must not silently replace the rest of the OCR text.
    if matched and ''.join(compact(line['text']) for line in matched)==observed:
        return [dict(text=line['text'],source=source(block,line['text'],line['bbox'],'block')) for line in matched]
    single=len([line for line in text.splitlines() if line.strip()])==1
    return [dict(text=line,source=source(block,line,kind='block' if single and block.get('extraction_method')=='pdf_text' else 'region'))
            for line in text.splitlines() if line.strip()]


def text_pairs(records):
    output=[];used=set()
    for i,record in enumerate(records):
        if i in used:continue
        matches=[m for m in LABEL.finditer(record['text']) if is_label(m[1])]
        for index,m in enumerate(matches):
            value=record['text'][m.end():matches[index+1].start() if index+1<len(matches) else None].strip()
            origin=dict(record['source']);basis='label'
            if not value and len(matches)==1 and origin['bbox_kind']=='block':
                box=origin['bbox'];height=box[3]-box[1]
                candidates=[]
                for j,other in enumerate(records):
                    if j==i or j in used or LABEL.search(other['text']) or other['source']['bbox_kind']!='block':continue
                    b=other['source']['bbox']
                    right=b[0]>=box[2] and abs((b[1]+b[3]-box[1]-box[3])/2)<height*.6 and b[0]-box[2]<.2
                    below=0<=b[1]-box[3]<=height*1.5 and abs(b[0]-box[0])<height
                    if right or below:candidates.append((j,other))
                if len(candidates)==1:
                    j,other=candidates[0];used.add(j);value=other['text'];basis='aligned_label'
                    b=other['source']['bbox'];origin['bbox']=[min(box[0],b[0]),min(box[1],b[1]),max(box[2],b[2]),max(box[3],b[3])]
                    origin['raw_text']+='\n'+value
            output.append(pair(m[1],value,origin,basis))
    return output


def table_pairs(block,grid):
    rows,merges=grid['rows'],grid['merges']
    def origin(r,columns,raw):
        native=block.get('table_rows',[])
        boxes=[]
        if r<len(native):
            cells=native[r].get('cell_bboxes',[])
            boxes=[cells[c] for c in columns[-1:] if c<len(cells) and cells[c]]
        bbox=[min(b[0] for b in boxes),min(b[1] for b in boxes),max(b[2] for b in boxes),max(b[3] for b in boxes)] if boxes else None
        return source(block,raw,bbox,'cell' if boxes else 'region')
    output=[]
    if grid.get('header_rows'):
        # A single value row can be a horizontally arranged form; repeated rows stay a table.
        if grid['header_rows']==1 and len(rows)==2 and not merges and all(is_label(v) for v in rows[0]):
            for c,key in enumerate(rows[0]):
                output.append(pair(key,rows[1][c],source(block,key+'\n'+rows[1][c]),'header_value'))
        return output
    covered={(r,c) for m in merges for r in range(m['row'],m['row']+m['rowspan'])
             for c in range(m['column'],m['column']+m['colspan']) if (r,c)!=(m['row'],m['column'])}
    anchors=[[(c,v) for c,v in enumerate(row) if (r,c) not in covered] for r,row in enumerate(rows)]
    # An explicit label somewhere establishes alternating form cells. Otherwise pure text is ambiguous.
    form=any(len(row)>=2 and is_label(row[0][1]) and row[0][1].rstrip().endswith((':','：')) for row in anchors)
    # Mixed value types support an unlabeled two-column form; uniform records do not.
    if not form and len(anchors)>=3 and all(len(row)==2 and is_label(row[0][1]) for row in anchors):
        numeric=[bool(re.fullmatch(r'[\d\s./年月日%+−-]+',row[1][1].strip())) for row in anchors]
        form=any(numeric) and not all(numeric[1:]) and any(len(row[1][1])>len(row[0][1]) for row in anchors)
    if not form:return []
    for r,row in enumerate(anchors):
        if len(row)%2:continue
        if not all(is_label(row[i][1]) for i in range(0,len(row),2)):continue
        for i in range(0,len(row),2):
            c,key=row[i];vcol,value=row[i+1]
            span=next((m for m in merges if m['row']==r and m['column']==c and m['rowspan']>1),None)
            if span:
                continuation=anchors[r+1:r+span['rowspan']]
                if not all(len(part)==1 and part[0][0]==vcol for part in continuation):continue
                value='\n'.join([value]+[part[0][1] for part in continuation])
                # A spanning label needs the enclosing region, not the first value cell alone.
                output.append(pair(key,value,source(block,key+'\n'+value),'table_cells'))
                continue
            output.append(pair(key,value,origin(r,[c,vcol],key+'\n'+value),'table_cells'))
    return output


def extract_generic(evidence):
    blocks=[];tables=[];pairs=[];full=[];limitations=[];prepared=[];text_by_page={}
    for b in evidence:
        raw=b['text']
        try:html=table_html(raw)
        except ValueError:
            html=raw;limitations.append('表格结构不完整，原始文字已保留，无法可靠配对的字段请手工补录。')
        grids=[]
        if '<table' in html.lower():
            try:grids=decode_table_output(html)
            except ValueError:limitations.append('表格结构不完整，原始文字已保留，无法可靠配对的字段请手工补录。')
        soup=BeautifulSoup(html,'html.parser') if '<' in html and '>' in html else None
        rendered=raw
        if soup is not None:
            for element,grid in zip(soup.find_all('table'),grids):
                element.replace_with('\n'+'\n'.join('\t'.join(row) for row in grid['rows'])+'\n')
            rendered=soup.get_text('\n',strip=True)
            # Preserve unparsed OTSL instead of stripping unknown structural tokens.
            if not grids and re.search(r'<(?:fcel|ecel|lcel|ucel|xcel|nl)>',raw):rendered=raw
        blocks.append(dict(text=rendered,raw_text=raw,page=b['page'],source=source(b,raw),
                           confidence=None,confidence_method='unavailable',**({'bbox':b['bbox']} if b.get('bbox') else {})))
        prepared.append((b,html,rendered,grids))
    native_tables=[(b,compact(rendered)) for b,_,rendered,grids in prepared
                   if grids and b.get('extraction_method')=='pdf_text' and b.get('bbox')]
    for b,html,rendered,grids in prepared:
        redundant=not grids and b.get('extraction_method')=='pdf_text' and b.get('bbox') and any(
            t['page']==b['page'] and contains(t['bbox'],b['bbox']) and compact(rendered) in table_text
            for t,table_text in native_tables)
        if redundant:continue  # Original duplicate remains in blocks with its own coordinates.
        full.append(rendered)
        if grids:
            for grid in grids:
                tables.append(dict(rows=grid['rows'],merges=grid['merges'],source=source(b,b['text'])))
                if not grid['warnings']:pairs.extend(table_pairs(b,grid))
            soup=BeautifulSoup(html,'html.parser')
            for t in soup.find_all('table'):t.decompose()
            text=soup.get_text('\n',strip=True)
        else:text=rendered
        text_by_page.setdefault(b['page'],[]).extend(text_records(b,text))
    for records in text_by_page.values():pairs.extend(text_pairs(records))
    return dict(full_text='\n\n'.join(full),blocks=blocks,key_values=pairs,tables=tables,
                doc_subtype_guess=None,doc_subtype_confidence=None,doc_subtype_confidence_method='unavailable',
                extraction_notes=list(dict.fromkeys(limitations)))
