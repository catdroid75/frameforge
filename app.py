#!/usr/bin/env python3
"""FrameForge — Python standard library + system FFmpeg. Local use only."""
import argparse, json, os, re, secrets, shutil, signal, subprocess, threading, uuid, webbrowser, shlex
from functools import lru_cache
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
import time
import storage
import auth
import scan
import naming
import hdr as hdr_tools
import subtitles as subtitle_tools
from tempfile import TemporaryDirectory
from audio import compile_audio
from urllib.parse import urlparse, parse_qs

ROOT = Path(__file__).resolve().parent
VERSION = (ROOT / "VERSION").read_text(encoding="utf-8").strip()
TOKEN = secrets.token_urlsafe(32)
LOCK = threading.RLock()
JOBS = []
MIN_FREE_BYTES = 4_000_000_000
PERFORMANCE = {'cpuJobs':1,'gpuJobs':1}
MAX_WORKERS = 16
CONTROL = {'paused':False,'reason':'','kind':'','run':None,'counts':{'done':0,'failed':0,'cancelled':0},'notificationError':''}
EXTS = {'.mp4','.mkv','.mov','.avi','.webm','.m4v','.mpg','.mpeg','.mts','.m2ts','.wmv','.flv','.ts','.ogv'}
NVENC = {'h264_nvenc','hevc_nvenc','av1_nvenc'}
FORMATS = {'mp4':({'libx264','libx265',*NVENC,'copy'},{'aac','ac3','eac3','libmp3lame','copy','none'}), 'mkv':({'libx264','libx265','libvpx-vp9',*NVENC,'copy'},{'aac','ac3','eac3','libopus','libmp3lame','flac','copy','none'}), 'mov':({'libx264','libx265','h264_nvenc','hevc_nvenc','prores_ks','copy'},{'aac','ac3','eac3','pcm_s16le','copy','none'}), 'webm':({'libvpx-vp9','copy'},{'libopus','copy','none'}), 'avi':({'mpeg4','copy'},{'ac3','libmp3lame','pcm_s16le','copy','none'})}
ENCODERS = set()
TEXT_SUBS = {'subrip','srt','ass','ssa','webvtt','mov_text','text','microdvd','subviewer','subviewer1','sami','realtext','jacosub','mpl2','vplayer','pjs'}

@lru_cache(maxsize=3)
def nvenc_capabilities(codec):
    if codec not in NVENC: return {}
    try:
        result=subprocess.run(['ffmpeg','-hide_banner','-h','encoder='+codec],capture_output=True,text=True,timeout=10)
        text=result.stdout+result.stderr
        if not re.search(r'^Encoder '+re.escape(codec)+r'\b',text,re.M): return {}
        flags={}; current=None
        for line in text.splitlines():
            m=re.match(r'  -([\w-]+)\s+<',line)
            if m: current=m[1]; flags[current]=[]
            elif current:
                enum=re.match(r'     ([\w-]+)\s+-?\d+\s+',line)
                if enum: flags[current].append(enum[1])
        pix=re.search(r'Supported pixel formats: (.+)',text)
        return {'flags':flags,'pixelFormats':pix.group(1).split() if pix else []}
    except (OSError,subprocess.SubprocessError): return {}

def nvenc_arguments(o,v,q,preset):
    caps=nvenc_capabilities(v); flags=caps.get('flags',{})
    def choice(key,default,allowed):
        value=str(o.get(key,default))
        if value not in allowed: raise ValueError('Invalid NVENC setting: '+key)
        return value
    def integer(key,default,lo,hi):
        raw=str(o.get(key,default))
        if not re.fullmatch(r'\d+',raw) or not lo<=int(raw)<=hi: raise ValueError(f'{key} must be between {lo} and {hi}')
        return int(raw)
    def decimal(key,default,lo,hi):
        raw=str(o.get(key,default))
        if not re.fullmatch(r'\d+(?:\.\d{1,3})?',raw) or not lo<=float(raw)<=hi: raise ValueError(f'{key} must be between {lo} and {hi}')
        return float(raw)
    args=[]
    def emit(flag,value):
        if caps and flag not in flags: raise ValueError(f'Installed FFmpeg does not support -{flag} for {v}. Choose Auto/default or update FFmpeg.')
        if flag in ('preset','tune','rc','multipass','profile') and flags.get(flag) and str(value) not in flags[flag]: raise ValueError(f'Installed FFmpeg does not support -{flag} {value} for {v}.')
        args.extend(['-'+flag+(':v' if flag=='profile' else ''),str(value)])
    speed=choice('nvPreset',{'ultrafast':'p1','fast':'p3','medium':'p4','slow':'p7'}[preset],{'auto',*[f'p{i}' for i in range(1,8)]})
    if speed!='auto': emit('preset',speed)
    tune=choice('nvTune','auto',{'auto','hq','ll','ull'})
    if tune!='auto': emit('tune',tune)
    mode=choice('nvRate','cq',{'cq','vbr','cbr','constqp'})
    rate=decimal('nvBitrate',5,0.1,1000); maximum=decimal('nvMaxrate',0,0,1000); buffer=decimal('nvBuffer',0,0,4000)
    def bits(mbps): return str(round(mbps*1_000_000))
    if mode=='constqp':
        if maximum or buffer: raise ValueError('Constant QP does not use maximum bitrate or VBV buffer')
        emit('rc','constqp');emit('qp',q)
    else:
        emit('rc','cbr' if mode=='cbr' else 'vbr')
        if mode=='cq': emit('cq',q);args+=['-b:v','0']
        else: args+=['-b:v',bits(rate)]
        if mode=='cbr':
            if maximum and maximum!=rate: raise ValueError('CBR maximum bitrate must match the target bitrate, or be zero for automatic')
            args+=['-minrate',bits(rate),'-maxrate',bits(rate),'-bufsize',bits(buffer or rate*2)]
        else:
            if mode=='vbr' and maximum and maximum<rate: raise ValueError('Maximum video bitrate cannot be below the VBR target')
            if maximum: args+=['-maxrate',bits(maximum)]
            if buffer or maximum: args+=['-bufsize',bits(buffer or maximum*2)]
    multipass=choice('nvMultipass','auto',{'auto','disabled','qres','fullres'})
    if mode=='constqp' and multipass not in ('auto','disabled'): raise ValueError('NVENC multipass requires VBR, CQ, or CBR rate control')
    if multipass!='auto': emit('multipass',multipass)
    look=choice('nvLookahead','auto',{'auto','0','8','16','32'})
    if look!='auto': emit('rc-lookahead',look)
    bframes=choice('nvBframes','auto',{'auto','0','1','2','3','4'})
    if bframes!='auto': args+=['-bf',bframes]
    gop=choice('nvGop','auto',{'auto','24','48','60','120','240'})
    if gop!='auto': args+=['-g',gop]
    aq=choice('nvAQ','auto',{'auto','off','spatial','temporal'})
    strength=integer('nvAQStrength',8,1,15)
    if aq!='auto':
        for name,enabled in (('spatial',aq=='spatial'),('temporal',aq=='temporal')):
            flag=next((f for f in (name+'-aq',name+'_aq') if f in flags),name+'-aq')
            if enabled or not caps or flag in flags: emit(flag,'1' if enabled else '0')
        if aq=='spatial': emit('aq-strength',strength)
    gpu=choice('nvGPU','auto',{'auto',*[str(i) for i in range(8)]})
    if gpu!='auto': emit('gpu',gpu)
    depth=choice('nvDepth','8',{'8','10'})
    profile=choice('nvProfile','auto',{'auto','baseline','main','high','main10'})
    allowed={'h264_nvenc':{'auto','baseline','main','high'},'hevc_nvenc':{'auto','main','main10'},'av1_nvenc':{'auto','main'}}[v]
    if profile not in allowed: raise ValueError('Selected profile is incompatible with '+v)
    if depth=='10' and v=='h264_nvenc': raise ValueError('10-bit H.264 NVENC is not supported by this app; choose HEVC or AV1')
    if v=='hevc_nvenc' and ((depth=='10' and profile=='main') or (depth=='8' and profile=='main10')): raise ValueError('HEVC profile and bit depth must match (Main = 8-bit, Main10 = 10-bit)')
    if v=='h264_nvenc' and profile=='baseline' and bframes not in ('auto','0'): raise ValueError('H.264 Baseline does not support B-frames')
    if v=='h264_nvenc' and profile=='baseline': args+=['-bf','0']
    pixel='p010le' if depth=='10' else 'yuv420p'
    if caps and pixel not in caps.get('pixelFormats',[]): raise ValueError(f'Installed {v} does not support {pixel}')
    args+=['-pix_fmt',pixel]
    if profile=='auto' and v=='hevc_nvenc' and depth=='10': profile='main10'
    if profile!='auto': emit('profile',profile)
    return args

