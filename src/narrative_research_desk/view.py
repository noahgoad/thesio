from html import escape
def render_status(status:str,mode:str,source:str,counterevidence_status:str|None=None)->str:
    allowed={"EMPTY","LOADING","PARTIAL","STALE","REJECTED","INSUFFICIENT","COMPLETE","ERROR"}
    if status not in allowed: raise ValueError("STATUS_UNKNOWN")
    label="No research yet" if status=="EMPTY" else status
    counterevidence = ""
    if counterevidence_status is not None:
        if counterevidence_status not in {"FOUND", "NOT_FOUND", "NOT_SEARCHED", "CONFLICT"}:
            raise ValueError("COUNTEREVIDENCE_STATUS_UNKNOWN")
        counterevidence = '<p data-testid="counterevidence">Counterevidence: '+escape(counterevidence_status)+'</p>'
    return '<section aria-label="Results"><p role="status" data-testid="status">'+escape(label)+'</p><p data-testid="mode">'+escape(mode)+'</p><p data-testid="source">'+escape(source)+'</p>'+counterevidence+'</section>'
