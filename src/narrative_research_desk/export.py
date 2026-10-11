import json
from hashlib import sha256
_MODES={"FIXTURE","USER_SUPPLIED","PUBLIC_READ","HISTORICAL_BACKTEST","HISTORICAL_REPLAY","FORWARD_PAPER","USER_TEST"}
def export_report(project_id:str,result:dict,source_hashes:list[str], *, format:str='json')->dict:
    if not source_hashes or any(not isinstance(item,str) or len(item)!=64 for item in source_hashes): raise ValueError("EXPORT_WITHOUT_PROVENANCE")
    if result.get("mode") not in _MODES: raise ValueError("EXPORT_MODE_REQUIRED")
    if format not in {'json', 'md'}: raise ValueError('EXPORT_FORMAT_INVALID')
    report={"schema_version":"1.0","project_id":project_id,"result":result,"source_hashes":sorted(set(source_hashes))}
    if format == 'md':
        # A dynamic fence prevents supplied text or notes escaping the retained JSON section.
        body=json.dumps(report,sort_keys=True,ensure_ascii=False,allow_nan=False,indent=2)
        import re
        fence='`' * max(3, 1+max((len(m.group()) for m in re.finditer(r'`+', body)),default=0))
        content=('# Research brief\n\nResearch only. Mode and verification limits are retained below.\n\n'+fence+'json\n'+body+'\n'+fence+'\n').encode()
    else:
        content=json.dumps(report,sort_keys=True,ensure_ascii=False,allow_nan=False,separators=(",",":")).encode()
    return {"content":content,"sha256":sha256(content).hexdigest(),"mime":"text/markdown" if format == 'md' else "application/json"}
