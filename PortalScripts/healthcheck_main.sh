!/bin/bash
#
#
#这个脚本用来做GPU集群的健康检查: 网络健康检查；GPU组件健康检查；NCCL检查
#只有DCGM检查的两个任务失败的话，才被我们认为是硬件相关的故障，需要重启；其他的错误不需要重启，但是需要通知相关人员来进行troubleshooting。
#
# Check if sshd is already running

if pgrep -x "sshd" >/dev/null; then
    echo "sshd is already running"
else
    # Start sshd
    /usr/sbin/sshd
fi

#check if  the SSH port is LISTEN state, if not, please wait the PORT become LISTEN state.
PORT=2022

# 设置最大等待时间（秒）
MAX_WAIT=60  # 5分钟
WAIT_INTERVAL=5  # 每5秒检查一次

# 计数器
counter=0

while true; do
    # 使用 netstat 检查指定端口是否处于 LISTEN 状态
    if netstat -tuln | grep -q ":$PORT.*LISTEN"; then
        echo "成功：sshd 正在监听端口 $PORT"
        break
    fi

    # 检查是否超过最大等待时间
    counter=$((counter + WAIT_INTERVAL))
    if [ $counter -ge $MAX_WAIT ]; then
        echo "错误：等待超时！sshd 未能在 $MAX_WAIT 秒内监听端口 $PORT"
        exit 1
    fi

    echo "端口 $PORT 未处于 LISTEN 状态，等待 $WAIT_INTERVAL 秒后重试... (已等待 $counter 秒)"
    sleep $WAIT_INTERVAL
done

SERVICE_NAME=$(hostname)

NCCLTEST_DOCKER_INSTALL_DIR=/healthcheck-workdir
echo "Portal Launch - In Healthcheck Main $SERVICE_NAME config path: $DIST_CONFIG_PATH"
echo "Portal Launch - In Healthcheck Main IB_DEV: $IBDEV_STR"
finish_file="$DIST_CONFIG_PATH/finish.txt"

# finish_file="/healthcheck/healthcheck/finish.txt"

# Check if the "finish.txt" file exists and remove it
if [ -f "$finish_file" ]; then
    echo "Removing existing 'finish.txt' file..."
    rm -f "$finish_file"
fi

#通过ls AWS Fsx中的文件进行健康检查
# ls -al /healthcheck/my_hosts
ls -al $DIST_CONFIG_PATH/my_hosts
if [ $? -eq 0 ] ;then
        fsx_health=1
        echo "AWS Fsx connection health"
        aws cloudwatch put-metric-data \
        --namespace "HybridGPUMonitoring" \
        --region "cn-north-1" \
        --metric-data \
        '{"MetricName": "Fsx_Health", "Dimensions": [{"Name": "Production", "Value": "'$SERVICE_NAME'"}], "Value": '$fsx_health', "Unit": "Count"}'
else
        fsx_health=0
        echo "fail on AWS Fsx connection"
        aws cloudwatch put-metric-data \
        --namespace "HybridGPUMonitoring" \
        --region "cn-north-1" \
        --metric-data \
        '{"MetricName": "Fsx_Health", "Dimensions": [{"Name": "Production", "Value": "'$SERVICE_NAME'"}], "Value": '$fsx_health', "Unit": "Count"}'
        exit 1
fi

#对外网的连通性测试
tcpping -x 3 baidu.com 443 | grep "open"
if [ $? -eq 0 ] ;then
        echo "health on tcp ping check on public internet."
        tcpping_internet_health=1

        aws cloudwatch put-metric-data \
        --namespace "HybridGPUMonitoring" \
        --region "cn-north-1" \
        --metric-data \
        '{"MetricName": "TCP_Health", "Dimensions": [{"Name": "Production", "Value": "'$SERVICE_NAME'"}], "Value": '$tcpping_internet_health', "Unit": "Count"}'

else
        echo "fail on tcp ping check on public internet."
        tcpping_internet_health=0

        aws cloudwatch put-metric-data \
        --namespace "HybridGPUMonitoring" \
        --region "cn-north-1" \
        --metric-data \
        '{"MetricName": "TCP_Health", "Dimensions": [{"Name": "Production", "Value": "'$SERVICE_NAME'"}], "Value": '$tcpping_internet_health', "Unit": "Count"}'

        exit 1
