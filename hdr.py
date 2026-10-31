"""HDR analysis, bounded frame inspection and explicit color conversion plans."""
import re,subprocess
from fractions import Fraction
from functools import lru_cache

@lru_cache(maxsize=1)
def capabilities():
    p=subprocess.run(['ffmpeg','-hide_banner','-filters'],capture_output=True,text=True,timeout=10)
    filters=set(re.findall(r'^\s*[TSC\.\|]{3}\s+(\w+)\s',p.stdout,re.M))
    helptext={}
    for name in ('sidedata','libplacebo'):
        if name in filters:
            q=subprocess.run(['ffmpeg','-hide_banner','-h','filter='+name],capture_output=True,text=True,timeout=10);helptext[name]=q.stdout+q.stderr
    return {'cpu':{'zscale','tonemap','sidedata','format','setparams'}<=filters,'libplacebo':'libplacebo' in filters,'dolbyVision':'apply_dolbyvision' in helptext.get('libplacebo',''),'filters':sorted(filters),'sideTypes':re.findall(r'^\s+([A-Z][A-Z0-9_]+)\s+\d+\s',helptext.get('sidedata',''),re.M)}

def read_frames(path):
    p=subprocess.run(['ffprobe','-v','error','-select_streams','v:0','-read_intervals','%+#32','-show_frames','-show_entries','frame=color_space,color_primaries,color_transfer,pix_fmt:frame_side_data','-of','json',str(path)],capture_output=True,text=True,timeout=30)
    if p.returncode: raise ValueError('Could not inspect HDR frame metadata: '+p.stderr[-1000:])
    import json
    return json.loads(p.stdout).get('frames',[])

def analyze(info,frames=None):
    video=next((s for s in info.get('streams',[]) if s.get('codec_type')=='video'),{})
    frames=frames or [];side=list(video.get('side_data_list',[]))
    for frame in frames: side.extend(frame.get('side_data_list',[]))
    dovi=next((x for x in side if 'dv_profile' in x),{})
    names=' '.join(x.get('side_data_type','') for x in side).lower()
    dovi_present=bool(dovi) or 'dolby vision' in names or 'dovi' in names
    dynamic='2094-40' in names or 'hdr10+' in names
    transfer=video.get('color_transfer') or next((x.get('color_transfer') for x in frames if x.get('color_transfer')),'unknown')
    primaries=video.get('color_primaries','unknown');matrix=video.get('color_space','unknown')
    kind='Dolby Vision' if dovi_present else 'HDR10+' if dynamic else 'HDR10 / PQ' if transfer=='smpte2084' else 'HLG' if transfer=='arib-std-b67' else 'SDR' if transfer=='bt709' else 'Unknown'
    mastering=next((x for x in side if x.get('side_data_type')=='Mastering display metadata'),None)
    cll=next((x for x in side if x.get('side_data_type')=='Content light level metadata'),None)
    return dict(kind=kind,dovi=dovi_present,profile=dovi.get('dv_profile'),compatibility=dovi.get('dv_bl_signal_compatibility_id'),enhancement=bool(dovi.get('el_present_flag')),baseLayer=bool(dovi.get('bl_present_flag',True)),rpuDecoded='dolby vision metadata' in names or 'dovi metadata' in names,hdr10plus=dynamic,transfer=transfer,primaries=primaries,matrix=matrix,range=video.get('color_range','tv'),pixelFormat=video.get('pix_fmt',''),mastering=mastering,cll=cll)

def validate(o):
    target=o.get('hdrTarget','none');engine=o.get('hdrEngine','auto');tone=o.get('hdrTone','hable');source=o.get('hdrSource','auto');peak=str(o.get('hdrPeak','auto'))
    if target not in ('none','hdr10','sdr') or engine not in ('auto','cpu','libplacebo') or tone not in ('hable','mobius','reinhard') or source not in ('auto','pq','dv5') or peak not in ('auto','1000','4000','10000'): raise ValueError('Invalid HDR conversion setting')
    for key in ('dvBaseLayer','hdrDefaultMaster'):
        if type(o.get(key,False)) is not bool: raise ValueError('Invalid HDR checkbox')
    if target=='none': return
    if o.get('video','libx264')=='copy': raise ValueError('HDR conversion requires video re-encoding')
    if target=='hdr10' and (o.get('video') not in ('libx265','hevc_nvenc') or o.get('format','mp4') not in ('mp4','mkv','mov')): raise ValueError('HDR10 output requires HEVC (software x265 or HEVC NVENC) in MP4, MKV, or MOV')
    cap=capabilities()
    if not cap['cpu']: raise ValueError('HDR conversion requires FFmpeg with zscale, tonemap, sidedata, format and setparams filters')
    if engine=='libplacebo' and not cap['libplacebo']: raise ValueError('This FFmpeg does not include libplacebo; use CPU for compatible HDR10/PQ sources')

