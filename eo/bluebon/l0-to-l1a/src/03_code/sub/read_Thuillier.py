import re, numpy as np
import platform
def read_Thuillier_F0():
    _dir = r'E:\TPX_2022\02_project\2025\07_블루본\11_L1B_to_L1C\01_code\sub' 
    fname=_dir+"/Thuillier_F0.dat"
    data=[]

    with open(fname, 'rt', encoding='Latin-1') as f:
        res=list(f)
        lines=[_.strip() for _ in res]
        for line in lines:
            if re.match(r'^[/!]', line): continue
            _data = line.split()
            data.append(_data)
    data=np.reshape(data,(-1,2))
    wave=np.array(data[:,0]).astype('float32')
    f0=np.array(data[:,1]).astype('float32')
    return (wave, f0)