fi

ping -c 3 baidu.com|grep "ttl"
if [ $? -eq 0 ] ;then
        ping_internet_health=1
        echo "health on ping check on public internet."

        aws cloudwatch put-metric-data \
        --namespace "HybridGPUMonitoring" \
        --region "cn-north-1" \
        --metric-data \
        '{"MetricName": "Ping_Health", "Dimensions": [{"Name": "Production", "Value": "'$SERVICE_NAME'"}], "Value": '$ping_internet_health', "Unit": "Count"}'

else
        public_internet_health=0
        echo "fail on ping check on public internet."

        aws cloudwatch put-metric-data \
        --namespace "HybridGPUMonitoring" \
        --region "cn-north-1" \
        --metric-data \
        '{"MetricName": "Ping_Health", "Dimensions": [{"Name": "Production", "Value": "'$SERVICE_NAME'"}], "Value": '$ping_internet_health', "Unit": "Count"}'

        exit 1
fi


#首先检查当前节点上的GPU数量是否是我们希望的数量

# 获取GPU数量
gpu_count=$(nvidia-smi --list-gpus | wc -l)

# 检查GPU数量是否小于8
if [ "$gpu_count" -lt 8 ]; then
    echo "错误：检测到 $gpu_count 个 GPU，但至少需要 8 个 GPU！" 
    
    GPU_health=0
    aws cloudwatch put-metric-data \
    --namespace "HybridGPUMonitoring" \
    --region "cn-north-1" \
    --metric-data \
    '{"MetricName": "GPU_Health", "Dimensions": [{"Name": "Production", "Value": "'$SERVICE_NAME'"}], "Value": '$GPU_health', "Unit": "Count"}'
    exit 
else
    echo "GPU检查通过：检测到 $gpu_count 个 GPU"
fi



#使用Nvidia DCGM工具来做GPU组件的健康检查：DCGMi health命令检查 和DCGMi diag检查 ------- 每次启动的时候以及定期都需要做这个检查；

#利用DCGM工具做Background health check,默认情况下dcgm把当前节点上的GPU都看作group 0
/usr/bin/nv-hostengine
dcgmi health -g 0 -s a

#模拟GPU失败
#dcgmi test --inject --gpuid 0 -f 202 -v 99999

dcgmi health -g 0 -c | grep -i "healthy"
if [ $? -eq 0 ] ;then
        echo "dcgmi health success"
else
        echo "fail on dcgm health check"

        test=$(aws ssm get-parameters --region "cn-north-1"  --names "test-$(hostname)-GPU" --query 'Parameters[0].Value' | tr -d '\"\n\r')

        echo "the parameter is $test"
        if [ "$test" = 1 ] ;then
                GPU_Second_Failure=1
                        aws cloudwatch put-metric-data \
                                --namespace "HybridGPUMonitoring" \
                                --region "cn-north-1" \
                                --metric-data \
                                '{"MetricName": "GPU_Second_Failure", "Dimensions": [{"Name": "Production", "Value": "'$SERVICE_NAME'"}], "Value": '$GPU_Second_Failure', "Unit": "Count"}'

                        aws ssm delete-parameter --region "cn-north-1"  --name "test-$(hostname)-GPU"

                        echo "GPU failure on continuously second time"
        else
                        aws ssm put-parameter --region "cn-north-1"  --name "test-$(hostname)-GPU" --value "1" --type String --overwrite

                        GPU_First_Failure=1
                        aws cloudwatch put-metric-data \
                                --namespace "HybridGPUMonitoring" \
                                --region "cn-north-1" \
                                --metric-data \
                                '{"MetricName": "GPU_First_Failure", "Dimensions": [{"Name": "Production", "Value": "'$SERVICE_NAME'"}], "Value": '$GPU_First_Failure', "Unit": "Count"}'
                        echo "GPU failure on first time"

                        #we will reboot and try again
                        reboot
        fi

    exit
fi

#利用DCGM工具做active health check：
#dcgm diag for level 2

dcgmi diag -r 2 | grep -i "fail"
if [ $? -ne 0 ] ;then
        echo "dcgmi diag health"
