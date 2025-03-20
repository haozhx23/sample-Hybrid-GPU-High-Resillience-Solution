#!/bin/bash
#
#
#这个脚本用来做GPU集群的健康检查: 网络健康检查；GPU组件健康检查；NCCL检查
#只有DCGM检查的两个任务失败的话，才被我们认为是硬件相关的故障，需要重启；其他的错误不需要重启，但是需要通知相关人员来进行troubleshooting。
#
# Check if sshd is already running
apt -y install bc

if pgrep -x "sshd" >/dev/null; then
    echo "sshd is already running"
else
    # Start sshd
    /usr/sbin/sshd
fi

sleep 10


SERVICE_NAME=$(hostname)

finish_file="/healthcheck/finish.txt"

#通过ls AWS Fsx中的文件进行健康检查
ls -al /healthcheck/my_hosts
if [ $? -eq 0 ] ;then
        fsx_health=1
        echo "AWS Fsx connection health"
        aws cloudwatch put-metric-data \
        --namespace "HybridGPUHealthCheck" \
        --region "cn-northwest-1" \
        --metric-data \
        '{"MetricName": "Fsx_Health", "Dimensions": [{"Name": "Production", "Value": "'$SERVICE_NAME'"}], "Value": '$fsx_health', "Unit": "Count"}' 
else
        fsx_health=0
        echo "fail on AWS Fsx connection"
        aws cloudwatch put-metric-data \
        --namespace "HybridGPUHealthCheck" \
        --region "cn-northwest-1" \
        --metric-data \
        '{"MetricName": "Fsx_Health", "Dimensions": [{"Name": "Production", "Value": "'$SERVICE_NAME'"}], "Value": '$fsx_health', "Unit": "Count"}' 
        exit
fi

#对外网的连通性测试
tcpping -x 3 baidu.com 443 | grep "open"
if [ $? -eq 0 ] ;then
        echo "health:tcp ping check on public internet."
        tcpping_internet_health=1

        aws cloudwatch put-metric-data \
        --namespace "HybridGPUHealthCheck" \
        --region "cn-northwest-1" \
        --metric-data \
        '{"MetricName": "TCP_Health", "Dimensions": [{"Name": "Production", "Value": "'$SERVICE_NAME'"}], "Value": '$tcpping_internet_health', "Unit": "Count"}' 

else
        echo "fail on tcp ping check on public internet."
        tcpping_internet_health=0
        echo "fail on ping check on public internet."

        aws cloudwatch put-metric-data \
        --namespace "HybridGPUHealthCheck" \
        --region "cn-northwest-1" \
        --metric-data \
        '{"MetricName": "TCP_Health", "Dimensions": [{"Name": "Production", "Value": "'$SERVICE_NAME'"}], "Value": '$tcpping_internet_health', "Unit": "Count"}' 

        exit
fi


ping -c 3 baidu.com|grep "ttl"
if [ $? -eq 0 ] ;then
        ping_internet_health=1
        echo "health:ping check on public internet."

        aws cloudwatch put-metric-data \
        --namespace "HybridGPUHealthCheck" \
        --region "cn-northwest-1" \
        --metric-data \
        '{"MetricName": "Ping_Health", "Dimensions": [{"Name": "Production", "Value": "'$SERVICE_NAME'"}], "Value": '$ping_internet_health', "Unit": "Count"}' 

else
        public_internet_health=0
        echo "fail on ping check on public internet."

        aws cloudwatch put-metric-data \
        --namespace "HybridGPUHealthCheck" \
        --region "cn-northwest-1" \
        --metric-data \
        '{"MetricName": "Ping_Health", "Dimensions": [{"Name": "Production", "Value": "'$SERVICE_NAME'"}], "Value": '$ping_internet_health', "Unit": "Count"}' 

        exit
fi


#使用Nvidia DCGM工具来做GPU组件的健康检查：DCGMi health命令检查 和DCGMi diag检查 ------- 每次启动的时候以及定期都需要做这个检查；

#利用DCGM工具做Background health check,默认情况下dcgm把当前节点上的GPU都看作group 0
/usr/bin/nv-hostengine
dcgmi health -g 0 -s a
dcgmi health -g 0 -c | grep -i "fail" 

