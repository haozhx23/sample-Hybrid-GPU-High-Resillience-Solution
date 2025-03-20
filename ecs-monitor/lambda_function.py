import json
import boto3
import os 

client = boto3.client('sns')
ecs_client = boto3.client('ecs')
ssm_client = boto3.client('ssm')

def parse_event_message(event_dict, event_attributes):
    print("parsing event")
    event_detail = {}
    for attribute in event_attributes:
        if event_dict.get(attribute):
            event_detail[attribute] = event_dict[attribute]
    return event_detail


def get_ssm_instance_info(ec2InstanceId):
    response = ssm_client.describe_instance_information(
    InstanceInformationFilterList=[
        {
            'key': 'InstanceIds',
            'valueSet': [
                ec2InstanceId,
            ]
        },
    ],
    MaxResults=5
    )
    return response

def lambda_handler(event, context):
    id_name = ""
    subject = "no specific subject"
    new_record = {}
    message = ""

    # For debugging so you can see raw event format.
    print('Here is the event:')
    print((json.dumps(event)))


    if not event.get('Records'):
        raise ValueError("Function only supports input from events with a source type of: aws.sns")

    records = event['Records']
    for record in records:
        if record["EventSource"] != "aws:sns":
            raise ValueError("Function only supports input from events with a source type of: aws.sns")
        sns_message = json.loads(record["Sns"]["Message"])
        print('Here is the sns message')
        print(sns_message)

        event = sns_message

        if event["source"] != "aws.ecs":
            raise ValueError("Function only supports input from events with a source type of: aws.ecs")

        # Switch on task/container events.
        if event["detail-type"] == "ECS Task State Change":
            print("ECS Task State Change")
            id_name = "taskArn"
            taskArn = event["detail"]["taskArn"]
            task_name = taskArn.split('/')[1]
            task_id = taskArn.split('/')[2]
            cluster_name = event['detail']['clusterArn'].split('/')[1]

            print("task state is %s " % event['detail']['lastStatus'])
            support_ecs_task_attributes = ["containers","clusterArn", "pullStartedAt", "pullStoppedAt", "startedBy", "stoppingAt", "stoppedAt", "stoppedReason", "stopCode", "taskDefinitionArn"]
            new_record = parse_event_message(event['detail'], support_ecs_task_attributes)
            if event['detail'].get('lastStatus'):
                if event['detail']['lastStatus'] == "STOPPED":
                    print("ecs task is stopped")
                    subject = "Your task is stopped"
                    message = ("yout task %s running on cluster %s is stopped, due to %s task will try to re-run after check the gpu server environment" %(task_name, cluster_name, event['detail']['stoppedReason']))
                    
                    # 
                    """
                    # parse the failed event
                    # add "CannotPullContainer"
                    non_calling_check_task_event = ["CannotCreateVolume", "CannotInspectContainer", "CannotStopContainer", "OutOfMemoryError", "InternalError", "ContainerRuntimeTimeoutError", "ContainerRuntimeError", "OutOfMemoryError", "ResourceInitializationError", "ResourceNotFoundException"]
                    if event['detail']['stoppedReason'] not in non_calling_check_task_event:
                        print("need to do health check on gpu server")
                        # ecs task is TaskFailedToStart
                        
                        try:
                            # calling ecs sdk to create a health_check task

                            # run master task
                            master_task =  os.environ.get('HEALTH_CHECK_MASTER_TASK')
                            slave_task =  os.environ.get('HEALTH_CHECK_SLAVE_TASK')
                            container_instance_ids = [event['detail']['containerInstanceArn']]
                            container_instance_response = ecs_client.describe_container_instances(
                            cluster=event['detail']['clusterArn'],
                            containerInstances=container_instance_ids
                            )
                            container_instance = container_instance_response['containerInstances'][0]
                            custom_attributes = container_instance['attributes']

                            placement_constraints = []

                            for attri in custom_attributes:
                                print(attri)
                                place_constr = {}
                                if not attri['name'].startswith("ecs.") and not attri['name'].startswith("com."):
                                    print(attri)
                                    expression = "attribute:" + attri['name'] + " == " + attri['value']
                                    print(expression)
                                    place_constr ={
                                    'type': 'memberOf',
                                    'expression': expression
                                    }
                                    placement_constraints.append(place_constr)
                            
                            print(placement_constraints)


                            print(container_instance_response)
                            #ec2_info = get_ssm_instance_info(ec2InstanceId)

                            master_response = ecs_client.run_task(
                            cluster=event['detail']['clusterArn'],  # Replace with your ECS cluster name
                            taskDefinition=master_task,  # Replace with your task definition (family:revision)
                            launchType='EXTERNAL',  # Use 'EC2' if you are using EC2 launch type
                            count=1,  # Number of tasks to run
                            placementConstraints=placement_constraints
                            )

                            # run slave task
                            slave_response = ecs_client.run_task(
                            cluster=event['detail']['clusterArn'],  # Replace with your ECS cluster name
                            taskDefinition=slave_task,  # Replace with your task definition (family:revision)
                            launchType='EXTERNAL',  # Use 'EC2' if you are using EC2 launch type
                            count=1, # Number of tasks to run
                            placementConstraints=placement_constraints
                            )


                        except Exception as e:
                            raise
                            print("launch health check task failed")
                            message = ("launch health check task failed, error is ", e)
                        print("launch healtch check task")
                    else:
                        message = event['detail']['stoppedReason']
                    """
                    
                elif event['detail']['lastStatus'] == "ACTIVE":
                    subject = 'Your ecs task is running'
                    message = (("Your ecs task %s is running in cluster %s, you may check the logs in cloudwatch and ecs console.") % (task_name, cluster_name))
                elif event['detail']['lastStatus'] == "PENDING":
                    subject = 'Your ecs task is pending'
                    message = (("Your ecs task %s in cluster %s is pending, please wait about 3 minutes for the task to running, if pending too long please check more logs in cloudwatch and ecs console.") % (task_name, cluster_name))
                elif event['detail']['lastStatus'] == 'PROVISIONING':
                    subject = 'Your ecs task is PROVISIONING'
                    message = (('Please wait for the ecs task %s in cluster %s to be running') % (task_name, cluster_name))
                elif event['detail']['lastStatus'] == 'DEPROVISIONING':
                    subject = 'Your ecs task is DEPROVISIONING'
                    message = (('Please wait for the ecs task %s in cluster %s to be DEPROVISIONING') % (task_name, cluster_name)) 
                elif event['detail']['lastStatus'] == 'RUNNING':
                    continue
                else: 
                    subject = 'Unhanled ecs task state'
                    message = (("unkonw ecs task %s in cluster %s state, please check with cloudwatch logs.") % (task_name, cluster_name))

        elif event["detail-type"] == "ECS Container Instance State Change":
            print("ECS Container Instance State Change")
            new_record['event_type'] = "ECS Container Instance State Change"
            support_ecs_container_attributes = ["containerInstanceArn", "agentConnected", "registeredResources", "remainingResources", "pendingTasksCount", "runningTasksCount", "status", "ec2InstanceId"]
            new_record = parse_event_message(event['detail'], support_ecs_container_attributes)
            cluster_name = event['detail']['clusterArn'].split('/')[1]
            ec2InstanceId = event['detail']['ec2InstanceId']
            container_instance_id = event['detail']['containerInstanceArn'].split('/')[2]

            # get ec2 info from system manager
            try:
                ec2_info = get_ssm_instance_info(ec2InstanceId)
            except:
                message = "unable to get ec2 info from ssm"
                raise ValueError("Unable to get ec2 info from ssm")
            
            print("get ec2 info from ssm")
            print(ec2_info)
            ec2_instance = ec2_info['InstanceInformationList'][0]
            IPAddress = ec2_instance['IPAddress']
            ComputerName = ec2_instance['ComputerName']
            PingStatus = ec2_instance['PingStatus']            
            gpu_server_info = "ec2_instance_id: " + ec2InstanceId + " container_instance_id: " + container_instance_id + " IPAddress: " + IPAddress + " ComputerName: " + ComputerName + " PingStatus: " + PingStatus
            
            if event['detail'].get('status'):
                if event['detail']['status'] == 'ACTIVE':
                    continue
                    subject = "GPU Server is online"
                    message = ("GPU Server %s is online in cluster %s, you may begin deploying your ecs task") % (gpu_server_info, cluster_name)
                elif event['detail']['status'] == 'DRAINING':
                    subject = "GPU Server is offline, start to drain the tasks"
                    message = ("GPU Server %s is offline in cluster %s, please check with cloudwatch logs for more details.") % (gpu_server_info, cluster_name)
                else:
                    subject = "GPU Server is offline"
                    message = ("GPU Server %s is offline in cluster %s with unkown reasons.") % (gpu_server_info, cluster_name)
            print(new_record)
            

        else:
            raise ValueError("detail-type for event is not a supported type. Exiting without saving event.")

        new_record["cw_version"] = event["version"]
        #new_record['orginal_message'] = event["detail"]

        sns_arn =  os.environ.get('SNS_ARN')
        print("message publish to sns")
        print(("subject is %s, message is %s") % (subject, message))

        response = client.publish(TopicArn=sns_arn,Subject=subject, Message=str(message))
        print("Message published")
        return(response)