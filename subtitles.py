"""Embedded subtitle selection and post-crop burn-in plans."""
import re,subprocess
from functools import lru_cache
TEXT={'subrip','srt','ass','ssa','webvtt','mov_text','text','microdvd','subviewer','subviewer1','sami','realtext','jacosub','mpl2','vplayer','pjs','eia_608','arib_caption','stl','ttml','hdmv_text_subtitle'}
BITMAP={'hdmv_pgs_subtitle','dvd_subtitle','dvb_subtitle','xsub'}

@lru_cache(maxsize=1)
def capabilities():
    p=subprocess.run(['ffmpeg','-hide_banner','-filters'],capture_output=True,text=True,timeout=10)
    output=p.stdout+'\n'+p.stderr
    if p.returncode: raise ValueError('Could not query FFmpeg filters: '+p.stderr[-1000:])
    return {'textBurn':bool(re.search(r'^\s*[TSC\.\|]{2,3}\s+subtitles\s',output,re.M)),'bitmapBurn':bool(re.search(r'^\s*[TSC\.\|]{2,3}\s+overlay\s',output,re.M)) and bool(re.search(r'^\s*[TSC\.\|]{2,3}\s+scale2ref\s',output,re.M))}

# Recognized language tags only: und/mul/zxx and unsupported tags stay unknown.
LANG2=set('aa ab ae af ak am an ar as av ay az ba be bg bh bi bm bn bo br bs ca ce ch co cr cs cu cv cy da de dv dz ee el en eo es et eu fa ff fi fj fo fr fy ga gd gl gn gu gv ha he hi ho hr ht hu hy hz ia id ie ig ii ik io is it iu ja jv ka kg ki kj kk kl km kn ko kr ks ku kv kw ky la lb lg li ln lo lt lu lv mg mh mi mk ml mn mr ms mt my na nb nd ne ng nl nn no nr nv ny oc oj om or os pa pi pl ps pt qu rm rn ro ru rw sa sc sd se sg si sk sl sm sn so sq sr ss st su sv sw ta te tg th ti tk tl tn to tr ts tt tw ty ug uk ur uz ve vi vo wa wo xh yi yo za zh zu'.split())
LANG3=set('aar abk afr alb sqi amh ara arm hye aze baq eus bel ben bos bul bur mya cat ces cze chi zho cym wel dan deu ger div dut nld ell gre eng epo est fao fas per fin fra fre fry gla gle glg guj hat hau heb hin hrv hun ice isl ido ind ina iku jav jpn kan kas kat geo kaz khm kir kor kur lao lat lav lit ltz lug mal mar may msa mkd mac mlt mon mri mao nep nob nno nor oci ori pan pol por pus roh ron rum rus san sin slk slo slv sme som spa srp sun swa swe tam tel tgk tha tib bod tir tuk tur uig ukr urd uzb vie yid yor zul'.split())

def language_kind(value):
    value=str(value or '').strip().lower().replace('_','-').split('-')[0]
    if value in ('en','eng','english'):return 'english'
    return 'foreign' if value in LANG2 or value in LANG3 else 'unknown'

def english_for_foreign(streams):
    audio=next((s for s in streams if s.get('codec_type')=='audio'),None)
    if audio is None:return [],'No source audio track found; no conditional subtitles added.'
    kind=language_kind(audio.get('tags',{}).get('language'))
    if kind=='english':return [],'First source audio track is English; no conditional subtitles added.'
    if kind=='unknown':return [],'First source audio language is unknown/untagged; no conditional subtitles added. Use explicit subtitle selection if needed.'
    candidates=[(i,s) for i,s in enumerate(s for s in streams if s.get('codec_type')=='subtitle') if language_kind(s.get('tags',{}).get('language'))=='english']
    if not candidates:return [],'First source audio is foreign, but no tagged English subtitle track exists. No subtitles were added; no translation/download was performed.'
    # Prefer a full subtitle track over forced-only dialogue, then source default.
    index,source=min(candidates,key=lambda item:(bool(item[1].get('disposition',{}).get('forced')),not bool(item[1].get('disposition',{}).get('default')),item[0]))
    return [dict(source=index,include=True,default=True)],f'First source audio is foreign; included English subtitle track {index+1} as the default.'

