'use strict';
const $=id=>document.getElementById(id), sources=new Map(),commandOpen=new Set(); let token='', encoders=[],nvCaps={},hdrCaps={},subCaps={},jobs=[],mode='',current='',parent='',selection=new Map(),browseGeneration=0;
const formats={mp4:[['libx264','libx265','h264_nvenc','hevc_nvenc','av1_nvenc','copy'],['aac','ac3','eac3','libmp3lame','copy','none']],mkv:[['libx264','libx265','libvpx-vp9','h264_nvenc','hevc_nvenc','av1_nvenc','copy'],['aac','ac3','eac3','libopus','libmp3lame','flac','copy','none']],mov:[['libx264','libx265','h264_nvenc','hevc_nvenc','prores_ks','copy'],['aac','ac3','eac3','pcm_s16le','copy','none']],webm:[['libvpx-vp9','copy'],['libopus','copy','none']],avi:[['mpeg4','copy'],['ac3','libmp3lame','pcm_s16le','copy','none']]};
const names={libx264:'H.264 / AVC',libx265:'H.265 / HEVC',h264_nvenc:'H.264 · NVIDIA NVENC',hevc_nvenc:'HEVC · NVIDIA NVENC',av1_nvenc:'AV1 · NVIDIA NVENC','libvpx-vp9':'VP9',prores_ks:'Apple ProRes 422 HQ',mpeg4:'MPEG-4 Part 2',copy:'Copy original stream',none:'No audio',aac:'AAC',ac3:'Dolby Digital · AC-3',eac3:'Dolby Digital Plus · E-AC-3',libopus:'Opus',libmp3lame:'MP3',flac:'FLAC',pcm_s16le:'PCM · uncompressed'};
function el(tag,text,cls){const n=document.createElement(tag);if(text!==undefined)n.textContent=text;if(cls)n.className=cls;return n}
async function api(path,data){const r=await fetch(path,data?{method:'POST',headers:{'Content-Type':'application/json','X-Token':token},body:JSON.stringify(data)}:{}); if(r.status===401){location.replace('/login');throw Error('Please sign in again.')} const d=await r.json();if(!r.ok)throw Error(d.error||r.statusText);return d}
const themePreference=$('themeMode'),systemTheme=matchMedia('(prefers-color-scheme: dark)');
themePreference.value=document.documentElement.dataset.themePreference||'system';
function applyTheme(){const preference=themePreference.value;document.documentElement.dataset.theme=preference==='system'?(systemTheme.matches?'dark':'light'):preference;try{localStorage.setItem('frameforge-theme',preference)}catch{}}
themePreference.onchange=applyTheme;
systemTheme.addEventListener('change',()=>{if(themePreference.value==='system')applyTheme()});
const settingsTabs=[...document.querySelectorAll('[role="tab"]')];
function selectSettingsTab(id,focus=false){
 for(const tab of settingsTabs){const active=tab.id===id;tab.setAttribute('aria-selected',String(active));tab.tabIndex=active?0:-1;$(tab.getAttribute('aria-controls')).hidden=!active;if(active&&focus)tab.focus()}
 try{sessionStorage.setItem('frameforge-tab',id)}catch{}
}
for(const [index,tab] of settingsTabs.entries()){
 tab.onclick=()=>selectSettingsTab(tab.id);
 tab.onkeydown=e=>{let next;if(e.key==='ArrowRight')next=(index+1)%settingsTabs.length;else if(e.key==='ArrowLeft')next=(index+settingsTabs.length-1)%settingsTabs.length;else if(e.key==='Home')next=0;else if(e.key==='End')next=settingsTabs.length-1;else return;e.preventDefault();selectSettingsTab(settingsTabs[next].id,true)};
}
try{const saved=sessionStorage.getItem('frameforge-tab');if(settingsTabs.some(tab=>tab.id===saved))selectSettingsTab(saved)}catch{}
function message(s,error=false){$('message').textContent=s;$('message').classList.toggle('error',error)}
function fillCodecs(){for(const [i,id] of ['video','audio'].entries()){const old=$(id).value;$(id).replaceChildren(...formats[$('format').value][i].map(c=>{const o=el('option',id==='audio'&&c==='copy'?'Passthrough · keep original audio':names[c]);o.value=c;o.disabled=!['copy','none'].includes(c)&&!encoders.includes(c);if(o.disabled)o.textContent+=' (unavailable)';return o}));if([...$(id).options].some(o=>o.value===old&&!o.disabled))$(id).value=old;else $(id).value=[...$(id).options].find(o=>!o.disabled)?.value||''}sync();if(typeof renderAudio==='function'){renderAudio();renderSubtitles()}}
const nvFields=['nvPreset','nvTune','nvRate','nvBitrate','nvMaxrate','nvBuffer','nvMultipass','nvLookahead','nvBframes','nvGop','nvAQ','nvAQStrength','nvDepth','nvProfile','nvGPU'];
function syncNV(){
 const v=$('video').value,nv=v.endsWith('_nvenc'),cap=nvCaps[v],flags=cap?.flags||{},rate=$('nvRate').value;
 $('nvencControls').hidden=!nv;
 if(!nv)return;
 const supported=(flag,value)=>!cap?.flags||flag in flags&&(!['preset','tune','rc','multipass','profile'].includes(flag)||!flags[flag].length||flags[flag].includes(value));
 for(const [id,flag] of [['nvPreset','preset'],['nvTune','tune'],['nvMultipass','multipass'],['nvLookahead','rc-lookahead'],['nvGPU','gpu']]){
  for(const o of $(id).options)o.disabled=o.value!=='auto'&&!supported(flag,o.value);
  if($(id).selectedOptions[0]?.disabled)$(id).value='auto';
 }
 for(const o of $('nvAQ').options)o.disabled=['spatial','temporal'].includes(o.value)&&!supported(o.value+'-aq','1')&&!supported(o.value+'_aq','1');
 if($('nvAQ').selectedOptions[0]?.disabled)$('nvAQ').value='auto';
 $('nvDepth').options[1].disabled=v==='h264_nvenc'||Boolean(cap?.pixelFormats?.length&&!cap.pixelFormats.includes('p010le'));
 if($('nvDepth').selectedOptions[0]?.disabled)$('nvDepth').value='8';
 const profiles={h264_nvenc:['auto','baseline','main','high'],hevc_nvenc:['auto','main','main10'],av1_nvenc:['auto','main']}[v];
 for(const o of $('nvProfile').options)o.disabled=!profiles.includes(o.value)||(o.value!=='auto'&&!supported('profile',o.value))||(v==='hevc_nvenc'&&((o.value==='main'&&$('nvDepth').value==='10')||(o.value==='main10'&&$('nvDepth').value==='8')));
 if($('nvProfile').selectedOptions[0]?.disabled)$('nvProfile').value='auto';
 if(v==='h264_nvenc'&&$('nvProfile').value==='baseline')$('nvBframes').value='0';
 $('nvBframes').disabled=v==='h264_nvenc'&&$('nvProfile').value==='baseline';
 for(const o of $('nvRate').options){const rc=o.value==='cq'?'vbr':o.value;o.disabled=!supported('rc',rc)||(o.value==='cq'&&!supported('cq','23'))||(o.value==='constqp'&&!supported('qp','23'));}
 if($('nvRate').selectedOptions[0]?.disabled)$('nvRate').value=[...$('nvRate').options].find(o=>!o.disabled)?.value||'cq';
 const mode=$('nvRate').value;
 $('nvBitrate').disabled=!['vbr','cbr'].includes(mode);
 $('nvMaxrate').disabled=['cbr','constqp'].includes(mode);if($('nvMaxrate').disabled)$('nvMaxrate').value='0';
 $('nvBuffer').disabled=mode==='constqp';if($('nvBuffer').disabled)$('nvBuffer').value='0';
 $('nvMultipass').disabled=mode==='constqp';if(mode==='constqp')$('nvMultipass').value='auto';
 $('nvAQStrength').disabled=$('nvAQ').value!=='spatial'||!supported('aq-strength','8');
 $('nvCapabilityNote').textContent=cap?.flags?'Controls reflect your FFmpeg encoder options. A compatible NVIDIA GPU and driver are still required.':'Could not inspect this encoder; conversion may fail. Install an NVENC-enabled FFmpeg and compatible NVIDIA driver.';
}
function namePreview(){
 $('namePreview').textContent=$('cleanNames').checked?'Example: Movie.Title.2020.Directors.Cut.mkv → Movie Title (2020) {Edition- Director’s Cut}.'+$('format').value+' · Existing names get a numeric suffix.':($('addConverted').checked?'Output files use “_converted” names.':'Original filenames are retained.')+' Existing files are never overwritten.';
}
function sync(){
 $('mirrorDirs').disabled=!$('recursive').checked;if(!$('recursive').checked)$('mirrorDirs').checked=false;
 syncHDR();
 const v=$('video').value,a=$('audio').value,copy=v==='copy',nv=v.endsWith('_nvenc');
 $('scanMode').disabled=copy;if(copy)$('scanMode').value='off';$('fieldOrder').disabled=copy||$('scanMode').value==='off';$('addConverted').disabled=$('cleanNames').checked;
 $('quality').disabled=(!['libx264','libx265','libvpx-vp9','mpeg4'].includes(v)&&!nv)||(nv&&['vbr','cbr'].includes($('nvRate').value));
 $('preset').disabled=!['libx264','libx265'].includes(v);syncNV();namePreview();
 for(const id of ['scale','fps']){$(id).disabled=copy;if(copy)$(id).value='original'}
 if(['ivtc','fieldmatch'].includes($('scanMode').value)||$('scanMode').value.endsWith('_field')){$('fps').value='original';$('fps').disabled=true}
 $('autocrop').disabled=copy;if(copy)$('autocrop').checked=false;
 $('channels').disabled=['copy','none'].includes(a);if($('channels').disabled)$('channels').value='original';
 $('audioTracks').disabled=a==='none';
 for(const option of $('subtitles').options)option.disabled=$('format').value==='avi'&&['forced','all','englishForeign'].includes(option.value);if($('subtitles').selectedOptions[0]?.disabled)$('subtitles').value='none';$('subtitleEditor').hidden=$('subtitles').value!=='custom';
 $('bitrate').disabled=!['aac','ac3','eac3','libopus','libmp3lame'].includes(a);
 for(const o of $('bitrate').options)o.disabled=(a==='ac3'&&Number(o.value)>640)||(['libopus','libmp3lame'].includes(a)&&Number(o.value)>320);
 if($('bitrate').selectedOptions[0]?.disabled)$('bitrate').value=a==='ac3'?'640':'320';
 $('qualityValue').textContent=$('quality').disabled?(copy?'Stream copy':nv?'Bitrate controlled':'Fixed ProRes HQ'):(v==='mpeg4'?'Q '+Math.max(1,Math.round(1+Number($('quality').value)*30/51)):(nv?($('nvRate').value==='constqp'?'QP ':'CQ '):'CRF ')+$('quality').value);
 const per=$('audioMode').value==='perTrack';$('audio').disabled=per;for(const id of ['audio','bitrate','channels','audioTracks'])if(per)$(id).disabled=true;$('audioEditor').hidden=!per;$('sharedTrackSelection').hidden=per||$('audioTracks').value!=='selected'||a==='none';
 $('qualityHint').textContent=copy?'Remuxes without encoding. Source codecs must fit the output container.':nv?'NVENC CQ/QP: lower values retain more detail. VBR/CBR uses target bitrate instead of this slider. Requires a supported NVIDIA GPU and driver. CQ 0 is automatic. Encoder listing alone does not confirm GPU availability.':v==='prores_ks'?'ProRes 422 HQ produces large files intended for editing.':'Lower values retain more detail. File size varies with your footage.';
}
function renderSources(){$('sources').replaceChildren();for(const [path,dir]of sources){const row=el('div',undefined,'source-row');const label=el('span',(dir?'▰  ':'▤  ')+path.split(/[\\/]/).pop());label.append(el('small',path));const remove=el('button','×');remove.setAttribute('aria-label','Remove '+path);remove.onclick=()=>{sources.delete(path);renderSources()};row.append(label,remove);$('sources').append(row)}$('sourceCount').textContent=sources.size?`${sources.size} source${sources.size===1?'':'s'} selected`:'No sources selected';$('ready').textContent=sources.size?`${sources.size} source${sources.size===1?'':'s'} ready to queue.`:'Ready when you are.'}
async function browse(path){const gen=++browseGeneration;$('selectBrowser').disabled=true;$('browseError').textContent='';try{const d=await api('/api/browse?path='+encodeURIComponent(path));if(gen!==browseGeneration)return;current=d.path;parent=d.parent;$('browsePath').value=current;$('selectBrowser').disabled=false;$('entries').replaceChildren();for(const f of d.entries){if(!['files','inspect'].includes(mode)&&!f.directory)continue;const row=el('div',undefined,'entry');if(['files','inspect'].includes(mode)&&!f.directory){const check=document.createElement('input');check.type='checkbox';check.checked=selection.has(f.path);check.setAttribute('aria-label',f.name);check.onchange=()=>{if(mode==='inspect'&&check.checked){selection.clear();for(const c of $('entries').querySelectorAll('input'))if(c!==check)c.checked=false;}check.checked?selection.set(f.path,false):selection.delete(f.path);$('selectionCount').textContent=selection.size+' selected'};row.append(check)}const b=el('button',(f.directory?'▰  ':'▤  ')+f.name);b.onclick=()=>{if(f.directory)browse(f.path);else{const c=row.querySelector('input');c.click()}};row.append(b);$('entries').append(row)}if(!$('entries').children.length)$('entries').append(el('p','No matching items in this folder.','hint'))}catch(e){$('browseError').textContent=e.message}}
function openBrowser(m,start){mode=m;selection.clear();$('selectionCount').textContent=['files','inspect'].includes(m)?'0 selected':'Select the folder currently open';$('browseTitle').textContent=m==='inspect'?'Choose one sample video to inspect':m==='files'?'Select video files':m==='output'?'Choose output folder':'Choose input folder';$('selectBrowser').textContent=m==='inspect'?'Inspect audio tracks':m==='files'?'Add selected files':'Use this folder';$('browser').showModal();browse(start||current||$('browsePath').value)}
$('browseFiles').onclick=()=>{const path=$('fileInput').value.trim(),index=Math.max(path.lastIndexOf('/'),path.lastIndexOf('\\'));openBrowser('files',index>=0?path.slice(0,index+1):'')};$('browseFolder').onclick=()=>openBrowser('folder',$('folderInput').value.trim());
async function addPath(directory){const input=$(directory?'folderInput':'fileInput');if(!input.value.trim())return message('Enter a source path or use Browse.',true);try{const d=await api('/api/source',{path:input.value.trim(),directory});sources.set(d.path,d.directory);input.value=d.path;renderSources();message('Source added.')}catch(e){message(e.message,true)}}
$('addFiles').onclick=()=>addPath(false);$('addFolder').onclick=()=>addPath(true);
for(const [id,dir]of [['fileInput',false],['folderInput',true]])$(id).onkeydown=e=>{if(e.key==='Enter')addPath(dir)};
$('chooseOutput').onclick=()=>openBrowser('output',$('output').value.trim());$('closeBrowser').onclick=()=>$('browser').close();$('up').onclick=()=>browse(parent);$('go').onclick=()=>browse($('browsePath').value);$('browsePath').onkeydown=e=>{if(e.key==='Enter')browse(e.target.value)};
$('selectBrowser').onclick=()=>{if(['inspect','inspectSubs'].includes(mode)){const path=[...selection.keys()][0];if(!path)return;$('browser').close();inspectAudio(path);return;}if(mode==='output')$('output').value=current;else if(mode==='folder'){sources.set(current,true);$('folderInput').value=current;}else{for(const [p,v]of selection)sources.set(p,v);$('fileInput').value=selection.size===1?[...selection.keys()][0]:'';}renderSources();$('browser').close()};
$('format').onchange=()=>{$('quick').value='custom';fillCodecs();renderAudio()};for(const id of ['video','audio','quality','preset','scale','fps','bitrate','audioTracks','channels','subtitles','autocrop','cleanNames','ownFolder','addConverted','scanMode','fieldOrder','detectInterlace','contentType','tvPattern','tvFolders','tvKeepTitle','tvKeepYear',...nvFields])$(id).oninput=()=>{$('quick').value='custom';sync()};
$('quick').onchange=()=>{const presets={gpu:['mkv','hevc_nvenc','ac3',23,'original'],balanced:['mp4','libx264','aac',23,'original'],small:['mp4','libx265','aac',28,'original'],web:['webm','libvpx-vp9','libopus',32,'1080'],edit:['mov','prores_ks','pcm_s16le',23,'original'],copy:['mkv','copy','copy',23,'original']};const p=presets[$('quick').value];if(!p)return;$('format').value=p[0];fillCodecs();$('video').value=p[1];$('audio').value=p[2];$('quality').value=p[3];$('scale').value=p[4];$('preset').value='medium';$('fps').value='original';$('bitrate').value=$('quick').value==='gpu'?'448':'192';sync()};
function renderJobs(){$('queueCount').textContent=jobs.length+' files';if(!jobs.length){$('queue').innerHTML='<div class="empty"><span>≋</span><p>Your next batch starts here.</p><small>Add videos above to get things moving.</small></div>';return}$('queue').replaceChildren();for(const j of jobs){const row=el('div',undefined,'job'),name=el('div',j.input.split(/[\\/]/).pop(),'job-name');name.append(el('small',`${j.options.format.toUpperCase()} · ${names[j.options.video]} · ${j.options.audioMode==='perTrack'?'Per-track audio':names[j.options.audio]}`));name.append(el('small',`${j.options.audioMode==='perTrack'?'Custom':j.options.audioTracks==='first'?'First':j.options.audioTracks==='selected'?'Selected':'All'} audio tracks · ${j.options.subtitles==='forced'?'Forced subtitles':j.options.subtitles==='englishForeign'?'English when first source audio is foreign':j.options.subtitles==='all'?'All subtitles':j.options.subtitles==='custom'?'Custom subtitles':'No subtitles'}`));if(j.crop)name.append(el('small','Detected crop: '+j.crop));else if(j.options.autocrop&&j.phase==='Encoding')name.append(el('small','No crop detected; original framing retained.'));if(j.options.cleanNames)name.append(el('small','Output filename cleanup enabled'));if(j.nameInfo)name.append(el('small','Detected: '+j.nameInfo.kind.toUpperCase()+(j.nameInfo.kind==='unknown'?' · review naming':'')));if(j.scanReport)name.append(el('small',j.scanReport.note));if(j.subtitleRuleNote)name.append(el('small',j.subtitleRuleNote));if(j.subtitleWarning)name.append(el('small',j.subtitleWarning));for(const path of j.generatedFiles||[])name.append(el('small','SRT: '+path));if(j.output)name.append(el('small',j.output));if(j.hdrNote)name.append(el('small',j.hdrNote));if(j.cleanupWarning)name.append(el('small',j.cleanupWarning,'error'));if(j.error)name.append(el('small',j.error,'error'));const status=el('div',j.status==='running'?j.phase&&j.phase!=='Encoding'?j.phase+'…':`Converting ${Math.round(j.progress)}% · ${Number.isFinite(j.fps)?j.fps.toFixed(1)+' fps':j.options.video==='copy'?'FPS n/a':'FPS pending'}`:j.status[0].toUpperCase()+j.status.slice(1),'status '+j.status);if(j.status==='running'){const p=document.createElement('progress');p.max=100;p.value=j.progress;p.setAttribute('aria-label','Conversion progress');status.append(p)}row.append(name,status);if(j.command){const details=el('details',undefined,'command');details.open=commandOpen.has(j.id);details.ontoggle=()=>{details.open?commandOpen.add(j.id):commandOpen.delete(j.id)};details.append(el('summary','FFmpeg arguments'),el('pre',j.command));row.append(details);}if(['queued','running','blocked'].includes(j.status)){const b=el('button','Cancel');b.onclick=async()=>{try{await api('/api/cancel',{id:j.id});await refresh()}catch(e){message(e.message,true)}};row.append(b)}else if(j.status==='failed'){const b=el('button','Retry');b.onclick=()=>queueAction('retry',j.id);row.append(b)}$('queue').append(row)}}
async function refresh(){const d=await api('/api/state');$('appVersion').textContent='v'+d.version;document.title='FrameForge v'+d.version+' · Video converter';token=d.token;jobs=d.jobs;if(!encoders.length){$('cpuJobs').value=String(d.performance?.cpuJobs||1);$('gpuJobs').value=String(d.performance?.gpuJobs||1);encoders=d.encoders;nvCaps=d.nvenc||{};hdrCaps=d.hdrCapabilities||{};subCaps=d.subtitleCapabilities||{};$('browsePath').value=d.home;if(!$('output').value)$('output').value=d.defaultOutput||'';fillCodecs()}const q=d.queue||{};$('performanceInfo').textContent=`Server reports ${d.cpuCount||1} logical CPU(s). Active: ${jobs.filter(j=>j.status==='running'&&!j.options.video.endsWith('_nvenc')).length} CPU / ${jobs.filter(j=>j.status==='running'&&j.options.video.endsWith('_nvenc')).length} GPU. Queue limits: ${d.performance?.cpuJobs||1} CPU / ${d.performance?.gpuJobs||1} GPU.`;$('queueStatus').textContent=(q.paused?'QUEUE STOPPED · '+q.reason:'Queue ready · stops on failures or low disk space')+(q.notificationError?'\n'+q.notificationError:'');$('queueStatus').classList.toggle('paused',Boolean(q.paused));$('resumeQueue').disabled=!q.paused;$('retryFailed').disabled=!jobs.some(j=>j.status==='failed');renderJobs();if(++mailPoll%4===0)loadMail().catch(()=>{});}
$('start').onclick=async()=>{if(!sources.size){selectSettingsTab('tab-io');return message('Select at least one video file or input folder.',true)}if(!$('output').value.trim()){selectSettingsTab('tab-io');$('output').focus();return message('Choose an output folder before starting.',true)}const options=gatherSettings().options;$('start').disabled=true;try{const d=await api('/api/add',{paths:[...sources.keys()],folder:$('output').value,recursive:$('recursive').checked,options});sources.clear();renderSources();message(`${d.count} video${d.count===1?'':'s'} added to the conversion queue.`);await refresh()}catch(e){message(e.message,true)}finally{$('start').disabled=false}};
$('cancelAll').onclick=async()=>{try{await api('/api/cancel',{all:true});await refresh()}catch(e){message(e.message,true)}};$('clear').onclick=async()=>{try{await api('/api/clear',{});await refresh()}catch(e){message(e.message,true)}};
let audioPlan=[],audioSelected=[],subtitlePlan=[],sampleSubtitles=[],sampleTracks=[],savedPresets=[],mailPoll=0,lastSamplePath='';
const baseFields=['contentType','tvPattern','tvFolders','exportSrt','scanMode','fieldOrder','cpuThreads','cpuJobs','gpuJobs','format','video','audio','quality','preset','scale','fps','bitrate','audioTracks','channels','subtitles','audioMode','audioFallback','hdrTarget','hdrEngine','hdrTone','hdrSource','hdrPeak',...nvFields];
function gatherSettings(){
 const options=Object.fromEntries(baseFields.map(id=>[id,$(id).value]));
 options.dvBaseLayer=$('dvBaseLayer').checked;options.hdrDefaultMaster=$('hdrDefaultMaster').checked;options.subtitlePlan=JSON.parse(JSON.stringify(subtitlePlan));options.autocrop=$('autocrop').checked;options.cleanNames=$('cleanNames').checked;options.addConverted=$('addConverted').checked;options.tvKeepTitle=$('tvKeepTitle').checked;options.tvKeepYear=$('tvKeepYear').checked;options.detectInterlace=$('detectInterlace').checked;options.ownFolder=$('ownFolder').checked;options.mirrorDirs=$('recursive').checked&&$('mirrorDirs').checked;options.audioPlan=JSON.parse(JSON.stringify(audioPlan));options.audioSelected=[...audioSelected];
 return {options,output:$('output').value,recursive:$('recursive').checked};
}
function selectControl(label,values,value,change){
 const wrap=el('label',label),input=document.createElement('select');
 for(const [v,text,disabled]of values){const opt=el('option',text);opt.value=String(v);opt.disabled=Boolean(disabled);input.append(opt)}
 if(!values.some(x=>String(x[0])===String(value))){const opt=el('option',String(value)+' · incompatible with format');opt.value=String(value);input.append(opt)}
 input.value=String(value);input.onchange=()=>change(input.value);wrap.append(input);return wrap;
}
function renderSharedAudioTracks(){
 $('sharedAudioTracks').replaceChildren();
 const count=Math.min(64,Math.max(sampleTracks.length,...audioSelected.map(i=>i+1),0));
 for(let i=0;i<count;i++){
  const track=sampleTracks.find(t=>t.position===i),wrap=el('label',undefined,'check'),check=document.createElement('input');
  check.type='checkbox';check.checked=audioSelected.includes(i);check.dataset.helpText='Include this source audio position using the shared output codec. Unchecked tracks are omitted. The same positions are used throughout the batch.';check.setAttribute('aria-label','Include audio track '+(i+1));
  check.onchange=()=>{audioSelected=check.checked?[...new Set([...audioSelected,i])].sort((a,b)=>a-b):audioSelected.filter(n=>n!==i);$('quick').value='custom'};
  wrap.append(check,document.createTextNode(`Track ${i+1}`+(track?` · ${track.language} · ${track.codec} · ${track.channels} ch${track.title?' · '+track.title:''}`:' · inspect a sample to verify')));$('sharedAudioTracks').append(wrap);
 }
 if(!count)$('sharedAudioTracks').append(el('p','Inspect a sample above, then select the audio tracks to include.','hint'));
}
function renderAudio(){
 renderSharedAudioTracks();
 const per=$('audioMode').value==='perTrack';$('audioEditor').hidden=!per;
 if(!per)return;
 $('audioRules').replaceChildren();
 audioPlan.forEach((rule,ruleIndex)=>{
  const card=el('div',undefined,'audio-rule'),head=el('div',undefined,'audio-rule-head');
  const limit=Math.min(64,Math.max(sampleTracks.length,8,rule.source+1));
  const choices=Array.from({length:limit},(_,i)=>{const t=sampleTracks.find(x=>x.position===i);return [i,`Track ${i+1}`+(t?` · ${t.language} · ${t.codec} · ${t.channels} ch${t.title?' · '+t.title:''}`:'')]});
  head.append(selectControl('Source audio track',choices,rule.source,value=>{rule.source=Number(value);renderAudio()}));
  const remove=el('button','Remove rule');remove.onclick=()=>{audioPlan.splice(ruleIndex,1);renderAudio()};head.append(remove);card.append(head);
  rule.outputs.forEach((spec,index)=>{
   const out=el('div',undefined,'audio-output'),grid=el('div',undefined,'grid');
   const codecs=formats[$('format').value][1].filter(x=>x!=='none').map(x=>[x,names[x],x!=='copy'&&!encoders.includes(x)]);
   grid.append(selectControl('Output '+(index+1)+' codec',codecs,spec.codec,value=>{spec.codec=value;if(value==='copy')spec.channels='original';if(['ac3','libopus','libmp3lame'].includes(value)&&Number(spec.bitrate)>(value==='ac3'?640:320))spec.bitrate='192';renderAudio()}));
   const rates=['96','128','192','256','320','384','448','512','640','768','1024'];
   const bitrate=selectControl('Bitrate · kbps',rates.map(x=>[x,x,(spec.codec==='ac3'&&Number(x)>640)||(['libmp3lame','libopus'].includes(spec.codec)&&Number(x)>320)]),spec.bitrate||'192',value=>spec.bitrate=value);
   bitrate.querySelector('select').disabled=!['aac','ac3','eac3','libopus','libmp3lame'].includes(spec.codec);grid.append(bitrate);
   const channels=selectControl('Channels',[['original','Preserve source'],['2','Stereo'],['6','5.1 · six channels',spec.codec==='libmp3lame']],spec.channels||'original',value=>spec.channels=value);
   channels.querySelector('select').disabled=spec.codec==='copy';grid.append(channels);
   const title=el('label','Output track title (optional)'),input=document.createElement('input');input.value=spec.title||'';input.maxLength=160;input.oninput=()=>spec.title=input.value;title.append(input);grid.append(title);
   const drop=el('button','Remove this output');drop.onclick=()=>{rule.outputs.splice(index,1);renderAudio()};out.append(grid,drop);card.append(out);
  });
  if(!rule.outputs.length)card.append(el('p','This source track will be omitted.','hint'));
  const add=el('button','＋ Add another output');add.disabled=rule.outputs.length>=8;add.onclick=()=>{rule.outputs.push({codec:'aac',bitrate:'192',channels:'2',title:'AAC stereo'});renderAudio()};card.append(add);$('audioRules').append(card);
 });
 if(!audioPlan.length)$('audioRules').append(el('p','No explicit rules yet. Add a rule, or inspect a sample video. Unlisted tracks follow the choice below.','hint'));
}
async function inspectAudio(path){
 try{const d=await api('/api/inspect',{path});lastSamplePath=d.path;sampleTracks=d.tracks;sampleSubtitles=d.subtitleTracks||[];if(!subtitlePlan.length)subtitlePlan=sampleSubtitles.map(t=>({source:t.position,include:true,burn:false,default:t.default,forced:t.forced,codec:'auto',language:'',title:''}));$('subtitleSample').textContent=d.path+' · '+sampleSubtitles.length+' subtitle track(s)';$('hdrSourceInfo').textContent=describeHDR(d.hdr);renderSubtitles();$('audioSample').textContent=d.path+' · '+d.tracks.length+' audio track(s)';
  if(!audioPlan.length)audioPlan=d.tracks.map(t=>({source:t.position,outputs:[{codec:'copy',bitrate:'192',channels:'original',title:''}]}));
  renderAudio();message('Audio tracks inspected. Choose shared settings for all/selected tracks, or advanced per-track outputs.');
 }catch(e){message(e.message,true)}
}
$('audioMode').onchange=()=>{$('quick').value='custom';sync();renderAudio()};$('audioTracks').onchange=()=>{$('quick').value='custom';sync();renderAudio()};$('audioFallback').onchange=()=>{};
$('inspectSelected').onclick=()=>{const file=[...sources].find(([path,directory])=>!directory)?.[0]||$('fileInput').value.trim();if(!file)return message('Use Browse sample video to inspect a video inside your source folder.',true);inspectAudio(file)};
$('browseAudioSample').onclick=()=>openBrowser('inspect');
$('addAudioRule').onclick=()=>{if(audioPlan.length>=64)return;let position=0;while(audioPlan.some(r=>r.source===position))position++;audioPlan.push({source:position,outputs:[{codec:'copy',bitrate:'192',channels:'original',title:''}]});renderAudio()};
function fillPresets(data){
 savedPresets=data.presets;$('savedPreset').replaceChildren(el('option','Choose a saved preset'));$('savedPreset').options[0].value='';
 for(const preset of savedPresets){const option=el('option',preset.name);option.value=preset.name;$('savedPreset').append(option)}
 $('savedPreset').value=data.lastPreset||'';
}
function applySettings(settings){
 const o={contentType:'auto',tvPattern:'standard',tvFolders:'none',exportSrt:'none',scanMode:'off',fieldOrder:'auto',cpuThreads:0,cpuJobs:1,gpuJobs:1,audioMode:'global',audioFallback:'copy',hdrTarget:'none',hdrEngine:'auto',hdrTone:'hable',hdrSource:'auto',hdrPeak:'auto',...(settings.options||{})};if(o.format)$('format').value=o.format;fillCodecs();
 for(const id of baseFields)if(o[id]!==undefined)$(id).value=String(o[id]);
 $('autocrop').checked=Boolean(o.autocrop);$('cleanNames').checked=Boolean(o.cleanNames);$('addConverted').checked=o.addConverted!==false;$('tvKeepTitle').checked=o.tvKeepTitle!==false;$('tvKeepYear').checked=o.tvKeepYear!==false;$('detectInterlace').checked=Boolean(o.detectInterlace);$('ownFolder').checked=Boolean(o.ownFolder);audioPlan=JSON.parse(JSON.stringify(o.audioPlan||[]));audioSelected=JSON.parse(JSON.stringify(o.audioSelected||[]));subtitlePlan=JSON.parse(JSON.stringify(o.subtitlePlan||[]));$('dvBaseLayer').checked=Boolean(o.dvBaseLayer);$('hdrDefaultMaster').checked=Boolean(o.hdrDefaultMaster);
 $('output').value=settings.output||'';$('recursive').checked=Boolean(settings.recursive);$('mirrorDirs').checked=Boolean(o.mirrorDirs)&&$('recursive').checked;$('quick').value='custom';sync();renderAudio();renderSubtitles();
 if(!$('video').value||($('audioMode').value==='global'&&!$('audio').value))message('A saved codec is unavailable or incompatible. Choose a supported codec before starting.',true);
}
$('savePreset').onclick=async()=>{try{const name=$('presetName').value.trim()||$('savedPreset').value;if(!name)return message('Enter a name for the preset.',true);fillPresets(await api('/api/presets',{action:'save',name,settings:gatherSettings()}));message('Settings saved.')}catch(e){message(e.message,true)}};
$('loadPreset').onclick=()=>{const p=savedPresets.find(p=>p.name===$('savedPreset').value);if(!p)return;applySettings(p.settings);$('presetName').value=p.name;message('Loaded '+p.name+'.')};
$('deletePreset').onclick=async()=>{const name=$('savedPreset').value;if(!name)return;try{fillPresets(await api('/api/presets',{action:'delete',name}));$('presetName').value='';message('Deleted preset '+name+'.')}catch(e){message(e.message,true)}};
async function loadMail(fields=false){
 const d=await api('/api/notifications');
 if(fields){const s=d.settings;$('mailEnabled').checked=s.enabled;$('mailFailure').checked=s.onFailure;$('mailFinished').checked=s.onFinished;for(const [id,key]of [['mailHost','host'],['mailPort','port'],['mailTLS','tls'],['mailUsername','username'],['mailSender','sender'],['mailRecipients','recipients']])$(id).value=s[key];}
 $('mailPasswordState').textContent=(d.settings.hasPassword?'An SMTP password is available to the server. ':'No SMTP password is configured. ')+'Entered passwords last only for this server session. Use FRAMEFORGE_SMTP_PASSWORD for persistent credentials.';
 $('mailHistory').textContent=d.history.length?d.history.map(x=>`${x.created} · ${x.subject} · ${x.status}${x.error?' · '+x.error:''}`).join('\n'):'No email notifications sent yet.';
}
async function saveMail(test=false){
 const settings={enabled:$('mailEnabled').checked,onFailure:$('mailFailure').checked,onFinished:$('mailFinished').checked,host:$('mailHost').value,port:$('mailPort').value,tls:$('mailTLS').value,username:$('mailUsername').value,sender:$('mailSender').value,recipients:$('mailRecipients').value};
 const data={settings,test};if($('mailPassword').value)data.password=$('mailPassword').value;
 try{await api('/api/notifications',data);$('mailPassword').value='';message(test?'Test email queued. Check delivery status below.':'Email settings saved.');await loadMail()}catch(e){message(e.message,true)}
}
$('saveMail').onclick=()=>saveMail(false);$('testMail').onclick=()=>saveMail(true);
async function queueAction(action,id){try{await api('/api/queue',{action,id});await refresh();message(action==='retry'?'Failed files queued for retry. Use Resume queue to continue.':'Queue updated.')}catch(e){message(e.message,true)}}
$('pauseQueue').onclick=()=>queueAction('pause');$('resumeQueue').onclick=()=>queueAction('resume');$('retryFailed').onclick=()=>queueAction('retry');

