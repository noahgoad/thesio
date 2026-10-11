from typing import Any
def research_basket(scores:dict[str,float],budget:float=.6)->dict[str,float]:
    if not 0<=budget<=1: raise ValueError("BUDGET_RANGE")
    if len(set(scores)) != len(scores): raise ValueError("DUPLICATE_ISSUER")
    positive={issuer:max(0.,float(score)) for issuer,score in scores.items()}
    total=sum(positive.values())
    weights={issuer:min(.25,budget*score/total) for issuer,score in positive.items()} if total else {}
    return {**weights,"CASH":1-sum(weights.values())}
