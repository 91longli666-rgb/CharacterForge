"""Local, bounded SVG avatar. Public example and private presentation stay apart."""
from pathlib import Path
import os
import re,xml.etree.ElementTree as ET

PROJECT=Path(os.environ.get('CF_PROJECT_ROOT',r'D:\Projects\CharacterForge')).resolve()
PUBLIC=PROJECT/'characters/original_demo/avatar.svg'
TAGS={'svg','g','path','circle','ellipse','rect','line','polygon','polyline'}
ATTRS={'viewBox','id','class','d','transform','cx','cy','r','rx','ry','x','y','width','height','x1','x2','y1','y2','points','fill','stroke','stroke-width','stroke-linecap','stroke-linejoin','opacity','role','aria-label'}
def safe_svg(path):
    raw=Path(path).read_bytes()
    if len(raw)>40000 or b'<!' in raw:raise ValueError('Avatar must be a small plain SVG')
    root=ET.fromstring(raw)
    if root.tag.split('}')[-1]!='svg' or len(list(root.iter()))>180:raise ValueError('Invalid avatar')
    for node in root.iter():
        if node.tag.split('}')[-1] not in TAGS:raise ValueError('Unsupported avatar element')
        for key,value in node.attrib.items():
            if key not in ATTRS or len(value)>4000 or re.search(r'url\s*\(|javascript:|https?:|data:',value,re.I):raise ValueError('Unsupported avatar attribute')
    return raw
def selected(card_path):
    local=Path(card_path).parent/'avatar.svg'
    if local.is_file():
        try:return safe_svg(local),'local'
        except (ValueError,OSError,ET.ParseError):pass
    return safe_svg(PUBLIC),'original_example'
