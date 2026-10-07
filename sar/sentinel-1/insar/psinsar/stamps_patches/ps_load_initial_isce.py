import numpy as np
import os.path
from math import pi
import datetime
from scipy.interpolate import griddata
from psi_python.logit import logit 
from psi_python.stamps_save import stamps_save
from psi_python.setparm import setparm 
from psi_python.llh2local import llh2local
from psi_python.load_isce import load_isce


def ps_load_initial_isce(data_inc=None):
    print("Loading data into python...")
    
    phname = "pscands.1.ph"
    ijname = "pscands.1.ij"
    bperpname = "bperp.1.in"
    dayname = "day.1.in"
    masterdayname = "reference_day.1.in"
    llname = "pscands.1.ll"
    daname = "pscands.1.da"
    hgtname = "pscands.1.hgt"
    laname = "look_angle.1.in"
    headingname = "heading.1.in"
    lambdaname = "lambda.1.in"
    calname = "calamp.out"
    widthname = "width.txt"
    lenname = "len.txt"
    
    psver = 1
    incname = "inc_angle.raw"
    incsavename = "inc" + str(psver)
    lasavename = "la" + str(psver)
    
    if not os.path.exists(dayname):
        dayname = os.path.join("..", dayname)
    day = np.loadtxt(dayname, dtype=int)
    year = day // 10000
    month = (day - year * 10000) // 100
    monthday = day - year * 10000 - month * 100
    slave_day = np.array([np.datetime64(f"{y}-{m:02d}-{d:02d}") for y, m, d in zip(year, month, monthday)])
    sorted_indices = np.argsort(slave_day)
    day_ix = sorted_indices
    slave_day = np.sort(slave_day)
    
    if not os.path.exists(masterdayname):
        masterdayname = os.path.join("..", masterdayname)
    master_day = np.loadtxt(masterdayname, dtype=int)
    master_day_yyyymmdd = master_day
    year = master_day // 10000
    month = (master_day - year * 10000) // 100
    monthday = master_day - year * 10000 - month * 100
    master_day = np.datetime64(f"{year}-{month:02d}-{monthday:02d}")
    
    master_ix = np.sum(slave_day < master_day)
    print('master_ix', master_ix)
    day = np.concatenate((slave_day[:master_ix], [master_day], slave_day[master_ix:]))
    if not os.path.exists(bperpname):
        bperpname = os.path.join("..", bperpname)
    bperp = np.loadtxt(bperpname)
    bperp = bperp[sorted_indices]
    bperp = np.insert(bperp, master_ix, 0)
    n_ifg = bperp.size
    n_image = n_ifg
    
    if not os.path.exists(headingname):
        headingname = os.path.join("..", headingname)
    heading = np.loadtxt(headingname)
    if heading.size == 0:
        raise ValueError("heading.1.in is empty")
    setparm('heading', heading, 1)
    
    if not os.path.exists(lambdaname):
        lambdaname = os.path.join("..", lambdaname)
    lambda_ = np.loadtxt(lambdaname)
    setparm('lambda', lambda_, 1)
    
    # Radar coordinates
    ij = np.loadtxt(ijname, dtype=int)
    n_ps = ij.shape[0]
    
    if not os.path.exists(calname):
        calname = os.path.join("..", calname)
    
    if os.path.exists(calname):
        with open(calname) as f:
            calfile_calconst = [tuple(line.strip().split()) for line in f]
        calfile, calconst = zip(*calfile_calconst)
        calconst = np.array(calconst, dtype=float)
        caldate = []
        for fname in calfile:
            parts = fname.split("/")
            try:
                date_part = parts[-2][-8:]
                try: 
                    date_part = int(date_part)
                except:
                    date_part = int(parts[-3][-8:])
            except ValueError:
                if parts[-2].lower() == "reference":
                    date_part = int(parts[-3][-8:])
    
            caldate.append(date_part)
        caldate = np.array(caldate, dtype=int)
        not_master_ix = caldate != master_day_yyyymmdd
        caldate = caldate[not_master_ix]
        calconst = calconst[not_master_ix]
        sorted_indices = np.argsort(caldate)
        calconst = calconst[sorted_indices]
    else:
        calconst = np.ones(n_ifg - 1)
    with open(phname, "rb") as f:
        ph = np.zeros((n_ps, n_ifg - 1), dtype=np.complex64)
        for i in range(n_ifg - 1):
            ph_bit = np.fromfile(f, dtype=np.float32, count=n_ps * 2)
            ph[:, i] = ph_bit[::2] + 1j * ph_bit[1::2]
    
    ph = ph[:, sorted_indices]
    zero_ph = np.sum(ph == 0, axis=1)
    nonzero_ix = zero_ph <= 1
    ph = ph / calconst
    ph = np.hstack((ph[:, :master_ix], np.ones((n_ps, 1)), ph[:, master_ix:]))
    
    
    # Load lonlat
    with open(llname, 'rb') as fid:
        lonlat = np.fromfile(fid, dtype=np.float32).reshape(-1, 2)
    
    # Calculate ll0 (average of min and max for each coordinate)
    ll0 = (lonlat.max(axis=0) + lonlat.min(axis=0)) / 2
    
    # Convert lonlat to local coordinates (in meters)
    xy = llh2local(lonlat, ll0) * 1000
    xy = xy
    sort_x = xy[np.argsort(xy[:, 0])]
    sort_y = xy[np.argsort(xy[:, 1])]
    n_pc = round(n_ps * 0.001)
    bl = np.mean(sort_x[:n_pc], axis=0)  # bottom left corner
    tr = np.mean(sort_x[-n_pc:], axis=0)  # top right corner
    br = np.mean(sort_y[:n_pc], axis=0)  # bottom right corner
    tl = np.mean(sort_y[-n_pc:], axis=0)  # top left corner
    
    # Calculate rotation angle
    theta = (180 - heading) * np.pi / 180
    if theta > np.pi:
        theta -= 2 * np.pi
    
    # Rotation matrix
    rotm = np.array([[np.cos(theta), np.sin(theta)], [-np.sin(theta), np.cos(theta)]])
    xy = xy.T
    
    # Apply rotation
    xynew = rotm @ xy  # rotate so that scene axes approx align with x=0 and y=0
    if (np.max(xynew[0, :]) - np.min(xynew[0, :]) < np.max(xy[0, :]) - np.min(xy[0, :])) and \
       (np.max(xynew[1, :]) - np.min(xynew[1, :]) < np.max(xy[1, :]) - np.min(xy[1, :])):
        xy = xynew  # check that rotation is an improvement
        print(f'Rotating by {theta * 180 / np.pi} degrees')
    xy = xy.T.astype(np.float32)
    sort_ix = np.argsort(xy[:, 1], kind='stable')
    xy = xy[sort_ix, :]
    xy = np.hstack((np.arange(1, n_ps + 1).reshape(-1, 1), xy))
    xy[:, 1:3] = np.round(xy[:, 1:3] * 1000) / 1000  # round to mm
    
    
    ph = ph[sort_ix]
    ij = ij[sort_ix]
    ij[:, 0] = np.arange(1, n_ps + 1)
    lonlat = lonlat[sort_ix]
    
    savename = f'ps{psver}'
    stamps_save(savename, ij=ij, lonlat=lonlat, xy=xy, bperp=bperp, 
                day=day, master_day=master_day, master_ix=master_ix, 
                n_ifg=n_ifg, n_image=n_image, n_ps=n_ps,
                sort_ix=sort_ix, ll0=ll0, calconst=calconst,
                day_ix=day_ix)

    # using an appropriate Python function or library.
    phsavename = f'ph{psver}'

    stamps_save(phsavename, ph=ph)

    if os.path.exists(daname):
        D_A = np.loadtxt(daname)[sort_ix]
        dasavename = f'da{psver}'

        stamps_save(dasavename, D_A=D_A);


    if os.path.exists(hgtname):
        with open(hgtname, 'rb') as fid:
            hgt = np.fromfile(fid, dtype=np.float32)
            hgt = hgt[sort_ix]
        hgtsavename = f'hgt{psver}'
        stamps_save(hgtsavename, hgt=hgt)

    if not os.path.exists(widthname):
        widthname = os.path.join('..', widthname)
    width = np.loadtxt(widthname)

    if not os.path.exists(lenname):
        lenname = os.path.join('..', lenname)
    length = np.loadtxt(lenname)

    # Try to see if inc angle exists, fallback to look angle if needed
    if data_inc is None:
        if not os.path.exists(incname):
            incname = os.path.join('.', incname)
            if not os.path.exists(incname):
                incname = os.path.join('..', incname)
    
        if os.path.exists(incname):
            data_inc = load_isce(incname)
            data_inc = data_inc[:,:,0].T
            data_inc = data_inc.astype(np.float32)
    
    # Check if inc angle exists; if not, try look angle
    if data_inc is not None:
        IND = np.ravel_multi_index((ij[:, 2].astype(int), ij[:, 1].astype(int)), data_inc.shape)
        inc = data_inc.flat[IND]
        inc = inc * np.pi / 180
        stamps_save(incsavename, inc=inc)
    else:
        # trying look angle instead
        if not os.path.exists(laname):
            laname = f'../{laname}'
            if not os.path.exists(laname):
                laname = f'../{laname}'

        if os.path.exists(laname):
            data_la = load_isce(laname)
            inds_array = [ij[:, 1], ij[:,2]]

            la = data_la[tuple(inds_array)]
            la = la * pi / 180
            stamps_save(lasavename, la=la)

    updir = 0
    bperpdir = [f for f in os.listdir('..') if f.startswith('baselineGRID_')]

    if not bperpdir:
        bperpdir = [f for f in os.listdir(os.path.join('..', '..')) if f.startswith('baselineGRID_')]
        updir = 1

    if len(bperpdir) > 0:
        bperp_mat = np.zeros((n_ps, n_image - 1), dtype=np.float32)
        counter = 1

        for i in np.setdiff1d(np.arange(0, n_image), master_ix):
            bperp_fname = os.path.join('..', f'baselineGRID_{day[i].item().strftime("%Y%m%d")}')
            if updir == 1:
                bperp_fname = os.path.join('..', bperp_fname)
            
            bperp_grid = load_isce(bperp_fname)
            # The following part of the code assumes 'bperp_grid' is already calculated from the previous step
            if bperp_grid.shape == (length, width):
                inds_array = [ij[:, 1], ij[:,2]]
                bp0_ps = bperp_grid[tuple(inds_array)]
                
                if counter == 1:
                    pass
            else:
                if counter == 1:
                    gridX, gridY = np.meshgrid(np.linspace(0, width, bperp_grid.shape[0]),
                                                np.linspace(0, length, bperp_grid.shape[1]))
                
                bp0_ps = griddata((gridX.ravel(), gridY.ravel()), bperp_grid.T.ravel(),
                                (ij[:, 2], ij[:, 1]), method='nearest')
            
            bperp_mat[:, counter - 1] = bp0_ps
            counter += 1
    else:
        # FIX: np.r_[0:master_ix, master_ix:] - the second slice has no stop, so
        # numpy repeats 0:master_ix and the matrix comes out 2*master_ix wide
        # (70 instead of n_image-1=72 here) and still contains the master. Drop
        # the master column explicitly.
        bperp_mat = np.tile(np.delete(np.asarray(bperp), master_ix).astype(np.float32), (n_ps, 1))
    
    bpsavename= f'bp{psver}'
    stamps_save(bpsavename, bperp_mat=bperp_mat)

