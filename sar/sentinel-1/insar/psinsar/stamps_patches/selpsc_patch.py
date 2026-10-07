import struct
import sys 
import os
import math
import numpy as np 

def cshortswap(f):
    b = bytearray(struct.pack("h", f.real) + struct.pack("h", f.imag))
    f.real, f.imag = struct.unpack("<h", b[2:4])[0], struct.unpack("<h", b[0:2])[0]

def shortswap(f):
    b = bytearray(struct.pack("h", f))
    f = struct.unpack("<h", b)[0]

def cfloatswap(f):
    b = bytearray(struct.pack("f", f.real) + struct.pack("f", f.imag))
    b2 = bytearray(struct.pack("<4B", *b[3::-1], *b[7:3:-1]))
    f.real, f.imag = struct.unpack("<f", b2[0:4])[0], struct.unpack("<f", b2[4:8])[0]

def floatswap(f):
    b = bytearray(struct.pack("f", f))
    b2 = bytearray(struct.pack("<4B", *b[3::-1]))
    f = struct.unpack("<f", b2)[0]

def longswap(f):
    b = bytearray(struct.pack("i", f))
    f = struct.unpack("<i", b[::-1])[0]

def main(argv):
    if len(argv) < 3:
        print("Usage: selpsc parmfile patch.in pscands.1.ij pscands.1.da mean_amp.flt precision byteswap maskfile")
        print("\ninput parameters:")
        print("  parmfile (input) amplitude dispersion threshold")
        print("                   width of amplitude files (range bins)")
        print("                   SLC file names & calibration constants")
        print("  patch.in (input) location of patch in rg and az")
        print("  pscands.1.ij   (output) PS candidate locations")
        print("  pscands.1.da   (output) PS candidate amplitude dispersion\n")
        print("  mean_amp.flt (output) mean amplitude of image\n")
        print("  precision(input) s or f (default)")
        print("  byteswap   (input) 1 for to swap bytes, 0 otherwise (default)")
        print("  maskfile   (input)  mask rows and columns (optional)")
        print("  master amplitude (input) in case files in parmfile are ifgs not SLCs (optional)")
        sys.exit()

    ijname = "pscands.1.ij" if len(argv) < 4 else argv[3]

    jiname = ijname + ".int"

    ijname0 = ijname + "0"
    print("file name for zero amplitude PS:", ijname0)

    daoutname = "pscands.1.da" if len(argv) < 5 else argv[4]

    meanoutname = "mean_amp.flt" if len(argv) < 6 else argv[5]

    prec = "f" if len(argv) < 7 else argv[6]

    byteswap = 0 if len(argv) < 8 else int(argv[7])

    maskfilename = "" if len(argv) < 9 else argv[8]

    masterampfilename = "0000"
    masteramp_exists = False
    if len(argv) < 10:
        pass
    else:
        try:
            with open(argv[9], 'r') as masterparmfile:
                masterampfilename = masterparmfile.readline().strip()
        except FileNotFoundError:
            print(f"Error opening file {argv[9]}")
            sys.exit()
    try:
        with open(masterampfilename, 'r') as masterampfile:
            masteramp_exists = True
            print(f"opening {masterampfilename}...")
    except FileNotFoundError:
        pass

    try:
        # with open(argv[1], 'r') as parmfile:
        parmfile = open(argv[1], 'r')
        line = parmfile.readline().strip()
        num_files = 0

        width = 0
        D_thresh = 0
        pick_higher = 0

        D_thresh = float(line)
        print(f"dispersion threshold = {D_thresh}")
        D_thresh_sq = D_thresh * D_thresh
        if D_thresh < 0:
            pick_higher = 1
        width = int(parmfile.readline().strip())
        print(f"width = {width}")
        savepos = parmfile.tell()
        line = parmfile.readline().strip()
        while line:
            line = parmfile.readline().strip()
            num_files += 1

        parmfile.seek(savepos)
        print(f'number of file {num_files}')
    except FileNotFoundError:
        print(f"Error opening file {argv[1]}")
        sys.exit()

    ampfilenames = []
    calib_factors = []

    for i in range(num_files):
        line = parmfile.readline().strip()
        ampfilename, calib_factor = line.split()
        calib_factors.append(float(calib_factor))
        ampfilenames.append(ampfilename)

        print(f"opening {ampfilename}...{calib_factor}")

        try:
            with open(ampfilename, 'rb') as ampfile:
                header = ampfile.read(32)
                magic = 0x59A66A95
                if int.from_bytes(header[:8], 'little') == magic:
                    print("sun raster file - skipping header")
                else:
                    ampfile.seek(0)
        except FileNotFoundError:
            print(f"Error opening file {ampfilename}")
            sys.exit()

    print(f"number of amplitude files = {num_files}")
    parmfile.close()

    try:
        with open(argv[2], 'r') as patchfile:
            pass
    except FileNotFoundError:
        print(f"Error opening file {argv[2]}")
        sys.exit()  

    rg_start = 0
    rg_end = sys.maxsize
    az_start = 0
    az_end = sys.maxsize

    with open(argv[2], 'r') as patchfile:
        rg_start = int(patchfile.readline().strip())
        rg_end = int(patchfile.readline().strip())
        az_start = int(patchfile.readline().strip())
        az_end = int(patchfile.readline().strip())

    patch_lines = az_end - az_start + 1
    patch_width = rg_end - rg_start + 1

    sizeoffloat = 4
    sizeofelement = 2 if prec[0] == 's' else 4

    linebytes = width * sizeofelement * 2
    patch_linebytes = patch_width * sizeofelement * 2
    patch_amp_linebytes = patch_width * sizeofelement

    with open(ampfilenames[0], 'rb') as ampfile:
        size = os.path.getsize(ampfilenames[0])
        numlines = size // (width * sizeofelement * 2)

    print(f"number of lines per file = {numlines}")

    print(f"patch lines = {patch_lines}")
    print(f"patch width = {patch_width}")

    mask_exists = False
    try:
        with open(maskfilename, 'r') as maskfile:
            mask_exists = True
            print(f"opening {maskfilename}...")
    except FileNotFoundError:
        pass

    if os.path.isfile(meanoutname):
        os.remove(meanoutname)
    ijfile = open(ijname, 'w') 
    jifile = open(jiname, 'wb')  
    ijfile0 = open(ijname0, 'w')
    daoutfile = open(daoutname, 'w')
    meanoutfile = open(meanoutname, 'wb')

    buffer = bytearray(num_files * patch_linebytes)
    bufferf = np.frombuffer(buffer, dtype=np.complex64)
    buffers = np.frombuffer(buffer, dtype=np.complex64)

    maskline = bytearray(patch_width)
    for x in range(patch_width):
        maskline[x] = 0

    masterampline = bytearray(patch_linebytes)
    masterlinef = np.frombuffer(masterampline, dtype=np.complex64)
    masterlines = np.frombuffer(masterampline, dtype=np.complex64)
    for x in range(patch_width):
        if prec[0] == 's':
            masterlines[x] = 1
            if byteswap == 1:
                masterlines[x] = masterlines[x].newbyteorder()
        else:
            masterlinef[x] = 1
            if byteswap == 1:
                masterlinef[x] = masterlinef[x].newbyteorder()

    y = 0
    pscid = 0

    pix_start = (az_start - 1) * width + (rg_start - 1)
    pos_start = pix_start * sizeofelement * 2

    # FIX: the upstream port read the mask only for the patch's first azimuth
    # line and never advanced it, so any patch whose first line fell entirely
    # outside the mask yielded zero candidates. Keep the handle open and read
    # the correct row inside the line loop instead.
    maskfh = open(maskfilename, 'rb') if mask_exists == 1 else None

    # if masteramp_exists == 1:
    #     masterampfile = open(masterampfilename, 'rb') 
    #     masterampfile.seek(pos_start)
    #     masterampfile.readinto(masterampline)


    # for i in range(num_files):

    #     with open(ampfilenames[i], 'rb') as file:
    #         file.seek(pos_start)
    #         file.readinto(memoryview(buffer)[i * patch_linebytes: (i + 1) * patch_linebytes])

    # while not all(file.closed for file in ampfilenames) and y < patch_lines:
    # FIX(perf): upstream re-opened all 32 SLCs for every azimuth line
    # (3570 lines x 32 files of open/close per patch). Keep them open.
    ampfh = [open(fn, 'rb') for fn in ampfilenames]

    slcset = np.zeros([num_files, patch_width], dtype='complex')
    ampset = np.zeros([num_files, patch_width], dtype='float')
    while y < patch_lines:
        if y >= 0:
            for i in range(num_files):
                file = ampfh[i]
                # FIX: pos_start is already a byte offset (pix_start*sizeofelement*2);
                # the upstream port multiplied by sizeofelement again, seeking 4x too
                # far. Patches past ~1/4 of the file then read past EOF -> 0 candidates.
                file.seek(pos_start + y*linebytes)
                if prec[0] == 'f':
                    testline = np.fromfile(file, count=patch_width*2, dtype='float32')
                else:
                    testline = np.fromfile(file, count=patch_width*2, dtype='float16')

                if testline.size < patch_width*2:      # 파일 끝을 넘으면 0 으로 채움
                    testline = np.concatenate([testline,
                                np.zeros(patch_width*2 - testline.size, dtype=testline.dtype)])
                slcset[i, :] = testline[0::2] + 1j * testline[1::2]
                ampset[i, :] = np.abs(slcset[i,:])/calib_factors[i]
            if maskfh is not None:
                maskfh.seek(((az_start - 1) + y) * width + (rg_start - 1))
                nread = maskfh.readinto(maskline)
                if nread is None:
                    nread = 0
                for _x in range(nread, patch_width):   # 파일 끝을 넘으면 제외 처리
                    maskline[_x] = 1

            zeroset = np.zeros([num_files, patch_width])
            zeroset[ampset<=0.00005] = 1
            zerosumset = np.sum(zeroset, axis=0)
            ampset[ampset<=0.00005] = np.nan
            sumamp = np.nansum(ampset, axis=0)
            sumampsq = np.nansum(ampset**2, axis=0)
            # print(np.shape(sumampsq), 'sumampsq')
            # print(np.shape(sumamp), 'sumamp')
            sumamp.tofile(meanoutfile)
            # print(type(sumamp))
            # print(type(maskline))
            # print(np.shape(maskline))
            # print(sumamp[0])
            # print(maskline[0])
            for x in range(patch_width):
                # sumamp = 0
                # sumampsq = 0
                # amp_0 = 0

                if maskline[x] == 0 and sumamp[x] > 0:
                    D_sq = num_files * sumampsq[x] / (sumamp[x] * sumamp[x]) - 1  # var/mean^2
                    if (pick_higher == 0 and D_sq < D_thresh_sq) or (pick_higher == 1 and D_sq >= D_thresh_sq):
                        if zerosumset[x] != 1:
                            pscid += 1

                            ijfile.write(f"{pscid} {(az_start - 1) + y} {(rg_start - 1) + x}\n")
                            J = (rg_start - 1) + x
                            I = (az_start - 1) + y
                            J = struct.unpack('>i', struct.pack('<i', J))[0]
                            I = struct.unpack('>i', struct.pack('<i', I))[0]
                            jifile.write(struct.pack('>i', J))
                            jifile.write(struct.pack('>i', I))

                            D_a = math.sqrt(D_sq)
                            daoutfile.write(f"{D_a}\n")
                        else:  # Keeping track of PS with zero amplitude values
                            ijfile0.write(f"{pscid} {(az_start - 1) + y} {(rg_start - 1) + x}\n")




                # if prec[0] == 's':
                #     master_amp = masterlines[x]
                # else:
                #     master_amp = masterlinef[x]


                # if abs(master_amp) == 0:
                #     master_amp = 1

                # for i in range(num_files):  # for each amp file
                #     if prec[0] == 's':
                #         camp = buffers[i * patch_width + x]
                #     else:
                #         camp = bufferf[i * patch_width + x]  # get amp value

                    
                    # amp = abs(camp) / calib_factor[i] / abs(master_amp)  # get amp value

                    # if amp <= 0.00005:  # do not use amp = 0 values for calculating the AD and set flag to 1
                    #     amp_0 = 1
                    #     sumamp = 0
                    #     continue
                    # else:
                    #     sumamp += amp
                    #     sumampsq += amp * amp
            
                
                # meanoutfile.write(struct.pack('f', sumamp))
                # if maskline[x] == 0 and sumamp > 0:
                #     D_sq = num_files * sumampsq / (sumamp * sumamp) - 1  # var/mean^2
                #     if (pick_higher == 0 and D_sq < D_thresh_sq) or (pick_higher == 1 and D_sq >= D_thresh_sq):
                #         if amp_0 != 1:
                #             pscid += 1

                #             ijfile.write(f"{pscid} {(az_start - 1) + y} {(rg_start - 1) + x}\n")
                #             J = (rg_start - 1) + x
                #             I = (az_start - 1) + y
                #             J = struct.unpack('>i', struct.pack('<i', J))[0]
                #             I = struct.unpack('>i', struct.pack('<i', I))[0]
                #             jifile.write(struct.pack('>i', J))
                #             jifile.write(struct.pack('>i', I))

                #             D_a = math.sqrt(D_sq)
                #             daoutfile.write(f"{D_a}\n")
                #         else:  # Keeping track of PS with zero amplitude values
                #             ijfile0.write(f"{pscid} {(az_start - 1) + y} {(rg_start - 1) + x}\n")

        y += 1

        # for i in range(num_files):  # read in next line from each amp file
        #     ampfile[i].seek(linebytes - patch_linebytes, 1)
        #     buffer[i * patch_linebytes:i * patch_linebytes + patch_linebytes] = ampfile[i].read(patch_linebytes)

        # if mask_exists == 1:
        #     maskfile.seek(width - patch_width, 1)
        #     maskline = maskfile.read(patch_width)

        # if masteramp_exists == 1:
        #     masterampfile.seek(linebytes - patch_linebytes, 1)
        #     masterampline = masterampfile.read(patch_linebytes)

        if y / 100.0 == round(y / 100.0):
            print(f"{y} lines processed")
    ijfile.close()
    jifile.close()
    ijfile0.close()
    daoutfile.close()
    meanoutfile.close()

    for _fh in ampfh:
        _fh.close()

    if maskfh is not None:
        maskfh.close()

    if masteramp_exists == 1:
        masterampfile.close()

    try:
        # The rest of your code goes here
        pass
    except Exception as e:
        print(e)
        sys.exit(999)

if __name__ == "__main__":
    main(sys.argv)
