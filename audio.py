"""Explicit per-output audio stream mapping, using only the standard library."""
RATES={'96','128','192','256','320','384','448','512','640','768','1024'}
LOSSY={'aac','ac3','eac3','libopus','libmp3lame'}

def validate_spec(spec,allowed,encoders,source=None):
    if not isinstance(spec,dict): raise ValueError('Invalid audio output settings')
    codec=spec.get('codec','copy'); rate=str(spec.get('bitrate','192')); channels=str(spec.get('channels','original'))
    if codec=='none' or codec not in allowed: raise ValueError('Audio codec is incompatible with this output format: '+str(codec))
    if codec!='copy' and codec not in encoders: raise ValueError('Audio encoder unavailable: '+str(codec))
    if rate not in RATES or channels not in ('original','2','6'): raise ValueError('Invalid audio bitrate or channels')
    if codec=='ac3' and int(rate)>640: raise ValueError('Dolby Digital AC-3 supports at most 640 kbps')
    if codec in ('libmp3lame','libopus') and int(rate)>320: raise ValueError('Select 320 kbps or less for MP3/Opus')
    if codec=='copy' and channels!='original': raise ValueError('Audio stream copy requires original channels')
    if codec=='libmp3lame' and channels=='6': raise ValueError('MP3 supports at most stereo audio')
    limit=2 if codec=='libmp3lame' else 6 if codec in ('ac3','eac3') else None
    if source and limit and channels=='original' and source.get('channels',0)>limit: raise ValueError(f'{codec} supports at most {limit} channels here; choose a downmix for this track')
    title=spec.get('title','')
    if not isinstance(title,str) or len(title)>160 or any(ord(c)<32 for c in title): raise ValueError('Audio title must be at most 160 characters without control characters')
    return dict(codec=codec,bitrate=rate,channels=channels,title=title)

def compile_audio(o,streams,allowed,encoders):
    mode=o.get('audioMode','global'); tracks=o.get('audioTracks','all'); codec=o.get('audio','aac')
    if mode not in ('global','perTrack') or tracks not in ('first','all'): raise ValueError('Invalid audio mode')
    sources=[s for s in (streams or []) if s.get('codec_type')=='audio']; mapped=[]
    if mode=='global':
        if codec=='none': return [],['-an']
        spec=validate_spec(dict(codec=codec,bitrate=o.get('bitrate','192'),channels=o.get('channels','original')),allowed,encoders)
        if streams is None:
            # During queue validation there is no media inspection yet.
            return ['-map','0:a?' if tracks=='all' else '0:a:0?'],spec_args(spec,'a')
        for i,s in enumerate(sources if tracks=='all' else sources[:1]): mapped.append((i,validate_spec(spec,allowed,encoders,s),s))
    else:
        plan=o.get('audioPlan',[]); fallback=o.get('audioFallback','copy')
        if not isinstance(plan,list) or len(plan)>64 or fallback not in ('copy','drop'): raise ValueError('Invalid per-track audio plan')
        rules={}; total=0
        for rule in plan:
            if not isinstance(rule,dict): raise ValueError('Invalid audio track rule')
            index=rule.get('source'); outputs=rule.get('outputs')
            if type(index) is not int or not 0<=index<64 or index in rules: raise ValueError('Audio source positions must be unique (1–64)')
            if not isinstance(outputs,list) or len(outputs)>8: raise ValueError('At most eight outputs per source audio track')
            rules[index]=[validate_spec(x,allowed,encoders) for x in outputs];total+=len(outputs)
        if total>128: raise ValueError('At most 128 explicit audio outputs per file')
        if streams is None: return [],[]
        if any(i>=len(sources) for i in rules): raise ValueError('An audio track in your plan is missing from this file. Inspect its tracks and adjust the plan.')
        for i,s in enumerate(sources):
            outputs=rules.get(i,[dict(codec='copy')] if fallback=='copy' else [])
            for spec in outputs: mapped.append((i,validate_spec(spec,allowed,encoders,s),s))
    maps=[];args=[];default_used=False;seen=set()
    for out,(i,spec,source) in enumerate(mapped):
        maps+=['-map',f'0:a:{i}'];args+=spec_args(spec,f'a:{out}')
        # Copy language/title metadata even when a source is mapped several times.
        if 'index' in source: args+=['-map_metadata:s:a:'+str(out),'0:s:'+str(source['index'])]
        if spec['title']: args+=['-metadata:s:a:'+str(out),'title='+spec['title']]
        flags=source.get('disposition',{});disposition=[]
        for flag in ('dub','original','comment','lyrics','karaoke','forced','hearing_impaired','visual_impaired','clean_effects'):
            if flags.get(flag): disposition.append(flag)
        if flags.get('default') and not default_used and i not in seen: disposition.append('default');default_used=True
        args+=['-disposition:a:'+str(out),'+'.join(disposition) or '0'];seen.add(i)
    return maps,args if mapped else ['-an']

def spec_args(spec,index):
    codec=spec['codec'];args=['-c:'+index,codec]
    if codec in LOSSY: args+=['-b:'+index,spec['bitrate']+'k']
    if spec['channels']!='original': args+=['-ac:'+index,spec['channels']]
    if codec in ('ac3','eac3'): args+=['-ar:'+index,'48000']
    return args
