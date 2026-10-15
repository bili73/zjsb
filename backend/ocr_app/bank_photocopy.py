"""Conservative photocopy regions and source-separated bank field candidates."""
import re
import unicodedata

PAN = re.compile(r'(?<![0-9０-９])(?:[0-9０-９][ \t\u3000－-]*){13,19}(?![ \t\u3000－-]*[0-9０-９])')
PHONE_NAME = re.compile(r'([\u4e00-\u9fff·]{2,8})\s*(?:电话[：:]?\s*)?1[3-9][0-9]{9}')
BACK = re.compile(r'持卡人签名|SIGNATURE|AUTH[O0]?RIZED|AUTOHRIZED|安全码|CVV|CVC|网上银行|客服电话|本卡须|若遗失|社会保障卡', re.I)
NON_PAN = re.compile(r'身份证|身份号码|社会保障号码|社保号|电话|热线|手机|行号|联行号|\b(?:TEL|PHONE|HOTLINE|CVV|CVC)\b',re.I)
BANK = re.compile(r'^(?:[A-Z]{2,8}\s+)?([\u4e00-\u9fff]{2,24}?(?:银行|銀行|信用社|信合|农商行))')
BRANCH = re.compile(r'[\u4e00-\u9fff0-9（）()·]{2,60}(?:支行|分行|营业部)')
BRANCH_LABEL = re.compile(r'^(?:开户支行|开户网点|支行名称|开户银行|开户行)\s*[:：]?\s*')


def chinese_id(text):
    from .validation import validate_field
    if not re.fullmatch(r'[0-9]{17}[0-9Xx]',text):return False
    checks=validate_field('ID_CARD_FRONT','id_number',text)
    return all(any(c['rule_id']==rule and c['kind']==kind and c['status']=='PASS' for c in checks)
               for rule,kind in [('id_cn_v1','CHECKSUM'),('id_birth_v1','FORMAT')])


def pan_numbers(text):
    """Line context wins over numeric length; never repair or choose by checksum."""
    lines=text.splitlines()
    for i,line in enumerate(lines):
        if NON_PAN.search(line) or BACK.search(line):continue
        if i and NON_PAN.fullmatch(lines[i-1].strip(' :：')):continue
        for match in PAN.finditer(line):
            if match.end()<len(line) and line[match.end()] in 'Xx':continue
            value=re.sub(r'[\s－-]','',unicodedata.normalize('NFKC',match[0]))
            if chinese_id(value) and not re.search(r'(?:银行卡号|卡号|账号)\s*[:：]?\s*$',line[:match.start()]):continue
            yield value,match[0]


def bare_name(text):
    return bool(re.fullmatch(r'[\u4e00-\u9fff·]{2,6}',text) and
                not re.search(r'银行|銀行|支行|姓名|电话|签名|卡号|开户|银联|借记|信用|信合|金卡|地址|有效|服务|热线|客服',text))


def card_boxes(image, check=lambda: None):
    """Low-contrast closed outlines; no choice of front/back is made here."""
    import cv2
    import numpy as np
    probe = image.convert('RGB');probe.thumbnail((1000, 1000))
    check()
    gray = cv2.cvtColor(np.asarray(probe), cv2.COLOR_RGB2GRAY)
    edges = cv2.morphologyEx(cv2.Canny(gray, 10, 30), cv2.MORPH_CLOSE, np.ones((7, 7), np.uint8))
    boxes = []
    for contour in cv2.findContours(edges, cv2.RETR_LIST, cv2.CHAIN_APPROX_SIMPLE)[0]:
        check()
        area = cv2.contourArea(contour);w, h = cv2.minAreaRect(contour)[1]
        if min(w, h) < 10 or not (.03 < area/(probe.width*probe.height) < .45 and
                1.25 < max(w,h)/min(w,h) < 2.3 and area/(w*h) > .65):continue
        x,y,w,h = cv2.boundingRect(contour)
        box = [x*image.width/probe.width, y*image.height/probe.height,
               (x+w)*image.width/probe.width, (y+h)*image.height/probe.height]
        if not any(overlap(box, old) > .65 for old in boxes):boxes.append(box)
    return sorted(boxes, key=lambda b: (b[1], b[0]))


def overlap(a, b):
    intersection = max(0, min(a[2],b[2])-max(a[0],b[0]))*max(0,min(a[3],b[3])-max(a[1],b[1]))
    return intersection/max(1,min((a[2]-a[0])*(a[3]-a[1]),(b[2]-b[0])*(b[3]-b[1])))