EDITION_PATTERNS = [
    (r"extended\s+director'?s\s+cut", "Extended Director's Cut"),
    (r"director'?s\s+cut", "Director's Cut"),
    (r"(?:\d+(?:st|nd|rd|th)\s+)?anniversary\s+edition", None),
    (r"ultimate\s+collector'?s\s+edition", "Ultimate Collector's Edition"),
    (r"collector'?s\s+edition", "Collector's Edition"),
    (r"special\s+edition", 'Special Edition'),
    (r"extended\s+cut", 'Extended Cut'),
    (r"extended\s+edition", 'Extended Edition'),
    (r"extended\s+version", 'Extended Version'),
    (r"ultimate\s+edition", 'Ultimate Edition'),
    (r"limited\s+edition", 'Limited Edition'),
    (r"imax(?:\s+(?:enhanced|edition))?", 'IMAX'),
    (r"fan\s+edit", 'Fan Edit'),
    (r"(?:original\s+)?theatrical\s+(?:cut|edition|version)", 'Theatrical Cut'),
    (r"final\s+cut", 'Final Cut'),
    (r"assembly\s+cut", 'Assembly Cut'),
    (r"rogue\s+cut", 'Rogue Cut'),
    (r"international\s+(?:cut|edition|version)", 'International Cut'),
    (r"unrated(?:\s+(?:cut|edition|version))?", 'Unrated'),
    (r"uncut(?:\s+(?:cut|edition|version))?", 'Uncut'),
    (r"remastered\s+edition", 'Remastered Edition'),
    (r"despecialized\s+edition", 'Despecialized Edition'),
    (r"criterion\s+(?:edition|collection)", 'Criterion Collection'),
    (r"redux", 'Redux'),
]
EDITION_RE = re.compile(r"(?<![A-Za-z0-9])(?:"+'|'.join('('+x[0]+')' for x in EDITION_PATTERNS)+r")(?![A-Za-z0-9])",re.I)

def edition_text(stem):
    text=stem.replace('.',' ').replace('_',' ').replace('’',"'");labels=[]
    for tag in re.findall(r'\{\s*Edition\s*-\s*([^{}]+)\}',text,re.I):
        tag=re.sub(r'\s+',' ',tag).strip()
        if tag and tag.casefold() not in [x.casefold() for x in labels]: labels.append(tag)
    for match in EDITION_RE.finditer(text):
        label=EDITION_PATTERNS[match.lastindex-1][1] or match.group(0).title()
        label=re.sub(r'(\d+)(St|Nd|Rd|Th)\b',lambda m:m[1]+m[2].lower(),label)
        if label.casefold() not in [x.casefold() for x in labels]: labels.append(label)
    return ', '.join(labels)

def strip_edition(text):
    text=re.sub(r'\{\s*Edition\s*-.*?\}','',text,flags=re.I)
    matches=list(EDITION_RE.finditer(text.replace('_',' ')))
    for match in reversed(matches): text=text[:match.start()]+text[match.end():]
    return re.sub(r'[\(\[\{]\s*[\)\]\}]','',text)

def output_stem(path,clean=False,converted=True,naming_options=None):
    stem=Path(path).stem
    if not clean: return stem+('_converted' if converted else '')
    policy=naming_options or {};identity=naming.detect(path,policy)
    if identity['kind']=='tv':return naming.tv_stem(identity,policy)
    edition=edition_text(stem)
    stem=stem.replace('.',' ').replace('’',"'")
    years=list(re.finditer(r'(?<![A-Za-z0-9])(?:18|19|20)\d{2}(?![A-Za-z0-9])',stem))
    if years:
        match=years[-1]; prefix=strip_edition(stem[:match.start()]).rstrip()
        if prefix.endswith(('(','[')): prefix=prefix[:-1].rstrip()
        prefix=re.sub(r'\s+',' ',prefix).strip(' ._-')
        title=(prefix+' ' if prefix else '')+'('+match.group(0)+')'
    else: title=re.sub(r'\s+',' ',strip_edition(stem)).strip(' ._-') or 'Video'
    return title+(' {Edition- '+edition+'}' if edition else '')


