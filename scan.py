"""Sample-based interlace analysis and explicit temporal correction plans."""
import re

def validate(o):
    mode=o.get('scanMode','off');parity=o.get('fieldOrder','auto')
    if mode not in ('off','auto','bwdif_frame','bwdif_field','yadif_frame','yadif_field','ivtc','fieldmatch') or parity not in ('auto','tff','bff'): raise ValueError('Invalid scan correction setting')
    if type(o.get('detectInterlace',False)) is not bool: raise ValueError('Invalid interlace detection setting')
    if mode!='off' and o.get('video','libx264')=='copy': raise ValueError('Deinterlacing/telecine correction requires video re-encoding')
    if (mode in ('ivtc','fieldmatch') or mode.endswith('_field')) and o.get('fps','original')!='original': raise ValueError('Keep original frame rate when using bob deinterlacing or telecine correction')

def parse(logs):
    counts=dict(tff=0,bff=0,progressive=0,undetermined=0,repeatTop=0,repeatBottom=0)
    for log in logs:
        matches=re.findall(r'Multi frame detection:\s*TFF:\s*(\d+)\s*BFF:\s*(\d+)\s*Progressive:\s*(\d+)\s*Undetermined:\s*(\d+)',log)
        if matches:
            for key,value in zip(('tff','bff','progressive','undetermined'),map(int,matches[-1])):counts[key]+=value
        matches=re.findall(r'Repeated Fields:\s*Neither:\s*(\d+)\s*Top:\s*(\d+)\s*Bottom:\s*(\d+)',log)
        if matches:counts['repeatTop']+=int(matches[-1][1]);counts['repeatBottom']+=int(matches[-1][2])
    classified=counts['tff']+counts['bff']+counts['progressive'];interlaced=counts['tff']+counts['bff']
    fraction=interlaced/max(1,classified)
    kind='unknown' if classified<10 else 'interlaced' if fraction>=.1 else 'progressive'
    parity='tff' if counts['tff']>counts['bff']*1.5 else 'bff' if counts['bff']>counts['tff']*1.5 else 'auto'
    possible=classified>=10 and (counts['repeatTop']+counts['repeatBottom'])/classified>=.05
    return dict(kind=kind,fieldOrder=parity,possibleTelecine=possible,counts=counts,note='Sampled '+kind+(' · possible repeated-field/telecine cadence; inspect before choosing IVTC' if possible else '')+'. Sampling cannot certify cadence across the whole file.')

def detect(path,duration,run,samples=3):
    offsets=sorted(set(round(max(0,duration*f),3) for f in (.1,.5,.8))) if samples>1 and duration>15 else [0]
    logs=[]
    for offset in offsets:
        logs.append(run(['ffmpeg','-hide_banner','-nostdin','-ss',str(offset),'-i',str(path),'-frames:v','300','-map','0:v:0','-an','-sn','-vf','idet','-f','null','-']))
    return parse(logs)

def filters(o,report=None,video=None):
    mode=o.get('scanMode','off');parity=o.get('fieldOrder','auto')
    if mode=='auto':
        if not report or report['kind']!='interlaced':return []
        mode='bwdif_frame'
        if parity=='auto':parity=report['fieldOrder']
    if mode=='off':return []
    if mode in ('ivtc','fieldmatch'):
        if mode=='ivtc' and video:
            try:
                a,b=video.get('avg_frame_rate','0/1').split('/');fps=float(a)/float(b)
            except (ValueError,ZeroDivisionError):fps=0
            if not 29<=fps<=31:raise ValueError('3:2 inverse telecine requires a roughly 29.97/30 fps source. Use field matching only for 2:2 material.')
        graph=[f'fieldmatch=order={parity}:combmatch=full',f'bwdif=mode=send_frame:parity={parity}:deint=interlaced']
        if mode=='ivtc':graph.append('decimate=cycle=5')
        return graph
    engine,rate=mode.split('_')
    return [f'{engine}=mode=send_{rate}:parity={parity}:deint=all']