def effective_options(o):
    o=dict(o);target=o.get('hdrTarget','none')
    if target=='hdr10' and o.get('video')=='hevc_nvenc': o.update(nvDepth='10',nvProfile='main10')
    if target=='sdr' and o.get('video','').endswith('_nvenc'):
        o['nvDepth']='8'
        if o.get('nvProfile')=='main10': o['nvProfile']='auto'
    return o

def number(value,default=0):
    try: return float(Fraction(str(value)))
    except (ValueError,ZeroDivisionError): return default

def master_string(master):
    if not master: return None
    keys=('green_x','green_y','blue_x','blue_y','red_x','red_y','white_point_x','white_point_y','max_luminance','min_luminance')
    if any(k not in master for k in keys): return None
    values=[round(number(master[k])*(10000 if 'luminance' in k else 50000)) for k in keys]
    return 'G(%d,%d)B(%d,%d)R(%d,%d)WP(%d,%d)L(%d,%d)'%tuple(values)

def build(o,source):
    validate(o);target=o.get('hdrTarget','none')
    plan=dict(filters=[],inputArgs=[],encoderArgs=[],note='',source=source,target=target)
    if target=='none': return plan
    source=dict(source);plan['source']=source;v=o.get('video','libx264');engine=o.get('hdrEngine','auto');cap=capabilities();notes=[]
    if o.get('hdrSource')=='pq': source.update(transfer='smpte2084',primaries='bt2020',matrix='bt2020nc');notes.append('Input explicitly assumed to be BT.2020/PQ.')
    if o.get('hdrSource')=='dv5': source.update(dovi=True,profile=5)
    dovi=source['dovi'];base=bool(o.get('dvBaseLayer'));profile=source.get('profile')
    if dovi:
        if profile not in (5,7,8): raise ValueError('Dolby Vision profile is unknown/unsupported. This app supports single-layer profiles 5/8 and explicit HDR10 base-layer conversion for profile 7.')
        if profile==7 or source.get('enhancement'):
            if not base: raise ValueError('Dolby Vision enhancement-layer reconstruction is not supported. Enable HDR10-compatible base layer only to convert a compatible profile 7/8 base layer; EL/FEL detail will not be used.')
        if base:
            compatible=(profile==7 and source.get('transfer')=='smpte2084' and source.get('primaries')=='bt2020') or (profile==8 and source.get('compatibility')==1)
            if not compatible or not source.get('baseLayer',True): raise ValueError('Base-layer-only conversion requires a first video stream containing an HDR10-compatible profile 7 base layer, or profile 8 compatibility ID 1. Profile 5 cannot use this path.')
            if not {'DOVI_METADATA','DOVI_RPU_BUFFER'}<=set(cap['sideTypes']) and target=='hdr10' and v!='libx265': raise ValueError('Use software x265 or update FFmpeg for base-layer HDR10 output when explicit Dolby Vision side-data removal is unavailable.')
            engine='cpu';source.update(transfer='smpte2084',primaries='bt2020',matrix='bt2020nc');notes.append('HDR10 base layer only: Dolby Vision trims and enhancement-layer detail are discarded.')
        else:
            if engine=='cpu': raise ValueError('Dolby Vision processing requires libplacebo. CPU tone mapping is only allowed for an explicitly selected HDR10-compatible base layer.')
            if not cap['dolbyVision']: raise ValueError('Dolby Vision requires FFmpeg libplacebo with apply_dolbyvision support and a Vulkan runtime.')
            if not source.get('rpuDecoded'): raise ValueError('The decoder did not expose parsed Dolby Vision RPU metadata in the opening frames. Update FFmpeg or use a supported HDR10-compatible base layer explicitly.')
            engine='libplacebo';notes.append('Dolby Vision RPU processing via libplacebo; no enhancement-layer reconstruction.')
    elif source.get('transfer')!='smpte2084':
        raise ValueError('No supported HDR10/PQ source was identified. Inspect the source, or explicitly choose Assume HDR10/PQ for an untagged PQ source. This mode does not invent HDR from SDR.')
    if engine=='auto': engine='cpu'
    if engine=='cpu' and (source.get('primaries')!='bt2020' or source.get('matrix') not in ('bt2020nc','bt2020ncl')): raise ValueError('CPU HDR conversion needs identified BT.2020/PQ colorimetry. Choose libplacebo for other tagged PQ gamuts, or explicitly Assume HDR10/PQ for a known untagged BT.2020 source.')
    if source.get('hdr10plus'): notes.append('HDR10+ dynamic metadata is removed; CPU mapping uses the HDR10/PQ base, not dynamic HDR10+ scene trims.')
    peak=number(o.get('hdrPeak'),0) or number((source.get('cll') or {}).get('max_content'),0) or number((source.get('mastering') or {}).get('max_luminance'),0) or 1000
    peak=max(100,min(10000,peak));tone=o.get('hdrTone','hable')
    pixel='yuv420p10le' if target=='hdr10' else 'yuv422p10le' if v=='prores_ks' else 'yuv420p'
    filters=plan['filters']
    if dovi and base and not {'DOVI_METADATA','DOVI_RPU_BUFFER'}<=set(cap['sideTypes']): filters.append('sidedata=mode=delete')
    if engine=='libplacebo':
        plan['inputArgs']=['-init_hw_device','vulkan=hdr','-filter_hw_device','hdr']
        if o.get('hdrSource')=='pq': filters.append('setparams=color_primaries=bt2020:color_trc=smpte2084:colorspace=bt2020nc:range=limited')
        color='colorspace=bt2020nc:color_primaries=bt2020:color_trc=smpte2084' if target=='hdr10' else 'colorspace=bt709:color_primaries=bt709:color_trc=bt709'
        filters.extend(['format=yuv420p10le','hwupload',f'libplacebo={color}:range=tv:format={pixel}:apply_dolbyvision=1:tonemapping={tone}','hwdownload','format='+pixel])
        if o.get('hdrPeak','auto')!='auto': notes.append('Source peak override is used only by the CPU engine; libplacebo uses frame metadata/peak detection.')
    else:
        rang='full' if source.get('range')=='pc' else 'limited'
        prefix=f'zscale=pin=bt2020:tin=smpte2084:min=bt2020nc:rin={rang}'
        if target=='sdr': filters.extend([prefix+':t=linear:npl=100','format=gbrpf32le','zscale=p=bt709',f'tonemap=tonemap={tone}:desat=2:peak={peak/100:g}','zscale=t=bt709:m=bt709:r=limited','format='+pixel])
        else: filters.extend([prefix+':p=bt2020:t=smpte2084:m=bt2020nc:r=limited','format='+pixel])
    if target=='sdr':
        filters.append('sidedata=mode=delete')
        plan['encoderArgs']=['-color_primaries','bt709','-color_trc','bt709','-colorspace','bt709','-color_range','tv']
    else:
        if 'DYNAMIC_HDR_PLUS' not in cap['sideTypes']: raise ValueError('Update FFmpeg: the sidedata filter must support DYNAMIC_HDR_PLUS removal')
        for name in ('DYNAMIC_HDR_PLUS','DOVI_RPU_BUFFER','DOVI_METADATA'):
            if name in cap['sideTypes']: filters.append('sidedata=mode=delete:type='+name)
        plan['encoderArgs']=['-color_primaries','bt2020','-color_trc','smpte2084','-colorspace','bt2020nc','-color_range','tv']
        master=master_string(source.get('mastering'))
        if not master:
            if not o.get('hdrDefaultMaster'): raise ValueError('Source mastering-display metadata is missing. Enable the explicitly labeled mastering defaults, or choose SDR.')
            if v!='libx265': raise ValueError('Missing mastering metadata requires software x265 to insert the selected HDR10 defaults. Use libx265 or choose SDR.')
            master=f'G(8500,39850)B(6550,2300)R(35400,14600)WP(15635,16450)L({round(peak*10000)},50)'
            notes.append(f'Using explicitly selected BT.2020/D65 mastering defaults, {peak:g} nit peak, 0.005 nit minimum; these are not recovered studio metadata.')
        if v=='libx265':
            cll=source.get('cll') or {};maxcll=int(number(cll.get('max_content')));maxfall=int(number(cll.get('max_average')))
            plan['encoderArgs']+=['-profile:v','main10','-x265-params',f'hdr10=1:repeat-headers=1:master-display={master}:max-cll={maxcll},{maxfall}']
    plan['note']=' '.join(notes) or ('HDR10/PQ → BT.709 SDR; 100 nit SDR reference.' if target=='sdr' else '10-bit BT.2020/PQ HDR10 output; dynamic metadata removed.')
    return plan

def verify(info,frames,target):
    source=analyze(info,frames)
    if source['dovi'] or source['hdr10plus']: raise ValueError('HDR output verification found residual Dolby Vision/HDR10+ metadata; output was not published. Update FFmpeg or use software x265.')
    if target=='hdr10':
        if source['transfer']!='smpte2084' or source['primaries']!='bt2020' or '10' not in source['pixelFormat'] or not source.get('mastering'): raise ValueError('HDR10 output verification failed (requires 10-bit BT.2020/PQ plus mastering-display metadata). Use software x265 if NVENC did not retain static HDR metadata.')
    elif source['transfer']!='bt709' or source['primaries']!='bt709' or source.get('mastering') or source.get('cll'): raise ValueError('SDR output verification failed; BT.709 output must not retain HDR static metadata.')
