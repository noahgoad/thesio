from typing import Any
def issuer_exposure(positions:list[dict[str,Any]])->dict[str,float]:
    totals={}
    for position in positions:
        issuer,weight=position.get("issuer_id"),position.get("weight")
        if not issuer or not isinstance(weight,(int,float)) or weight<0: raise ValueError("POSITION_MAPPING")
        totals[issuer]=totals.get(issuer,0.)+weight
    return totals
def review_positions(positions:list[dict[str,Any]])->dict[str,Any]: return {"exposure":issuer_exposure(positions),"action":"HUMAN_REVIEW_REQUIRED","execution":"NO_LIVE"}
