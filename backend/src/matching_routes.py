from fastapi import APIRouter,Depends
from sqlalchemy import select
from .database import session
from .auth import current,editor,admin
from .matching_models import CustomerTarget,MatchRun,MatchItem
from .matching_schemas import TargetInput,MatchRunInput
from . import matching_service
router=APIRouter()
@router.get('/customer-targets')
def targets(user=Depends(current),db=Depends(session)):return db.scalars(select(CustomerTarget).order_by(CustomerTarget.id)).all()
@router.post('/customer-targets')
def add_target(p:TargetInput,user=Depends(editor),db=Depends(session)):return matching_service.create_target(db,p,user)
@router.get('/match-runs')
def runs(user=Depends(current),db=Depends(session)):
    rows=db.scalars(select(MatchRun).order_by(MatchRun.id.desc())).all()
    items=db.scalars(select(MatchItem).order_by(MatchItem.id)).all()
    by_run={}
    for i in items:by_run.setdefault(i.run_id,[]).append(i)
    return [matching_service.view(db,r,by_run.get(r.id,[])) for r in rows]
@router.post('/match-runs')
def add_run(p:MatchRunInput,user=Depends(editor),db=Depends(session)):return matching_service.view(db,matching_service.create_run(db,p,user))
@router.post('/match-runs/{key}/confirm')
def confirm(key:int,user=Depends(admin),db=Depends(session)):return matching_service.view(db,matching_service.confirm(db,key,user))
@router.post('/match-runs/{key}/rematch')
def rematch(key:int,user=Depends(editor),db=Depends(session)):return matching_service.view(db,matching_service.rematch(db,key,user))
