"""Local SQLite settings and SMTP notification history. No extra packages."""
import json, os, sqlite3, ssl, smtplib, threading, uuid
from contextlib import contextmanager
from email.message import EmailMessage
from email.utils import parseaddr
from pathlib import Path

SECRET=''

def data_path(): return Path(os.environ.get('FRAMEFORGE_DATA',str(Path.home()/'.frameforge'))).expanduser()

@contextmanager
def database():
    path=data_path();path.mkdir(parents=True,exist_ok=True)
    db=sqlite3.connect(path/'settings.sqlite3',timeout=10)
    try:
        db.executescript('''CREATE TABLE IF NOT EXISTS presets(name TEXT PRIMARY KEY, data TEXT NOT NULL, updated TEXT DEFAULT CURRENT_TIMESTAMP);
        CREATE TABLE IF NOT EXISTS preferences(key TEXT PRIMARY KEY, data TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS notifications(id TEXT PRIMARY KEY, event TEXT, subject TEXT, status TEXT, error TEXT, created TEXT DEFAULT CURRENT_TIMESTAMP);''')
        yield db;db.commit()
    finally: db.close()

def get_pref(key,default=None):
    with database() as db:
        row=db.execute('SELECT data FROM preferences WHERE key=?',(key,)).fetchone()
    return json.loads(row[0]) if row else default

def set_pref(key,value):
    with database() as db: db.execute('INSERT OR REPLACE INTO preferences VALUES (?,?)',(key,json.dumps(value)))

def presets():
    with database() as db: rows=db.execute('SELECT name,data,updated FROM presets ORDER BY name COLLATE NOCASE').fetchall()
    return {'presets':[dict(name=r[0],settings=json.loads(r[1]),updated=r[2]) for r in rows],'lastPreset':get_pref('lastPreset','')}

def save_preset(name,settings):
    if not isinstance(name,str) or not name.strip() or len(name)>80 or any(ord(c)<32 for c in name): raise ValueError('Preset name must be 1–80 characters')
    if not isinstance(settings,dict) or len(json.dumps(settings))>256000: raise ValueError('Preset settings are too large')
    name=name.strip()
    with database() as db: db.execute('INSERT OR REPLACE INTO presets(name,data,updated) VALUES (?,?,CURRENT_TIMESTAMP)',(name,json.dumps(settings)))
    set_pref('lastPreset',name)

def delete_preset(name):
    with database() as db: db.execute('DELETE FROM presets WHERE name=?',(name,))
    if get_pref('lastPreset','')==name: set_pref('lastPreset','')

def mail_settings():
    defaults=dict(enabled=False,onFailure=True,onFinished=True,host='',port=587,tls='starttls',username='',sender='',recipients='')
    defaults.update(get_pref('smtp',{}))
    fields={'enabled':'ENABLED','onFailure':'ON_FAILURE','onFinished':'ON_FINISHED',
            'host':'HOST','port':'PORT','tls':'TLS','username':'USERNAME',
            'sender':'SENDER','recipients':'RECIPIENTS'}
    for field,suffix in fields.items():
        name='FRAMEFORGE_SMTP_'+suffix
        value=os.environ.get(name,'').strip()
        if not value: continue
        if field in ('enabled','onFailure','onFinished'):
            if value.lower() not in ('true','false','1','0','yes','no','on','off'):
                raise ValueError(name+' must be true or false')
            value=value.lower() in ('true','1','yes','on')
        elif field=='port':
            try: value=int(value)
            except ValueError: raise ValueError(name+' must be a port number') from None
            if not 1<=value<=65535: raise ValueError(name+' must be between 1 and 65535')
        elif field=='tls':
            value=value.lower()
            if value not in ('starttls','ssl','none'): raise ValueError(name+' must be starttls, ssl, or none')
        defaults[field]=value
    return defaults

