#!/bin/bash

# 获取当前节点IP
# CURRENT_NODE_IP=$(hostname -i)

# 获取path参数
path="$1"
if [ -z "$path" ]; then
    echo "错误：请提供路径参数"
    exit 1
fi

# 获取master_ip的内容
# master=$(cat "$path/master_ip")

# 判断当前节点是否为master节点
if [ "$CURRENT_NODE_IP" = "$MASTER_NODE_IP" ]; then
    echo "当前节点是master节点，开始创建myhost文件..."
    
    # 创建myhost文件，首先添加master_ip的内容
    echo "$MASTER_NODE_IP slots=8" > "$path/my_hosts"
    
    # 添加所有其他IP文件的内容，排除与master_ip相同的内容
    for ip_file in "$path"/*.ip; do
        ip_content=$(cat "$ip_file")
        if [ "$ip_content" != "$MASTER_NODE_IP" ]; then
            echo "$ip_content slots=8" >> "$path/my_hosts"
        fi
    done
    
    # 创建完成标志文件
    touch "$path/my_hosts.finish"
    echo "myhost文件创建完成，已创建完成标志文件"
else
    echo "当前节点不是master节点，等待master节点创建myhost文件..."
    
    # 等待myhost.finish文件出现
    while [ ! -f "$path/my_hosts.finish" ]; do
        echo "等待myhost.finish文件..."
        sleep 2
    done
    
    echo "检测到myhost.finish文件，myhost文件已准备就绪"
fi

echo "脚本执行完成"
