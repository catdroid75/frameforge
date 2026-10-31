"""Login and HTTP boundary tests. No real user credentials or emails."""
import json, os, tempfile, threading, unittest, re, time
from unittest.mock import patch
from urllib.request import Request,urlopen
from urllib.error import HTTPError
import app,auth,storage

class Authentication(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp=tempfile.TemporaryDirectory()
        cls.env=patch.dict(os.environ,{'FRAMEFORGE_DATA':cls.tmp.name,'FRAMEFORGE_AUTH_TOKEN':'test-only-long-token-0123456789','FRAMEFORGE_COOKIE_SECURE':'false'})
        cls.env.start();auth.configure()
        cls.server=app.ThreadingHTTPServer(('127.0.0.1',0),app.Handler)
        cls.base='http://127.0.0.1:'+str(cls.server.server_port)
        threading.Thread(target=cls.server.serve_forever,daemon=True).start()
    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown();cls.server.server_close();cls.env.stop();cls.tmp.cleanup()
    def setUp(self):
        with auth.LOCK: auth.ATTEMPTS.clear();auth.SESSIONS.clear()
    def request(self,path,data=None,cookie=None,token=True,origin=None):
        headers={}
        if cookie:headers['Cookie']=cookie
        if token:headers['X-Token']=app.TOKEN
        if origin:headers['Origin']=origin
        try:
            r=urlopen(Request(self.base+path,data=json.dumps(data).encode() if data is not None else None,headers=headers))
        except HTTPError as e:r=e
        with r:return r.status,r.headers,r.read()
    def sign_in(self):
        code,headers,_=self.request('/api/login',{'token':'test-only-long-token-0123456789'})
        self.assertEqual(code,200)
        return headers['Set-Cookie'].split(';')[0]
    def test_no_anonymous_data_or_actions(self):
        for path in ('/api/state','/api/browse','/api/presets','/api/notifications','/app.js'):
            self.assertEqual(self.request(path)[0],401,path)
        code,_,body=self.request('/')
        self.assertEqual(code,200);self.assertIn(b'loginForm',body);self.assertNotIn(b'fileInput',body)
        self.assertEqual(self.request('/api/cancel',{'all':True})[0],401)
        self.assertEqual(self.request('/healthz')[2],b'{"ok": true}')
    def test_login_cookie_logout_and_csrf(self):
        self.assertEqual(self.request('/api/login',{'token':'wrong'})[0],401)
        self.assertEqual(self.request('/api/login',{'token':'test-only-long-token-0123456789'},token=False)[0],403)
        cookie=self.sign_in()
        code,headers,_=self.request('/api/login',{'token':'test-only-long-token-0123456789'})
        self.assertIn('HttpOnly',headers['Set-Cookie']);self.assertIn('SameSite=Strict',headers['Set-Cookie'])
        self.assertEqual(self.request('/api/state',cookie=cookie)[0],200)
        self.assertEqual(self.request('/api/logout',{},cookie=cookie,token=False)[0],403)
        self.assertEqual(self.request('/api/logout',{},cookie=cookie,origin='https://attacker.example')[0],403)
        self.assertEqual(self.request('/api/logout',{},cookie=cookie)[0],200)
        self.assertEqual(self.request('/api/state',cookie=cookie)[0],401)
    def test_hash_expiry_throttle_and_secure_flag(self):
        account=storage.get_pref('loginToken');self.assertNotIn('test-only-long-token-0123456789',json.dumps(account))
        self.assertEqual(account['iterations'],600000)
        cookie=self.sign_in()
        with auth.LOCK:auth.SESSIONS[auth.session_id(cookie)]=time.monotonic()-1
        self.assertEqual(self.request('/api/state',cookie=cookie)[0],401)
        for _ in range(5):self.assertEqual(self.request('/api/login',{'token':'wrong'})[0],401)
        self.assertEqual(self.request('/api/login',{'token':'wrong'})[0],429)
        with patch.dict(os.environ,{'FRAMEFORGE_COOKIE_SECURE':'true'}):self.assertIn('; Secure',auth.cookie('test'))
    def test_token_required_and_hash_persistence(self):
        with patch.dict(os.environ,{'FRAMEFORGE_AUTH_TOKEN':''}):auth.configure()
        self.assertTrue(self.sign_in())
        with tempfile.TemporaryDirectory() as d,patch.dict(os.environ,{'FRAMEFORGE_DATA':d,'FRAMEFORGE_AUTH_TOKEN':''}):
            with self.assertRaisesRegex(ValueError,'Set FRAMEFORGE_AUTH_TOKEN'):auth.configure()
        with patch.dict(os.environ,{'FRAMEFORGE_AUTH_TOKEN':'short'}):
            with self.assertRaises(ValueError):auth.configure()

    def test_old_credentials_rejected_and_migrated(self):
        storage.set_pref('login',{'username':'old-user','hash':'old-hash'})
        auth.configure()
        self.assertIsNone(storage.get_pref('login'))
        self.assertNotIn('username',storage.get_pref('loginToken'))
        self.assertEqual(self.request('/api/login',{'username':'admin','password':'test-only-long-token-0123456789'})[0],401)
        self.assertTrue(self.sign_in())

    def test_twelve_character_minimum(self):
        try:
            with patch.dict(os.environ,{'FRAMEFORGE_AUTH_TOKEN':'a'*11}):
                with self.assertRaises(ValueError):auth.configure()
            with patch.dict(os.environ,{'FRAMEFORGE_AUTH_TOKEN':'a'*12}):
                auth.configure()
                session,limited=auth.login('a'*12,'minimum-length-test')
                self.assertTrue(session);self.assertFalse(limited)
        finally:auth.configure()

if __name__=='__main__':unittest.main()
