#!/bin/bash

# 切换目录并安装依赖
cd /workspace/sample-ddp-training/
pip install -r requirements.txt -i https://pypi.tuna.tsinghua.edu.cn/simple

# 直接使用节点预定义环境变量
echo "ECS_NUM_NODES: $ECS_NUM_NODES"
echo "ECS_MASTER_ADDR: $ECS_MASTER_ADDR"
echo "ECS_MASTER_PORT: $ECS_MASTER_PORT"

export NCCL_DEBUG=INFO

torchrun \
    --nproc-per-node=1 \
    --nnodes=${ECS_NUM_NODES} \
    --rdzv-backend=c10d \
    --rdzv-endpoint=${ECS_MASTER_ADDR}:${ECS_MASTER_PORT} \
    /workspace/sample-ddp-training/train_err.py