def movie_folder_name(path):
    name=re.sub(r'\s*\{Edition- [^{}]*\}', '', output_stem(path,True,naming_options={'contentType':'movie'})).strip()
    name=re.sub(r'[<>:"/\\|?*\x00-\x1f]', '', name).strip(' .') or 'Video'
    if name.split('.')[0].upper() in {'CON','PRN','AUX','NUL',*[f'COM{i}' for i in range(1,10)],*[f'LPT{i}' for i in range(1,10)]}: name+='_' 
    return name

def output_directory(j):
    root=Path(j['folder'])
    folder=root
    if j['options'].get('mirrorDirs',False):
        relative=Path(j.get('relativeDir',''))
        if relative.is_absolute() or '..' in relative.parts: raise ValueError('Invalid relative output directory')
        folder=folder/relative
    identity=naming.detect(j['input'],j['options'])
    if identity['kind']=='tv':
        for part in naming.folders(identity,j['options']):folder=folder/part
    elif j['options'].get('ownFolder',False): folder=folder/movie_folder_name(j['input'])
    if not folder.resolve().is_relative_to(root.resolve()): raise ValueError('Output directory must stay inside the selected destination')
    return folder

def staging_directory(j,create=False):
    root=Path(j['folder']);stage=root/'_FFtmp'
    if stage.resolve().parent!=root.resolve(): raise ValueError('The destination temp folder must stay inside the selected destination')
    if create: stage.mkdir(exist_ok=True)
    return stage

def ensure_job_space(j):
    # All encoded media and subtitle assets stage in destination/_FFtmp.
    free=ensure_space(j['folder'])
    stage=staging_directory(j)
    if stage.is_dir(): free=min(free,ensure_space(stage))
    folder=output_directory(j)
    while not folder.exists(): folder=folder.parent
    if folder.resolve()!=Path(j['folder']).resolve(): free=min(free,ensure_space(folder))
    return free


def reserve_destination(j,fmt,exports=None):
    """Reserve the final name before encoding so its title is always accurate."""
    with LOCK:
        reserved={path for x in JOBS if x.get('_working') for path in [x.get('_destination'),*x.get('_sidecars',[])]}
        folder=output_directory(j)
        ensure_job_space(j)
        base=folder/output_stem(j['input'],j['options'].get('cleanNames',False),j['options'].get('addConverted',True),j['options'])
        for n in range(10000):
            dest=Path(str(base)+(f'_{n}' if n else '')+'.'+fmt)
            sidecars=[dest.with_name(dest.stem+spec['suffix']) for spec in (exports or [])]
            if all(not os.path.lexists(path) and str(path) not in reserved for path in [dest,*sidecars]):
                j['_destination']=str(dest);j['_sidecars']=[str(path) for path in sidecars]
                return dest
    raise ValueError('Too many matching output names')


def thread_count(o):
    value=o.get('cpuThreads',0)
    if isinstance(value,bool) or not str(value).isdigit() or not 0<=int(value)<=256:
        raise ValueError('CPU threads must be an integer from 0 (automatic) to 256')
    return int(value)

def job_limits(o):
    result={}
    for key in ('cpuJobs','gpuJobs'):
        value=o.get(key,1)
        if isinstance(value,bool) or not str(value).isdigit() or not 1<=int(value)<=8:
            raise ValueError(key+' must be an integer from 1 to 8')
        result[key]=int(value)
    return result

def thread_input_args(o):
    n=thread_count(o)
    return ['-threads',str(n),'-filter_threads',str(n),'-filter_complex_threads',str(n)] if n else []

def job_kind(j):
    return 'gpuJobs' if j['options'].get('video') in NVENC else 'cpuJobs'

def claim_job():
    # Claim and capacity accounting share one lock across all worker threads.
    with LOCK:
        if CONTROL['paused']: return None
        active={key:sum(bool(j.get('_working')) and job_kind(j)==key for j in JOBS) for key in PERFORMANCE}
        for j in JOBS:
            if j['status']=='queued' and not j.get('_working') and active[job_kind(j)]<PERFORMANCE[job_kind(j)]:
                j.update(status='running',_working=True,fps=None)
                return j
    return None


