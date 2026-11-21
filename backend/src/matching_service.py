from datetime import datetime
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from fastapi import HTTPException
from .fulfillment_models import ColorDispatch
from .production_models import DyeBatch
from .matching_models import CustomerTarget,MatchRun,MatchItem
from .matching_schemas import MatchRunInput
from .acceptance_service import train,predict,THRESHOLD
from .recipe_service import log
from .stock_service import recipe_snapshot

FORBIDDEN=-1e9

def create_target(db,p,user):
    if db.scalar(select(CustomerTarget).where(CustomerTarget.customer==p.customer)):raise HTTPException(409,'该客户已录入目标色，可直接发起匹配')
    item=CustomerTarget(**p.model_dump(),created_by=user.email)
    db.add(item);log(db,user,f'录入客户目标色 {p.customer} L{p.l}/a{p.a}/b{p.b}');db.commit();return item

def _training_records(db):
    # 只读取已签收且有结论的发样单，历史结论不改写
    rows=db.scalars(select(ColorDispatch).where(ColorDispatch.state.in_(['accepted','disputed'])).order_by(ColorDispatch.id)).all()
    records=[]
    for d in rows:
        t=d.snapshot['target']
        de=round(sum((d.snapshot['lab_'+k]-t[k])**2 for k in ['l','a','b'])**.5,6)
        records.append({'dispatch_id':d.id,'tracking':d.tracking,'customer':d.customer,'batch_code':d.snapshot['batch_code'],'delta_e':de,'conclusion':d.state})
    return records

def _eligible_batches(db):
    dispatched=set(db.scalars(select(ColorDispatch.batch_id)).all())
    return [b for b in db.scalars(select(DyeBatch).where(DyeBatch.state=='released').order_by(DyeBatch.id)) if b.id not in dispatched]

def _assign(profit):
    # 匈牙利算法求全局最大概率和分派；FORBIDDEN 表示概率低于门限不可配
    n=len(profit);m=len(profit[0]) if n else 0
    if not n or not m:return {}
    N=max(n,m);cost=[[0.0]*(N+1) for _ in range(N+1)]
    for i in range(1,N+1):
        for j in range(1,N+1):
            cost[i][j]=-profit[i-1][j-1] if i<=n and j<=m else 0.0
    u=[0.0]*(N+1);v=[0.0]*(N+1);p=[0]*(N+1);way=[0]*(N+1)
    for i in range(1,N+1):
        p[0]=i;j0=0;minv=[float('inf')]*(N+1);used=[False]*(N+1)
        while True:
            used[j0]=True;i0=p[j0];delta=float('inf');j1=0
            for j in range(1,N+1):
                if used[j]:continue
                cur=cost[i0][j]-u[i0]-v[j]
                if cur<minv[j]:minv[j]=cur;way[j]=j0
                if minv[j]<delta:delta=minv[j];j1=j
            for j in range(N+1):
                if used[j]:u[p[j]]+=delta;v[j]-=delta
                else:minv[j]-=delta
            j0=j1
            if p[j0]==0:break
        while j0:p[j0]=p[way[j0]];j0=way[j0]
    return {p[j]-1:j-1 for j in range(1,N+1) if p[j] and p[j]<=n and j<=m}

def create_run(db,p,user):
    q=select(CustomerTarget).order_by(CustomerTarget.id)
    if p and p.target_ids:q=select(CustomerTarget).where(CustomerTarget.id.in_(p.target_ids)).order_by(CustomerTarget.id)
    targets=db.scalars(q).all()
    if not targets:raise HTTPException(409,'请先录入客户目标色再发起匹配')
    model=train(_training_records(db))
    batches=_eligible_batches(db)
    run=MatchRun(state='open' if model['sufficient'] else 'insufficient',model_snapshot=model,created_by=user.email)
    db.add(run);db.flush()
    matrix=[[(sum((getattr(b,'lab_'+k)-getattr(t,k))**2 for k in ['l','a','b'])**.5,None) for b in batches] for t in targets]
    if model['sufficient']:
        matrix=[[(de,predict(model,de)) for de,_ in row] for row in matrix]
        profit=[[pr if pr>=THRESHOLD else FORBIDDEN for _,pr in row] for row in matrix]
        assignment={i:j for i,j in _assign(profit).items() if profit[i][j]>=THRESHOLD}
    else:assignment={}
    owners={j:targets[i].customer for i,j in assignment.items()}
    for i,t in enumerate(targets):
        chosen=assignment.get(i);candidates=[]
        for j,b in enumerate(batches):
            de,pr=matrix[i][j]
            if pr is None:continue
            if j==chosen:reason=''
            elif pr<THRESHOLD:reason=f'接受概率{pr:.2f}低于门限{THRESHOLD:.2f}，证据不足'
            elif j in owners:reason=f'联合匹配中该缸分派给客户{owners[j]}，全局总概率更高'
            else:reason=f'本客户改配缸{batches[chosen].code}，全局总概率更高'
            candidates.append({'batch_id':b.id,'batch_code':b.code,'delta_e':round(de,4),'probability':round(pr,4),'chosen':j==chosen,'reason':reason})
        if chosen is not None:
            item=MatchItem(run_id=run.id,target_id=t.id,customer=t.customer,target_snapshot={'l':t.l,'a':t.a,'b':t.b},
                           batch_id=batches[chosen].id,probability=round(matrix[i][chosen][1],4),reason='',candidates=candidates)
        else:
            if not model['sufficient']:reason='训练证据不足：'+model['insufficient_reason']
            elif not batches:reason='当前无已签放未发样缸可参与匹配'
            elif not any(pr is not None and pr>=THRESHOLD for _,pr in matrix[i]):reason=f'候选缸接受概率均低于门限{THRESHOLD:.2f}，证据不足不给推荐'
            else:reason='联合匹配后候选缸已分派其他客户，本客户无可分缸'
            item=MatchItem(run_id=run.id,target_id=t.id,customer=t.customer,target_snapshot={'l':t.l,'a':t.a,'b':t.b},
                           batch_id=None,probability=None,reason=reason,candidates=candidates)
        db.add(item)
    log(db,user,f'发起匹配方案{run.id} 客户{len(targets)}家 候选缸{len(batches)}口 状态{run.state}')
    db.commit();return run

