from datetime import datetime
from sqlalchemy import String,Float,ForeignKey,JSON,DateTime,CheckConstraint,UniqueConstraint,func
from sqlalchemy.orm import Mapped,mapped_column
from .database import Base
class CustomerTarget(Base):
    __tablename__='customer_targets'
    __table_args__=(CheckConstraint('l>=0 AND l<=100'),)
    id:Mapped[int]=mapped_column(primary_key=True)
    customer:Mapped[str]=mapped_column(String(100),unique=True)
    l:Mapped[float]=mapped_column(Float)
    a:Mapped[float]=mapped_column(Float)
    b:Mapped[float]=mapped_column(Float)
    note:Mapped[str]=mapped_column(String(300),default='')
    created_by:Mapped[str]=mapped_column(String(120))
    created_at:Mapped[object]=mapped_column(DateTime,server_default=func.now())
class MatchRun(Base):
    __tablename__='match_runs'
    id:Mapped[int]=mapped_column(primary_key=True)
    state:Mapped[str]=mapped_column(String(24),default='open')
    model_snapshot:Mapped[dict]=mapped_column(JSON,default=dict)
    reject_reason:Mapped[str]=mapped_column(String(300),default='')
    created_by:Mapped[str]=mapped_column(String(120))
    created_at:Mapped[object]=mapped_column(DateTime,server_default=func.now())
    confirmed_by:Mapped[str]=mapped_column(String(120),default='')
    confirmed_at:Mapped[datetime|None]=mapped_column(DateTime,nullable=True)
class MatchItem(Base):
    __tablename__='match_items'
    __table_args__=(UniqueConstraint('run_id','target_id'),UniqueConstraint('run_id','batch_id'))
    id:Mapped[int]=mapped_column(primary_key=True)
    run_id:Mapped[int]=mapped_column(ForeignKey('match_runs.id'))
    target_id:Mapped[int]=mapped_column(ForeignKey('customer_targets.id'))
    customer:Mapped[str]=mapped_column(String(100))
    target_snapshot:Mapped[dict]=mapped_column(JSON)
    batch_id:Mapped[int|None]=mapped_column(ForeignKey('dye_batches.id'),nullable=True)
    probability:Mapped[float|None]=mapped_column(Float,nullable=True)
    reason:Mapped[str]=mapped_column(String(300),default='')
    candidates:Mapped[list]=mapped_column(JSON,default=list)
    dispatch_id:Mapped[int|None]=mapped_column(ForeignKey('color_dispatches.id'),nullable=True)