def options(o, streams=None, crop=None, hdr_plan=None, burn_assets=None, scan_filters=None):
    thread_count(o);job_limits(o);scan.validate(o);naming.validate(o)
    if type(o.get('addConverted',True)) is not bool:raise ValueError('Invalid converted suffix setting')
    if o.get('exportSrt','none') not in ('none','all','forced','custom'):raise ValueError('Invalid SRT export setting')
    if o.get('exportSrt')=='custom' and o.get('subtitles')!='custom':raise ValueError('Custom SRT selection requires custom subtitle mode')
    hdr_tools.validate(o);o=hdr_tools.effective_options(o)
    fmt=o.get('format','mp4'); v=o.get('video','libx264'); a=o.get('audio','aac')
    if fmt not in FORMATS or v not in FORMATS[fmt][0] : raise ValueError('Incompatible format or codec selection')
    for c in (v,):
        if c not in ('copy','none') and c not in ENCODERS: raise ValueError('Encoder unavailable in this FFmpeg installation: '+c)
    q=int(o.get('quality',23)); preset=o.get('preset','medium'); scale=o.get('scale','original'); fps=o.get('fps','original'); rate=str(o.get('bitrate','192'))
    tracks=o.get('audioTracks','all'); channels=o.get('channels','original'); subtitles=o.get('subtitles','none'); autocrop=o.get('autocrop',False)
    if not isinstance(o.get('mirrorDirs',False),bool): raise ValueError('Invalid mirror directory setting')
    if not isinstance(o.get('ownFolder',False),bool): raise ValueError('Invalid movie folder setting')
    if not isinstance(o.get('cleanNames',False),bool): raise ValueError('Invalid filename cleanup setting')
    if not isinstance(autocrop,bool): raise ValueError('Invalid auto crop setting')
    if tracks not in ('first','all','selected') or channels not in ('original','2','6') or subtitles not in ('none','forced','all','custom','englishForeign'): raise ValueError('Invalid track setting')
    rates=('96','128','192','256','320','384','448','512','640','768','1024')
    if not 0<=q<=51 or preset not in ('ultrafast','fast','medium','slow') or scale not in ('original','2160','1080','720','480') or fps not in ('original','24','25','30','60') or rate not in rates: raise ValueError('Invalid encoding option')
    if v=='copy' and (scale!='original' or fps!='original' or autocrop): raise ValueError('Video stream copy requires original resolution, frame rate, and no cropping')
    args=['-map','0:v:0?']
    audio_maps,audio_args=compile_audio(o,streams,FORMATS[fmt][1],ENCODERS)
    args+=audio_maps
    subtitle_maps,subtitle_args,burn=subtitle_tools.compile_plan(o,streams)
    if burn and o.get('hdrTarget','none')=='none' and any(x.get('color_transfer') in ('smpte2084','arib-std-b67') or any('dv_profile' in z for z in x.get('side_data_list',[])) for x in (streams or []) if x.get('codec_type')=='video'): raise ValueError('Select HDR10 or SDR color conversion before burning subtitles into an HDR source')
    args+=subtitle_maps
    args+=['-c:v',v]
    if v in ('libx264','libx265'): args+=['-crf',str(q),'-preset',preset,'-pix_fmt','yuv420p10le' if o.get('hdrTarget')=='hdr10' else 'yuv420p']
    elif v in NVENC: args+=nvenc_arguments(o,v,q,preset)
    elif v=='libvpx-vp9': args+=['-crf',str(q),'-b:v','0']
    elif v=='prores_ks': args+=['-profile:v','3','-pix_fmt','yuv422p10le']
    elif v=='mpeg4': args+=['-q:v',str(max(1,round(1+q*30/51)))]
    filters=(list(scan_filters) if scan_filters is not None else scan.filters(o))+list((hdr_plan or {}).get('filters',[]))
    if crop: filters.append('crop='+crop)
    if scale!='original': filters.append(f'scale=-2:min({scale}\\,ih)')
    if burn_assets:
        graph,label=subtitle_tools.graph(filters,burn_assets,crop,scale,o.get('hdrTarget','none'));args[0:2]=['-map',label];args+=['-filter_complex',graph]
    elif filters: args+=['-vf',','.join(filters)]
    if fps!='original': args+=['-r',fps]
    args+=audio_args+subtitle_args+(hdr_plan or {}).get('encoderArgs',[])
    if fmt in ('mp4','mov'): args+=['-movflags','+faststart']
    if v in ('libx265','hevc_nvenc') and fmt in ('mp4','mov'): args+=['-tag:v','hvc1']
    n=thread_count(o)
    if n:
        args+=['-threads:v',str(n),'-threads:a',str(n)]
        if v=='libx265':
            # Keep HDR mastering parameters in the same x265 parameter string.
            extra=f'pools={n}:frame-threads=1'
            if '-x265-params' in args:
                index=args.index('-x265-params')+1;args[index]+=':'+extra
            else: args+=['-x265-params',extra]
    return fmt,args

def media_info(path):
    p=subprocess.run(['ffprobe','-v','error','-show_format','-show_streams','-of','json',str(path)],capture_output=True,text=True,timeout=30)
    if p.returncode: raise ValueError('Could not read media: '+p.stderr[-1000:])
    return json.loads(p.stdout)

def probe(path):
    return float(media_info(path).get('format',{}).get('duration',0) or 0)

def detect_crop(j,duration,hdr_plan=None):
    # Sample several scenes, then retain the union of their visible rectangles.
    # This is deliberately conservative for mixed aspect ratios and dark scenes.
    offsets=sorted(set(round(max(0,duration*f),3) for f in (0.1,0.5,0.8))) if duration>15 else [0]
    rectangles=[]
    for offset in offsets:
        with tempfile_log() as log:
            filters=list((hdr_plan or {}).get('filters',[]))+['cropdetect=limit=24:round=2:reset=0']
            cmd=['ffmpeg','-hide_banner','-nostdin',*thread_input_args(j['options']),*(hdr_plan or {}).get('inputArgs',[]),'-ss',str(offset),'-i',j['input'],'-t','10','-map','0:v:0','-an','-sn','-vf',','.join(filters),'-f','null','-']
            with LOCK:
                check_interrupted(j)
                if j['status']=='cancelled': return None
                j['phase']='Detecting crop'; p=subprocess.Popen(cmd,stdout=subprocess.DEVNULL,stderr=log); j['_process']=p
            try: p.wait(timeout=120)
            except subprocess.TimeoutExpired:
                p.kill();p.wait();raise ValueError('Crop detection timed out; disable auto crop or try a shorter source')
            finally:
                with LOCK: j.pop('_process',None)
            with LOCK:
                if j['status']=='cancelled': return None
            log.seek(0); text=log.read().decode('utf-8','replace')
            check_interrupted(j)
            if p.returncode: raise ValueError('Crop detection failed: '+text[-1500:])
            found=re.findall(r'crop=(\d+):(\d+):(\d+):(\d+)',text)
            if found: rectangles.append(tuple(map(int,found[-1])))
    if not rectangles: return None
    left=min(r[2] for r in rectangles)//2*2; top=min(r[3] for r in rectangles)//2*2
    right=max(r[2]+r[0] for r in rectangles); bottom=max(r[3]+r[1] for r in rectangles)
    width=(right-left)//2*2; height=(bottom-top)//2*2
    return f'{width}:{height}:{left}:{top}' if width>0 and height>0 else None

class LowDiskSpace(RuntimeError): pass

def ensure_space(folder):
    try: free=shutil.disk_usage(folder).free
    except OSError as e: raise LowDiskSpace('Cannot check output disk space: '+str(e))
    if free<MIN_FREE_BYTES: raise LowDiskSpace(f'Queue stopped: {free/1e9:.2f} GB free in {folder}; at least 4 GB is required.')
    return free

def safe_notify(event,subject,body,key=None):
    try: storage.notify(event,subject,body,key)
    except Exception as e:
        with LOCK: CONTROL['notificationError']='Email notification could not be queued: '+str(e)

def pause_queue(kind,reason):
    with LOCK:
        CONTROL.update(paused=True,reason=reason,kind=kind)
        if kind=='disk':
            for active in JOBS:
                if active.get('_working'): active['_disk_error']=reason

