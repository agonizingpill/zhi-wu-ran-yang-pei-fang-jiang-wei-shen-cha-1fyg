from datetime import date,datetime
from src.fulfillment_models import DyeLot,DyeIssue,ColorDispatch,ShadeComplaint
from src.matching_models import CustomerTarget
import math,random
from sqlalchemy import select,func
from src.database import Base,engine,Session
from src.models import User,DyeRecipe,Swatch,Trial
from src.production_models import RecipeRevision,DyeBatch
from src.auth import hash_password

def seed():
    Base.metadata.create_all(engine)
    with Session() as db:
        for role in ['admin','colorist','viewer']:
            email=f'{role}@qise.test'
            if not db.scalar(select(User).where(User.email==email)):db.add(User(email=email,password=hash_password('Dye2026!'),role=role))
        recipes=[('DY-021','靛蓝亚麻',1.8,.4,.2),('DY-022','苔绿棉麻',.3,1.7,.7),('DY-023','赤陶平纹',.8,.3,1.5)]
        for code,name,a,b,c in recipes:
            if not db.scalar(select(DyeRecipe).where(DyeRecipe.code==code)):db.add(DyeRecipe(code=code,name=name,dye_a=a,dye_b=b,dye_c=c))
        db.flush();rr=db.scalars(select(DyeRecipe).order_by(DyeRecipe.id)).all();rng=random.Random(42)
        for i in range(60):
            lot=['REF-021','SAMPLE-021','SAMPLE-OFF'][i] if i<3 else f'SW-{i:03}'
            if db.scalar(select(Swatch).where(Swatch.lot==lot)):continue
            group=0 if i<3 else i%3
            l,a,b=(48,-2,-25) if i==0 else (48.7,-1.5,-24.5) if i==1 else (62,8,-14) if i==2 else (48+group*9+rng.uniform(-2,2),-2+group*6+rng.uniform(-1,1),-25+group*15+rng.uniform(-1,1))
            spectrum=[round(min(.95,max(.03,.26+group*.11+.1*math.sin(j/5+group)+rng.gauss(0,.012))),5) for j in range(36)]
            db.add(Swatch(recipe_id=rr[group].id,lot=lot,spectrum=spectrum,l=l,a=a,b=b,measured=True))
        prod=db.scalar(select(DyeRecipe).where(DyeRecipe.code=='DY-PROD'))
        if not prod:
            prod=DyeRecipe(code='DY-PROD',name='量产靛蓝基准',dye_a=1.8,dye_b=.4,dye_c=.2,locked=True);db.add(prod);db.flush()
        for lot,l,a,b in [('PROD-REF',48,-2,-25),('PROD-OK',48.5,-1.8,-24.8)]:
            if not db.scalar(select(Swatch).where(Swatch.lot==lot)):db.add(Swatch(recipe_id=prod.id,lot=lot,spectrum=[.3]*36,l=l,a=a,b=b))
        db.flush();ref=db.scalar(select(Swatch).where(Swatch.lot=='PROD-REF'));candidate=db.scalar(select(Swatch).where(Swatch.lot=='PROD-OK'))
        trial=db.scalar(select(Trial).where(Trial.recipe_id==prod.id,Trial.state=='approved'))
        if not trial:
            trial=Trial(recipe_id=prod.id,reference_swatch_id=ref.id,candidate_swatch_id=candidate.id,delta_e=.574456,state='approved',note='量产演示基准');db.add(trial);db.flush()
        if not db.scalar(select(DyeBatch).where(DyeBatch.code=='DB-DEMO-001')):db.add(DyeBatch(code='DB-DEMO-001',approved_trial_id=trial.id,kg=250,target_snapshot={'lot':ref.lot,'recipe_id':prod.id,'l':ref.l,'a':ref.a,'b':ref.b,'trial_delta_e':trial.delta_e}))
        for code,component,kg,expiry,state in [('DYE-A-1117','A',80,date(2027,12,31),'active'),('DYE-B-1117','B',40,date(2027,12,31),'active'),('DYE-C-1117','C',20,date(2027,12,31),'active'),('DYE-C-HOLD','C',5,date(2027,12,31),'quarantine'),('DYE-B-OLD','B',5,date(2026,1,1),'active')]:
            if not db.scalar(select(DyeLot).where(DyeLot.code==code)):db.add(DyeLot(code=code,component=component,available_kg=kg,expires_on=expiry,state=state))
        # V4：历史已签收结论（接受概率训练依据）、已签放未发样候选缸、客户目标色
        targets_map={'禾里服装':(48,-2,-25),'南山家纺':(57,4,-10),'北野户外':(40,-6,-18)}
        hist=[('禾里服装',.4,'accepted'),('南山家纺',.7,'accepted'),('禾里服装',.9,'accepted'),('北野户外',1.1,'accepted'),('南山家纺',1.3,'accepted'),('禾里服装',1.5,'accepted'),
              ('北野户外',1.7,'disputed'),('禾里服装',1.9,'disputed'),('南山家纺',2.2,'disputed'),('禾里服装',2.5,'disputed'),('北野户外',2.8,'disputed'),('南山家纺',3.0,'disputed')]
        recipe_snap={'id':prod.id,'code':prod.code,'name':prod.name,'dye_a':prod.dye_a,'dye_b':prod.dye_b,'dye_c':prod.dye_c}
        for idx,(customer,de,conclusion) in enumerate(hist,1):
            code=f'DB-HIST-{idx:02}'
            if db.scalar(select(DyeBatch).where(DyeBatch.code==code)):continue
            tl,ta,tb=targets_map[customer];lab=(round(tl+.6*de,3),round(ta+.48*de,3),round(tb+.64*de,3))
            batch=DyeBatch(code=code,approved_trial_id=trial.id,kg=180+idx*10,state='released',released_by='admin@qise.test',
                           target_snapshot={'lot':f'{code}-TARGET','recipe_id':prod.id,'l':tl,'a':ta,'b':tb,'trial_delta_e':trial.delta_e,'recipe_snapshot':recipe_snap},
                           lab_l=lab[0],lab_a=lab[1],lab_b=lab[2],delta_e=de)
            db.add(batch);db.flush()
            db.add(ColorDispatch(batch_id=batch.id,tracking=f'QISE-HIST-{idx:02}',customer=customer,state=conclusion,
                                 received_by='林工',received_at=datetime(2026,10,idx,10,30),conclusion_note=('标准光源对色接受' if conclusion=='accepted' else '客户灯箱下色差争议'),
                                 sent_by='colorist@qise.test',
                                 snapshot={'batch_code':code,'batch_kg':batch.kg,'approved_trial_id':trial.id,'lab_l':lab[0],'lab_a':lab[1],'lab_b':lab[2],'delta_e':de,
                                           'target':{'lot':f'{code}-TARGET','recipe_id':prod.id,'l':tl,'a':ta,'b':tb},'recipe':recipe_snap,'released_by':'admin@qise.test'}))
        ready=[('DB-READY-01',(48,-2,-25),(48.3,-1.9,-24.7)),('DB-READY-02',(57,4,-10),(56.8,4.2,-10.3)),
               ('DB-READY-03',(48.5,-1.5,-24.2),(49.2,-1.2,-23.9)),('DB-READY-04',(52,2,-20),(52.5,2.0,-20.0)),
               ('DB-READY-05',(48,-2,-25),(48.4,-1.8,-24.6)),('DB-READY-06',(57,4,-10),(57.4,3.7,-9.7))]
        for idx,(code,(tl,ta,tb),(ll,la,lb)) in enumerate(ready,1):
            if db.scalar(select(DyeBatch).where(DyeBatch.code==code)):continue
            de=round(((ll-tl)**2+(la-ta)**2+(lb-tb)**2)**.5,4)
            db.add(DyeBatch(code=code,approved_trial_id=trial.id,kg=220+idx*20,state='released',released_by='admin@qise.test',
                            target_snapshot={'lot':f'{code}-TARGET','recipe_id':prod.id,'l':tl,'a':ta,'b':tb,'trial_delta_e':trial.delta_e,'recipe_snapshot':recipe_snap},
                            lab_l=ll,lab_a=la,lab_b=lb,delta_e=de))
        for customer,note in [('禾里服装','秋冬亚麻主色'),('南山家纺','床品苔绿季色')]:
            if not db.scalar(select(CustomerTarget).where(CustomerTarget.customer==customer)):
                tl,ta,tb=targets_map[customer];db.add(CustomerTarget(customer=customer,l=tl,a=ta,b=tb,note=note,created_by='colorist@qise.test'))
        db.commit()
        print({name:db.scalar(select(func.count()).select_from(model)) for name,model in [('users',User),('recipes',DyeRecipe),('swatches',Swatch)]})
if __name__=='__main__':seed()