def validate_mail(d,require=False):
    if not isinstance(d,dict): raise ValueError('Invalid SMTP settings')
    out={key:d.get(key,value) for key,value in mail_settings().items()}
    for key in ('enabled','onFailure','onFinished'):
        if type(out[key]) is not bool: raise ValueError('Invalid email toggle')
    for key in ('host','username','sender','recipients'):
        if not isinstance(out[key],str) or len(out[key])>1000 or any(ord(c)<32 for c in out[key]): raise ValueError('Invalid SMTP text field')
        out[key]=out[key].strip()
    try: out['port']=int(out['port'])
    except (TypeError,ValueError): raise ValueError('Invalid SMTP port')
    if not 1<=out['port']<=65535 or out['tls'] not in ('starttls','ssl','none'): raise ValueError('Invalid SMTP port/security')
    if out['enabled'] or require:
        recipients=[x.strip() for x in out['recipients'].split(',') if x.strip()]
        for address in [out['sender'],*recipients]:
            if parseaddr(address)[1]!=address or '@' not in address: raise ValueError('Use plain email addresses, separated by commas for multiple recipients')
        if not out['host'] or not recipients: raise ValueError('SMTP server, sender and recipient are required')
        if out['username'] and out['tls']=='none': raise ValueError('Use STARTTLS or TLS for SMTP authentication')
    return out

def public_mail():
    d=mail_settings();d['hasPassword']=bool(os.environ.get('FRAMEFORGE_SMTP_PASSWORD') or SECRET)
    with database() as db: rows=db.execute('SELECT id,event,subject,status,error,created FROM notifications ORDER BY rowid DESC LIMIT 20').fetchall()
    return {'settings':d,'history':[dict(zip(('id','event','subject','status','error','created'),r)) for r in rows]}

def save_mail(d,password=None):
    global SECRET
    settings=validate_mail(d)
    if password is not None:
        if not isinstance(password,str) or len(password)>2000: raise ValueError('Invalid SMTP password')
        SECRET=password
    set_pref('smtp',settings)

def deliver(config,password,subject,body):
    message=EmailMessage();message['Subject']=subject;message['From']=config['sender'];message['To']=config['recipients'];message.set_content(body)
    context=ssl.create_default_context()
    transport=smtplib.SMTP_SSL if config['tls']=='ssl' else smtplib.SMTP
    kwargs={'context':context} if config['tls']=='ssl' else {}
    with transport(config['host'],config['port'],timeout=20,**kwargs) as smtp:
        smtp.ehlo()
        if config['tls']=='starttls': smtp.starttls(context=context);smtp.ehlo()
        if config['username']: smtp.login(config['username'],password)
        refused=smtp.send_message(message,to_addrs=[x.strip() for x in config['recipients'].split(',') if x.strip()])
        if refused: raise RuntimeError('SMTP refused one or more recipients: '+', '.join(refused))

def notify(event,subject,body,key=None,force=False):
    config=mail_settings()
    if not force and (not config['enabled'] or (event=='failure' and not config['onFailure']) or (event=='finished' and not config['onFinished'])): return None
    config=validate_mail(config,True); ident=key or uuid.uuid4().hex
    with database() as db:
        if db.execute('INSERT OR IGNORE INTO notifications(id,event,subject,status,error) VALUES (?,?,?,?,?)',(ident,event,subject,'sending','')).rowcount==0: return ident
    password=os.environ.get('FRAMEFORGE_SMTP_PASSWORD') or SECRET
    def send():
        try: deliver(config,password,subject,body);status,error='sent',''
        except Exception as e: status,error='failed',str(e).replace(password,'[redacted]') if password else str(e)
        try:
            with database() as db: db.execute('UPDATE notifications SET status=?,error=? WHERE id=?',(status,error[:1000],ident))
        except Exception: pass
    threading.Thread(target=send,daemon=True).start();return ident


def recover_notifications():
    with database() as db: db.execute("UPDATE notifications SET status='failed',error='Email delivery was interrupted by a server restart; delivery is unconfirmed.' WHERE status='sending'")