def compile_plan(o,streams=None):
    mode=o.get('subtitles','none');fmt=o.get('format','mp4');plan=o.get('subtitlePlan',[])
    if mode not in ('none','forced','all','custom','englishForeign'): raise ValueError('Invalid subtitle mode')
    if mode=='custom':
        if not isinstance(plan,list) or len(plan)>64: raise ValueError('At most 64 subtitle track rules')
        seen=set();defaults=0
        for rule in plan:
            if not isinstance(rule,dict) or type(rule.get('source')) is not int or not 0<=rule['source']<64 or rule['source'] in seen: raise ValueError('Subtitle positions must be unique (1–64)')
            seen.add(rule['source'])
            for key in ('include','burn','default','forced','export'):
                if type(rule.get(key,False)) is not bool: raise ValueError('Invalid subtitle checkbox')
            if rule.get('codec','auto') not in ('auto','copy','ass','srt','mov_text','webvtt'): raise ValueError('Invalid subtitle codec')
            for key in ('title','language'):
                value=rule.get(key,'')
                if not isinstance(value,str) or len(value)>160 or any(ord(c)<32 for c in value): raise ValueError('Invalid subtitle title/language')
            if rule.get('bitmapPlacement','fit') not in ('fit','aligned'): raise ValueError('Invalid bitmap subtitle placement')
            defaults+=bool(rule.get('include') and rule.get('default'))
            if rule.get('burn') and o.get('video','libx264')=='copy': raise ValueError('Burned subtitles require video re-encoding')
        if defaults>1: raise ValueError('Choose only one default soft subtitle track')
    if fmt=='avi' and (mode in ('all','forced','englishForeign') or mode=='custom' and any(x.get('include') for x in plan)): raise ValueError('AVI cannot contain these soft subtitles. Choose MKV, or use burn-only subtitles.')
    if streams is None: return [],[],[]
    sources=[s for s in streams if s.get('codec_type')=='subtitle'];selected=[]
    if mode=='all': selected=[dict(source=i,include=True) for i in range(len(sources))]
    elif mode=='forced': selected=[dict(source=i,include=True,forced=True) for i,s in enumerate(sources) if s.get('disposition',{}).get('forced')]
    elif mode=='englishForeign': selected,_=english_for_foreign(streams)
    elif mode=='custom': selected=plan
    maps=[];args=[];burn=[];out=0;default_used=False
    for rule in selected:
        if rule['source']>=len(sources): raise ValueError('A selected subtitle track is missing from this file. Inspect its tracks and adjust the plan.')
        source=sources[rule['source']];codec=source.get('codec_name');text=codec in TEXT
        if rule.get('burn'):
            if not text and codec not in BITMAP: raise ValueError('This subtitle decoder cannot be burned: '+str(codec))
            cap=capabilities()
            if not cap['textBurn' if text else 'bitmapBurn']: raise ValueError('Burn-in requires FFmpeg with libass subtitles or bitmap overlay support')
            burn.append(dict(source=rule['source'],text=text,stream=source,bitmapPlacement=rule.get('bitmapPlacement','fit')))
        if not rule.get('include'): continue
        target=rule.get('codec','auto')
        if target=='auto': target='copy' if fmt=='mkv' else 'mov_text' if fmt in ('mp4','mov') else 'webvtt'
        if fmt in ('mp4','mov') and target not in ('mov_text','copy') or fmt=='webm' and target not in ('webvtt','copy'): raise ValueError('Choose a subtitle codec compatible with the output container, or Auto')
        if not text and (target!='copy' or fmt!='mkv'): raise ValueError('Choose MKV stream copy or burn-only output for bitmap subtitles; converting images to text would require OCR')
        if target=='copy' and ((fmt in ('mp4','mov') and codec!='mov_text') or (fmt=='webm' and codec!='webvtt')): raise ValueError('This source subtitle codec cannot be copied to the selected container; choose Auto, MKV, or burn-only')
        maps+=['-map',f"0:s:{rule['source']}"];args+=['-c:s:'+str(out),target]
        if 'index' in source: args+=['-map_metadata:s:s:'+str(out),'0:s:'+str(source['index'])]
        for key in ('title','language'):
            if rule.get(key): args+=['-metadata:s:s:'+str(out),key+'='+rule[key]]
        flags=source.get('disposition',{});default=rule.get('default',bool(flags.get('default')))
        forced=rule.get('forced',bool(flags.get('forced')))
        disposition=[]
        if forced: disposition.append('forced')
        if default and not default_used: disposition.append('default');default_used=True
        args+=['-disposition:s:'+str(out),'+'.join(disposition) or '0'];out+=1
    return maps,args,burn

