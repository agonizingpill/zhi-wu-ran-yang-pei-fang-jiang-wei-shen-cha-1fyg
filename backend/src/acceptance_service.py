import numpy as np
# 证据门槛与推荐门限为模拟业务规则，需按真实客户容差校准
MIN_RECORDS=6
MIN_PER_CLASS=2
THRESHOLD=0.6
LAMBDA=1.0

def _fit(x,y,lam=LAMBDA):
    # L2 正则逻辑回归（截距不罚），牛顿法，确定性收敛
    X=np.column_stack([np.ones(len(x)),x]);w=np.zeros(2)
    for _ in range(200):
        z=np.clip(X@w,-500,500);p=1/(1+np.exp(-z))
        g=X.T@(p-y)+lam*np.array([0.0,w[1]])
        H=X.T@(X*(p*(1-p))[:,None])+lam*np.diag([0.0,1.0])
        step=np.linalg.solve(H,g);w=w-step
        if float(np.max(np.abs(step)))<1e-10:break
    return w

def _sigmoid(z):return 1/(1+np.exp(-np.clip(z,-500,500)))

def _metrics(y,p):
    p=np.clip(p,1e-9,1-1e-9)
    return {'logloss':round(float(np.mean(-(y*np.log(p)+(1-y)*np.log(1-p)))),4),
            'brier':round(float(np.mean((p-y)**2)),4),
            'accuracy':round(float(np.mean((p>=0.5)==(y>=0.5))),4)}

def train(records):
    # records: 已签收且有结论的发样单，特征为发样实测与客户目标 ΔE76
    n=len(records)
    y=np.array([1.0 if r['conclusion']=='accepted' else 0.0 for r in records])
    x=np.array([r['delta_e'] for r in records],float)
    accepted=int(y.sum());disputed=n-accepted
    base={'trained_records':n,'accepted':accepted,'disputed':disputed,'threshold':THRESHOLD,'lambda':LAMBDA,
          'sources':[dict(r) for r in records]}
    if n<MIN_RECORDS:
        return {**base,'sufficient':False,'insufficient_reason':f'已签收结论仅{n}条，不足{MIN_RECORDS}条，证据不足不给推荐'}
    if accepted<MIN_PER_CLASS or disputed<MIN_PER_CLASS:
        return {**base,'sufficient':False,'insufficient_reason':f'接受{accepted}条、争议{disputed}条，两类结论均须至少{MIN_PER_CLASS}条，证据不足不给推荐'}
    w=_fit(x,y)
    # 按生产缸分组检验：每张发样单对应唯一生产缸，分组交叉验证即留一缸验证
    preds=np.zeros(n);base_preds=np.zeros(n)
    for i in range(n):
        mask=np.ones(n,bool);mask[i]=False
        preds[i]=_sigmoid(_fit(x[mask],y[mask])@np.array([1.0,x[i]]))
        base_preds[i]=y[mask].mean()
    cv=_metrics(y,preds);baseline=_metrics(y,base_preds)
    if cv['logloss']>=baseline['logloss']:
        return {**base,'sufficient':False,'cv':cv,'baseline':baseline,'cv_note':'按生产缸分组留一交叉验证；基准为各折训练集接受率',
                'insufficient_reason':f"按生产缸分组检验 logloss {cv['logloss']} 未优于基准 {baseline['logloss']}，证据不足不给推荐"}
    return {**base,'sufficient':True,'insufficient_reason':'','coefficients':[round(float(w[0]),6),round(float(w[1]),6)],
            'cv':cv,'baseline':baseline,'cv_note':'按生产缸分组留一交叉验证；基准为各折训练集接受率'}

def predict(model,delta_e):
    w0,w1=model['coefficients']
    return float(_sigmoid(w0+w1*delta_e))
