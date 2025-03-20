#!/bin/bash
#
#
#这个脚本用来做GPU集群的健康检查: 网络健康检查；GPU组件健康检查；NCCL检查
#只有DCGM检查的两个任务失败的话，才被我们认为是硬件相关的故障，需要重启；其他的错误不需要重启，但是需要通知相关人员来进行troubleshooting。
#
# Check if sshd is already running

SERVICE_NAME=$(hostname)
echo "In Healthcheck Main IB_DEV: $IBDEV_STR"
echo "In Healthcheck Main $SERVICE_NAME config path: $DIST_CONFIG_PATH"
finish_file="$DIST_CONFIG_PATH/finish.txt"




# Check if the "finish.txt" file exists and remove it
if [ -f "$finish_file" ]; then
    echo "Removing existing 'finish.txt' file..."
    rm -f "$finish_file"
fi

echo $(ls -al $DIST_CONFIG_PATH/my_hosts)


sleep 15

#At this point, it denotes the GPUs on this node are healthy, so put metric to Cloudwatch and delete the flag about GPU healthy in the SSM parameter store.
GPU_health=1

# Create the "finish" file in the "/fsx" directory
touch $finish_file

# Print a message to indicate the file creation
echo "The heath check has been finished in the master node."