def prepare(j,info,burn,workdir,run):
    assets=[]
    if any(b['text'] for b in burn):
        fonts=workdir/'fonts';fonts.mkdir()
        attachments=[s for s in info.get('streams',[]) if s.get('codec_type')=='attachment']
        options=[]
        for position,stream in enumerate(attachments):
            name=stream.get('tags',{}).get('filename','').lower()
            if stream.get('codec_name') in ('ttf','otf') or name.endswith(('.ttf','.otf')):
                options+=['-dump_attachment:t:'+str(position),str(fonts/f'font{position}.ttf')]
        if options: run(['ffmpeg','-hide_banner','-nostdin','-y',*options,'-i',j['input'],'-map','0:v:0?','-frames:v','0','-f','null','-'],workdir)
    for index,b in enumerate(burn):
        asset=dict(b)
        if b['text']:
            asset['file']=f'burn{index}.ass'
            run(['ffmpeg','-hide_banner','-nostdin','-y','-i',j['input'],'-map',f"0:s:{b['source']}",'-c:s','ass',asset['file']],workdir)
        assets.append(asset)
    return assets

def graph(filters,burn,crop,scale,hdr_target='none'):
    parts=['[0:v:0]'+(','.join(filters) if filters else 'null')+'[v0]']
    hdr_color='format=gbrap16le,zscale=pin=bt709:tin=bt709:min=gbr:rin=full:p=bt2020:t=smpte2084:m=bt2020nc:r=limited:npl=203,format=yuva420p10le'
    for i,b in enumerate(burn):
        if b['text'] and hdr_target!='hdr10': parts.append(f"[v{i}]subtitles=filename={b['file']}:fontsdir=fonts[v{i+1}]")
        else:
            if b['text']:
                parts.append(f'[v{i}]split=2[base{i}][canvas{i}]')
                parts.append(f"[canvas{i}]format=rgba,colorchannelmixer=rr=0:gg=0:bb=0:aa=0,subtitles=filename={b['file']}:fontsdir=fonts:alpha=1,"+hdr_color+f'[sub{i}]')
                base=f'[base{i}]'
            else:
                if b.get('bitmapPlacement','fit')=='fit':
                    parts.append(f"[0:s:{b['source']}][v{i}]scale2ref=w=iw:h=ih:force_original_aspect_ratio=decrease[canvas{i}][base{i}]")
                    transforms=['format=rgba'];input_label=f'[canvas{i}]';base=f'[base{i}]'
                else:
                    transforms=['format=rgba'];input_label=f"[0:s:{b['source']}]";base=f'[v{i}]'
                    if crop: transforms.append('crop='+crop)
                    if scale!='original': transforms.append(f'scale=-2:min({scale}\\,ih)')
                if hdr_target=='hdr10': transforms.append(hdr_color)
                parts.append(input_label+','.join(transforms)+f'[sub{i}]')
            parts.append(base+f'[sub{i}]overlay=x=(W-w)/2:y=(H-h)/2:eof_action=pass:shortest=0:format=auto[v{i+1}]')
    return ';'.join(parts),'[v'+str(len(burn))+']'


def export_plan(o,streams):
    mode=o.get('exportSrt','none')
    if mode not in ('none','all','forced','custom'):raise ValueError('Invalid SRT export setting')
    if mode=='none':return [],''
    sources=[s for s in streams if s.get('codec_type')=='subtitle']
    rules=o.get('subtitlePlan',[]) if mode=='custom' else [dict(source=i) for i,s in enumerate(sources) if mode=='all' or s.get('disposition',{}).get('forced')]
    result=[];skipped=0
    for rule in rules:
        if mode=='custom' and not rule.get('export',False):continue
        index=rule['source']
        if index>=len(sources):raise ValueError('A subtitle selected for SRT export is missing')
        stream=sources[index]
        if stream.get('codec_name') not in TEXT:
            if mode=='custom':raise ValueError('SRT export requires text subtitles; bitmap subtitles require OCR')
            skipped+=1;continue
        language=re.sub('[^a-z0-9-]','',str(rule.get('language') or stream.get('tags',{}).get('language','und')).lower())[:16] or 'und'
        forced=rule.get('forced',bool(stream.get('disposition',{}).get('forced')))
        result.append(dict(source=index,suffix=f'.{language}.s{index+1}'+('.forced' if forced else '')+'.srt'))
    return result,(f'{skipped} non-text subtitle track(s) skipped for SRT export; OCR is required.' if skipped else '')
