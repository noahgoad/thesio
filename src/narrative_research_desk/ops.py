from math import isfinite
def health_state(age_seconds:float,stale_after:float,error_count:int,paused:bool)->dict:
    if not isfinite(age_seconds) or age_seconds<0 or stale_after<=0:raise ValueError("INVALID_HEALTH_INPUT")
    blocked=paused or age_seconds>stale_after or error_count>0
    return {"ready":not blocked,"paused":paused,"source_age_seconds":age_seconds,"error_count":error_count,"permission":"NO_LIVE","new_actions_allowed":not blocked}
