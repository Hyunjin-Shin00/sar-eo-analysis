import warnings; warnings.filterwarnings("ignore")
import os, json, numpy as np, geopandas as gpd
from sklearn.linear_model import LogisticRegression
from sklearn.preprocessing import StandardScaler
from sklearn.pipeline import make_pipeline
from sklearn.model_selection import StratifiedKFold, cross_val_predict
from sklearn.metrics import roc_auc_score
V=os.environ.get("DATA_ROOT","<DATA_ROOT>")+"/Venezuela/analysis_v7/"
J=json.load(open(V+"damage_classifier_v7.json")); f=gpd.read_file(V+"damage_features_v7.gpkg",ignore_geometry=True)
F=J["features"]
# (a) 수작업 161동만으로 5-fold LR
h=f[(f.is_hand_damaged==1)|(f.is_hand_intact==1)].dropna(subset=F); y=(h.is_hand_damaged==1).astype(int).values
aucs=[]
for seed in range(10):
    p=cross_val_predict(make_pipeline(StandardScaler(),LogisticRegression(max_iter=1000)),h[F].values,y,cv=StratifiedKFold(5,shuffle=True,random_state=seed),method="predict_proba")[:,1]; aucs.append(roc_auc_score(y,p))
print("(a) 수작업 라벨 n=%d LR 5-fold AUC %.3f ± %.3f (10회)"%(len(y),np.mean(aucs),np.std(aucs)))
# (b) v7c 방식 근사: pos=hand_damaged, neg=hand_intact(w5)+HCI(w5)+기타 MS==0(w1)
hci=(f.ms_damage_pct_0m==0)&(f.ms_num_observations>=2)&(f.ms_uncertainty==0)
neg=((f.is_hand_intact==1)|(f.ms_damage_pct_0m==0))&(f.is_hand_damaged!=1)
d=f[(f.is_hand_damaged==1)|neg].dropna(subset=F).copy(); y=(d.is_hand_damaged==1).astype(int).values
w=np.where(y==1,1.0,np.where((d.is_hand_intact==1)|hci.loc[d.index],5.0,1.0))
print("(b) 학습셋 n=%d pos %d neg %d (json: 15028/86/14942)"%(len(y),y.sum(),len(y)-y.sum()))
aucs=[]
for seed in range(5):
    ps=np.zeros(len(y))
    for tr,te in StratifiedKFold(5,shuffle=True,random_state=seed).split(d[F],y):
        m=make_pipeline(StandardScaler(),LogisticRegression(max_iter=1000)); m.fit(d[F].values[tr],y[tr],logisticregression__sample_weight=w[tr]); ps[te]=m.predict_proba(d[F].values[te])[:,1]
    aucs.append(roc_auc_score(y,ps))
print("    LR 가중 5-fold AUC %.3f ± %.3f"%(np.mean(aucs),np.std(aucs)))