def check_interrupted(j):
    if j.get('_disk_error'): raise LowDiskSpace(j['_disk_error'])

def terminate(p):
    if not p or p.poll() is not None: return
    try:
        p.terminate()
        try: p.wait(timeout=3)
        except subprocess.TimeoutExpired: p.kill();p.wait(timeout=3)
    except (OSError,subprocess.SubprocessError): pass

def disk_monitor(j,stop):
    while not stop.wait(.5):
        try:
            check_interrupted(j);ensure_job_space(j)
        except LowDiskSpace as e:
            with LOCK:
                j['_disk_error']=str(e);p=j.get('_process')
                pause_queue('disk',str(e))
            terminate(p);return

def finish_queue():
    with LOCK:
        if (CONTROL['paused'] and CONTROL['kind']!='user') or not CONTROL['run'] or any(j['status'] in ('queued','running','blocked') or j.get('_working') for j in JOBS): return
        run=CONTROL['run'];counts=dict(CONTROL['counts']);CONTROL['run']=None
    safe_notify('finished',"FrameForge: queue finished",f"The conversion queue has finished.\nCompleted: {counts['done']}\nFailed attempts: {counts['failed']}\nCancelled: {counts['cancelled']}\n",run+'-finished')

def queue_action(action,ident=None):
    with LOCK:
        if action=='resume':
            if any(j.get('_disk_error') or (j.get('_working') and j['status'] in ('blocked','failed')) for j in JOBS): raise ValueError('The interrupted job is still cleaning up. Try Resume again shortly.')
            for pending in JOBS:
                if pending['status'] in ('queued','blocked'): ensure_job_space(pending)
            for j in JOBS:
                if j['status']=='blocked': j.update(status='queued',progress=0,fps=None,error='')
            CONTROL.update(paused=False,reason='',kind='')
        elif action=='pause': pause_queue('user','Queue paused by you. Active files will finish.')
        elif action=='retry':
            for j in JOBS:
                if j['status']=='failed' and (ident is None or j['id']==ident):
                    if j.get('_working'): raise ValueError('Wait for failure cleanup to finish')
                    if not CONTROL['run']: CONTROL.update(run=uuid.uuid4().hex,counts={'done':0,'failed':0,'cancelled':0})
                    j.update(status='queued',progress=0,fps=None,error='');j.pop('_counted',None)
        else: raise ValueError('Unknown queue action')

def preparation_command(j,cmd,cwd):
    if cmd and cmd[0]=='ffmpeg': cmd=[cmd[0],*thread_input_args(j['options']),*cmd[1:]]
    with tempfile_log() as log:
        with LOCK:
            check_interrupted(j)
            if j['status']=='cancelled': raise ValueError('Preparation cancelled')
            p=subprocess.Popen(cmd,stdout=subprocess.DEVNULL,stderr=log,cwd=cwd);j['_process']=p
        try: p.wait(timeout=300)
        except subprocess.TimeoutExpired: terminate(p);raise ValueError('Subtitle preparation timed out')
        finally:
            with LOCK: j.pop('_process',None)
        check_interrupted(j);log.seek(0)
        text=log.read().decode('utf-8','replace')
        if p.returncode: raise ValueError('Media preparation failed: '+text[-2000:])
        return text

