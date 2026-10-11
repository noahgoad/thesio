from urllib.parse import urlsplit
def validate_source_url(url:str,allowed_hosts:set[str])->str:
    parsed=urlsplit(url)
    if parsed.scheme!="https" or parsed.username or parsed.password: raise ValueError("URL_NOT_ALLOWED")
    if parsed.port not in {None,443} or parsed.hostname not in allowed_hosts: raise ValueError("HOST_NOT_ALLOWED")
    if parsed.fragment: raise ValueError("URL_FRAGMENT_NOT_ALLOWED")
    return url
