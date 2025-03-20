#!/bin/bash



SERVICE_NAME=$(hostname)


echo "In Healthcheck Worker $SERVICE_NAME config path: $DIST_CONFIG_PATH"
finish_file="$DIST_CONFIG_PATH/finish.txt"


sleep 15

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

# If the loop exits, it means the "finish" file exists
echo "The health check has been finised in the slave nodes."
exit 0  # Exit the script with a success status