def plan_bank_regions(image, box, check):
    """Only associate supplements with one observed front, never by fixed pixels."""
    from .table_recognition import nearby_text
    fallback = [dict(box=box, task='ocr', bank_role='whole')]
    try:
        cards = card_boxes(image, check)
        lines = nearby_text(image, [], check)
    except Exception:
        check()
        return fallback, ['银行卡主体检测不可用，保留整图识别，请核对材料归属。']
    check()
    backs, fronts = [], []
    for card in cards:
        text = '\n'.join(line['text'] for line in lines if overlap(card,line['box']) > .6)
        # A real issuer header/PAN is stronger than small-print service text.
        issuer=any(BANK.match(t.strip()) for t in text.splitlines())
        if issuer and (list(pan_numbers(text)) or not BACK.search(text)):fronts.append(card)
        elif BACK.search(text):backs.append(card)
    if not fronts:
        # No outlines: retain the page, plus source-bound handwriting lines at
        # higher resolution. Do not promote the quick recognizer's text to fields.
        extra=[line for line in lines if re.search(r'1[3-9][0-9]{9}',line['text']) and
               not NON_PAN.search(line['text']) and line['box'][2]-line['box'][0]>2*(line['box'][3]-line['box'][1])]
        return fallback+[dict(box=padded_box(line['box'],image),task='ocr',bank_role='supplement') for line in extra[:4]], []
    outside = [line for line in lines if not any(overlap(card,line['box']) > .9 for card in cards)]
    if len(fronts) != 1 or len(fronts)+len(backs) != len(cards):
        return [dict(box=tuple(round(v) for v in card),task='ocr',bank_role='ambiguous_front') for card in fronts], [
            '存在多张卡面，手写姓名与开户支行未自动配对，请拆分或人工填写。']
    front = fronts[0]
    width = front[2]-front[0]
    # Keep geometrically observed lines even when fast OCR misreads handwriting.
    below=[line for line in outside if abs((line['box'][0]+line['box'][2]-front[0]-front[2])/2)<width*.4
           and front[3] <= (line['box'][1]+line['box'][3])/2 < front[3]+width*1.3]
    connected=[];bottom=front[3]
    for line in sorted(below,key=lambda l:l['box'][1]):
        if line['box'][1]-bottom>width*.35 or BACK.search(line['text']):break
        connected.append(line);bottom=max(bottom,line['box'][3])
    below=connected
    sides=[line for line in outside if front[1]-width*.5 < (line['box'][1]+line['box'][3])/2 < front[3]
           and (-width*.3<front[0]-line['box'][2]<width*.7 or -width*.3<line['box'][0]-front[2]<width*.7)]
    # Side groups need bank/branch context; an adjacent personnel form is not enough.
    selected=below[:]
    for side in ('left','right'):
        group=[line for line in sides if ((line['box'][0]+line['box'][2])<(front[0]+front[2]))==(side=='left')]
        if any(BANK.match(line['text'].strip()) or BRANCH.search(line['text']) for line in group):selected.extend(group)
    selected=[line for line in selected if not BACK.search(line['text']) and
              line['box'][2]-line['box'][0]>1.3*(line['box'][3]-line['box'][1])]
    # Adjacent lines in one column preserve wrapped branches and handwriting context.
    areas=[]
    for line in sorted(selected,key=lambda l:(l['box'][1],l['box'][0])):
        area=line['box'];merged=False
        for j,old in enumerate(areas):
            common=min(area[2],old[2])-max(area[0],old[0])
            if common>.5*min(area[2]-area[0],old[2]-old[0]) and 0<=area[1]-old[3]<max(area[3]-area[1],old[3]-old[1])*.4:
                areas[j]=[min(old[0],area[0]),old[1],max(old[2],area[2]),max(old[3],area[3])];merged=True;break
            if common>.5*min(area[2]-area[0],old[2]-old[0]) and old[1]<=area[1]<old[3]:
                areas[j]=[min(old[0],area[0]),old[1],max(old[2],area[2]),max(old[3],area[3])];merged=True;break
        if not merged:areas.append(area)
    # Keep each line separate: no rectangle can bridge over a card back or another form.
    plans = []
    for area, role in [(front,'front'), *((area,'supplement') for area in areas[:10])]:
        padded=padded_box(area,image,.02 if role=='front' else .12)
        if role == 'supplement' and any(overlap(padded,card) > .05 for card in backs):continue
        plans.append(dict(box=tuple(padded),task='ocr',bank_role=role))
    if len(plans)==1 and not backs:return fallback, []
    return plans, ['按卡面和补充文字分区识别；卡背及邻近表单未作为字段来源，姓名与卡片归属仍需人工核对。']


def padded_box(area,image,ratio=.12):
    margin=max(8,round(min(area[2]-area[0],area[3]-area[1])*ratio))
    return tuple([max(0,round(area[0]-margin)),max(0,round(area[1]-margin)),
                  min(image.width,round(area[2]+margin)),min(image.height,round(area[3]+margin))])


