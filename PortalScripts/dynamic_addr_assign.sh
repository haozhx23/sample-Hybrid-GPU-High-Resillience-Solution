#!/bin/sh
set -e

# 默认值
DEFAULT_HOST_PATH="/fsx/shared"
DEFAULT_NUM_NODES=2
DEFAULT_MAX_WAIT_TIME=300

# 设置初始值
HOST_PATH=${DEFAULT_HOST_PATH}
NUM_NODES=${DEFAULT_NUM_NODES}
MAX_WAIT_TIME=${DEFAULT_MAX_WAIT_TIME}

# 显示帮助信息
show_help() {
    echo "用法: $0 [选项]"
    echo "选项:"
    echo "  -h, --help                 显示此帮助信息"
    echo "  -p, --host-path PATH       设置共享存储路径 (默认: ${DEFAULT_HOST_PATH})"
    echo "  -n, --num-nodes NUMBER     设置节点总数 (默认: ${DEFAULT_NUM_NODES})"
    echo "  -w, --wait-time SECONDS    设置最大等待时间(秒) (默认: ${DEFAULT_MAX_WAIT_TIME})"
    echo "  -d, --debug                启用调试模式"
}

# 解析参数 - 修复的部分，使用 POSIX 兼容语法
while [ $# -gt 0 ]; do
    key="$1"
    case $key in
        -h|--help)
            show_help
            exit 0
            ;;
        -p|--host-path)
            HOST_PATH="$2"
            shift 2
            ;;
        -n|--num-nodes)
            NUM_NODES="$2"
            shift 2
            ;;
        -w|--wait-time)
            MAX_WAIT_TIME="$2"
            shift 2
            ;;
        -d|--debug)
            DEBUG_HOLD=true
            shift
            ;;
        *)
            echo "未知选项: $1"
            show_help
            exit 1
            ;;
    esac
done

# 检查必要参数
if [ -z "${HOST_PATH}" ]; then
    echo "错误: 必须提供共享存储路径!"
    show_help
    exit 1
fi

# 修复数值检查，使用 POSIX 兼容语法
echo "${NUM_NODES}" | grep -q '^[0-9]\+$'
if [ $? -ne 0 ] || [ "${NUM_NODES}" -lt 1 ]; then
    echo "错误: 节点数必须是正整数!"
    show_help
    exit 1
fi

echo "${MAX_WAIT_TIME}" | grep -q '^[0-9]\+$'
if [ $? -ne 0 ] || [ "${MAX_WAIT_TIME}" -lt 1 ]; then
    echo "错误: 等待时间必须是正整数!"
    show_help
    exit 1
fi

# 使用参数
echo "配置参数:"
echo "- 共享存储路径: ${HOST_PATH}"
echo "- 节点总数: ${NUM_NODES}"
echo "- 最大等待时间: ${MAX_WAIT_TIME}秒"
echo "- 调试模式: ${DEBUG_HOLD:-false}"

# 其余脚本不变
# ASSIGNED_NODES_DIR="${HOST_PATH}/assigned_nodes_$(date +%H_%S)"
# ASSIGNED_NODES_DIR="${HOST_PATH}assigned_nodes"
ASSIGNED_NODES_DIR="${HOST_PATH}"
NODE_IP=$(hostname -i 2>/dev/null || ip route get 1 | awk '{print $NF;exit}')

# # 如果路径已经存在，则将该路径改名为: 原路径_0
# if [ -d "${ASSIGNED_NODES_DIR}" ]; then
#     mv "${ASSIGNED_NODES_DIR}" "${ASSIGNED_NODES_DIR}_$(date +%H_%S)"
#     echo "已存在的目录 ${ASSIGNED_NODES_DIR} 已重命名为 ${ASSIGNED_NODES_DIR}_$(date +%H_%S)"
# fi

# 创建协调目录
mkdir -p ${ASSIGNED_NODES_DIR}
echo "节点 ${NODE_IP} 启动，共享目录: ${ASSIGNED_NODES_DIR}"

# 注册当前节点
# echo "$(date +"%Y-%m-%d %H:%M:%S")" > "${ASSIGNED_NODES_DIR}/${NODE_IP}.ip"
echo "${NODE_IP}" > "${ASSIGNED_NODES_DIR}/${NODE_IP}.ip"
echo "已注册节点 IP: ${NODE_IP}"

# 等待所有节点注册
echo "等待所有 ${NUM_NODES} 个节点注册..."
start_time=$(date +%s)
while true; do
    current_time=$(date +%s)
    elapsed=$((current_time - start_time))
    
    # 检查是否超时
    if [ ${elapsed} -gt ${MAX_WAIT_TIME} ]; then
        echo "等待超时！当前只有 $(ls ${ASSIGNED_NODES_DIR}/*.ip 2>/dev/null | wc -l) 个节点注册"
        registered_nodes=$(ls -la ${ASSIGNED_NODES_DIR}/*.ip 2>/dev/null || echo "无节点")
        echo "已注册节点: ${registered_nodes}"
        exit 1
    fi
    
    # 计算当前注册节点数
    node_count=$(ls ${ASSIGNED_NODES_DIR}/*.ip 2>/dev/null | wc -l)
    echo "[${elapsed}s] 等待中... 当前已有 ${node_count}/${NUM_NODES} 个节点注册"
    
    if [ "${node_count}" -eq "${NUM_NODES}" ]; then
        echo "所有 ${NUM_NODES} 个节点已完成注册!"
        break
    fi
    
    sleep 5
done

# 选择 master 节点 (IP 排序最大的节点)
MASTER_IP=$(ls -1 ${ASSIGNED_NODES_DIR}/*.ip | sort -V | tail -n 1 | sed 's|.*/\(.*\)\.ip|\1|')
echo "选择的 master 节点 IP: ${MASTER_IP}"

# 将 master IP 写入共享文件以供其他脚本使用
echo ${MASTER_IP} > "${ASSIGNED_NODES_DIR}/master_ip"

# 确定当前节点角色
if [ "${NODE_IP}" = "${MASTER_IP}" ]; then
    NODE_RANK=0
    echo "当前节点是 MASTER (rank=${NODE_RANK})"
else
    # 为 worker 节点分配 rank (1 到 n-1)
    # 获取所有 IP 并排序
    ALL_IPS=$(ls -1 ${ASSIGNED_NODES_DIR}/*.ip | grep -v "master_ip" | sed 's|.*/\(.*\)\.ip|\1|' | sort -V)
    
    # 找到当前 IP 的索引位置
    NODE_RANK=1  # 默认为 1
    for ip in ${ALL_IPS}; do
        if [ "${ip}" = "${MASTER_IP}" ]; then
            continue  # 跳过 master
        fi
        
        if [ "${ip}" = "${NODE_IP}" ]; then
            break
        fi
        NODE_RANK=$((NODE_RANK + 1))
    done
    
    echo "当前节点是 WORKER (rank=${NODE_RANK})"
fi

# 输出最终配置信息
echo "===== 分布式训练配置 ====="
echo "总节点数: ${NUM_NODES}"
echo "Master IP: ${MASTER_IP}"
echo "当前节点 IP: ${NODE_IP}"
echo "当前节点 Rank: ${NODE_RANK}"
echo "=========================="


export DYNAMIC_MASTER_ADDR=${MASTER_IP}
export DYNAMIC_NODE_RANK=${NODE_RANK}

echo "DBG: ${DYNAMIC_MASTER_ADDR}"

# 如果只需要输出配置，可以在此退出
echo "Node Dynamic assignment done. Start customized training script..."
