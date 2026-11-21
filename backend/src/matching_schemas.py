from pydantic import Field
from .fulfillment_schemas import Inputs
class TargetInput(Inputs):
    customer:str=Field(min_length=2,max_length=100)
    l:float=Field(ge=0,le=100)
    a:float=Field(ge=-128,le=128)
    b:float=Field(ge=-128,le=128)
    note:str=Field(default='',max_length=300)
class MatchRunInput(Inputs):
    target_ids:list[int]|None=None
