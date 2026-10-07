#!/bin/bash
# Environment for the StaMPS-Python (isce2psi) pipeline.
source "$(conda info --base)/etc/profile.d/conda.sh"
conda activate isce2_snaphu
export STAMPS_PYTHON=<WORK_ROOT>/StaMPS_Python
export ISCE2PSI=<DATA_ROOT>/CSK_PSInSAR/code/isce2psi_fixed
export PSI_PYTHON=$STAMPS_PYTHON/timeseries_S1/python/psi_python
export PATH=<DATA_ROOT>/CSK_PSInSAR/code/bin:$ISCE2PSI:$PSI_PYTHON:$PATH
export PYTHONPATH=<DATA_ROOT>/CSK_PSInSAR/code/psipkg:$STAMPS_PYTHON/timeseries_S1/python:${PYTHONPATH:-}
export PSI_MAX_WORKERS=${PSI_MAX_WORKERS:-8}
export OMP_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1 MKL_NUM_THREADS=1
