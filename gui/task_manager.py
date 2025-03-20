from typing import Dict, Any, List
import os
import subprocess
import json

from file_manager import FileManager
from ddb_handler import DynamoDBHandler
from node_manager import NodeManager

from datetime import datetime
import boto3


def _run_aws_cli(cmd):
    cmdstr = ' '.join(cmd)
    print(f"TaskManager Executing: {cmdstr}")
    
    result = subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        check=True  # This will raise CalledProcessError if the command fails
    )
    
    # Parse the JSON output
    response = json.loads(result.stdout)

    print(f"TaskManager Execution Result: {response}")

    return response


def _get_arn_id(arn):
    return arn.split('/')[-1]

session = boto3.Session()
region = session.region_name
print(f"Get Default AWS REGION from configure {region}")
if region.startswith('cn-'):
    LAUNCH_TYPE = 'EXTERNAL'
else:
    LAUNCH_TYPE = 'EC2'


class TaskManager:
    def __init__(self):
        self.ecs_task_def = FileManager.load_json(os.environ['ECS_TASK_DEF'])
        self.training_container_def = FileManager.load_json(os.environ['TRAINING_CONTAINER_DEF'])
        self.healthcheck_container_def = FileManager.load_json(os.environ['HEALTH_CONTAINER_DEF'])

        self.node_manager = NodeManager()

    def get_ecs_task_def(self):
        return self.ecs_task_def.copy()

    def get_training_container_def(self):
        return self.training_container_def.copy()

    def get_healthcheck_container_def(self):
        return self.healthcheck_container_def.copy()


    @staticmethod
    def task_register(task_def_path):
        reg_task_cmd = [
            'aws', 'ecs', 'register-task-definition',
            '--cli-input-json', f'file://{task_def_path}',
            '--output', 'json'
        ]
        
        reg_result = _run_aws_cli(reg_task_cmd)

        return reg_result['taskDefinition']['taskDefinitionArn'], reg_task_cmd



    @staticmethod
    def task_exec(task_def_arn, is_training):

        if is_training:
            exec_task_cmd = [
                'aws', 'ecs', 'run-task',
                '--cluster', os.environ['CLUSTER_NAME'],
                '--task-definition', task_def_arn,
                '--count', '1',
                '--launch-type', LAUNCH_TYPE,
                '--tag', 'key=jobtype,value=training_job',
                '--output', 'json'
            ]
        else:
            exec_task_cmd = [
                'aws', 'ecs', 'run-task',
                '--cluster', os.environ['CLUSTER_NAME'],
                '--task-definition', task_def_arn,
                '--count', '1',
                '--launch-type', LAUNCH_TYPE,
                '--output', 'json'
            ]

        exec_result = _run_aws_cli(exec_task_cmd)
        
        task_id = _get_arn_id(exec_result['tasks'][0]['taskArn'])
        # task_def_arn = _get_arn_id(exec_result['tasks'][0]['taskDefinitionArn'])
        cluster_name = _get_arn_id(exec_result['tasks'][0]['clusterArn'])
        container_inst_id = _get_arn_id(exec_result['tasks'][0]['containerInstanceArn'])

        return task_id, cluster_name, container_inst_id, exec_result, exec_task_cmd

    
    @staticmethod
    def task_start(task_def_arn, container_inst_id):
        exec_task_cmd = [
            'aws', 'ecs', 'start-task',
            '--cluster', os.environ['CLUSTER_NAME'],
            '--task-definition', task_def_arn,
            '--container-instances', container_inst_id,
            '--tag', 'key=jobtype,value=training_job',
            '--output', 'json'
        ]

        exec_result = _run_aws_cli(exec_task_cmd)
        
        task_id = _get_arn_id(exec_result['tasks'][0]['taskArn'])
        # task_def_arn = _get_arn_id(exec_result['tasks'][0]['taskDefinitionArn'])
        cluster_name = _get_arn_id(exec_result['tasks'][0]['clusterArn'])
        container_inst_id = _get_arn_id(exec_result['tasks'][0]['containerInstanceArn'])

        return task_id, cluster_name, container_inst_id, exec_result, exec_task_cmd


    @staticmethod
    def record_task_to_ddb(task_id,
                        node_name_orchestrated,
                        node_index,
                        job_id,
                        job_timestamp,
                        nnodes,
                        task_def_arn,
                        cluster_name,
                        container_inst_id,
                        # reg_result,
                           ):
        task_ddb_table_name = os.environ.get('TASK_MANAGE_TABLE')

        resp = DynamoDBHandler.write_item(table_name = task_ddb_table_name,
                                    item = {
                                    'ecs_task_id': task_id,
                                    'node_name': node_name_orchestrated,
                                    'node_index_in_job': node_index, #Decimal(rank),
                                    'job_id': job_id,
                                    'job_timestamp': job_timestamp,
                                    'job_num_nodes': nnodes, #Decimal(nnodes),
                                    'task_def_arn': task_def_arn,
                                    'task_def_name': task_def_arn.split(':')[0],
                                    'task_def_revision': task_def_arn.split(':')[-1],
                                    'cluster_name': cluster_name,
                                    'container_inst_id': container_inst_id,
                                    # 'retry': 0,
                                    # 'task_status': 'IN_PROGRESS',
                                    'updated_at': datetime.now().isoformat(),
                                    'created_at': datetime.now().isoformat(),
                                    # 'metadata': _convert_floats_to_decimal({
                                    #     'task_reg_result': reg_result,
                                    #     'task_exec_result': exec_result
                                    # })
                                }
                            )
        
        print('TaskManager Record Task to DDB Response: ', resp)


    @staticmethod
    def register_task_and_run_all(
                      job_id,
                      job_timestamp,
                      num_nodes,
                      task_def_path,
                      exec_history_save_dir,
                      container_instance_ids = None
                    ):
        
        node_manager = NodeManager()

        all_commands = []
        container_inst_ids = []
        ecs_task_ids = []
        orch_node_names = []


        ## TODO
        ## Read task_def_path and check if healthcheck container or training container
        ## and take flag to task_exec and task_start

        is_training = True
        taskdefdict = FileManager.load_json(task_def_path)
        if taskdefdict['containerDefinitions'][0]['name'] == 'HealthCheckContainer':
            is_training = False

        task_def_arn, reg_task_cmd = TaskManager.task_register(task_def_path)
        all_commands.append(reg_task_cmd)

        for nodei in range(num_nodes):
            if container_instance_ids is None:
                task_id, cluster_name, container_inst_id, exec_result, exec_task_cmd = TaskManager.task_exec(task_def_arn, is_training)
            else:
                task_id, cluster_name, container_inst_id, exec_result, exec_task_cmd = TaskManager.task_start(task_def_arn, container_instance_ids[nodei])

            node_name_orchestrated = node_manager.fetch_node_name(container_inst_id)
            print(f"Training task {task_id} launched for node {node_name_orchestrated}")

            TaskManager.record_task_to_ddb(
                task_id = task_id,
                node_name_orchestrated = node_name_orchestrated,
                node_index = -1,
                job_id = job_id,
                job_timestamp = job_timestamp,
                nnodes = num_nodes,
                task_def_arn = task_def_arn,
                cluster_name = cluster_name,
                container_inst_id = container_inst_id,
            )

            all_commands.append(exec_task_cmd)
            container_inst_ids.append(container_inst_id)
            ecs_task_ids.append(task_id)
            orch_node_names.append(node_name_orchestrated)

        history_file = FileManager.create_execution_history(exec_history_save_dir, all_commands)
        print('TaskManager Save history_file: ', history_file)

        return ecs_task_ids, orch_node_names, container_inst_ids, history_file


    @staticmethod
    def task_register_and_exec(task_def_path):

        reg_task_cmd = [
            'aws', 'ecs', 'register-task-definition',
            '--cli-input-json', f'file://{task_def_path}',
            '--output', 'json'
        ]
        
        reg_result = _run_aws_cli(reg_task_cmd)
        # reg_result = {'taskDefinition': {'taskDefinitionArn': 'arn:aws-cn:ecs:cn-northwest-1:455385591292:task-definition/TrainingTask:453', 'containerDefinitions': [{'name': 'TrainingContainer', 'image': '455385591292.dkr.ecr.cn-northwest-1.amazonaws.com.cn/hybridgpu-training-torch260:latest', 'cpu': 0, 'portMappings': [{'containerPort': 10086, 'hostPort': 10086, 'protocol': 'tcp'}], 'essential': True, 'entryPoint': ['/bin/sh'], 'command': ['/workspace/training_output_20250222-073224/training-node002.sh'], 'environment': [], 'mountPoints': [{'sourceVolume': 'mylustre', 'containerPath': '/workspace', 'readOnly': False}, {'sourceVolume': 'mylustremodel', 'containerPath': '/modeldatas', 'readOnly': False}, {'sourceVolume': 'mylustredata', 'containerPath': '/datafiles', 'readOnly': False}, {'sourceVolume': 'instancelocaldata', 'containerPath': '/localdata', 'readOnly': False}], 'volumesFrom': [], 'linuxParameters': {'devices': [{'hostPath': '/dev/infiniband', 'containerPath': '/dev/infiniband', 'permissions': ['read', 'write']}], 'sharedMemorySize': 16384}, 'privileged': True, 'ulimits': [{'name': 'memlock', 'softLimit': -1, 'hardLimit': -1}], 'logConfiguration': {'logDriver': 'awslogs', 'options': {'awslogs-group': '/ecs/ECSHybridGpuTraining', 'mode': 'non-blocking', 'awslogs-create-group': 'true', 'max-buffer-size': '25m', 'awslogs-region': 'cn-northwest-1', 'awslogs-stream-prefix': 'ecs'}, 'secretOptions': []}, 'systemControls': [], 'resourceRequirements': [{'value': '8', 'type': 'GPU'}]}], 'family': 'TrainingTask', 'taskRoleArn': 'arn:aws-cn:iam::455385591292:role/ecsanywhereTaskRole', 'executionRoleArn': 'arn:aws-cn:iam::455385591292:role/ecsanywhereTaskExecutionRole', 'networkMode': 'host', 'revision': 453, 'volumes': [{'name': 'mylustre', 'host': {'sourcePath': '/fsx/hzworkspace/ecs-gpu-console-v2'}}, {'name': 'mylustremodel', 'host': {'sourcePath': '/fsx/hzworkspace/modeldatas'}}, {'name': 'mylustredata', 'host': {'sourcePath': '/fsx/hzworkspace/datafiles'}}, {'name': 'instancelocaldata', 'host': {'sourcePath': '/home/node-user/local-data-test'}}], 'status': 'ACTIVE', 'requiresAttributes': [{'name': 'ecs.capability.execution-role-awslogs'}, {'name': 'com.amazonaws.ecs.capability.task-iam-role-network-host'}, {'name': 'com.amazonaws.ecs.capability.ecr-auth'}, {'name': 'com.amazonaws.ecs.capability.privileged-container'}, {'name': 'com.amazonaws.ecs.capability.docker-remote-api.1.17'}, {'name': 'com.amazonaws.ecs.capability.docker-remote-api.1.28'}, {'name': 'com.amazonaws.ecs.capability.task-iam-role'}, {'name': 'com.amazonaws.ecs.capability.docker-remote-api.1.22'}, {'name': 'ecs.capability.execution-role-ecr-pull'}, {'name': 'com.amazonaws.ecs.capability.docker-remote-api.1.18'}, {'name': 'com.amazonaws.ecs.capability.docker-remote-api.1.29'}, {'name': 'com.amazonaws.ecs.capability.logging-driver.awslogs'}, {'name': 'com.amazonaws.ecs.capability.docker-remote-api.1.19'}, {'name': 'ecs.capability.pid-ipc-namespace-sharing'}], 'placementConstraints': [{'type': 'memberOf', 'expression': 'attribute:node==node002'}], 'compatibilities': ['EXTERNAL', 'EC2'], 'runtimePlatform': {'cpuArchitecture': 'X86_64', 'operatingSystemFamily': 'LINUX'}, 'requiresCompatibilities': ['EXTERNAL'], 'memory': '1843200', 'ipcMode': 'host', 'registeredAt': 1740236698.253, 'registeredBy': 'arn:aws-cn:iam::455385591292:user/zhenghao'}}

        exec_task_cmd = [
            'aws', 'ecs', 'run-task',
            '--cluster', os.environ['CLUSTER_NAME'],
            '--task-definition', reg_result['taskDefinition']['taskDefinitionArn'],
            '--count', '1',
            '--launch-type', LAUNCH_TYPE,
            '--output', 'json'
        ]

        exec_result = _run_aws_cli(exec_task_cmd)
        
        # exec_result = {'tasks': [{'attachments': [], 'attributes': [{'name': 'ecs.cpu-architecture', 'value': 'x86_64'}], 'clusterArn': 'arn:aws-cn:ecs:cn-northwest-1:455385591292:cluster/nwcd-gpu-testing', 'containerInstanceArn': 'arn:aws-cn:ecs:cn-northwest-1:455385591292:container-instance/nwcd-gpu-testing/2c0cf09946f8409b94f0494dc059bd39', 'containers': [{'containerArn': 'arn:aws-cn:ecs:cn-northwest-1:455385591292:container/nwcd-gpu-testing/595b16b4d57f4efc8bf65692164b2c71/5180808f-49cf-469b-872c-454b853fb736', 'taskArn': 'arn:aws-cn:ecs:cn-northwest-1:455385591292:task/nwcd-gpu-testing/595b16b4d57f4efc8bf65692164b2c71', 'name': 'TrainingContainer', 'image': '455385591292.dkr.ecr.cn-northwest-1.amazonaws.com.cn/hybridgpu:training', 'lastStatus': 'PENDING', 'networkInterfaces': [], 'cpu': '0', 'gpuIds': ['GPU-01d4f7d4-1ec5-2a06-c2d0-20a6dd73f53a', 'GPU-32eba458-d805-fa5e-2394-83ffbee5ecef', 'GPU-3a76ac8a-8175-09e2-50ec-6fea87363da2', 'GPU-3d686c9d-4e09-6cc8-3ed6-e5c200ae8366', 'GPU-7780ccd7-d529-ab9e-176e-39abd92b551b', 'GPU-b79120c4-b809-2edb-9d9a-8f3c77b707c0', 'GPU-c2547f54-68ff-a581-8669-e3fd61cd9dee', 'GPU-cb9055ed-c530-853a-027e-53256bd3e32a']}], 'cpu': '0', 'createdAt': 174072, 'desiredStatus': 'RUNNING', 'enableExecuteCommand': False, 'group': 'family:TrainingTask', 'lastStatus': 'PENDING', 'launchType': 'EXTERNAL', 'memory': '1843200', 'overrides': {'containerOverrides': [{'name': 'TrainingContainer'}], 'inferenceAcceleratorOverrides': []}, 'tags': [], 'taskArn': 'arn:aws-cn:ecs:cn-northwest-1:455385591292:task/nwcd-gpu-testing/595b16b4d57f4efc8bf65692164b2c71', 'taskDefinitionArn': 'arn:aws-cn:ecs:cn-northwest-1:455385591292:task-definition/TrainingTask:411', 'version': 1}], 'failures': []}
        
        task_id = _get_arn_id(exec_result['tasks'][0]['taskArn'])
        task_def_arn = _get_arn_id(exec_result['tasks'][0]['taskDefinitionArn'])
        cluster_name = _get_arn_id(exec_result['tasks'][0]['clusterArn'])
        container_inst_id = _get_arn_id(exec_result['tasks'][0]['containerInstanceArn'])

        return task_id, task_def_arn, cluster_name, container_inst_id, reg_result, exec_result, reg_task_cmd, exec_task_cmd


    @staticmethod
    def stop_ecs_task(task_id):

        stop_task_cmd = [
            'aws', 'ecs', 'stop-task',
            '--cluster', os.environ['CLUSTER_NAME'],
            '--task', task_id,
            '--output', 'json'
        ]

        exec_result = _run_aws_cli(stop_task_cmd)

        return exec_result


    @staticmethod
    def is_task_running(task_id):
        """
        Check if an ECS task is currently running.
        
        Args:
            task_id (str): The ID of the task to check
            
        Returns:
            bool: True if the task is running, False otherwise (stopped, crashed, etc.)
        """
        describe_task_cmd = [
            'aws', 'ecs', 'describe-tasks',
            '--cluster', os.environ['CLUSTER_NAME'],
            '--tasks', task_id,
            '--output', 'json'
        ]
        
        try:
            result = _run_aws_cli(describe_task_cmd)
            
            # Check if we got task information back
            if not result.get('tasks'):
                return False
                
            task = result['tasks'][0]
            last_status = task.get('lastStatus')
            desired_status = task.get('desiredStatus')
            
            # Task is running if both lastStatus and desiredStatus are "RUNNING"
            return last_status == 'RUNNING' and desired_status == 'RUNNING'
            
        except Exception as e:
            print(f"Error checking task status: {e}")
            return False


    @staticmethod
    def check_task_stop_status(task_id):
        """
        Check if an ECS task has stopped successfully.
        
        Args:
            task_id (str): The ID of the task to check
            
        """
        describe_task_cmd = [
            'aws', 'ecs', 'describe-tasks',
            '--cluster', os.environ['CLUSTER_NAME'],
            '--tasks', task_id,
            '--output', 'json'
        ]
        
        try:
            result = _run_aws_cli(describe_task_cmd)
            
            # Check if we got task information back
            if not result.get('tasks'):
                print(f"While check task stop status, task {task_id} not found")
                return "NO_TASK"
                
            task = result['tasks'][0]
            last_status = task.get('lastStatus')
            
            # First check if the task is actually stopped
            if last_status != 'STOPPED':
                return "RUNNING"
                
            # Check containers for exit codes
            containers = task.get('containers', [])
            for container in containers:
                exit_code = container.get('exitCode')
                if exit_code is None or exit_code != 0:
                    return 'FAIL'

            return 'SUCCESS'
            
        except Exception as e:
            print(f"Error checking task status: {e}")
            return False
