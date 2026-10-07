# KuroSiwo AOI08(actid 567) 타일별 Edge-Otsu 수체마스크 vs MLU 라벨 재계산
import rasterio, numpy as np, glob, json, os, sys
R=os.environ.get('DATA_ROOT', '<DATA_ROOT>')
tiles=sorted(os.listdir(f'{R}/Kurosiwo/08'))
def m(p):
    with rasterio.open(p) as s: return s.read(1)
def sc(tp,fp,fn):
    p=tp/(tp+fp) if tp+fp else np.nan; r=tp/(tp+fn) if tp+fn else np.nan
    f=2*tp/(2*tp+fp+fn) if (2*tp+fp+fn) else np.nan; iou=tp/(tp+fp+fn) if (tp+fp+fn) else np.nan
    return dict(P=p,R=r,F1=f,IoU=iou)
out={}
chk=[]
for pol in ['VV','VH']:
    agg={k:np.zeros(3) for k in ['water_post','flood_change','water_pre_perm']}
    per=[]
    for t in tiles:
        d=f'{R}/Kurosiwo/08/{t}'; info=json.load(open(f'{d}/info.json'))
        mlu=glob.glob(f'{d}/MK0_MLU_*.tif')[0]; lab=m(mlu); valid=lab!=3
        w=f'{R}/flood_mapping_kuro_all_{pol}/{t}'
        ms=glob.glob(f'{w}/MS1_I{pol}_*_watermask.tif'); sl=glob.glob(f'{w}/SL2_I{pol}_*_watermask.tif')
        if not ms or not sl: continue
        post=m(ms[0])==1; pre=m(sl[0])==1
        if pol=='VV': chk.append((info['pwater'],info['pflood'],100*(lab==1).mean(),100*(lab==2).mean()))
        gt_w=(lab==1)|(lab==2); gt_f=lab==2
        gain=post&~pre
        for k,(pr,gt) in {'water_post':(post,gt_w),'flood_change':(gain,gt_f),'water_pre_perm':(pre,lab==1)}.items():
            tp=(pr&gt&valid).sum(); fp=(pr&~gt&valid).sum(); fn=(~pr&gt&valid).sum()
            agg[k]+=[tp,fp,fn]
        tp=(post&gt_w&valid).sum(); fp=(post&~gt_w&valid).sum(); fn=(~post&gt_w&valid).sum()
        per.append(sc(tp,fp,fn)['F1'])
    out[pol]={k:{**sc(*v),'tp_fp_fn':v.tolist()} for k,v in agg.items()}
    per=np.array(per,float); out[pol]['n_tiles']=len(per); out[pol]['tileF1_water_post_median']=float(np.nanmedian(per))
    out[pol]['tileF1_lt0.5']=int((per<0.5).sum())
chk=np.array(chk); print('label mapping check (pwater,pflood vs %lab1,%lab2) max abs diff:', np.abs(chk[:,0]-chk[:,2]).max(), np.abs(chk[:,1]-chk[:,3]).max())
print(json.dumps(out,indent=1,default=float))
