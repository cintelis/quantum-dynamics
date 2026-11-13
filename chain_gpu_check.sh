cd /mnt/c/code/nvidia-poc/quantum
OPENBLAS_NUM_THREADS=8 ~/cudaq-env/bin/python -W ignore ibm/chain_gpu.py --check 2>&1 | grep -v "^   9 spins" | tail -n 25