else
    echo "fail on dcgm diag check"

        test=$(aws ssm get-parameters --names "test-$(hostname)-GPU" --query 'Parameters[0].Value' | tr -d '\"\n\r')

        if [ "$test" = 1 ] ;then
                GPU_Second_Failure=1
                        aws cloudwatch put-metric-data \
                                --namespace "HybridGPUMonitoring" \
                                --region "cn-north-1" \
                                --metric-data \
                                '{"MetricName": "GPU_Second_Failure", "Dimensions": [{"Name": "Production", "Value": "'$SERVICE_NAME'"}], "Value": '$GPU_Second_Failure', "Unit": "Count"}'

                        aws ssm delete-parameter --name "test-$(hostname)-GPU"
                        echo "GPU failure on second time"
        else
                        aws ssm put-parameter --name "test-$(hostname)-GPU" --value "1" --type String --overwrite

                        GPU_First_Failure=1
                        aws cloudwatch put-metric-data \
                                --namespace "HybridGPUMonitoring" \
                                --region "cn-north-1" \
                                --metric-data \
                                '{"MetricName": "GPU_First_Failure", "Dimensions": [{"Name": "Production", "Value": "'$SERVICE_NAME'"}], "Value": '$GPU_First_Failure', "Unit": "Count"}'
                        echo "GPU failure on first time"

                        #we will reboot and try again
                        reboot
        fi

        exit 1
fi


#3. 检查NCCL（包括节点内的和节点间的）：

# 设置 MPI 参数

mpirun --allow-run-as-root  --hostfile $DIST_CONFIG_PATH/my_hosts -x NCCL_DEBUG=INFO -x NCCL_SOCKET_IFNAME=enp -x NCCL_IB_DISABLE=0 -x NCCL_IB_HCA=$IBDEV_STR --mca plm_rsh_args "-p 2022"  --bind-to none --mca btl_openib_allow_ib 1 --mca btl_openib_if_include $IBDEV_STR  --mca btl '^tcp' $NCCLTEST_DOCKER_INSTALL_DIR/nccl-tests/build/all_reduce_perf -b 8M -e 128M -f 2-g 1
#mpirun --allow-run-as-root --hostfile /healthcheck/my_hosts --mca plm_rsh_args "-p 2022"  --bind-to none --mca btl tcp,self --mca btl_tcp_if_exclude lo,docker0 /workspace/nccl-tests/build/all_reduce_perf -b 8 -e 8G -f 2 -g 1


if [ $? -eq 0 ] ;then
        echo "NCCL health"
        nccl_health=1

        aws cloudwatch put-metric-data \
        --namespace "HybridGPUMonitoring" \
        --region "cn-north-1" \
        --metric-data \
        '{"MetricName": "NCCL_Health", "Dimensions": [{"Name": "Production", "Value": "'$SERVICE_NAME'"}], "Value": '$nccl_health', "Unit": "Count"}'
else
        nccl_health=0
        echo "fail on multiple host NCCL check"

        aws cloudwatch put-metric-data \
        --namespace "HybridGPUMonitoring" \
        --region "cn-north-1" \
        --metric-data \
        '{"MetricName": "NCCL_Health", "Dimensions": [{"Name": "Production", "Value": "'$SERVICE_NAME'"}], "Value": '$nccl_health', "Unit": "Count"}'

        exit 1
fi


#At this point, it denotes the GPUs on this node are healthy, so put metric to Cloudwatch and delete the flag about GPU healthy in the SSM parameter store.
GPU_health=1

aws cloudwatch put-metric-data \
--namespace "HybridGPUMonitoring" \
--region "cn-north-1" \
--metric-data \
'{"MetricName": "GPU_Health", "Dimensions": [{"Name": "Production", "Value": "'$SERVICE_NAME'"}], "Value": '$GPU_health', "Unit": "Count"}'


#delete the parameter if every is OK.
aws ssm delete-parameter --name "test-$(hostname)-GPU" --region "cn-north-1"

# Create the "finish" file in the "/fsx" directory
touch $finish_file

# Print a message to indicate the file creation
echo "The heath check has been finished in the main node."
exit 0  # Exit the script with a success status