def bank_candidates(evidence):
    """Keep raw text and role provenance, including disagreeing printed/handwritten PANs."""
    from .extraction import plain
    candidates = {key: [] for key in ('card_number','holder_name','bank_name','branch_name')}
    for block in evidence:
        role = block.get('_bank_role','whole')
        if role == 'back':continue
        text = plain(block['text'])
        for number,raw in pan_numbers(text):
            candidates['card_number'].append((number,block,raw))
        if role == 'ambiguous_front':continue
        lines=text.splitlines()
        for i,raw in enumerate(lines):
            line = unicodedata.normalize('NFKC',raw).strip().strip('|').strip()
            if BACK.search(line):continue
            name = re.fullmatch(r'(?:持卡人姓名|姓名|户名)\s*[:：]?\s*([\u4e00-\u9fff·]{2,8})(?:\s+1[3-9][0-9]{9})?',line)
            if not name:name=PHONE_NAME.fullmatch(re.sub(r'[,，、;；]',' ',line))
            if name and bare_name(name[1]):candidates['holder_name'].append((name[1],block,raw))
            elif bare_name(line) and (role=='supplement' or
                    (i+1<len(lines) and chinese_id(re.sub(r'\s','',lines[i+1])))):
                candidates['holder_name'].append((line,block,raw))
            clean=BRANCH_LABEL.sub('',re.sub(r'^发卡行\s*[:：]?\s*','',line))
            bank=BANK.match(clean)
            if bank:candidates['bank_name'].append((bank[1],block,raw))
            branch=clean if BRANCH.fullmatch(clean) else None
            branch_raw=raw
            if branch and i and not BRANCH.fullmatch(BRANCH_LABEL.sub('',lines[i-1].strip())):
                previous=BRANCH_LABEL.sub('',lines[i-1].strip())
                if BANK.match(previous) and not BANK.fullmatch(previous) and re.fullmatch(r'[\u4e00-\u9fff（）()·]+',previous):
                    branch=previous+branch;branch_raw=lines[i-1]+'\n'+raw
            if branch:candidates['branch_name'].append((branch,block,branch_raw))
            # Latin cardholder names are source text, never a transliteration guess.
            if role in {'front','whole'} and re.fullmatch(r"[A-Z][A-Z'-]+(?: [A-Z][A-Z'-]+){1,3}",line) and not re.search(
                    r'BANK|CARD|DEBIT|CREDIT|VALID|THRU|MONTH|YEAR|CHINA|UNION|SIGN|COMMUNICATION|CONSTRUCTION',line):
                candidates['holder_name'].append((line,block,raw))
    return candidates


def build_bank_fields(evidence, fields):
    from .extraction import _field, source, issue
    from .validation import validate_field
    from .document_fields import _candidates
    from .doc_profiles import profile
    candidates = bank_candidates(evidence)
    labelled=_candidates([b for b in evidence if b.get('_bank_role') not in {'back','ambiguous_front'}],profile('BANK_CARD'))
    for index, old in enumerate(fields):
        key = old['key']
        if key not in candidates:continue
        choices = candidates[key]
        # Preserve labelled table extraction only when the value has the right
        # meaning. A label such as 开户行 does not turn a branch into an issuer.
        for value,origin,raw in labelled[key]:
            valid=(key=='holder_name' and not BACK.search(value) and
                   (bare_name(value) or re.fullmatch(r"[A-Za-z][A-Za-z .'-]{1,79}",value))) or (
                   key=='bank_name' and (BANK.fullmatch(value) or (re.match(r'发卡行\s*[:：]',raw)
                                       and not BRANCH.fullmatch(value)))) or (key=='branch_name' and BRANCH.fullmatch(value))
            if valid and value not in {c[0] for c in choices}:choices.append((value,origin,raw))
        if key=='bank_name':
            spellings={};canonical=[]
            for value,origin,raw in choices:
                identity=value.translate(str.maketrans({'國':'国','銀':'银'}))
                canonical.append((spellings.setdefault(identity,value),origin,raw))
            choices=canonical
        field = _field(key,old['label'],choices,key=='card_number')
        sources = [source(block,raw) for _,block,raw in choices]
        if sources:field['sources'] = sources
        if field.get('candidates'):
            for candidate in field['candidates']:
                hits = [(block,raw) for value,block,raw in choices if value == candidate['value']]
                candidate['source'] = source(*hits[0])
                candidate['reason'] = ' / '.join(dict.fromkeys('补充文字识别' if b.get('_bank_role')=='supplement' else '卡面识别' for b,_ in hits))
        field['validation_checks'] = validate_field('BANK_CARD',key,field['value'])
        if key == 'card_number' and field['value'] is not None:
            field['review_issues'].append(issue('UNKNOWN','离线匹配不验证账户或Luhn适用性，请对照原件确认卡号。',True))
        if any(c['status']=='FAIL' for c in field['validation_checks']):
            field['review_issues'].append(issue('VALIDATION_FAILED','本地格式校验失败，请核对原件。'))
        if choices and key in {'holder_name','branch_name'} and not field['review_issues']:
            field['review_issues'].append(issue('CONFIDENCE_UNAVAILABLE','补充文字及其与卡片的归属需人工核对。',True))
        field['need_review'] = bool(field['review_issues'])
        fields[index] = field
