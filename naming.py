"""Conservative local movie/episode recognition; no online title lookup."""
import re
from pathlib import Path

TECH=re.compile(r'(?i)(?<!\w)(?:\d{3,4}p|\d{3,4}i|WEB[ ._-]*(?:DL|Rip)|Blu[ ._-]*Ray|BDRip|BRRip|HDTV|DVDRip|REMUX|x26[45]|h[ ._-]?26[45]|HEVC|AV1|AAC|AC3|EAC3|DDP?\d|DTS|TRUEHD|\d{1,2}bit)(?![a-z])')

def words(text):
    text=re.sub(r'\(\s*\)|\[\s*\]','',text.replace('.',' ').replace('_',' '))
    text=re.sub(r'\s+',' ',text).strip(' -').lstrip(']) ').rstrip('([ ')
    while text.endswith(')') and text.count(')')>text.count('('):text=text[:-1].rstrip()
    while text.endswith(']') and text.count(']')>text.count('['):text=text[:-1].rstrip()
    return text

def safe(text):
    result=re.sub(r'[<>:"/\\|?*\x00-\x1f]','',text).strip(' .') or 'Untitled'
    if result.split('.')[0].upper() in {'CON','PRN','AUX','NUL',*[f'COM{i}' for i in range(1,10)],*[f'LPT{i}' for i in range(1,10)]}:result+='_' 
    return result

def validate(o):
    if o.get('contentType','auto') not in ('auto','movie','tv'):raise ValueError('Invalid content type')
    if o.get('tvPattern','standard') not in ('standard','compact','x'):raise ValueError('Invalid TV naming pattern')
    if o.get('tvFolders','none') not in ('none','series','season'):raise ValueError('Invalid TV folder setting')
    for key in ('tvKeepTitle','tvKeepYear'):
        if type(o.get(key,True)) is not bool:raise ValueError('Invalid TV naming checkbox')

def detect(path,o=None):
    o=o or {};path=Path(path);stem=path.stem
    result=dict(kind='unknown',series='',year='',season=None,episodes=[],date='',episodeTitle='',note='No reliable episode marker or movie year found; movie-style cleanup is used. Review the preview.')
    if o.get('contentType')=='movie':result.update(kind='movie',note='Movie naming selected manually.');return result
    marker=re.search(r'(?i)(?<![a-z0-9])s(?P<s>\d{1,3})[ ._-]*e(?P<e>\d{1,3})(?P<more>(?:[ ._-]*e\d{1,3}|-\d{1,3})*)(?!\d)',stem)
    if not marker:marker=re.search(r'(?i)(?<![a-z0-9])(?P<s>\d{1,2})x(?P<e>\d{2,3})(?P<more>(?:[ ._-]*x\d{2,3}|-\d{2,3})*)(?!\d)',stem)
    date=None
    if not marker:date=re.search(r'(?<!\d)((?:19|20)\d{2})[ ._-](0[1-9]|1[0-2])[ ._-](0[1-9]|[12]\d|3[01])(?!\d)',stem)
    prefix='';tail=''
    if marker:
        prefix=stem[:marker.start()];tail=stem[marker.end():]
        result.update(season=int(marker['s']),episodes=[int(marker['e']),*map(int,re.findall(r'\d+',marker['more']))])
    elif date:
        from datetime import date as calendar_date
        try:calendar_date(*map(int,date.groups()))
        except ValueError:date=None
        if date:
            prefix=stem[:date.start()];tail=stem[date.end():];result['date']='-'.join(date.groups())
    else:
        parent_season=re.fullmatch(r'(?i)season[ ._-]*(\d{1,3})',path.parent.name)
        episode=re.match(r'(?i)(?:episode[ ._-]*)?(\d{1,3})(?:[ ._-]+)(.+)',stem)
        if parent_season and episode:
            prefix=path.parent.parent.name;tail=episode[2];result.update(season=int(parent_season[1]),episodes=[int(episode[1])]);marker=True
    if marker or date:
        if not words(prefix):
            if re.fullmatch(r'(?i)season[ ._-]*\d+',path.parent.name):prefix=path.parent.parent.name
        year=re.search(r'(?<!\d)((?:19|20)\d{2})(?!\d)',prefix)
        if year and words(prefix[:year.start()]+prefix[year.end():]) and not words(prefix[year.end():]):result['year']=year[1];prefix=prefix[:year.start()]+prefix[year.end():]
        result['series']=words(prefix)
        technical=TECH.search(tail)
        result['episodeTitle']=words(tail[:technical.start()] if technical else tail)
        if result['series']:
            result.update(kind='tv',note='TV episode detected from filename/date or Season-folder context. No online title lookup was used.')
    if result['kind']!='tv' and re.search(r'(?<!\d)(?:18|19|20)\d{2}(?!\d)',stem):result.update(kind='movie',note='Movie-like name detected from a year without a recognized episode marker.')
    if o.get('contentType')=='tv' and result['kind']!='tv':result.update(kind='tv',note='TV selected manually, but series/episode could not be identified.')
    return result

def series_name(info,o):return safe(info['series']+(' ('+info['year']+')' if info['year'] and o.get('tvKeepYear',True) else ''))
def tv_stem(info,o):
    if not info['series'] or not (info['episodes'] or info['date']):raise ValueError('Cannot name this TV episode. Use S01E02, 1x02, an air date, or numbered files in a Season folder; otherwise choose Movie or turn cleanup off.')
    if info['date']:tag=info['date']
    elif o.get('tvPattern')=='x':tag=str(info['season'])+'x'+f"{info['episodes'][0]:02d}"+''.join(f'-{n:02d}' for n in info['episodes'][1:])
    else:tag=f"S{info['season']:02d}E{info['episodes'][0]:02d}"+''.join(f'-E{n:02d}' for n in info['episodes'][1:])
    compact=o.get('tvPattern','standard')=='compact';name=series_name(info,o)+(' ' if compact else ' - ')+tag
    if not compact and o.get('tvKeepTitle',True) and info['episodeTitle']:name+=' - '+info['episodeTitle']
    return safe(name)

def folders(info,o):
    mode=o.get('tvFolders','none')
    if mode=='none':return []
    tv_stem(info,o)
    return [series_name(info,o)]+([f"Season {info['season']:02d}" if info['season'] is not None else 'Season '+info['date'][:4]] if mode=='season' else [])