function describeHDR(s){return s?`${s.kind}${s.profile?' · DV profile '+s.profile:''}${s.compatibility!==null&&s.compatibility!==undefined?' · compatibility '+s.compatibility:''} · ${s.transfer} · ${s.pixelFormat}${s.mastering?' · mastering metadata present':''}`:'No HDR metadata inspected.'}
function syncHDR(){
 const target=$('hdrTarget').value,enabled=target!=='none';
 for(const id of ['hdrEngine','hdrTone','hdrSource','hdrPeak','dvBaseLayer'])$(id).disabled=!enabled;
 $('hdrDefaultMaster').disabled=target!=='hdr10';
 if(target==='hdr10'&&$('video').value==='hevc_nvenc'){$('nvDepth').value='10';$('nvProfile').value='main10'}
 if(target==='sdr'&&$('video').value.endsWith('_nvenc')){$('nvDepth').value='8';if($('nvProfile').value==='main10')$('nvProfile').value='auto'}
 const placebo=$('hdrEngine').querySelector('option[value="libplacebo"]');if(placebo)placebo.disabled=hdrCaps.libplacebo===false;
}
$('hdrTarget').onchange=()=>{
 if($('hdrTarget').value==='hdr10'){
  if(!['mp4','mkv','mov'].includes($('format').value)){$('format').value='mkv';fillCodecs()}
  if(!['libx265','hevc_nvenc'].includes($('video').value))$('video').value=$('video').value.endsWith('_nvenc')&&encoders.includes('hevc_nvenc')?'hevc_nvenc':encoders.includes('libx265')?'libx265':encoders.includes('hevc_nvenc')?'hevc_nvenc':'libx265';
 }
 $('quick').value='custom';sync();
};
for(const id of ['hdrEngine','hdrTone','hdrSource','hdrPeak','dvBaseLayer','hdrDefaultMaster'])$(id).oninput=()=>{$('quick').value='custom';sync()};
function inspectFirst(){const file=[...sources].find(([p,dir])=>!dir)?.[0]||$('fileInput').value.trim();if(!file)return message('Browse a sample video in the track editor to inspect a file inside your source folder.',true);inspectAudio(file)}
$('inspectHDR').onclick=inspectFirst;$('browseHDRSample').onclick=()=>openBrowser('inspect');$('inspectSubtitles').onclick=inspectFirst;$('browseSubtitleSample').onclick=()=>openBrowser('inspect');
function renderSubtitles(){
 $('subtitleEditor').hidden=$('subtitles').value!=='custom';$('subtitleRules').replaceChildren();
 for(const rule of subtitlePlan){
  const source=sampleSubtitles.find(s=>s.position===rule.source),row=el('div',undefined,'subtitle-row');
  row.append(el('strong',`Subtitle ${rule.source+1}`+(source?` · ${source.language} · ${source.codec}${source.title?' · '+source.title:''}`:'')));
  const toggles=el('div',undefined,'subtitle-toggles');
  for(const [key,label]of [['include','Keep as soft track'],['burn','Burn into video'],['export','Export SRT'],['default','Default'],['forced','Forced']]){
   const wrap=el('label',undefined,'check'),check=document.createElement('input');check.type='checkbox';check.checked=Boolean(rule[key]);
   if(key==='export')check.disabled=$('exportSrt').value!=='custom'||Boolean(source&&!source.text);
   if(key==='burn'&&source)check.disabled=source.text?subCaps.textBurn===false:subCaps.bitmapBurn===false;
   check.onchange=()=>{rule[key]=check.checked;if(key==='default'&&check.checked){for(const other of subtitlePlan)if(other!==rule)other.default=false;renderSubtitles()}if(key==='burn'&&check.checked&&$('video').value==='copy'){const candidate=formats[$('format').value][0].find(c=>c!=='copy'&&encoders.includes(c)&&($('hdrTarget').value!=='hdr10'||['libx265','hevc_nvenc'].includes(c)));if(candidate)$('video').value=candidate;message('Burn-in requires video encoding. Review the selected video codec.');sync()}};wrap.append(check,document.createTextNode(label));toggles.append(wrap);
  }
  row.append(toggles);const grid=el('div',undefined,'grid');grid.append(selectControl('Soft subtitle codec',[['auto','Auto / compatible codec'],['copy','Stream copy'],['srt','SRT · MKV'],['ass','ASS · MKV'],['mov_text','Timed text · MP4 / MOV'],['webvtt','WebVTT']],rule.codec||'auto',value=>rule.codec=value));
  for(const [key,label]of [['language','Language override'],['title','Title override']]){const wrap=el('label',label),input=document.createElement('input');input.value=rule[key]||'';input.maxLength=160;input.oninput=()=>rule[key]=input.value;wrap.append(input);grid.append(wrap)}
  if(source&&!source.text)grid.append(selectControl('Bitmap burn placement',[['fit','Fit inside cropped frame'],['aligned','Original positions · clip removed borders']],rule.bitmapPlacement||'fit',value=>rule.bitmapPlacement=value));row.append(grid);$('subtitleRules').append(row);
 }
 if(!subtitlePlan.length)$('subtitleRules').append(el('p','Inspect a sample video to select subtitle tracks.','hint'));
}
$('subtitles').onchange=()=>{if($('subtitles').value!=='custom'&&$('exportSrt').value==='custom')$('exportSrt').value='none';sync();renderSubtitles()};
$('exportSrt').onchange=()=>{if($('exportSrt').value==='custom')$('subtitles').value='custom';sync();renderSubtitles()};
async function inspectScan(){const path=[...sources].find(([p,dir])=>!dir)?.[0]||lastSamplePath||$('fileInput').value.trim();if(!path)return message('Choose an individual file or browse a sample first.',true);$('inspectScan').disabled=true;try{const report=await api('/api/interlace',{path});$('scanInfo').textContent=report.note+' Field order: '+report.fieldOrder+'; counts: '+JSON.stringify(report.counts)}catch(e){message(e.message,true)}finally{$('inspectScan').disabled=false}}
$('inspectScan').onclick=inspectScan;$('browseScanSample').onclick=()=>openBrowser('inspect');
(async()=>{try{await refresh();const presets=await api('/api/presets');fillPresets(presets);const saved=savedPresets.find(p=>p.name===presets.lastPreset);if(saved){applySettings(saved.settings);$('presetName').value=saved.name;}await loadMail(true);message('Connected to local FFmpeg.');}catch(e){message('Cannot connect to local server: '+e.message,true)}setInterval(()=>refresh().catch(()=>message('Connection lost. Check that app.py is still running.',true)),1200)})();


