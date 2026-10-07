#by YP
#2025.07.13
# copied: rayleigh_viirs.py
import numpy as np 

def read_LUT_Ray():
    LUTdir = "./../LUT/"
    fname="LUT_Ray"
    fname = LUTdir+fname
    print("raylLUt data from "+fname)

    with open(fname+".readme", 'rt') as f:
        line = f.readline()

        waves = (np.array(line.split('=')[1].split())).astype(np.float64)

        line = f.readline()
        phigrid = (np.array(line.split('=')[1].split())).astype(np.float64)
         #phigrid = float( strsplit( (strsplit(str,'=',/extract))[1], /extract) )

        line = f.readline()
        musgrid = (np.array(line.split('=')[1].split())).astype(np.float64)

        line = f.readline()
        mu0grid = (np.array(line.split('=')[1].split())).astype(np.float64)

        line = f.readline()
        dims = (np.array(line.split('=')[1].split())).astype(np.int32)

    data = np.fromfile(fname, dtype=np.float64)
    LUTray = np.reshape(data, dims)
    return (LUTray, mu0grid, musgrid, phigrid, waves)

#;compute NN grids and ..
def get_nn_r (th0arr, tharr, phiarr):
    mu0arr = np.cos(th0arr*np.pi/180.)
    musarr = np.cos(tharr*np.pi/180.)

    nnsol = (np.floor( (mu0arr-0.1)/0.1)).astype('int32')
    ind = (nnsol >= 9)
    if np.count_nonzero(ind) > 0: nnsol[ind]=8
    rsol = (mu0arr-0.1-nnsol*0.1)/0.1
    nnsen = np.floor( (musarr-0.1)/0.1 ).astype('int32')
    ind=(nnsen >= 9)
    if np.count_nonzero(ind) > 0 : nnsen[ind]=8
    rsen = (musarr-0.1-nnsen*0.1)/0.1
    ind = (phiarr > 180.)
    if np.count_nonzero(ind) > 0: phiarr[ind]=360-phiarr[ind]
    nnphi = np.floor( phiarr/10.).astype('int32')
    ind = (nnphi == 18)
    if np.count_nonzero(ind) > 0 : nnphi[ind]=17
    rphi = (phiarr-nnphi*10)/10.

    return (nnsol, rsol, nnsen, rsen, nnphi, rphi)


def get_rayleigh_1D( th0arr, tharr, phiarr):# if th0arr is 1D

    dims = np.shape(th0arr)
    (nnsol, rsol, nnsen, rsen, nnphi, rphi)=get_nn_r (th0arr, tharr, phiarr)
    LUTray, mu0grid, musgrid, phigrid, wave = read_LUT_Ray()
    ss = np.shape(LUTray)
    nwave = ss[-1]
    rayleigh = np.zeros((nwave, dims[0]), dtype=np.float32)

    for ibd in range(nwave):
        _LUT = np.reshape(LUTray[:,:,:,ibd],ss[2]*ss[1]*ss[0])
        index = nnphi + nnsen*ss[2] + nnsol*ss[2]*ss[1]
        _rayleigh = (1.-rphi)*(1.-rsen)*(1.-rsol)*_LUT[index ]
        index = nnphi+1 + nnsen*ss[2] + nnsol*ss[2]*ss[1]
        _rayleigh +=  rphi *(1.-rsen)*(1.-rsol)*_LUT[index]
        index = nnphi + (nnsen+1)*ss[2] + nnsol*ss[2]*ss[1]
        _rayleigh +=  (1.-rphi)*    rsen *(1.-rsol)*_LUT[index]
        index = nnphi+1 + (nnsen+1)*ss[2] + nnsol*ss[2]*ss[1]
        _rayleigh +=  rphi *    rsen *(1.-rsol)*_LUT[index ]
        index = nnphi + nnsen*ss[2] + (nnsol+1)*ss[2]*ss[1]
        _rayleigh += (1.-rphi)*(1.-rsen)*    rsol *_LUT[index]
        index = nnphi+1 + nnsen*ss[2] + (nnsol+1)*ss[2]*ss[1]
        _rayleigh += rphi *(1.-rsen)*    rsol *_LUT[index]
        index = nnphi + (nnsen+1)*ss[2] + (nnsol+1)*ss[2]*ss[1]
        _rayleigh +=  (1.-rphi)*    rsen*     rsol *_LUT[index]
        index = nnphi+1 + (nnsen+1)*ss[2] + (nnsol+1)*ss[2]*ss[1]
        _rayleigh +=  rphi *    rsen*     rsol *_LUT[index]
        rayleigh[ibd,:]=_rayleigh

    return rayleigh