def worker(shutdown=None):
    while not (shutdown and shutdown.is_set()):
        j=claim_job()
        if not j:
            finish_queue();threading.Event().wait(.2);continue
        temp=None;work=None;side_temps=[];stop=threading.Event();monitor=None
        try:
            ensure_job_space(j);monitor=threading.Thread(target=disk_monitor,args=(j,stop),daemon=True);monitor.start()
            info=media_info(j['input']);check_interrupted(j); duration=float(info.get('format',{}).get('duration',0) or 0)
            with LOCK:j['nameInfo']=naming.detect(j['input'],j['options'])
            scan_report=None
            if j['options'].get('scanMode')=='auto' or j['options'].get('detectInterlace'):
                with LOCK:j['phase']='Detecting interlace / cadence'
                scan_report=scan.detect(j['input'],duration,lambda cmd:preparation_command(j,cmd,None))
                with LOCK:j['scanReport']=scan_report
            video=next((s for s in info.get('streams',[]) if s.get('codec_type')=='video'),{})
            temporal=scan.filters(j['options'],scan_report,video)
            if j['options'].get('subtitles')=='englishForeign':
                with LOCK:j['subtitleRuleNote']=subtitle_tools.english_for_foreign(info.get('streams',[]))[1]
            export_specs,export_warning=subtitle_tools.export_plan(j['options'],info.get('streams',[]))
            with LOCK:j['subtitleWarning']=export_warning
            hdr_plan=None
            if j['options'].get('hdrTarget','none')!='none':
                with LOCK: j['phase']='Inspecting HDR'
                hdr_plan=hdr_tools.build(j['options'],hdr_tools.analyze(info,hdr_tools.read_frames(j['input'])))
                with LOCK: j['hdrNote']=hdr_plan['source']['kind']+' → '+hdr_plan['target']+'. '+hdr_plan['note']
            check_interrupted(j)
            crop_plan=dict(hdr_plan or {});crop_plan['filters']=temporal+list(crop_plan.get('filters',[]))
            crop=detect_crop(j,duration,crop_plan) if j['options'].get('autocrop') else None
            check_interrupted(j)
            _,_,burn=subtitle_tools.compile_plan(j['options'],info.get('streams',[]));assets=[]
            if burn:
                with LOCK: j['phase']='Preparing subtitles'
                work=TemporaryDirectory(prefix='.frameforge-subs-',dir=staging_directory(j,True))
                assets=subtitle_tools.prepare(j,info,burn,Path(work.name),lambda cmd,cwd:preparation_command(j,cmd,cwd))
            fmt,args=options(j['options'],info.get('streams',[]),crop,hdr_plan,assets,temporal)
            dest=reserve_destination(j,fmt,export_specs)
            with LOCK: j['crop']=crop or '';j['phase']='Encoding'
            temp=staging_directory(j,True)/('.frameforge-'+j['id']+'.'+fmt)
            input_args=list((hdr_plan or {}).get('inputArgs',[]))
            if any(not b['text'] for b in assets):
                video=next((s for s in info['streams'] if s.get('codec_type')=='video'),{})
                if video.get('width') and video.get('height'): input_args+=['-canvas_size',f"{video['width']}x{video['height']}"]
            cmd=['ffmpeg','-hide_banner','-nostdin','-n',*thread_input_args(j['options']),*input_args,'-i',j['input'],*args,'-metadata','title='+dest.stem,'-progress','pipe:1','-nostats',str(temp)]
            with LOCK: j['command']=subprocess.list2cmdline(cmd) if os.name=='nt' else shlex.join(cmd)
            with tempfile_log() as log:
                with LOCK:
                    check_interrupted(j)
                    if j['status']=='cancelled': continue
                    p=subprocess.Popen(cmd,stdout=subprocess.PIPE,stderr=log,text=True,cwd=work.name if work else None);j['_process']=p
                for line in p.stdout:
                    if line.startswith('fps='):
                        try:
                            fps=float(line.partition('=')[2])
                            if 0<=fps<float('inf'):
                                with LOCK:j['fps']=fps
                        except ValueError:pass
                    if line.startswith('out_time_us=') and duration:
                        try:
                            with LOCK: j['progress']=min(99,float(line.split('=')[1])/1e6/duration*100)
                        except ValueError: pass
                code=p.wait();p.stdout.close();log.seek(0);error=log.read().decode('utf-8','replace')[-4000:]
            with LOCK:
                j.pop('_process',None);check_interrupted(j)
                if j['status']=='cancelled': continue
                if code:
                    hint='NVENC requires a compatible NVIDIA GPU, driver, and NVENC-enabled FFmpeg. ' if j['options'].get('video') in NVENC else ''
                    raise ValueError(hint+(error or 'FFmpeg conversion failed'))
            if hdr_plan:
                with LOCK: j['phase']='Verifying HDR output'
                hdr_tools.verify(media_info(temp),hdr_tools.read_frames(temp),hdr_plan['target'])
            for index,spec in enumerate(export_specs):
                with LOCK:j['phase']='Exporting SRT subtitles'
                side=staging_directory(j,True)/f'.frameforge-{j["id"]}-s{index}.srt';side_temps.append(side)
                preparation_command(j,['ffmpeg','-hide_banner','-nostdin','-n','-i',j['input'],'-map',f'0:s:{spec["source"]}','-c:s','srt',str(side)],None)
            with LOCK:
                check_interrupted(j)
                if j['status']=='cancelled': continue
                ensure_job_space(j)
                dest.parent.mkdir(parents=True,exist_ok=True)
                ensure_job_space(j)
                published=[]
                try:
                    for source,target in zip(side_temps,map(Path,j.get('_sidecars',[]))):
                        os.link(source,target);published.append((source,target))
                    os.link(temp,dest)
                except Exception:
                    for source,target in published:
                        try:
                            if os.path.samefile(source,target):target.unlink()
                        except OSError:pass
                    raise
                j.update(status='done',progress=100,output=str(dest),generatedFiles=list(j.get('_sidecars',[])))

        except Exception as e:
            with LOCK:
                p=j.pop('_process',None)
                if j.get('_disk_error'): e=LowDiskSpace(j['_disk_error'])
                if j['status']!='cancelled':
                    j.update(status='blocked' if isinstance(e,LowDiskSpace) else 'failed',error=str(e))
                    pause_queue('disk' if isinstance(e,LowDiskSpace) else 'failure',str(e))
                    run=CONTROL['run'] or 'queue'
                    safe_notify('failure',"FrameForge: queue stopped",f"File: {Path(j['input']).name}\n\n{str(e)[:2500]}\n\nRemaining files are paused. Correct the problem, then use Resume queue.",run+'-'+j['id']+'-'+uuid.uuid4().hex)
            terminate(p)
        finally:
            stop.set()
            if monitor: monitor.join(timeout=4)
            if temp:
                try: temp.unlink(missing_ok=True)
                except OSError as e:
                    with LOCK: j['cleanupWarning']='Could not remove partial file: '+str(e)
            for side in side_temps:
                try:side.unlink(missing_ok=True)
                except OSError as e:j['cleanupWarning']='Could not remove SRT staging file: '+str(e)
            if work:
                try: work.cleanup()
                except OSError as e:
                    with LOCK: j['cleanupWarning']='Could not remove subtitle temporary files: '+str(e)
            with LOCK:
                if j['status'] in ('done','failed','cancelled') and not j.get('_counted'):
                    CONTROL['counts'][j['status']]+=1;j['_counted']=True
                j.pop('_disk_error',None);j.pop('_working',None);j.pop('_destination',None);j.pop('_sidecars',None)