// One help system covers static settings and rebuilt per-track editors.
$('applyPerformance').onclick=async()=>{try{await api('/api/performance',{cpuJobs:$('cpuJobs').value,gpuJobs:$('gpuJobs').value});await refresh();message('Queue limits applied. Active jobs finish when a limit is reduced. CPU thread changes apply to newly queued files.')}catch(e){message(e.message,true)}};
$('recursive').onchange=()=>sync();
$('previewNaming').onclick=async()=>{const path=[...sources].find(([p,dir])=>!dir)?.[0]||lastSamplePath||$('fileInput').value.trim();if(!path)return message('Choose an individual file or browse a sample first.',true);try{const data=await api('/api/naming',{path,options:gatherSettings().options});$('namePreview').textContent=data.identity.kind.toUpperCase()+': '+[...data.folders,data.filename].join(' / ')+' · '+data.identity.note}catch(e){message(e.message,true)}};
$('browseNamingSample').onclick=()=>openBrowser('inspect');
const settingHelp = {
contentType:'Detect movie-like filenames or TV episode markers locally, or force a type for this batch. Unknown names use movie-style cleanup and are marked for review. No online metadata service is contacted. Preview first; use separate batches for different naming conventions.',
tvPattern:'When cleanup is enabled, TV episodes use a standard S01E02 label, a compact series/episode name, or a 1x02 label. Multi-episode files retain their episode numbers. Daily shows use their air date. Episode titles are taken from the filename, not downloaded.',
tvFolders:'For detected TV episodes, choose no extra folder, a series folder, or series plus season folders. Date-based episodes use the air-date year as season. These sit inside mirrored parent directories. The movie-folder checkbox does not create a separate folder for each TV episode.',
tvKeepTitle:'Keep the detected episode title after its episode/date marker. Compact style always omits it. Common release tags such as 1080p, WEB-DL and codecs are removed from the detected tail.',
tvKeepYear:'Retain a detected series year, such as Series Name (2020), in TV filenames and series folders. Numeric series titles such as 1923 are kept as titles.',
addConverted:'Append _converted when filename cleanup is off. Uncheck to preserve the source filename. Cleaned filenames omit this suffix. Existing files, including source videos and subtitle sidecars, are never overwritten; numeric suffixes resolve collisions.',
exportSrt:'Write SRT subtitle files next to the final video, using its basename, language and source track number. All/Forced exports text streams only and reports skipped bitmap streams. Custom enables an Export SRT checkbox per subtitle track. Requires text subtitles; OCR is not included.',
scanMode:'Correct temporal scan structure before HDR, crop, resize and subtitle burn-in. Auto samples idet results and applies BWDIF at the original frame rate if interlaced. Bob doubles frame rate. Inverse telecine uses fieldmatch plus decimate for uniform 3:2 film cadence only; it can discard real motion on mixed/video sources.',
fieldOrder:'Order in which interlaced fields were captured. Auto follows metadata; Auto scan correction uses detected order when clear. Override TFF/BFF only when you know the source order; wrong parity can cause motion judder.',
detectInterlace:'Sample up to 300 frames from three scenes (one for short files) and report progressive/interlaced and repeated-field counts. Auto correction always runs this analysis. Sampling does not prove whole-file cadence or guarantee correct telecine detection.',
mirrorDirs:'Keep paths relative to each selected source folder when scanning subdirectories. The selected source folder name itself is omitted. Different source roots may merge into the same destination tree; existing filenames get numeric suffixes. Individually selected files stay at the destination root. Works together with per-movie folders.',
ownFolder:'Create or reuse a folder named from the cleaned movie title and year, omitting edition labels. Different editions share that movie folder. Filename cleanup is separate; enable both for a cleaned folder and filename. Existing files get a numeric suffix, and title metadata still matches the final filename.',
themeMode:'Choose Light or Dark, or follow your system appearance. This preference is saved in this browser; the logo changes with the theme.',
cpuThreads:'FFmpeg decoder, video/audio encoder and filter thread request per job. 0 lets FFmpeg choose. Start with 0 for one job, or divide available logical CPUs among concurrent jobs. x265 uses a worker pool of this size plus a frame thread. Libraries and drivers may create additional threads; this is not a process-wide CPU cap.',
cpuJobs:'Maximum simultaneous non-NVENC jobs, including stream copy, across the queue. Start at 1; increase to 2 if CPU, RAM and disk have capacity. More jobs can reduce throughput when each already uses the CPU fully. Saved with presets; Apply changes the global queue limit.',
gpuJobs:'Maximum concurrent NVENC encoding sessions across all NVIDIA GPUs. Start at 1, then try 2 with sufficient GPU memory and session capacity. NVENC does not expose a GPU thread count. Decode, audio and filters still use CPU resources. Hardware/driver session limits can cause failures.',
savedPreset:'Choose a locally saved configuration. Load applies it; it does not start a conversion.',presetName:'Name this configuration so you can reuse it for another batch. Source selections and SMTP passwords are not saved.',
fileInput:'Full path to a video on the server computer. Browse selects files; Add includes the entered path in the batch.',folderInput:'Select a folder on the server computer. Add includes supported videos; Include subfolders controls recursion.',output:'Destination on the server computer, or a mounted output folder in Docker. Choose a writable drive with room for the batch; the queue stops below 4 GB free.',recursive:'Search nested folders when adding a folder. Leave off to process only videos directly inside it.',cleanNames:'Replace dots with spaces, format the last year as (2020), remove release details, and preserve recognized cuts as {Edition- Director\'s Cut}. Originals remain unchanged.',
quick:'Choose a starting point for format, video/audio codec, quality and resolution. Other settings, including HDR and track rules, remain yours to review.',format:'Container for video, audio and subtitles. MP4 is a good playback starting point; MKV offers the broadest track and subtitle flexibility.',video:'Compression method. H.264 suits broad playback, HEVC can reduce size, and NVENC uses supported NVIDIA hardware. Copy avoids quality loss but cannot crop, resize or burn subtitles.',quality:'Lower CRF/CQ/QP generally increases quality and size. Start with H.264 CRF 23 or HEVC CRF 28, then test a sample. NVENC CQ 0 is automatic. Scales differ across encoders; bitrate modes ignore this slider.',preset:'CPU encoding effort: medium is a useful starting point. Slower searches harder for compression and takes longer. NVENC uses its separate P1–P7 preset.',scale:'Limit output height while preserving aspect ratio. Keep original avoids unnecessary resizing; 1080p can reduce storage for portable playback.',fps:'Keep original is recommended for normal conversions. Changing frame rate drops or duplicates frames; it does not create genuine smoother motion.',
audio:'Passthrough preserves original audio without re-encoding; AAC is a useful playback choice. AC-3 is Dolby Digital and E-AC-3 is Dolby Digital Plus. Compatibility depends on the container and player.',bitrate:'Bits per second for each encoded audio output. Try AAC stereo at 192 kbps or AC-3 5.1 at 448–640 kbps. Copy and lossless encoders do not use this setting.',audioMode:'Use global settings for a consistent layout, or per-track rules to preserve an original and add another encode such as AAC stereo.',audioTracks:'Choose All, First, or specific audio track positions. Inspect a sample to identify languages and commentary. Shared Passthrough, AAC or Dolby settings apply once to every included track; unchecked tracks are omitted. Missing required positions stop the queue.',channels:'Preserve source channels by default. Stereo is useful for portable devices. Converting stereo to 5.1 cannot recover real surround sound.',audioFallback:'What happens to audio tracks without a rule. Copy preserves them when the container supports the source codec; Drop omits them.',
subtitles:'None omits subtitles; Forced uses stream flags; All keeps streams; Custom selects/exports/burns individual tracks. Conditional English checks language metadata of the first source audio track and includes one existing English subtitle as default if it is foreign. Unknown languages or missing English tracks are reported; nothing is downloaded or translated. Burn-in is permanent and happens after crop and resize.',autocrop:'Sample several scenes to detect black borders. Leave off for mixed aspect ratios or dark footage unless you have checked a sample. Requires video encoding.',
nvPreset:'P1 is fastest; P7 spends more encoding effort on quality. P4 is a balanced starting point; try P6 for offline quality if your GPU supports it.',nvTune:'HQ favors normal offline conversion. Low-latency modes trade compression options for less delay and are mainly useful for live applications.',nvRate:'CQ is a useful starting point for quality-driven files. VBR targets an average bitrate; CBR suits constrained delivery; constant QP fixes quantization. No mode guarantees an exact file size.',nvBitrate:'Average video bitrate for VBR/CBR, in megabits per second. Choose for resolution, motion and delivery limits; there is no universal best value.',nvMaxrate:'Upper bitrate constraint, in Mbps. Zero leaves it uncapped/automatic. Set a cap only for a player or delivery requirement.',nvBuffer:'Rate-control buffer size in megabits, not memory in megabytes. Leave automatic unless you have a delivery buffer requirement.',nvMultipass:'Additional NVENC analysis within encoding. Quarter-resolution analysis is a speed/quality compromise; full resolution uses more resources. This is not two separate passes over the file.',nvLookahead:'Buffer future frames to improve rate decisions. Try 16 or 32 for offline encoding; higher values use more GPU memory and add latency. Leave automatic for compatibility.',nvBframes:'Predicted frames that can improve compression. Leave automatic unless testing a supported GPU/codec combination; some hardware restricts B-frames.',nvGop:'Frames between keyframes. Leave automatic for ordinary files. Short intervals improve seeking but can increase file size.',nvAQ:'Redistribute bits to improve perceived quality spatially or over time. Try Spatial AQ for offline viewing if supported. Only one AQ mode can be selected.',nvAQStrength:'Strength of spatial AQ, from 1 to 15. Start at 8; active only when Spatial AQ is selected.',nvDepth:'8-bit suits broad playback. HDR10 requires 10-bit HEVC; 10-bit HEVC/AV1 can also reduce banding if your GPU and player support it.',nvProfile:'Codec compatibility profile. Auto is the safest starting point. HDR10 HEVC requires Main10; profiles must match codec and bit depth.',nvGPU:'Select which NVIDIA device encodes the video. Leave Auto for a single GPU; numbered indices refer to the server/container device order.',
hdrTarget:'Leave unchanged for sources that need no color conversion. Choose SDR for an SDR display, or HDR10 to remove dynamic HDR while retaining a compatible static HDR output. Inspect the source first.',hdrEngine:'Auto chooses an available path for the source. CPU handles compatible PQ base layers; Dolby Vision profile 5 requires libplacebo, Vulkan and decoded RPU metadata.',hdrTone:'How bright HDR highlights are compressed into SDR. Hable is a useful starting point; compare highlights and midtones with Mobius or Reinhard on a sample.',hdrSource:'Prefer metadata detection. Assume PQ only for a known mistagged BT.2020/PQ source; a wrong override can seriously distort color. Profile 5 requires the Dolby Vision processing path.',hdrPeak:'CPU tone-mapping estimate of source peak brightness. Prefer metadata/automatic; override only when you know the mastering/peak values.',dvBaseLayer:'Explicitly discard Dolby Vision RPU and enhancement-layer information and use a compatible HDR10 base. Needed for supported profile 7/base-layer workflows; does not reconstruct FEL. Do not use for profile 5.',hdrDefaultMaster:'Allow software x265 to write generic BT.2020/D65 mastering metadata when source metadata is missing. These are assumptions, not recovered original mastering values. Leave off unless you accept that fallback.',
mailEnabled:'Enable configured email alerts. Save email settings to apply changes; conversion continues even if email delivery fails.',mailFailure:'Email when a conversion fails or low disk space stops the queue. The queue requires manual Resume.',mailFinished:'Email once the queue drains. A paused queue is not finished; resolve the stop and resume it.',mailHost:'SMTP hostname supplied by your email provider or relay. This is not a webmail URL.',mailPort:'Use the port supplied by your provider, commonly 587 for STARTTLS or 465 for TLS.',mailTLS:'Use STARTTLS or TLS with authenticated email. None is only for a trusted local relay and does not permit password authentication.',mailUsername:'Account name required by your SMTP provider, often the full email address.',mailSender:'From address authorized by your SMTP provider. It may need to match the authenticated account.',mailRecipients:'Comma-separated destination email addresses for queue alerts and test messages.',mailPassword:'SMTP password or provider app password. Kept only in server memory; use FRAMEFORGE_SMTP_PASSWORD for persistence. Never saved in presets.',browsePath:'Folder on the server computer. Enter a full path and press Go; in Docker, only mounted paths are available.'
};
const trackHelp = {
'Export SRT':'Export this text subtitle as a separate SRT next to the video, independently of Keep and Burn. Available with custom SRT export. Bitmap tracks require OCR and cannot be exported as text here.',
'Source audio track':'Select the source audio stream by its audio-track position. The same position is used for every file; a missing required track stops the queue.',
'Bitrate · kbps':settingHelp.bitrate,'Channels':settingHelp.channels,
'Output track title (optional)':'Optional player-visible name, for example Original surround or AAC stereo. Empty preserves the source title.',
'Keep as soft track':'Include a selectable subtitle stream that the player can turn on or off. You may also burn the same track.',
'Burn into video':'Permanently draw this track after HDR conversion, crop and resize. Cannot be switched off in playback; multiple burns may overlap.',
'Default':'Mark this soft track as the preferred subtitle stream. Player preferences may override this flag.',
'Forced':'Set the soft-stream forced flag. This does not filter a mixed track down to forced dialogue events.',
'Soft subtitle codec':'Auto chooses a compatible text format. Copy preserves supported streams; bitmap-to-text conversion/OCR is not available. MKV is recommended for bitmap soft subtitles.',
'Language override':'Optional language metadata, such as eng or spa. This labels the stream; it does not translate subtitles.',
'Title override':'Optional subtitle name displayed by players. Empty preserves the source title.',
'Bitmap burn placement':'Fit keeps the full subtitle canvas inside the final cropped/resized frame. Original positions aligns with the source and may clip text in removed black borders.'
};
let helpSequence=0;
function addSettingHelp(root=document){
 for(const control of root.querySelectorAll('input,select')){
  if(control.dataset.helpReady)continue;
  const label=control.closest('label')||document.querySelector(`label[for="${control.id}"]`);
  const labelText=label?[...label.childNodes].filter(n=>n.nodeType===3).map(n=>n.textContent).join('').trim():'';
  const text=control.dataset.helpText||settingHelp[control.id]||trackHelp[labelText]||(/^Output \d+ codec$/.test(labelText)?settingHelp.audio:null);
  if(!text)continue;
  control.dataset.helpReady='true';
  const host=label||control.parentElement,wrap=el('span',undefined,'setting-help'),button=el('button','?','help-trigger'),tip=el('span',text,'help-tooltip');
  button.type='button';button.setAttribute('aria-label','Help: '+(labelText||control.getAttribute('aria-label')||control.id));
  tip.id='setting-help-'+(++helpSequence);tip.setAttribute('role','tooltip');button.setAttribute('aria-describedby',tip.id);
  control.setAttribute('aria-describedby',((control.getAttribute('aria-describedby')||'')+' '+tip.id).trim());
  const positionTip=()=>{const r=button.getBoundingClientRect(),width=Math.min(290,window.innerWidth*.7);tip.style.left=Math.max(8,Math.min(r.left,window.innerWidth-width-8))+'px';tip.style.top='auto';tip.style.bottom='auto';const height=tip.getBoundingClientRect().height;if(r.top>height+16)tip.style.bottom=(window.innerHeight-r.top+8)+'px';else tip.style.top=(r.bottom+8)+'px'};
  wrap.onmouseenter=positionTip;button.onfocus=positionTip;
  button.onclick=e=>{e.preventDefault();e.stopPropagation();wrap.classList.toggle('help-open');positionTip()};
  button.onkeydown=e=>{if(e.key==='Escape'){wrap.classList.remove('help-open');button.blur()}};
  button.onblur=()=>wrap.classList.remove('help-open');wrap.append(button,tip);host.append(wrap);
 }
}
addSettingHelp();
new MutationObserver(records=>{if(records.some(r=>[...r.addedNodes].some(n=>n.nodeType===1&&!n.classList.contains('setting-help'))))addSettingHelp()}).observe(document.querySelector('main'),{childList:true,subtree:true});

$('logout').onclick=async()=>{try{await api('/api/logout',{});location.replace('/login')}catch(e){message(e.message,true)}};
