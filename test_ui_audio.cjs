// Optional developer check: node test_ui_audio.cjs (no npm dependencies).
const fs=require('fs'),vm=require('vm'),assert=require('assert');
const source=fs.readFileSync(__dirname+'/static/app.js','utf8');
const start=source.indexOf('function sync(){'),end=source.indexOf('function renderSources()',start);
const defaults={video:'libx264',audio:'ac3',audioMode:'perTrack',audioTracks:'all',channels:'6',bitrate:'448',format:'mkv',scanMode:'off',fps:'original',scale:'original',subtitles:'none'};
const nodes={};
function $(id){if(!nodes[id]){nodes[id]={value:defaults[id]||'',disabled:false,checked:false,hidden:false,textContent:'',options:id==='subtitles'?['none','forced','all','custom','englishForeign'].map(value=>({value,disabled:false})):id==='bitrate'?['96','128','192','448','640','768','1024'].map(value=>({value,disabled:false})):[]};Object.defineProperty(nodes[id],'selectedOptions',{get(){return [this.options.find(o=>o.value===this.value)||{disabled:false}]}})}return nodes[id]}
const context={$,syncHDR(){},syncNV(){},namePreview(){}};vm.createContext(context);vm.runInContext(source.slice(start,end),context);
context.sync();assert.equal($('audio').disabled,true);
$('audioMode').value='global';context.sync();assert.equal($('audio').disabled,false,'Returning to shared mode must unlock its codec selector');
$('audio').value='aac';$('bitrate').value='192';$('channels').value='2';context.sync();assert(!$('audio').disabled);assert(!$('bitrate').disabled);assert(!$('channels').disabled);
$('audio').value='copy';context.sync();assert(!$('audio').disabled);assert($('bitrate').disabled);assert($('channels').disabled);assert.equal($('channels').value,'original');
$('audioTracks').value='selected';context.sync();assert.equal($('sharedTrackSelection').hidden,false);
$('audioMode').value='perTrack';context.sync();assert.equal($('sharedTrackSelection').hidden,true);
$('audioMode').value='global';context.sync();assert.equal($('audio').disabled,false);assert.equal($('sharedTrackSelection').hidden,false);
$('audio').value='none';context.sync();assert.equal($('sharedTrackSelection').hidden,true);
console.log('Shared audio mode switching, Passthrough/AAC controls and selected-track visibility passed.');