if [ $? -ne 0 ] ;then
        echo "dcgmi health success"
else
        echo "fail on dcgm health check"

        test=$(aws ssm get-parameters --region "cn-northwest-1"  --names "test-$(hostname)-GPU" --query 'Parameters[0].Value' | tr -d '\"\n\r')

        if [ "$test" = 1 ] ;then
                        GPU_health=0
                        aws cloudwatch put-metric-data \
                                --namespace "HybridGPUHealthCheck" \
                                --region "cn-northwest-1" \
                                --metric-data \
                                '{"MetricName": "GPU_Health", "Dimensions": [{"Name": "Production", "Value": "'$SERVICE_NAME'"}], "Value": '$GPU_health', "Unit": "Count"}'

			aws ssm delete-parameter --region "cn-northwest-1"  --name "test-$(hostname)-GPU"
                        #put metrtic to cloudwatch end flag to GPU failutre and alarm.
                        echo "GPU failure on continuously second time"
        else
                        aws ssm put-parameter --region "cn-northwest-1"  --name "test-$(hostname)-GPU" --value "1" --type String --overwrite
                        echo "GPU failure on first time"
        fi

        exit
fi

#利用DCGM工具做active health check：
#dcgm diag for level 1

dcgmi diag -r 1 | grep -i "fail"
if [ $? -ne 0 ] ;then
        echo "dcgmi diag health"
	GPU_health=1
	aws cloudwatch put-metric-data \
                                --namespace "HybridGPUHealthCheck" \
                                --region "cn-northwest-1" \
                                --metric-data \
                                '{"MetricName": "GPU_Health", "Dimensions": [{"Name": "Production", "Value": "'$SERVICE_NAME'"}], "Value": '$GPU_health', "Unit": "Count"}'
else
        echo "fail on dcgm diag check"

        test=$(aws ssm get-parameters ---region "cn-northwest-1" -names "test-$(hostname)-GPU" --query 'Parameters[0].Value' | tr -d '\"\n\r')

        if [ "$test" = 1 ] ;then
                        GPU_health=0
                        aws cloudwatch put-metric-data \
                                --namespace "HybridGPUHealthCheck" \
                                --region "cn-northwest-1" \
                                --metric-data \
                                '{"MetricName": "GPU_Health", "Dimensions": [{"Name": "Production", "Value": "'$SERVICE_NAME'"}], "Value": '$GPU_health', "Unit": "Count"}'

			aws ssm delete-parameter --name "test-$(hostname)-GPU" --region "cn-northwest-1" 
                        #put metrtic to cloudwatch end flag to GPU failutre and alarm.
                        echo "GPU failure on second time"
        else
                        aws ssm put-parameter --name "test-$(hostname)-GPU" --value "1" --type String --overwrite --region "cn-northwest-1" 
                        echo "GPU failure on first time"
        fi
fi



finish_file="/healthcheck/finish.txt"


# Loop until the "finish" file exists

i=0
while [ ! -f "$finish_file" ]; do
    if [ $i -eq 5 ]; then
	    break  # 当i等于50时(也就是最多让slave等待5分钟)，退出循环
    fi   

    i=$((i + 1)) 
    echo "Waiting for the 'finish' file to be created..."
    sleep 60  # Wait for 5 seconds before checking again
done


#At this point, it denotes the GPUs on this node are healthy, so put metric to Cloudwatch and delete the flag about GPU healthy in the SSM parameter store.
GPU_health=1

aws cloudwatch put-metric-data \
--namespace "HybridGPUHealthCheck" \
--region "cn-northwest-1" \
--metric-data \
'{"MetricName": "GPU_Health", "Dimensions": [{"Name": "Production", "Value": "'$SERVICE_NAME'"}], "Value": '$GPU_health', "Unit": "Count"}'

#delete the parameter if every is OK.
aws ssm delete-parameter --name "test-$(hostname)-GPU" --region "cn-northwest-1" 

# If the loop exits, it means the "finish" file exists
echo "The health check has been finised in the slave nodes."
exit 0  # Exit the script with a success status
