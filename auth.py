"""Single-token login using Python's standard library; no plaintext DB tokens."""
import hashlib, hmac, os, secrets, threading, time
from http.cookies import SimpleCookie, CookieError
import storage

LOCK=threading.RLock()
ACCOUNT=None
SESSIONS={}
ATTEMPTS={}
LIFETIME=8*60*60
COOKIE='frameforge_session'


def secure_cookie():
    value=os.environ.get('FRAMEFORGE_COOKIE_SECURE','false').lower()
    if value not in ('true','false','1','0'): raise ValueError('FRAMEFORGE_COOKIE_SECURE must be true or false')
    return value in ('true','1')


def configure(token=None):
    global ACCOUNT
    saved=storage.get_pref('loginToken',None)
    token=os.environ.get('FRAMEFORGE_AUTH_TOKEN') or token
    secure_cookie()
    if token:
        if not 12<=len(token)<=1024: raise ValueError('Login token must contain 12–1024 characters')
        salt=secrets.token_bytes(32)
        saved=dict(salt=salt.hex(),hash=hashlib.pbkdf2_hmac('sha256',token.encode(),salt,600000).hex(),iterations=600000)
        storage.set_pref('loginToken',saved)
    elif not saved:
        raise ValueError('Set FRAMEFORGE_AUTH_TOKEN (at least 12 characters) before starting FrameForge')
    # Retire the previous username/password configuration after token setup.
    with storage.database() as db: db.execute("DELETE FROM preferences WHERE key='login'")
    with LOCK:
        ACCOUNT=saved;SESSIONS.clear();ATTEMPTS.clear()


def session_id(header):
    try:
        jar=SimpleCookie();jar.load(header or '')
        value=jar.get(COOKIE)
        return value.value if value else ''
    except CookieError: return ''


def authenticated(header):
    with LOCK:
        now=time.monotonic()
        for key,expires in list(SESSIONS.items()):
            if expires<=now: del SESSIONS[key]
        return ACCOUNT is not None and session_id(header) in SESSIONS


def login(token,address,old_cookie=''):
    if not isinstance(token,str) or len(token)>1024:
        return None,False
    now=time.monotonic()
    with LOCK:
        if ACCOUNT is None: return None,False
        for key,(_,until) in list(ATTEMPTS.items()):
            if until<=now: del ATTEMPTS[key]
        count,until=ATTEMPTS.get(address,(0,now+60))
        if count>=5 or (address not in ATTEMPTS and len(ATTEMPTS)>=1024): return None,True
        ATTEMPTS[address]=(count+1,until)
        account=dict(ACCOUNT)
    candidate=hashlib.pbkdf2_hmac('sha256',token.encode(),bytes.fromhex(account['salt']),account['iterations']).hex()
    valid=hmac.compare_digest(candidate,account['hash'])
    if not valid: return None,False
    with LOCK:
        ATTEMPTS.pop(address,None)
        SESSIONS.pop(session_id(old_cookie),None)
        for key,expires in list(SESSIONS.items()):
            if expires<=now: del SESSIONS[key]
        if len(SESSIONS)>=128: del SESSIONS[min(SESSIONS,key=SESSIONS.get)]
        token=secrets.token_urlsafe(32);SESSIONS[token]=now+LIFETIME
    return token,False


def logout(header):
    with LOCK: SESSIONS.pop(session_id(header),None)


def cookie(token=''):
    return f'{COOKIE}={token}; Path=/; HttpOnly; SameSite=Strict; Max-Age={LIFETIME if token else 0}'+('; Secure' if secure_cookie() else '')