def get_run(db,key,lock=True):
    q=select(MatchRun).where(MatchRun.id==key)
    run=db.scalar(q.with_for_update() if lock else q)
    if not run:raise HTTPException(404,'匹配方案不存在')
    return run

def confirm(db,key,user):
    run=get_run(db,key)
    if run.state=='confirmed':return run
    if run.state!='open':raise HTTPException(409,f'方案状态为{run.state}，不能确认发样')
    items=db.scalars(select(MatchItem).where(MatchItem.run_id==run.id,MatchItem.batch_id.isnot(None)).order_by(MatchItem.id)).all()
    if not items:raise HTTPException(409,'方案没有可发样的匹配结果')
    # 单事务内按缸号顺序加锁复核；任一缸已被别处发走则整单拒绝，不落任何发样单
    batch_ids=sorted({i.batch_id for i in items})
    batches={b.id:b for b in db.scalars(select(DyeBatch).where(DyeBatch.id.in_(batch_ids)).order_by(DyeBatch.id).with_for_update())}
    taken=db.scalars(select(ColorDispatch).where(ColorDispatch.batch_id.in_(batch_ids))).all()
    stale=[b for b in batches.values() if b.state!='released']
    if taken or stale:
        codes='、'.join(sorted({t.snapshot['batch_code'] for t in taken}|{b.code for b in stale}))
        run.state='rejected';run.reject_reason=f'缸{codes}已被别处发走或状态变更，整单拒绝'
        log(db,user,f'匹配方案{run.id}确认失败：{run.reject_reason}');db.commit()
        raise HTTPException(409,run.reject_reason+'；可重算剩余缸重新匹配')
    for item in items:
        batch=batches[item.batch_id]
        customer_de=round(sum((getattr(batch,'lab_'+k)-item.target_snapshot[k])**2 for k in ['l','a','b'])**.5,4)
        dispatch=ColorDispatch(batch_id=batch.id,tracking=f'QISE-MATCH-{run.id}-{item.id}',customer=item.customer,
            snapshot={'batch_code':batch.code,'batch_kg':batch.kg,'approved_trial_id':batch.approved_trial_id,
                      'lab_l':batch.lab_l,'lab_a':batch.lab_a,'lab_b':batch.lab_b,'delta_e':batch.delta_e,
                      'target':{'l':item.target_snapshot['l'],'a':item.target_snapshot['a'],'b':item.target_snapshot['b'],'lot':f'客户{item.customer}目标色'},
                      'customer_delta_e':customer_de,'production_target':dict(batch.target_snapshot),
                      'recipe':recipe_snapshot(db,batch),'released_by':batch.released_by,
                      'match_run_id':run.id,'match_probability':item.probability},
            sent_by=user.email)
        db.add(dispatch);db.flush();item.dispatch_id=dispatch.id
    run.state='confirmed';run.confirmed_by=user.email;run.confirmed_at=datetime.utcnow()
    log(db,user,f'主管确认匹配方案{run.id}，生成{len(items)}张真实发样单')
    try:
        db.commit()
    except IntegrityError:
        # 并发确认的另一方案已抢先发缸（缸号/运单唯一约束兜底）：本单整单拒绝
        db.rollback();run=get_run(db,key)
        run.state='rejected';run.reject_reason='并发确认冲突：相关缸已被别处发走，整单拒绝'
        log(db,user,f'匹配方案{run.id}确认失败：{run.reject_reason}');db.commit()
        raise HTTPException(409,run.reject_reason+'；可重算剩余缸重新匹配')
    return run

def rematch(db,key,user):
    run=get_run(db,key,lock=False)
    ids=[i.target_id for i in db.scalars(select(MatchItem).where(MatchItem.run_id==run.id).order_by(MatchItem.id))]
    return create_run(db,MatchRunInput(target_ids=ids),user)

def view(db,run,items=None):
    if items is None:items=db.scalars(select(MatchItem).where(MatchItem.run_id==run.id).order_by(MatchItem.id)).all()
    return {'id':run.id,'state':run.state,'model_snapshot':run.model_snapshot,'reject_reason':run.reject_reason,
            'created_by':run.created_by,'created_at':run.created_at,'confirmed_by':run.confirmed_by,'confirmed_at':run.confirmed_at,
            'items':[{'id':i.id,'target_id':i.target_id,'customer':i.customer,'target_snapshot':i.target_snapshot,
                      'batch_id':i.batch_id,'probability':i.probability,'reason':i.reason,'candidates':i.candidates,
                      'dispatch_id':i.dispatch_id} for i in items]}