from tempfile import TemporaryFile as tempfile_log
class Handler(BaseHTTPRequestHandler):
    def log_message(self,*a): pass
    def end_headers(self):
        self.send_header('Cache-Control','no-store')
        self.send_header('X-Frame-Options','DENY')
        self.send_header('Referrer-Policy','no-referrer')
        self.send_header('Content-Security-Policy',"frame-ancestors 'none'; base-uri 'self'; form-action 'self'")
        super().end_headers()
    def auth_reply(self,obj,status=200,cookie=None):
        data=json.dumps(obj).encode();self.send_response(status)
        self.send_header('Content-Type','application/json');self.send_header('Content-Length',str(len(data)))
        if cookie is not None:self.send_header('Set-Cookie',cookie)
        self.end_headers();self.wfile.write(data)
    def redirect_login(self):
        self.send_response(303);self.send_header('Location','/login');self.send_header('Content-Length','0');self.end_headers()

    def reply(self,obj,status=200):
        data=json.dumps(obj).encode(); self.send_response(status); self.send_header('Content-Type','application/json'); self.send_header('Content-Length',str(len(data))); self.send_header('Cache-Control','no-store'); self.end_headers(); self.wfile.write(data)
    def trusted(self):
        origins=getattr(self.server,'allowed_origins',{f'http://127.0.0.1:{self.server.server_port}'})
        hosts={urlparse(o).netloc for o in origins}
        return self.headers.get('Host') in hosts and (not self.headers.get('Origin') or self.headers['Origin'] in origins)
    def do_GET(self):
        if not self.trusted(): return self.reply({'error':'Local access only'},403)
        u=urlparse(self.path)
        if u.path=='/healthz': return self.reply({'ok':True})
        public={'/login','/login.js','/style.css','/logo.png','/logo-dark.png','/favicon.ico','/favicon.png'}
        if u.path not in public and not auth.authenticated(self.headers.get('Cookie')):
            if u.path=='/': return self.redirect_login()
            return self.reply({'error':'Sign in required'},401)
        try:
            if u.path=='/api/state':
                with LOCK: return self.reply({'version':VERSION,'name':'FrameForge','jobs':[{k:v for k,v in j.items() if not k.startswith('_')} for j in JOBS], 'queue':dict(CONTROL),'performance':dict(PERFORMANCE),'cpuCount':os.cpu_count() or 1,'hdrCapabilities':hdr_tools.capabilities(),'subtitleCapabilities':subtitle_tools.capabilities(),'token':TOKEN,'encoders':sorted(ENCODERS),'nvenc':{c:nvenc_capabilities(c) for c in sorted(NVENC & ENCODERS)},'home':os.environ.get('FRAMEFORGE_INPUT',str(Path.home())),'defaultOutput':os.environ.get('FRAMEFORGE_OUTPUT','')})
            if u.path=='/api/presets': return self.reply(storage.presets())
            if u.path=='/api/notifications': return self.reply(storage.public_mail())
            if u.path=='/api/browse':
                p=Path(parse_qs(u.query).get('path',[str(Path.home())])[0]).expanduser().resolve()
                entries=[]
                for x in sorted(p.iterdir(),key=lambda x:(not x.is_dir(),x.name.lower())):
                    try:
                        if x.is_dir() or x.suffix.lower() in EXTS: entries.append({'name':x.name,'path':str(x),'directory':x.is_dir(),'size':x.stat().st_size if x.is_file() else 0})
                    except OSError: pass
                return self.reply({'path':str(p),'parent':str(p.parent),'entries':entries})
            files={'/favicon.ico':'favicon.ico','/favicon.png':'favicon.png','/login':'login.html','/login.js':'login.js','/':'index.html','/app.js':'app.js','/style.css':'style.css','/logo.png':'frameforge-logo.png','/logo-dark.png':'frameforge-logo.png'}
            if u.path not in files: return self.reply({'error':'Not found'},404)
            data=(ROOT/'static'/files[u.path]).read_bytes()
            if u.path=='/login': data=data.replace(b'__LOGIN_TOKEN__',TOKEN.encode()).replace(b'__VERSION__',VERSION.encode())
            self.send_response(200); self.send_header('Content-Type',{'/favicon.ico':'image/vnd.microsoft.icon','/favicon.png':'image/png','/login':'text/html','/login.js':'text/javascript','/':'text/html','/app.js':'text/javascript','/style.css':'text/css','/logo.png':'image/png','/logo-dark.png':'image/png'}[u.path]); self.send_header('Content-Length',str(len(data))); self.send_header('X-Content-Type-Options','nosniff'); self.end_headers(); self.wfile.write(data)
        except Exception as e: self.reply({'error':str(e)},400)
    def do_POST(self):
        if not self.trusted() or self.headers.get('X-Token')!=TOKEN: return self.reply({'error':'Invalid local session'},403)
        if self.path!='/api/login' and not auth.authenticated(self.headers.get('Cookie')): return self.reply({'error':'Sign in required'},401)
        try:
            length=int(self.headers.get('Content-Length',0))
            if not 0<length<2_000_000: raise ValueError('Request too large')
            if self.path=='/api/login' and length>8192: return self.reply({'error':'Invalid login request'},400)
            d=json.loads(self.rfile.read(length))
            if self.path=='/api/login':
                session,limited=auth.login(d.get('token'),self.client_address[0],self.headers.get('Cookie'))
                if not session: return self.auth_reply({'error':'Too many attempts. Try again in one minute.' if limited else 'Invalid login token'},429 if limited else 401)
                return self.auth_reply({'ok':True},cookie=auth.cookie(session))
            if self.path=='/api/logout':
                auth.logout(self.headers.get('Cookie'));return self.auth_reply({'ok':True},cookie=auth.cookie())
            if self.path=='/api/performance':
                limits=job_limits(d)
                with LOCK:
                    storage.set_pref('performance',limits);PERFORMANCE.update(limits)
                return self.reply({'ok':True,'performance':dict(PERFORMANCE)})
            if self.path=='/api/queue':
                queue_action(d.get('action'),d.get('id'));return self.reply({'ok':True})
            if self.path=='/api/naming':
                policy=d.get('options',{});naming.validate(policy)
                path=Path(d['path']).expanduser().resolve()
                if not path.is_file() or path.suffix.lower() not in EXTS:raise ValueError('Choose a sample video')
                identity=naming.detect(path,policy)
                stem=output_stem(path,policy.get('cleanNames',False),policy.get('addConverted',True),policy)
                folder=naming.folders(identity,policy) if identity['kind']=='tv' else [movie_folder_name(path)] if policy.get('ownFolder') else []
                return self.reply({'identity':identity,'filename':stem+'.'+policy.get('format','mkv'),'folders':folder})
            if self.path=='/api/interlace':
                path=Path(d['path']).expanduser().resolve()
                if not path.is_file() or path.suffix.lower() not in EXTS:raise ValueError('Choose a sample video')
                def run_scan(cmd):
                    result=subprocess.run(cmd,capture_output=True,text=True,timeout=60)
                    if result.returncode:raise ValueError('Interlace inspection failed: '+result.stderr[-1500:])
                    return result.stderr
                return self.reply(scan.detect(path,0,run_scan,samples=1))
            if self.path=='/api/inspect':
                p=Path(d['path']).expanduser().resolve()
                if not p.is_file() or p.suffix.lower() not in EXTS: raise ValueError('Select a video file to inspect')
                info=media_info(p);tracks=[dict(position=i,codec=s.get('codec_name','unknown'),channels=s.get('channels',0),layout=s.get('channel_layout',''),language=s.get('tags',{}).get('language','und'),title=s.get('tags',{}).get('title','')) for i,s in enumerate(x for x in info.get('streams',[]) if x.get('codec_type')=='audio')]
                subs=[dict(position=i,codec=s.get('codec_name','unknown'),language=s.get('tags',{}).get('language','und'),title=s.get('tags',{}).get('title',''),forced=bool(s.get('disposition',{}).get('forced')),default=bool(s.get('disposition',{}).get('default')),text=s.get('codec_name') in subtitle_tools.TEXT) for i,s in enumerate(x for x in info.get('streams',[]) if x.get('codec_type')=='subtitle')]
                return self.reply({'path':str(p),'tracks':tracks,'subtitleTracks':subs,'hdr':hdr_tools.analyze(info,hdr_tools.read_frames(p))})
            if self.path=='/api/presets':
                if d.get('action')=='save':
                    settings=d.get('settings',{});options(settings.get('options',{}));storage.save_preset(d.get('name'),settings)
                elif d.get('action')=='delete': storage.delete_preset(d.get('name',''))
                else: raise ValueError('Unknown preset action')
                return self.reply(storage.presets())
            if self.path=='/api/notifications':
                storage.save_mail(d.get('settings',{}),d.get('password'))
                with LOCK: CONTROL['notificationError']=''
                ident=storage.notify('test',"FrameForge: test notification","Your FrameForge email notifications are configured.",force=True) if d.get('test') else None
                return self.reply({'ok':True,'notification':ident})
            if self.path=='/api/source':
                p=Path(d['path']).expanduser().resolve(); directory=d.get('directory',False)
                if directory and not p.is_dir(): raise ValueError('Select an existing input folder')
                if not directory and (not p.is_file() or p.suffix.lower() not in EXTS): raise ValueError('Select an existing supported video file')
                return self.reply({'path':str(p),'directory':directory})
            if self.path=='/api/add':
                options(d['options']); folder=Path(d['folder']).expanduser().resolve()
                if not folder.is_dir(): raise ValueError('Select an existing output folder')
                if d['options'].get('mirrorDirs') and not d.get('recursive'): raise ValueError('Mirroring directories requires Include subfolders')
                inputs={}
                for raw in d['paths']:
                    p=Path(raw).expanduser().resolve()
                    if p.is_dir():
                        candidates=p.rglob('*') if d.get('recursive') else p.iterdir()
                        for x in sorted(candidates):
                            if x.is_file() and x.suffix.lower() in EXTS and not x.resolve().is_relative_to((folder/'_FFtmp').resolve()):
                                inputs.setdefault(x,str(x.parent.relative_to(p)) if d['options'].get('mirrorDirs') else '')
                    elif p.is_file() and p.suffix.lower() in EXTS: inputs.setdefault(p,'')
                    else: raise ValueError('Not a supported video file: '+str(p))
                if not inputs: raise ValueError('No videos found')
                if len(inputs)>5000: raise ValueError('Maximum 5,000 files per batch')
                with LOCK:
                    limits=job_limits(d['options']);storage.set_pref('performance',limits);PERFORMANCE.update(limits)
                    if not CONTROL['run']:
                        CONTROL.update(run=uuid.uuid4().hex,counts={'done':0,'failed':0,'cancelled':0})
                    for p,relative in inputs.items(): JOBS.append({'relativeDir':relative,'id':uuid.uuid4().hex,'input':str(p),'folder':str(folder),'options':json.loads(json.dumps(d['options'])),'status':'queued','progress':0,'error':'','output':''})
                return self.reply({'count':len(inputs)})
            if self.path=='/api/cancel':
                with LOCK:
                    for j in JOBS:
                        if (d.get('id')==j['id'] or d.get('all')) and j['status'] in ('queued','running','blocked'):
                            j['status']='cancelled'
                            if not j.get('_working') and not j.get('_counted'): CONTROL['counts']['cancelled']+=1;j['_counted']=True
                            if j.get('_process'): j['_process'].terminate()
                return self.reply({'ok':True})
            if self.path=='/api/clear':
                with LOCK: JOBS[:]=[j for j in JOBS if j['status'] in ('queued','running','blocked') or j.get('_working')]
                return self.reply({'ok':True})
            self.reply({'error':'Not found'},404)
        except Exception as e: self.reply({'error':str(e)},400)

