"""End-to-end checks against a real local HTTP server and real FFmpeg."""
import json, subprocess, tempfile, threading, time, unittest, os
from unittest.mock import patch
import storage
from pathlib import Path
from urllib.request import Request, urlopen
from urllib.error import HTTPError
import app
import auth

class Integration(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp=tempfile.TemporaryDirectory(); cls.root=Path(cls.tmp.name)
        cls.original_data=os.environ.get('FRAMEFORGE_DATA');os.environ['FRAMEFORGE_DATA']=str(cls.root/'data')
        cls.input=cls.root/'input'; cls.output=cls.root/'output'
        cls.input.mkdir(); cls.output.mkdir()
        cls.video=cls.input/'test video.mp4'
        subprocess.run(['ffmpeg','-v','error','-f','lavfi','-i','testsrc2=size=160x120:rate=24','-f','lavfi','-i','sine=frequency=440','-t','1','-c:v','libx264','-c:a','aac',str(cls.video)],check=True)
        with patch.dict(os.environ,{'FRAMEFORGE_AUTH_TOKEN':'integration-test-token-001','FRAMEFORGE_COOKIE_SECURE':'false'}): auth.configure()
        session,_=auth.login('integration-test-token-001','integration-test')
        cls.cookie=auth.cookie(session).split(';')[0]
        app.ENCODERS.update({'libx264','libx265','aac','libvpx-vp9','libopus','prores_ks','pcm_s16le','mpeg4','libmp3lame','flac','ac3','eac3',*app.NVENC})
        cls.server=app.ThreadingHTTPServer(('127.0.0.1',0),app.Handler)
        cls.base='http://127.0.0.1:'+str(cls.server.server_port)
        threading.Thread(target=cls.server.serve_forever,daemon=True).start()
        threading.Thread(target=app.worker,daemon=True).start()
    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown();cls.server.server_close();cls.tmp.cleanup()
        if cls.original_data is None: os.environ.pop('FRAMEFORGE_DATA',None)
        else: os.environ['FRAMEFORGE_DATA']=cls.original_data
    def resume(self):
        for _ in range(100):
            try: return self.call('/api/queue',{'action':'resume'})
            except HTTPError as e:
                error=json.load(e).get('error','')
                if 'cleaning up' not in error: raise
                time.sleep(.02)
        self.fail('Queue cleanup did not finish')
    def call(self,path,data=None,token=True,origin=None):
        headers={'X-Token':app.TOKEN if token else 'bad','Cookie':self.cookie}
        if origin: headers['Origin']=origin
        req=Request(self.base+path,data=json.dumps(data).encode() if data is not None else None,headers=headers)
        with urlopen(req) as r: return json.load(r)
    def add(self,**kw):
        opts=dict(format='mp4',video='libx264',audio='aac',quality=23,preset='fast',scale='original',fps='original',bitrate='128');opts.update(kw)
        self.call('/api/add',dict(paths=[str(self.video)],folder=str(self.output),options=opts))
        return self.call('/api/state')['jobs'][-1]['id']
    def wait(self,jid):
        deadline=time.monotonic()+60
        while time.monotonic()<deadline:
            j=next(j for j in self.call('/api/state')['jobs'] if j['id']==jid)
            if j['status'] not in ('queued','running'): return j
            time.sleep(.05)
        self.fail('Timed out waiting for conversion')
    def test_01_assets_and_security(self):
        for path in ('/','/app.js','/style.css','/logo.png','/logo-dark.png'):
            with urlopen(Request(self.base+path,headers={'Cookie':self.cookie})) as r: self.assertEqual(r.status,200)
        state=self.call('/api/state')
        self.assertEqual(state['version'],Path(app.__file__).with_name('VERSION').read_text().strip())
        self.assertEqual(state['name'],'FrameForge')
        for token,origin in ((False,None),(True,'https://example.com')):
            with self.assertRaises(HTTPError) as e: self.call('/api/clear',{},token,origin)
            self.assertEqual(e.exception.code,403)
        with self.assertRaises(HTTPError): self.call('/api/add',dict(paths=[str(self.video)],folder=str(self.output),options=dict(format='webm',video='libx264')))
    def test_02_real_conversions(self):
        for params in ({},{'video':'libx265'},{'format':'webm','video':'libvpx-vp9','audio':'libopus'},{'format':'mov','video':'prores_ks','audio':'pcm_s16le'},{'format':'avi','video':'mpeg4','audio':'libmp3lame'},{'format':'mkv','video':'copy','audio':'copy'},{'scale':'480','fps':'30','audio':'none'}):
            j=self.wait(self.add(**params));self.assertEqual(j['status'],'done',j['error']);self.assertEqual(j['progress'],100)
            p=Path(j['output']);self.assertTrue(p.is_file());self.assertGreater(app.probe(p),0)
    def test_03_collisions_preserve_existing(self):
        j=self.wait(self.add());p=Path(j['output']);original=p.read_bytes()
        k=self.wait(self.add());self.assertNotEqual(k['output'],j['output']);self.assertEqual(p.read_bytes(),original);self.assertTrue(self.video.exists())
    def test_04_failed_job_and_recovery(self):
        bad=self.input/'broken.mp4';bad.write_text('not media')
        self.call('/api/add',dict(paths=[str(bad)],folder=str(self.output),options=dict(format='mp4',video='libx264',audio='aac')))
        jid=self.call('/api/state')['jobs'][-1]['id'];self.assertEqual(self.wait(jid)['status'],'failed')
        self.assertTrue(self.call('/api/state')['queue']['paused']);self.resume()
        self.assertEqual(self.wait(self.add())['status'],'done');bad.unlink()
    def test_05_folder_and_cancel(self):
        self.call('/api/add',dict(paths=[str(self.input)],folder=str(self.output),options=dict(format='mp4',video='libx264',audio='aac')))
        jid=self.call('/api/state')['jobs'][-1]['id']
        self.call('/api/cancel',{'all':True})
        self.assertEqual(self.wait(jid)['status'],'cancelled')
        self.call('/api/clear',{})
        self.assertEqual(self.call('/api/state')['jobs'],[])
        from urllib.parse import quote
        browse=self.call('/api/browse?path='+quote(str(self.input)))
        self.assertTrue(any(e['name']=='test video.mp4' for e in browse['entries']))

    def rich_source(self):
        path=self.input/'multi-track.mkv'
        if path.exists(): return path
        sub=self.root/'captions.srt';sub.write_text('1\n00:00:00,000 --> 00:00:00,800\nForced caption\n',encoding='utf-8')
        subprocess.run(['ffmpeg','-v','error','-i',str(self.video),'-f','lavfi','-i','sine=frequency=880','-i',str(sub),'-i',str(sub),'-t','1','-map','0:v','-map','0:a','-map','1:a','-map','2:s','-map','3:s','-vf','pad=192:160:16:20:black','-c:v','libx264','-c:a','aac','-c:s','srt','-metadata:s:a:0','language=eng','-metadata:s:a:1','language=spa','-disposition:s:0','forced','-disposition:s:1','0',str(path)],check=True)
        return path
    def add_source(self,path,**opts):
        settings=dict(format='mkv',video='libx264',audio='copy');settings.update(opts)
        self.call('/api/add',dict(paths=[str(path)],folder=str(self.output),options=settings))
        return self.call('/api/state')['jobs'][-1]['id']
    def test_06_multi_audio_dolby_and_forced_subtitles(self):
        src=self.rich_source()
        for codec in ('ac3','eac3','copy'):
            j=self.wait(self.add_source(src,audio=codec,bitrate='448',subtitles='forced',audioTracks='all'))
            self.assertEqual(j['status'],'done',j['error'])
            streams=app.media_info(j['output'])['streams'];audio=[s for s in streams if s['codec_type']=='audio'];subs=[s for s in streams if s['codec_type']=='subtitle']
            self.assertEqual(len(audio),2);self.assertEqual([s['tags']['language'] for s in audio],['eng','spa'])
            self.assertTrue(all(s['codec_name']==('aac' if codec=='copy' else codec) for s in audio))
            self.assertEqual(len(subs),1);self.assertEqual(subs[0]['disposition']['forced'],1)
        for codec in ('ac3','eac3'):
            j=self.wait(self.add_source(src,audio=codec,channels='6',bitrate='448'))
            self.assertEqual(j['status'],'done',j['error'])
            self.assertTrue(all(s['channels']==6 and s['sample_rate']=='48000' for s in app.media_info(j['output'])['streams'] if s['codec_type']=='audio'))
        j=self.wait(self.add_source(src,format='mp4',audio='ac3',audioTracks='first',subtitles='forced',bitrate='448'))
        self.assertEqual(j['status'],'done',j['error']);streams=app.media_info(j['output'])['streams']
        self.assertEqual(len([s for s in streams if s['codec_type']=='audio']),1)
        self.assertEqual(next(s for s in streams if s['codec_type']=='subtitle')['codec_name'],'mov_text')
        j=self.wait(self.add_source(src,format='webm',video='libvpx-vp9',audio='libopus',subtitles='forced'))
        self.assertEqual(j['status'],'done',j['error'])
        self.assertEqual(next(s for s in app.media_info(j['output'])['streams'] if s['codec_type']=='subtitle')['codec_name'],'webvtt')
    def test_07_auto_crop_and_resize(self):
        j=self.wait(self.add_source(self.rich_source(),autocrop=True,scale='480'))
        self.assertEqual(j['status'],'done',j['error']);self.assertEqual(j['crop'],'160:120:16:20')
        v=next(s for s in app.media_info(j['output'])['streams'] if s['codec_type']=='video')
        self.assertEqual((v['width'],v['height']),(160,120))
        j=self.wait(self.add_source(self.video,autocrop=True))
        self.assertEqual(j['status'],'done',j['error'])
        v=next(s for s in app.media_info(j['output'])['streams'] if s['codec_type']=='video');self.assertEqual((v['width'],v['height']),(160,120))
    def test_08_invalid_track_combinations(self):
        for opts in ({'format':'avi','subtitles':'forced'},{'video':'copy','autocrop':True},{'audio':'copy','channels':'2'},{'audio':'ac3','bitrate':'768'},{'audio':'libmp3lame','channels':'6'}):
            with self.assertRaises(ValueError): app.options(opts)
        with self.assertRaisesRegex(ValueError,'Choose MKV'):
            app.options({'subtitles':'forced'},[{'index':3,'codec_type':'subtitle','codec_name':'hdmv_pgs_subtitle','disposition':{'forced':1}}])
    def test_09_nvenc_runtime(self):
        for codec in sorted(app.NVENC):
            # Real invocation checks FFmpeg's parser as well as any available GPU.
            j=self.wait(self.add_source(self.video,video=codec,audio='none'))
            if j['status']=='done':
                self.assertEqual(next(s for s in app.media_info(j['output'])['streams'] if s['codec_type']=='video')['codec_name'],{'h264_nvenc':'h264','hevc_nvenc':'hevc','av1_nvenc':'av1'}[codec])
            else:
                self.assertIn('NVENC requires a compatible NVIDIA GPU',j['error'])
                self.assertTrue(any(x in j['error'].lower() for x in ('cuda','nvidia','device','driver','not supported','unknown encoder')),j['error'])
                print('\nNVENC unavailable on test host ('+codec+'); hardware encode not verified.');self.resume()

    def test_10_container_hosts_and_origin_checks(self):
        origin='http://localhost:9999'
        self.server.allowed_origins={self.base,origin}
        try:
            req=Request(self.base+'/api/state',headers={'Host':'localhost:9999','Origin':origin,'Cookie':self.cookie})
            with urlopen(req) as r: self.assertIn('jobs',json.load(r))
            for host,source in (('evil.example',origin),('localhost:9999','https://evil.example')):
                with self.assertRaises(HTTPError) as e:
                    urlopen(Request(self.base+'/api/state',headers={'Host':host,'Origin':source}))
                self.assertEqual(e.exception.code,403)
        finally: del self.server.allowed_origins

    def test_11_filename_cleanup_and_collision(self):
        examples={
            'Movie.Title.2020.1080p.BluRay.x264.mkv':'Movie Title (2020)',
            '2001.A.Space.Odyssey.1968.2160p.mkv':'2001 A Space Odyssey (1968)',
            'Movie.Title.(2020).1080p.mkv':'Movie Title (2020)',
            'No.Year.Here.mkv':'No Year Here',
            'Movie.Title.2020.mkv':'Movie Title (2020)',
            '(2020).1080p.mkv':'(2020)',
            'Movie.2020.1920x1080.mkv':'Movie (2020)',
            'Title.2020abc.1080p.mkv':'Title 2020abc 1080p',
            'Movie.[1999].BluRay.mkv':'Movie (1999)',
        }
        for source,result in examples.items(): self.assertEqual(app.output_stem(source,True),result)
        source=self.input/'Movie.Title.2020.1080p.BluRay.mp4'
        source.write_bytes(self.video.read_bytes()); original=source.read_bytes()
        first=self.wait(self.add_source(source,video='copy',cleanNames=True))
        second=self.wait(self.add_source(source,video='copy',cleanNames=True))
        self.assertEqual(first['status'],'done',first['error']);self.assertEqual(second['status'],'done',second['error'])
        self.assertEqual(Path(first['output']).name,'Movie Title (2020).mkv')
        self.assertEqual(Path(second['output']).name,'Movie Title (2020)_1.mkv')
        self.assertEqual(source.read_bytes(),original)
        self.assertGreater(app.probe(second['output']),0)
    def test_12_source_input_paths(self):
        result=self.call('/api/source',{'path':str(self.video),'directory':False})
        self.assertEqual(result['path'],str(self.video));self.assertFalse(result['directory'])
        self.assertTrue(self.call('/api/source',{'path':str(self.input),'directory':True})['directory'])
        for path,directory in ((self.video,True),(self.input,False),(self.root/'missing.mp4',False)):
            with self.assertRaises(HTTPError): self.call('/api/source',{'path':str(path),'directory':directory})
    def test_13_nvenc_modes_and_ffmpeg_parser(self):
        cap=app.nvenc_capabilities('hevc_nvenc');self.assertIn('preset',cap['flags'])
        for codec,profile,depth in (('h264_nvenc','high','8'),('hevc_nvenc','main10','10')):
            for mode in ('cq','vbr','cbr','constqp'):
                settings=dict(video=codec,audio='none',nvPreset='p5',nvTune='hq',nvRate=mode,nvBitrate='4.5',nvMaxrate='0',nvBuffer='0',nvLookahead='16',nvAQ='spatial',nvAQStrength='8',nvBframes='2',nvGop='120',nvProfile=profile,nvDepth=depth,nvGPU='0',nvMultipass='auto' if mode=='constqp' else 'qres')
                fmt,args=app.options(settings)
                self.assertNotIn('-crf',args)
                if mode in ('vbr','cbr'): self.assertNotIn('-cq',args);self.assertEqual(args[args.index('-b:v')+1],'4500000')
                if mode=='constqp': self.assertIn('-qp',args);self.assertNotIn('-cq',args)
                p=subprocess.run(['ffmpeg','-hide_banner','-v','error','-f','lavfi','-i','testsrc2=size=128x128:rate=24','-t','0.1',*args,'-f','null','-'],capture_output=True,text=True,timeout=30)
                if p.returncode:
                    self.assertTrue(any(x in p.stderr.lower() for x in ('cuda','nvidia','device','driver','not supported')),p.stderr)
                    self.assertNotIn('Unrecognized option',p.stderr)
                    self.assertNotIn('Error setting option',p.stderr)
        # Ensure advertised capabilities gate flags instead of passing unknown arguments.
        from unittest.mock import patch
        with patch.object(app,'nvenc_capabilities',return_value={'flags':{'rc':['vbr'],'cq':[]},'pixelFormats':['yuv420p']}):
            with self.assertRaisesRegex(ValueError,'does not support -preset'): app.options({'video':'h264_nvenc','nvPreset':'p7'})
    def test_14_nvenc_validation(self):
        for nv in ({'nvRate':'bogus'},{'nvBitrate':'1;echo bad'},{'nvRate':'vbr','nvBitrate':'10','nvMaxrate':'5'}, {'nvRate':'constqp','nvMultipass':'fullres'}, {'nvDepth':'10'}, {'nvAQStrength':'16'}, {'nvProfile':'baseline','nvBframes':'2'}, {'nvPreset':'p9'}, {'nvRate':'cbr','nvBitrate':'5','nvMaxrate':'8'}):
            with self.assertRaises(ValueError): app.options(dict(video='h264_nvenc',**nv))
        with self.assertRaises(ValueError): app.options({'cleanNames':'true'})

    def until(self,predicate,timeout=10):
        deadline=time.monotonic()+timeout
        while time.monotonic()<deadline:
            if predicate(): return
            time.sleep(.03)
        self.fail('Timed out waiting for state change')
    def test_15_edition_names(self):
        examples={
            "Movie.Title.2020.Directors.Cut.1080p.mkv":"Movie Title (2020) {Edition- Director's Cut}",
            "Movie.Title.(2020).Special.Edition.BluRay.mkv":"Movie Title (2020) {Edition- Special Edition}",
            "Movie.Title.Extended.Edition.2020.1080p.mkv":"Movie Title (2020) {Edition- Extended Edition}",
            "Movie.Title.2020.Extended.Directors.Cut.mkv":"Movie Title (2020) {Edition- Extended Director's Cut}",
            "Movie Title (2020) {Edition- Director's Cut}.mkv":"Movie Title (2020) {Edition- Director's Cut}",
            "Movie.Title.2020.25th.Anniversary.Edition.mkv":"Movie Title (2020) {Edition- 25th Anniversary Edition}",
            "Movie.Title.2020.Final.Cut.mkv":"Movie Title (2020) {Edition- Final Cut}",
        }
        for name,expected in examples.items(): self.assertEqual(app.output_stem(name,True),expected)
        self.assertEqual(app.output_stem('Movie.2020.Special.Edition.mkv',False),'Movie.2020.Special.Edition_converted')
    def test_16_per_track_audio_and_duplicate_encodes(self):
        src=self.rich_source();info=self.call('/api/inspect',{'path':str(src)})
        self.assertEqual([s['language'] for s in info['tracks']],['eng','spa'])
        plan=[{'source':0,'outputs':[{'codec':'copy'},{'codec':'aac','bitrate':'128','channels':'2','title':'AAC stereo'}]}, {'source':1,'outputs':[{'codec':'ac3','bitrate':'448','channels':'6','title':'Spanish surround'}]}]
        j=self.wait(self.add_source(src,video='copy',audioMode='perTrack',audioPlan=plan,audioFallback='drop'))
        self.assertEqual(j['status'],'done',j['error'])
        audio=[s for s in app.media_info(j['output'])['streams'] if s['codec_type']=='audio']
        self.assertEqual([s['codec_name'] for s in audio],['aac','aac','ac3']);self.assertEqual([s['channels'] for s in audio],[1,2,6])
        self.assertEqual([s['tags']['language'] for s in audio],['eng','eng','spa']);self.assertEqual(audio[1]['tags']['title'],'AAC stereo')
        self.assertLessEqual(sum(s['disposition']['default'] for s in audio),1)
        def hashes(path):
            p=subprocess.run(['ffprobe','-v','error','-select_streams','a:0','-show_packets','-show_data_hash','sha256','-show_entries','packet=data_hash','-of','json',str(path)],capture_output=True,text=True,check=True)
            return [x['data_hash'] for x in json.loads(p.stdout)['packets']]
        self.assertEqual(hashes(src),hashes(j['output']))
        # Invalid and missing track references are explicit errors, not silent drops.
        for invalid in ([{'source':0,'outputs':[{'codec':'copy','channels':'2'}]}],[{'source':0,'outputs':[]},{'source':0,'outputs':[]}]):
            with self.assertRaises(ValueError): app.options(dict(format='mkv',audioMode='perTrack',audioPlan=invalid))
        with self.assertRaisesRegex(ValueError,'missing'):
            app.options(dict(format='mkv',audioMode='perTrack',audioPlan=[{'source':5,'outputs':[{'codec':'aac'}]}]),app.media_info(src)['streams'])
        j=self.wait(self.add_source(src,video='copy',audioMode='perTrack',audioPlan=[{'source':0,'outputs':[]}],audioFallback='copy'))
        self.assertEqual(j['status'],'done',j['error']);audio=[s for s in app.media_info(j['output'])['streams'] if s['codec_type']=='audio'];self.assertEqual(len(audio),1);self.assertEqual(audio[0]['tags']['language'],'spa')
    def test_17_stop_on_failure_and_notifications(self):
        self.until(lambda:self.call('/api/state')['queue']['run'] is None)
        bad=self.input/'stop-on-bad.mp4';bad.write_text('broken media')
        with patch.object(storage,'notify') as notify:
            self.call('/api/add',dict(paths=[str(bad),str(self.video)],folder=str(self.output),options=dict(format='mkv',video='copy',audio='copy')))
            state=self.call('/api/state');first,second=state['jobs'][-2:]
            self.assertEqual(self.wait(first['id'])['status'],'failed')
            self.assertTrue(self.call('/api/state')['queue']['paused'])
            time.sleep(.3)
            pending=next(j for j in self.call('/api/state')['jobs'] if j['id']==second['id']);self.assertEqual(pending['status'],'queued')
            self.resume();self.assertEqual(self.wait(second['id'])['status'],'done')
            self.until(lambda:self.call('/api/state')['queue']['run'] is None)
            self.until(lambda:sum(c.args[0]=='finished' for c in notify.call_args_list)==1)
            app.finish_queue();app.finish_queue()
            self.assertEqual(sum(c.args[0]=='failure' for c in notify.call_args_list),1)
            self.assertEqual(sum(c.args[0]=='finished' for c in notify.call_args_list),1)
        # Retry the failed record after repairing its input.
        bad.write_bytes(self.video.read_bytes());self.call('/api/queue',{'action':'retry','id':first['id']})
        self.assertEqual(self.wait(first['id'])['status'],'done');bad.unlink()
    def test_18_low_disk_before_and_during_encoding(self):
        self.until(lambda:self.call('/api/state')['queue']['run'] is None)
        from collections import namedtuple
        Usage=namedtuple('Usage','total used free')
        real_usage=app.shutil.disk_usage
        with patch.object(app.shutil,'disk_usage',return_value=Usage(10**10,6*10**9,app.MIN_FREE_BYTES-1)):
            jid=self.add();self.assertEqual(self.wait(jid)['status'],'blocked');self.assertEqual(self.call('/api/state')['queue']['kind'],'disk')
            with self.assertRaises(HTTPError): self.call('/api/queue',{'action':'resume'})
        self.resume();self.assertEqual(self.wait(jid)['status'],'done')
        low=threading.Event();started=threading.Event();popen=app.subprocess.Popen
        def slow_popen(cmd,*args,**kwargs):
            if isinstance(cmd,list) and '-progress' in cmd:
                cmd=list(cmd);i=cmd.index('-i');cmd[i:i]=['-re','-stream_loop','10'];i=cmd.index('-progress');cmd[i:i]=['-t','5'];p=popen(cmd,*args,**kwargs);started.set();return p
            return popen(cmd,*args,**kwargs)
        def usage(path): return Usage(10**10,9*10**9,1000) if low.is_set() else real_usage(path)
        with patch.object(app.shutil,'disk_usage',side_effect=usage),patch.object(app.subprocess,'Popen',side_effect=slow_popen):
            self.call('/api/add',dict(paths=[str(self.video),str(self.rich_source())],folder=str(self.output),options=dict(format='mkv',video='copy',audio='copy')))
            one,two=self.call('/api/state')['jobs'][-2:];self.assertTrue(started.wait(5));low.set()
            self.assertEqual(self.wait(one['id'])['status'],'blocked')
            self.assertEqual(next(j for j in self.call('/api/state')['jobs'] if j['id']==two['id'])['status'],'queued')
            self.until(lambda:not list((self.output/'_FFtmp').glob('.frameforge-*')))
        self.resume();self.assertEqual(self.wait(one['id'])['status'],'done');self.assertEqual(self.wait(two['id'])['status'],'done')
        with patch.object(app.shutil,'disk_usage',return_value=Usage(10**10,6*10**9,app.MIN_FREE_BYTES)): self.assertEqual(app.ensure_space(self.output),app.MIN_FREE_BYTES)
    def test_19_preset_sqlite_persistence(self):
        settings={'options':{'format':'mkv','video':'copy','audioMode':'perTrack','audioPlan':[{'source':0,'outputs':[{'codec':'copy'},{'codec':'aac','channels':'2','bitrate':'192'}]}],'cleanNames':True},'output':str(self.output),'recursive':True}
        self.call('/api/presets',{'action':'save','name':'Cinema','settings':settings})
        saved=self.call('/api/presets');self.assertEqual(saved['lastPreset'],'Cinema');self.assertEqual(saved['presets'][0]['settings'],settings)
        p=subprocess.run([os.sys.executable,'-c','import storage,json; print(json.dumps(storage.presets()))'],cwd=Path(app.__file__).parent,capture_output=True,text=True,check=True)
        self.assertEqual(json.loads(p.stdout)['presets'][0]['settings'],settings)
        self.call('/api/presets',{'action':'delete','name':'Cinema'});self.assertEqual(self.call('/api/presets')['presets'],[])
    def test_20_email_config_and_delivery_history(self):
        self.until(lambda:self.call('/api/state')['queue']['run'] is None)
        config=dict(enabled=True,onFailure=True,onFinished=True,host='smtp.example.test',port=587,tls='starttls',username='tester',sender='from@example.test',recipients='to@example.test')
        try:
            with patch.object(storage,'deliver') as deliver:
                self.call('/api/notifications',{'settings':config,'password':'session-secret','test':True})
                self.until(lambda:self.call('/api/notifications')['history'][0]['status']=='sent')
                public=self.call('/api/notifications');self.assertNotIn('session-secret',json.dumps(public));self.assertTrue(public['settings']['hasPassword']);self.assertEqual(deliver.call_count,1)
                storage.notify('finished','A completed queue','Done',key='exactly-once-test');storage.notify('finished','A completed queue','Done',key='exactly-once-test')
                self.until(lambda:any(x['id']=='exactly-once-test' and x['status']=='sent' for x in storage.public_mail()['history']));self.assertEqual(deliver.call_count,2)
            with patch.object(storage,'deliver',side_effect=RuntimeError('SMTP unavailable')):
                self.call('/api/notifications',{'settings':config,'test':True})
                self.until(lambda:self.call('/api/notifications')['history'][0]['status']=='failed')
                self.assertIn('SMTP unavailable',self.call('/api/notifications')['history'][0]['error'])
                self.assertFalse(self.call('/api/state')['queue']['paused'])
            self.assertNotIn(b'session-secret',(storage.data_path()/'settings.sqlite3').read_bytes())
        finally:
            config['enabled']=False;storage.save_mail(config,password='')

    def test_21_smtp_tls_and_password_handling(self):
        config=dict(host='smtp.example.test',port=587,tls='starttls',username='user',sender='from@example.test',recipients='to@example.test')
        with patch.object(storage.smtplib,'SMTP') as smtp:
            session=smtp.return_value.__enter__.return_value;session.send_message.return_value={}
            storage.deliver(config,'private','Test','Body');session.starttls.assert_called_once();session.login.assert_called_once_with('user','private');session.send_message.assert_called_once()
        config.update(tls='ssl',port=465)
        with patch.object(storage.smtplib,'SMTP_SSL') as smtp:
            session=smtp.return_value.__enter__.return_value;session.send_message.return_value={}
            storage.deliver(config,'private','Test','Body');session.starttls.assert_not_called();session.login.assert_called_once()
        with self.assertRaisesRegex(ValueError,'STARTTLS'):
            storage.validate_mail(dict(config,enabled=True,tls='none'),True)
        # Interrupted mail is marked unconfirmed rather than claiming success after restart.
        with storage.database() as db: db.execute("INSERT INTO notifications(id,event,subject,status,error) VALUES ('interrupted','test','test','sending','')")
        storage.recover_notifications();row=next(x for x in storage.public_mail()['history'] if x['id']=='interrupted');self.assertEqual(row['status'],'failed');self.assertIn('unconfirmed',row['error'])

    def hdr_source(self):
        path=self.input/'hdr-source.mkv'
        if path.exists(): return path
        params='pools=1:frame-threads=1:log-level=error:hdr10=1:repeat-headers=1:master-display=G(8500,39850)B(6550,2300)R(35400,14600)WP(15635,16450)L(10000000,50):max-cll=1000,400'
        subprocess.run(['ffmpeg','-v','error','-i',str(self.rich_source()),'-map','0:v','-map','0:a','-map','0:s','-c:v','libx265','-pix_fmt','yuv420p10le','-color_primaries','bt2020','-color_trc','smpte2084','-colorspace','bt2020nc','-x265-params',params,'-c:a','copy','-c:s','copy',str(path)],capture_output=True,check=True)
        return path
    def test_22_hdr10_and_sdr_cpu_conversion(self):
        import hdr
        source=self.hdr_source();data=hdr.analyze(app.media_info(source),hdr.read_frames(source));self.assertTrue(data['mastering']);self.assertEqual(data['transfer'],'smpte2084')
        for target,codec in (('sdr','libx264'),('hdr10','libx265')):
            j=self.wait(self.add_source(source,video=codec,hdrTarget=target,hdrEngine='cpu',subtitles='all'))
            self.assertEqual(j['status'],'done',j['error'])
            hdr.verify(app.media_info(j['output']),hdr.read_frames(j['output']),target)
            self.assertEqual(len([s for s in app.media_info(j['output'])['streams'] if s['codec_type']=='subtitle']),2)
        plus=dict(data,hdr10plus=True,kind='HDR10+')
        plan=hdr.build({'format':'mkv','video':'libx265','hdrTarget':'hdr10'},plus)
        self.assertTrue(any('DYNAMIC_HDR_PLUS' in x for x in plan['filters']))
    def test_23_dolby_vision_profile_guards(self):
        import hdr
        dv=dict(hdr.analyze(app.media_info(self.hdr_source()),hdr.read_frames(self.hdr_source())),dovi=True,profile=5,rpuDecoded=True)
        plan=hdr.build({'video':'libx264','hdrTarget':'sdr'},dv);self.assertIn('-init_hw_device',plan['inputArgs']);self.assertTrue(any('apply_dolbyvision=1' in f for f in plan['filters']))
        for change,opts in (({'profile':7,'enhancement':True},{'hdrTarget':'sdr','video':'libx264'}),({'profile':5},{'hdrTarget':'sdr','video':'libx264','dvBaseLayer':True}),({'rpuDecoded':False},{'hdrTarget':'sdr','video':'libx264'})):
            with self.assertRaises(ValueError): hdr.build(opts,dict(dv,**change))
        with self.assertRaises(ValueError): app.options({'video':'copy','hdrTarget':'sdr'})
        with self.assertRaises(ValueError): app.options({'video':'libx264','hdrTarget':'hdr10'})
    def test_24_full_subtitle_selection(self):
        src=self.rich_source();data=self.call('/api/inspect',{'path':str(src)})
        self.assertEqual(len(data['subtitleTracks']),2)
        plan=[dict(source=1,include=True,burn=False,codec='srt',default=True,forced=False,language='spa',title='Spanish subtitles')]
        j=self.wait(self.add_source(src,video='copy',subtitles='custom',subtitlePlan=plan))
        self.assertEqual(j['status'],'done',j['error']);subs=[s for s in app.media_info(j['output'])['streams'] if s['codec_type']=='subtitle']
        self.assertEqual(len(subs),1);self.assertEqual(subs[0]['tags']['language'],'spa');self.assertEqual(subs[0]['disposition']['default'],1);self.assertEqual(subs[0]['disposition']['forced'],0)
        with self.assertRaises(ValueError): app.options(dict(subtitles='custom',subtitlePlan=[dict(source=0,burn=True)],video='copy'))
        with self.assertRaises(ValueError): app.options(dict(subtitles='custom',subtitlePlan=[dict(source=0,include=True,default=True),dict(source=1,include=True,default=True)]))
    def test_25_burn_subtitles_after_crop_and_resize(self):
        import subtitles
        src=self.rich_source();plan=[dict(source=0,include=False,burn=True)]
        j=self.wait(self.add_source(src,video='libx264',subtitles='custom',subtitlePlan=plan,autocrop=True,scale='480'))
        self.assertEqual(j['status'],'done',j['error']);self.assertEqual(j['crop'],'160:120:16:20')
        streams=app.media_info(j['output'])['streams'];self.assertFalse(any(s['codec_type']=='subtitle' for s in streams))
        video=next(s for s in streams if s['codec_type']=='video');self.assertEqual((video['width'],video['height']),(160,120))
        command=j['command'];self.assertLess(command.index('crop=160:120:16:20'),command.index('subtitles=filename='));self.assertLess(command.index('scale='),command.index('subtitles=filename='))
        baseline=self.wait(self.add_source(src,video='libx264',autocrop=True,scale='480'));self.assertEqual(baseline['status'],'done',baseline['error'])
        def pixels(path):
            return subprocess.run(['ffmpeg','-v','error','-i',path,'-ss','0.3','-frames:v','1','-f','rawvideo','-pix_fmt','gray','-'],capture_output=True,check=True).stdout
        self.assertNotEqual(pixels(j['output']),pixels(baseline['output']))
        graph,label=subtitles.graph(['crop=160:120:16:20','scale=-2:120'],[dict(text=False,source=1,bitmapPlacement='aligned')],'160:120:16:20','480')
        self.assertLess(graph.index('crop=160'),graph.index('overlay='));self.assertIn('[0:s:1]format=rgba,crop=160:120:16:20',graph)
    def test_26_hdr10_burn_color_pipeline(self):
        j=self.wait(self.add_source(self.hdr_source(),video='libx265',hdrTarget='hdr10',hdrEngine='cpu',subtitles='custom',subtitlePlan=[dict(source=0,include=True,burn=True)],autocrop=True))
        self.assertEqual(j['status'],'done',j['error'])
        self.assertIn('npl=203',j['command'])
        self.assertLess(j['command'].index('crop='),j['command'].index('subtitles=filename='))

    def test_27_bitmap_subtitle_post_crop_overlay(self):
        import struct
        def be16(n): return struct.pack('>H',n)
        def packet(kind,payload,pts): return b'PG'+struct.pack('>II',pts,pts)+bytes([kind])+be16(len(payload))+payload
        def composition(number,count,state=0):
            data=be16(192)+be16(160)+bytes([0x10])+be16(number)+bytes([state,0,0,count])
            return data+(be16(0)+bytes([0,0])+be16(64)+be16(105) if count else b'')
        rle=(bytes([1])*40+b'\0\0')*8
        obj=be16(0)+bytes([0,0xc0])+(len(rle)+4).to_bytes(3,'big')+be16(40)+be16(8)+rle
        palette=bytes([0,0,0,16,128,128,0,1,235,128,128,255])
        data=b''.join([packet(0x16,composition(0,1,0x80),18000),packet(0x17,bytes([1,0])+be16(0)+be16(0)+be16(192)+be16(160),18000),packet(0x14,palette,18000),packet(0x15,obj,18000),packet(0x80,b'',18000),packet(0x16,composition(1,0),72000),packet(0x80,b'',72000)])
        sup=self.root/'bitmap.sup';sup.write_bytes(data);src=self.input/'bitmap-source.mkv'
        p=subprocess.run(['ffmpeg','-v','error','-i',str(self.rich_source()),'-f','sup','-i',str(sup),'-map','0:v','-map','0:a','-map','1:s','-c','copy',str(src)],capture_output=True,text=True)
        self.assertEqual(p.returncode,0,p.stderr)
        j=self.wait(self.add_source(src,video='libx264',autocrop=True,subtitles='custom',subtitlePlan=[dict(source=0,include=False,burn=True)]))
        self.assertEqual(j['status'],'done',j['error']);v=next(s for s in app.media_info(j['output'])['streams'] if s['codec_type']=='video');self.assertEqual((v['width'],v['height']),(160,120))
        p=subprocess.run(['ffmpeg','-v','error','-ss','0.4','-i',j['output'],'-frames:v','1','-f','rawvideo','-pix_fmt','gray','-'],capture_output=True,check=True)
        region=[p.stdout[y*160+x] for y in range(80,84) for x in range(58,84)];self.assertGreater(sum(region)/len(region),210)
        self.assertGreater(app.probe(j['output']),.9)

    def test_28_hdr_metadata_fallback_and_base_layer(self):
        import hdr
        source=hdr.analyze(app.media_info(self.hdr_source()),hdr.read_frames(self.hdr_source()))
        base=dict(source,dovi=True,profile=7,enhancement=True,baseLayer=True,compatibility=None)
        plan=hdr.build(dict(format='mkv',video='libx265',hdrTarget='hdr10',dvBaseLayer=True),base)
        self.assertFalse(plan['inputArgs']);self.assertIn('base layer only',plan['note']);self.assertIn('-x265-params',plan['encoderArgs'])
        missing=dict(source,mastering=None)
        with self.assertRaisesRegex(ValueError,'mastering-display'): hdr.build(dict(video='libx265',hdrTarget='hdr10'),missing)
        plan=hdr.build(dict(video='libx265',hdrTarget='hdr10',hdrDefaultMaster=True),missing);self.assertIn('explicitly selected',plan['note'])
        with self.assertRaises(ValueError): hdr.build(dict(video='hevc_nvenc',hdrTarget='hdr10',hdrDefaultMaster=True),missing)
        info=app.media_info(self.hdr_source());frames=hdr.read_frames(self.hdr_source());frames[0].setdefault('side_data_list',[]).append({'side_data_type':'HDR Dynamic Metadata SMPTE2094-40 (HDR10+)'})
        with self.assertRaisesRegex(ValueError,'residual'): hdr.verify(info,frames,'hdr10')
    def test_29_multiple_burns_and_embedded_fonts(self):
        font=Path('/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf')
        if not font.exists(): self.skipTest('No test font available on this host')
        src=self.input/"Movie's [sample];2020.mkv"
        subprocess.run(['ffmpeg','-v','error','-i',str(self.rich_source()),'-map','0','-c','copy','-attach',str(font),'-metadata:s:t:0','mimetype=application/x-truetype-font','-metadata:s:t:0','filename=DejaVuSans.ttf',str(src)],capture_output=True,check=True)
        plan=[dict(source=0,include=True,burn=True,default=True),dict(source=1,include=True,burn=True,default=False)]
        j=self.wait(self.add_source(src,video='libx264',subtitles='custom',subtitlePlan=plan,autocrop=True))
        self.assertEqual(j['status'],'done',j['error']);self.assertEqual(j['command'].count('subtitles=filename='),2)
        self.assertEqual(len([s for s in app.media_info(j['output'])['streams'] if s['codec_type']=='subtitle']),2)

    def test_30_parallel_cpu_jobs_and_thread_arguments(self):
        for _ in range(100):
            with app.LOCK: busy=any(j.get('_working') for j in app.JOBS)
            if not busy: break
            time.sleep(.02)
        gate=threading.Event();shutdown=threading.Event();entered=[];original=app.media_info
        def held_info(path):
            with app.LOCK:
                entered.append(str(path))
                if len(entered)>=2: gate.set()
            if not gate.wait(5): raise ValueError('Second parallel job did not start')
            return original(path)
        extra=threading.Thread(target=app.worker,args=(shutdown,),daemon=True)
        ids=[]
        try:
            with patch.object(app,'media_info',side_effect=held_info):
                extra.start()
                ids.append(self.add(cpuJobs=2,gpuJobs=1,cpuThreads=2,ownFolder=True))
                ids.append(self.add(cpuJobs=2,gpuJobs=1,cpuThreads=2,ownFolder=True))
                self.assertTrue(gate.wait(5),'Both jobs must enter processing simultaneously')
                jobs=[self.wait(i) for i in ids]
                for j in jobs:
                    self.assertEqual(j['status'],'done',j['error'])
                    self.assertIn('-threads:v 2',j['command']);self.assertIn('-filter_complex_threads 2',j['command'])
                self.assertNotEqual(jobs[0]['output'],jobs[1]['output'])
                for j in jobs: self.assertEqual(app.media_info(j['output'])['format']['tags']['title'],Path(j['output']).stem)
        finally:
            gate.set();shutdown.set();extra.join(10)
            self.call('/api/performance',dict(cpuJobs=1,gpuJobs=1))

    def test_31_thread_validation_and_x265_hdr_merge(self):
        for key,values in [('cpuThreads',[-1,257,True,1.5,'abc']),('cpuJobs',[0,9,True]),('gpuJobs',[0,9,False])]:
            for value in values:
                with self.assertRaises(ValueError): app.options({key:value})
        plan={'encoderArgs':['-x265-params','hdr10=1:repeat-headers=1']}
        _,args=app.options(dict(video='libx265',cpuThreads=3),hdr_plan=plan)
        self.assertEqual(args.count('-x265-params'),1)
        self.assertIn('hdr10=1:repeat-headers=1:pools=3:frame-threads=1',args)
        j=self.wait(self.add(video='libx265',cpuThreads=2))
        self.assertEqual(j['status'],'done',j['error'])

    def test_32_scheduler_capacity_pause_and_global_disk_stop(self):
        # Hold the same lock used by live workers while exercising claims.
        with app.LOCK:
            saved_jobs=app.JOBS[:];saved_control=dict(app.CONTROL);saved_limits=dict(app.PERFORMANCE)
            try:
                app.JOBS[:]=[dict(id=str(i),options={'video':v},status='queued') for i,v in enumerate(['libx264','libx264','hevc_nvenc','hevc_nvenc'])]
                app.PERFORMANCE.update(cpuJobs=1,gpuJobs=1);app.CONTROL['paused']=False
                a=app.claim_job();b=app.claim_job()
                self.assertEqual([a['id'],b['id']],['0','2']);self.assertIsNone(app.claim_job())
                app.PERFORMANCE['cpuJobs']=2;c=app.claim_job();self.assertEqual(c['id'],'1')
                app.PERFORMANCE['cpuJobs']=1;self.assertIsNone(app.claim_job())
                app.pause_queue('failure','failed');self.assertIsNone(app.claim_job())
                self.assertNotIn('_disk_error',a)
                app.pause_queue('disk','less than 4 GB')
                for j in (a,b,c):
                    with self.assertRaises(app.LowDiskSpace): app.check_interrupted(j)
                self.assertIsNone(app.claim_job())
                terminated=[]
                a['_process']=object();b['_process']=object()
                with patch.object(app,'terminate',side_effect=terminated.append):
                    app.disk_monitor(a,threading.Event());app.disk_monitor(b,threading.Event())
                self.assertEqual(terminated,[a['_process'],b['_process']])
                # Cancelled-but-cleaning jobs still reserve a slot.
                app.CONTROL['paused']=False;b['status']='cancelled'
                self.assertIsNone(app.claim_job())
            finally:
                app.JOBS[:]=saved_jobs;app.CONTROL.clear();app.CONTROL.update(saved_control);app.PERFORMANCE.update(saved_limits)

    def test_33_performance_api_and_presets(self):
        self.call('/api/performance',dict(cpuJobs=2,gpuJobs=3))
        self.assertEqual(self.call('/api/state')['performance'],dict(cpuJobs=2,gpuJobs=3))
        self.assertEqual(storage.get_pref('performance',{}),dict(cpuJobs=2,gpuJobs=3))
        with self.assertRaises(HTTPError): self.call('/api/performance',dict(cpuJobs=99,gpuJobs=1))
        self.call('/api/presets',dict(action='save',name='Thread settings',settings={'options':dict(cpuThreads=4,cpuJobs=2,gpuJobs=3)}))
        preset=next(p for p in self.call('/api/presets')['presets'] if p['name']=='Thread settings')
        self.assertEqual(preset['settings']['options']['cpuThreads'],4)
        self.call('/api/performance',dict(cpuJobs=1,gpuJobs=1))

    def test_34_failure_does_not_launch_remaining_parallel_jobs(self):
        gate=threading.Event();entered=threading.Event();shutdown=threading.Event();original=app.media_info
        bad=self.input/'parallel-bad.mp4';bad.write_bytes(b'not a video')
        first_path=str(self.video)
        def held_info(path):
            if str(path)==first_path and not gate.is_set():
                entered.set()
                if not gate.wait(5): raise ValueError('Parallel test timed out')
            return original(path)
        extra=threading.Thread(target=app.worker,args=(shutdown,),daemon=True)
        try:
            self.call('/api/queue',{'action':'pause'})
            first=self.add(cpuJobs=2,cpuThreads=1)
            opts=dict(format='mp4',video='libx264',audio='aac',cpuJobs=2,cpuThreads=1)
            self.call('/api/add',dict(paths=[str(bad)],folder=str(self.output),options=opts))
            failed=self.call('/api/state')['jobs'][-1]['id']
            remaining=self.add(cpuJobs=2,cpuThreads=1)
            with patch.object(app,'media_info',side_effect=held_info):
                extra.start();self.resume();self.assertTrue(entered.wait(5))
                self.assertEqual(self.wait(failed)['status'],'failed')
                state=self.call('/api/state');self.assertTrue(state['queue']['paused'])
                self.assertEqual(next(j for j in state['jobs'] if j['id']==remaining)['status'],'queued')
                gate.set();self.assertEqual(self.wait(first)['status'],'done')
            self.assertEqual(next(j for j in self.call('/api/state')['jobs'] if j['id']==remaining)['status'],'queued')
            self.resume();self.assertEqual(self.wait(remaining)['status'],'done')
        finally:
            gate.set();shutdown.set();extra.join(10)
            self.call('/api/performance',dict(cpuJobs=1,gpuJobs=1))

    def test_35_output_title_matches_final_filename(self):
        src=self.input/"Title.with.dots.2020.Directors.Cut.mkv"
        subprocess.run(['ffmpeg','-v','error','-i',str(self.video),'-map','0','-c','copy','-metadata','title=Old source title',str(src)],check=True)
        for fmt in ('mp4','mkv','mov','webm','avi'):
            params=dict(format=fmt,cpuThreads=1,cleanNames=True)
            if fmt=='webm': params.update(video='libvpx-vp9',audio='libopus')
            elif fmt=='avi': params.update(video='mpeg4',audio='libmp3lame')
            if fmt=='mkv': params.update(video='copy',audio='copy')
            for _ in range(2):
                j=self.wait(self.add_source(src,**params))
                self.assertEqual(j['status'],'done',j['error'])
                tags=app.media_info(j['output'])['format'].get('tags',{})
                self.assertEqual({k.lower():v for k,v in tags.items()}.get('title'),Path(j['output']).stem)
                self.assertIn("(2020) {Edition- Director's Cut}",Path(j['output']).stem)
        j=self.wait(self.add(cpuThreads=1))
        tags=app.media_info(j['output'])['format'].get('tags',{})
        self.assertEqual(tags.get('title'),Path(j['output']).stem)

    def test_36_movie_output_folders_editions_and_collisions(self):
        outputs=[]
        for edition in ('Criterion.Collection','Directors.Cut','Criterion.Collection'):
            source=self.input/f'Folder.Movie.2020.{edition}.mp4'
            source.write_bytes(self.video.read_bytes())
            j=self.wait(self.add_source(source,format='mkv',video='copy',audio='copy',ownFolder=True,cleanNames=True))
            self.assertEqual(j['status'],'done',j['error'])
            output=Path(j['output']);outputs.append(output)
            self.assertEqual(output.parent,self.output/'Folder Movie (2020)')
            self.assertIn('{Edition- ',output.stem)
            tags=app.media_info(output)['format']['tags']
            self.assertEqual({k.lower():v for k,v in tags.items()}['title'],output.stem)
            self.assertEqual(source.read_bytes(),self.video.read_bytes())
        self.assertEqual(outputs[2].stem,outputs[0].stem+'_1')
        self.assertNotEqual(outputs[0],outputs[1])
        j=self.wait(self.add(ownFolder=True,cleanNames=False,cpuThreads=1))
        self.assertEqual(j['status'],'done',j['error'])
        self.assertEqual(Path(j['output']).parent,self.output/'test video')
        self.assertTrue(Path(j['output']).stem.startswith('test video_converted'))
        self.call('/api/presets',dict(action='save',name='Movie folders',settings={'options':dict(ownFolder=True,cleanNames=True)}))
        preset=next(p for p in self.call('/api/presets')['presets'] if p['name']=='Movie folders')
        self.assertTrue(preset['settings']['options']['ownFolder'])

    def test_37_movie_folder_validation_and_disk_target(self):
        for value in (1,'yes',None):
            with self.assertRaises(ValueError):app.options({'ownFolder':value})
        self.assertEqual(app.movie_folder_name('Movie.Title.2020.Criterion.Collection.mkv'),'Movie Title (2020)')
        self.assertEqual(app.movie_folder_name('Movie.Title.Directors.Cut.mkv'),'Movie Title')
        job=dict(folder=str(self.output),input='Movie.Title.2020.Special.Edition.mkv',options={'ownFolder':True})
        directory=app.output_directory(job);directory.mkdir(exist_ok=True)
        with patch.object(app,'ensure_space',return_value=app.MIN_FREE_BYTES) as space:
            app.ensure_job_space(job);self.assertEqual(space.call_args_list[0].args[0],str(self.output));self.assertEqual(space.call_args_list[-1].args[0],directory)

    def test_38_root_staging_and_mirrored_tree(self):
        root=self.input/'mirror-tree';nested=root/'Drama'/'Classics';nested.mkdir(parents=True,exist_ok=True)
        source=nested/'Mirrored.Movie.2020.Criterion.Collection.mp4';source.write_bytes(self.video.read_bytes())
        for own in (False,True):
            self.call('/api/add',dict(paths=[str(root)],folder=str(self.output),recursive=True,options=dict(format='mkv',video='copy',audio='copy',mirrorDirs=True,ownFolder=own,cleanNames=True)))
            j=self.wait(self.call('/api/state')['jobs'][-1]['id'])
            self.assertEqual(j['status'],'done',j['error'])
            parent=self.output/'Drama'/'Classics'
            if own:parent=parent/'Mirrored Movie (2020)'
            self.assertEqual(Path(j['output']).parent,parent)
            # Command records the encoded media staging path inside destination/_FFtmp.
            self.assertIn(str(self.output/'_FFtmp'/('.frameforge-'+j['id']+'.mkv')),j['command'])
            self.assertFalse(list((self.output/'_FFtmp').glob('.frameforge-*')))
            tags=app.media_info(j['output'])['format']['tags'];self.assertEqual(tags['title'],Path(j['output']).stem)
        self.call('/api/add',dict(paths=[str(source)],folder=str(self.output),recursive=True,options=dict(format='mkv',video='copy',audio='copy',mirrorDirs=True)))
        j=self.wait(self.call('/api/state')['jobs'][-1]['id']);self.assertEqual(Path(j['output']).parent,self.output)
        with self.assertRaises(HTTPError):self.call('/api/add',dict(paths=[str(root)],folder=str(self.output),recursive=False,options=dict(mirrorDirs=True)))
        job=dict(folder=str(self.output),input=str(source),relativeDir='../escape',options={'mirrorDirs':True})
        with self.assertRaises(ValueError):app.output_directory(job)

    def test_39_staging_precedes_final_directory_creation(self):
        # Reserving the final name must not create its movie folder early.
        source=self.input/'Publish.Later.2021.mp4';source.write_bytes(self.video.read_bytes())
        job=dict(id='staging-test',input=str(source),folder=str(self.output),options={'ownFolder':True,'cleanNames':True})
        destination=app.reserve_destination(job,'mkv')
        self.assertEqual(destination.parent,self.output/'Publish Later (2021)')
        self.assertFalse(destination.parent.exists())
        self.call('/api/presets',dict(action='save',name='Mirrored tree',settings={'recursive':True,'options':dict(mirrorDirs=True,ownFolder=True)}))
        saved=next(p for p in self.call('/api/presets')['presets'] if p['name']=='Mirrored tree')
        self.assertTrue(saved['settings']['options']['mirrorDirs'])

    def test_40_temp_directory_is_reused_and_excluded_from_scans(self):
        root=self.root/'scan-with-temp';root.mkdir(exist_ok=True)
        (root/'source.mp4').write_bytes(self.video.read_bytes())
        stage=root/'_FFtmp';stage.mkdir(exist_ok=True)
        (stage/'unfinished.mp4').write_bytes(b'incomplete')
        self.call('/api/add',dict(paths=[str(root)],folder=str(root),recursive=True,options=dict(format='mkv',video='copy',audio='copy')))
        j=self.call('/api/state')['jobs'][-1]
        self.assertEqual(self.wait(j['id'])['status'],'done')
        self.assertEqual(Path(j['input']).name,'source.mp4')
        self.assertTrue(stage.is_dir());self.assertEqual((stage/'unfinished.mp4').read_bytes(),b'incomplete')

    def test_41_optional_suffix_and_srt_sidecars(self):
        j=self.wait(self.add(addConverted=False,cpuThreads=1))
        self.assertEqual(j['status'],'done',j['error']);self.assertFalse('_converted' in Path(j['output']).name)
        source=self.rich_source()
        for mode,count in [('all',2),('forced',1)]:
            j=self.wait(self.add_source(source,video='copy',exportSrt=mode,ownFolder=True,addConverted=False))
            self.assertEqual(j['status'],'done',j['error']);self.assertEqual(len(j['generatedFiles']),count)
            for filename in j['generatedFiles']:
                path=Path(filename);self.assertEqual(path.parent,Path(j['output']).parent)
                self.assertTrue(path.name.startswith(Path(j['output']).stem+'.'))
                self.assertIn('Forced caption',path.read_text(encoding='utf-8'))
        # An existing SRT reserves the whole basename, even with no video there.
        name=app.output_stem(source,False,False);collision=self.output/(name+'.und.s1.forced.srt')
        collision.write_text('leave unchanged')
        j=self.wait(self.add_source(source,video='copy',exportSrt='forced',addConverted=False))
        self.assertEqual(j['status'],'done',j['error']);self.assertNotEqual(Path(j['output']).stem,name)
        self.assertEqual(collision.read_text(),'leave unchanged')

    def test_42_custom_srt_and_post_crop_filter_order(self):
        plan=[dict(source=0,include=False,burn=True,export=True,forced=True,language='eng')]
        j=self.wait(self.add_source(self.rich_source(),subtitles='custom',subtitlePlan=plan,exportSrt='custom',scanMode='bwdif_frame',fieldOrder='tff',autocrop=True,cpuThreads=1))
        self.assertEqual(j['status'],'done',j['error']);self.assertEqual(len(j['generatedFiles']),1)
        self.assertIn('.eng.s1.forced.srt',j['generatedFiles'][0])
        self.assertLess(j['command'].index('bwdif='),j['command'].index('crop='));self.assertLess(j['command'].index('crop='),j['command'].index('subtitles=filename='))
        self.assertFalse(any(s['codec_type']=='subtitle' for s in app.media_info(j['output'])['streams']))
        import subtitles
        bitmap=[{'codec_type':'subtitle','codec_name':'hdmv_pgs_subtitle'}]
        exports,warning=subtitles.export_plan({'exportSrt':'all'},bitmap);self.assertFalse(exports);self.assertIn('OCR',warning)
        with self.assertRaisesRegex(ValueError,'OCR'):subtitles.export_plan({'exportSrt':'custom','subtitlePlan':[{'source':0,'export':True}]},bitmap)

    def test_43_real_interlace_detection_and_bob(self):
        src=self.input/'interlaced.mkv'
        subprocess.run(['ffmpeg','-v','error','-f','lavfi','-i','testsrc2=size=192x160:rate=60','-vf','tinterlace=mode=interleave_top','-t','2','-c:v','ffv1',str(src)],check=True)
        report=self.call('/api/interlace',{'path':str(src)})
        self.assertEqual(report['kind'],'interlaced',report)
        j=self.wait(self.add_source(src,audio='none',scanMode='auto',cpuThreads=1))
        self.assertEqual(j['status'],'done',j['error']);self.assertIn('bwdif=',j['command']);self.assertEqual(j['scanReport']['kind'],'interlaced')
        j=self.wait(self.add_source(src,audio='none',scanMode='bwdif_field',fieldOrder='tff',cpuThreads=1))
        self.assertEqual(j['status'],'done',j['error'])
        video=next(s for s in app.media_info(j['output'])['streams'] if s['codec_type']=='video')
        a,b=map(int,video['avg_frame_rate'].split('/'));self.assertAlmostEqual(a/b,60,delta=.01)

    def test_44_real_inverse_telecine_and_validation(self):
        src=self.input/'telecine.mkv'
        subprocess.run(['ffmpeg','-v','error','-f','lavfi','-i','testsrc2=size=192x160:rate=24','-vf','telecine=pattern=23','-t','2','-c:v','libx264',str(src)],check=True)
        j=self.wait(self.add_source(src,audio='none',scanMode='ivtc',fieldOrder='tff',cpuThreads=1))
        self.assertEqual(j['status'],'done',j['error'])
        video=next(s for s in app.media_info(j['output'])['streams'] if s['codec_type']=='video');a,b=map(int,video['avg_frame_rate'].split('/'));self.assertAlmostEqual(a/b,24,delta=.01)
        for settings in [dict(scanMode='ivtc',video='copy'),dict(scanMode='bwdif_field',fps='30'),dict(scanMode='invalid'),dict(addConverted='yes')]:
            with self.assertRaises(ValueError):app.options(settings)
        self.call('/api/presets',dict(action='save',name='Scan and SRT',settings={'options':dict(addConverted=False,scanMode='auto',detectInterlace=True,fieldOrder='auto',exportSrt='all')}))
        saved=next(p for p in self.call('/api/presets')['presets'] if p['name']=='Scan and SRT')
        self.assertFalse(saved['settings']['options']['addConverted']);self.assertEqual(saved['settings']['options']['scanMode'],'auto')

    def test_45_movie_tv_naming_patterns(self):
        import naming
        cases=[
            ('Series.Name.2020.S01E02.Pilot.1080p.WEB-DL.mkv','Series Name (2020) - S01E02 - Pilot'),
            ('Series.Name.1x02x03.Double.Feature.720p.mkv','Series Name - S01E02-E03 - Double Feature'),
            ('Series.Name.S01E02-E04.Parts.1080p.mkv','Series Name - S01E02-E04 - Parts'),
            ('Daily.Show.2024.03.05.Guest.1080p.mkv','Daily Show - 2024-03-05 - Guest'),
            ('1923.S01E01.Premiere.mkv','1923 - S01E01 - Premiere'),
            ('The.Office.(US).2005.S01E01.Pilot.1080p.mkv','The Office (US) (2005) - S01E01 - Pilot'),
            ('Series Name/Season 03/02 - Next Episode.mkv','Series Name - S03E02 - Next Episode')]
        for source,expected in cases:
            self.assertEqual(naming.detect(source)['kind'],'tv');self.assertEqual(app.output_stem(source,True),expected)
        source='Series.Name.2020.S02E03.Pilot.1080p.mkv'
        self.assertEqual(app.output_stem(source,True,naming_options={'tvPattern':'x','tvKeepYear':False}),'Series Name - 2x03 - Pilot')
        self.assertEqual(app.output_stem(source,True,naming_options={'tvPattern':'compact'}),'Series Name (2020) S02E03')
        self.assertEqual(app.output_stem(source,True,naming_options={'tvKeepTitle':False}),'Series Name (2020) - S02E03')
        self.assertEqual(naming.detect('Movie.Title.2020.Criterion.Collection.mkv')['kind'],'movie')
        self.assertEqual(naming.detect('Unknown.Name.mkv')['kind'],'unknown')
        with self.assertRaises(ValueError):app.output_stem('Unknown.Name.mkv',True,naming_options={'contentType':'tv'})
        self.assertEqual(naming.detect('Daily.Show.2024.02.30.mkv')['kind'],'movie')

    def test_46_tv_folders_preview_metadata_and_srt(self):
        root=self.input/'tv-batch';folder=root/'Drama';folder.mkdir(parents=True,exist_ok=True)
        source=folder/'Series.Name.2020.S02E03.Pilot.1080p.mkv';source.write_bytes(self.rich_source().read_bytes())
        policy=dict(format='mkv',video='copy',audio='copy',subtitles='none',exportSrt='forced',contentType='auto',cleanNames=True,tvFolders='season',ownFolder=True,mirrorDirs=True)
        preview=self.call('/api/naming',{'path':str(source),'options':policy})
        self.assertEqual(preview['identity']['kind'],'tv');self.assertEqual(preview['filename'],'Series Name (2020) - S02E03 - Pilot.mkv')
        self.call('/api/add',dict(paths=[str(root)],folder=str(self.output),recursive=True,options=policy))
        j=self.wait(self.call('/api/state')['jobs'][-1]['id'])
        self.assertEqual(j['status'],'done',j['error']);self.assertEqual(j['nameInfo']['kind'],'tv')
        output=Path(j['output']);self.assertEqual(output.parent,self.output/'Drama'/'Series Name (2020)'/'Season 02')
        self.assertEqual(output.name,preview['filename']);self.assertEqual(Path(j['generatedFiles'][0]).parent,output.parent)
        tags=app.media_info(output)['format']['tags'];self.assertEqual(tags['title'],output.stem)
        self.call('/api/presets',dict(action='save',name='TV layout',settings={'recursive':True,'options':policy}))
        saved=next(p for p in self.call('/api/presets')['presets'] if p['name']=='TV layout');self.assertEqual(saved['settings']['options']['tvFolders'],'season')

    def test_47_sidecar_publication_rollback(self):
        source=self.input/'Rollback.Source.mkv';source.write_bytes(self.rich_source().read_bytes())
        original=app.os.link
        def interrupted_link(src,dst):
            if Path(dst).name=='Rollback Source.mkv':raise FileExistsError('Simulated destination collision during publication')
            return original(src,dst)
        try:
            with patch.object(app.os,'link',side_effect=interrupted_link):
                j=self.wait(self.add_source(source,video='copy',exportSrt='all',cleanNames=True,ownFolder=True))
                self.assertEqual(j['status'],'failed')
            folder=self.output/'Rollback Source'
            self.assertFalse(list(folder.glob('*.srt')));self.assertFalse(list(folder.glob('*.mkv')))
            self.assertTrue(self.call('/api/state')['queue']['paused'])
        finally:self.resume()

if __name__=='__main__': unittest.main(verbosity=2)