def main():
    parser=argparse.ArgumentParser(description='FrameForge local video converter'); parser.add_argument('--version',action='version',version='FrameForge '+VERSION); parser.add_argument('--port',type=int,default=8765); parser.add_argument('--no-browser',action='store_true'); parser.add_argument('--host',default='127.0.0.1',choices=('127.0.0.1','0.0.0.0')); a=parser.parse_args()
    if not all(shutil.which(x) for x in ('ffmpeg','ffprobe')): parser.exit(1,'Install FFmpeg (including ffprobe) and add its bin folder to PATH first.\n')
    result=subprocess.run(['ffmpeg','-hide_banner','-encoders'],capture_output=True,text=True,check=True)
    ENCODERS.update(line.split()[1] for line in result.stdout.splitlines() if len(line.split())>1 and len(line.split()[0])==6)
    try:
        try: auth.configure()
        except ValueError:
            import sys,getpass
            if storage.get_pref('loginToken',None) or os.environ.get('FRAMEFORGE_AUTH_TOKEN') or not sys.stdin.isatty(): raise
            print('Configure your FrameForge login token.')
            token=getpass.getpass('Login token (at least 12 characters): ')
            if token!=getpass.getpass('Confirm token: '): raise ValueError('Tokens did not match')
            auth.configure(token)
    except ValueError as e: parser.exit(1,str(e)+'\n')
    storage.recover_notifications()
    server=ThreadingHTTPServer((a.host,a.port),Handler)
    configured=os.environ.get('FRAMEFORGE_ORIGINS',f'http://127.0.0.1:{server.server_port},http://localhost:{server.server_port}')
    server.allowed_origins={x.strip().rstrip('/') for x in configured.split(',') if x.strip()}
    if not server.allowed_origins or any(urlparse(x).scheme not in ('http','https') or not urlparse(x).hostname or urlparse(x).path for x in server.allowed_origins): parser.exit(1,'FRAMEFORGE_ORIGINS must contain comma-separated HTTP(S) origins without paths.\n')
    def stop(signum,frame): raise KeyboardInterrupt
    signal.signal(signal.SIGTERM,stop)
    PERFORMANCE.update(job_limits(storage.get_pref('performance',{})))
    for _ in range(MAX_WORKERS): threading.Thread(target=worker,daemon=True).start()
    url=f'http://127.0.0.1:{server.server_port}'; print("FrameForge "+VERSION+" is running at "+url+' — Ctrl+C to stop.',flush=True)
    if not a.no_browser: webbrowser.open(url)
    try: server.serve_forever()
    except KeyboardInterrupt:
        with LOCK:
            for j in JOBS:
                if j.get('_process'): j['_process'].terminate()
        server.server_close()
if __name__=='__main__': main()
