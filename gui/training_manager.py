from datetime import datetime
import os
import re
from typing import List, Dict, Any, Tuple, Optional

from file_manager import FileManager
from dist_command_generator import DistCommandGenerator
from node_manager import NodeManager
from task_manager import TaskManager
from job_manager import JobManager
# from job_manager import Job
from health_manager import HealthManager
from ddb_handler import DynamoDBHandler

import boto3
from datetime import datetime
from decimal import Decimal


import subprocess
import json
import boto3


def _convert_floats_to_decimal(obj):
    if isinstance(obj, float):
        return Decimal(str(obj))  # Convert float to string first for precision
    elif isinstance(obj, dict):
        return {k: _convert_floats_to_decimal(v) for k, v in obj.items()}
    elif isinstance(obj, list):
        return [_convert_floats_to_decimal(item) for item in obj]
    return obj




class TrainingManager:
    def __init__(self):
        # self.ddb_handler = DynamoDBHandler()
        self.job_ddb_table_name = os.environ.get('JOB_MANAGE_TABLE')
        self.task_ddb_table_name = os.environ.get('TASK_MANAGE_TABLE')
        self.node_manager = NodeManager()
        self.health_manager = HealthManager()
        self.task_manager = TaskManager()
        self.command_generator = DistCommandGenerator()
        # self.nodes = self.node_manager.get_node_names()
        self.job_manager = JobManager()


    def generate_job_id(self, base_job_name):
        timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        # output_dir = f"training_output_{timestamp}"
        job_id = f"{base_job_name}-{timestamp}-{os.urandom(4).hex()}"
        exec_history_save_path = f'_submit_history/output-scripts-{job_id}'
        return job_id, exec_history_save_path, timestamp


    def assign_job_nodes(self, num_nodes):
        master_node_name = self.node_manager.assign_a_node_name()

        all_node_names = [master_node_name]

        for _ in range(num_nodes-1):
            node_name = self.node_manager.assign_a_node_name()
            all_node_names.append(node_name)

        return all_node_names

    def assign_master_node(self):
        master_node_name = self.node_manager.assign_a_node_name()
        return master_node_name


    def generate_nodes_script(self, 
                              num_nodes, 
                              master_port, 
                              user_script_path, 
                              exec_history_save_dir,
                            is_health_check
                              ):
        
        # print('Assigned node name: ', node_name)
        
        script_content = self.command_generator.generate_dist_wrapper_script(num_nodes, 
                                                                             master_port,
                                                                             user_script_path,
                                                                             exec_history_save_dir,
                                                                             is_health_check
                                                                             )




        # script_content = self.command_generator.generate_script_content(command)
        # script_path = os.path.join(output_dir, f"training-{node_name}.sh")
        wrap_script_path = os.path.join(exec_history_save_dir, f"training-rdzv.sh")
        
        FileManager.write_script(wrap_script_path, script_content)

        node_task_def_path = self.construct_node_task_def(None, -99, master_port, wrap_script_path, None, exec_history_save_dir)

        return node_task_def_path

    


    def construct_node_task_def(self, node_name: str, node_index: int, master_port: int, train_script_path: str, task_config: Dict[str, str], output_dir: str):
        
        ecs_task_def = self.task_manager.get_ecs_task_def()
        # ecs_task_def['family'] = task_config['family']

        # ecs_task_def['placementConstraints'] = [{"type": "memberOf","expression": f"attribute:node_name=={node_name}"}]
        

        training_container_def = self.task_manager.get_training_container_def()
        # training_container_def['image'] = task_config['image']
        training_container_def['portMappings'][0]['containerPort'] = int(master_port)
        training_container_def['portMappings'][0]['hostPort'] = int(master_port)
        # training_container_def['logConfiguration']['options']['awslogs-group'] = task_config['logGroup']
        training_container_def['command'] = ['/workspace/'+train_script_path]


        # if task_config['traininghealth_check']:
        #     health_container_def = self.health_manager.generate_healthcheck_container_def(node_index, dependent=True)
        #     training_container_def['dependsOn'] = [{"containerName": health_container_def['name'], "condition": "COMPLETE"}]
        #     training_container_def['essential'] = True
        #     ecs_task_def['containerDefinitions'] = [health_container_def, training_container_def]
        # else:
        #     ecs_task_def['containerDefinitions'] = [training_container_def]

        ecs_task_def['containerDefinitions'] = [training_container_def]

        # node_task_def_path = os.path.join(output_dir, f"task_def_{node_name}.json")
        node_task_def_path = os.path.join(output_dir, f"task_def_rdzv.json")
        FileManager.save_json(node_task_def_path, ecs_task_def)

        return node_task_def_path


    def get_summary(self, timestamp: str, num_nodes: int, master_port: str, 
                   output_dir: str, entry_script_path: str) -> Dict[str, Any]:
        return {
            "Timestamp": timestamp,
            "Number of Nodes": num_nodes,
            "Master Port": master_port,
            "Execution History Directory": output_dir,
            "User Entry Script Path": os.path.basename(entry_script_path)
        }









    # def register_task_and_run_all(self, 
    #                   job_id,
    #                   job_timestamp,
    #                   num_nodes,
    #                   task_def_path,
    #                   exec_history_save_dir
    #                 ):
        
    #     all_commands = []
    #     container_inst_ids = []
    #     ecs_task_ids = []
    #     orch_node_names = []

    #     task_def_arn, reg_task_cmd = TaskManager.task_register(task_def_path)
    #     all_commands.append(reg_task_cmd)

    #     for _ in range(num_nodes):
    #         task_id, cluster_name, container_inst_id, exec_result, exec_task_cmd = TaskManager.task_exec(task_def_arn)

    #         node_name_orchestrated = self.node_manager.fetch_node_name(container_inst_id)
    #         print(f"Training task {task_id} launched for node {node_name_orchestrated}")

    #         TaskManager.record_task_to_ddb(
    #             task_id = task_id,
    #             node_name_orchestrated = node_name_orchestrated,
    #             node_index = -1,
    #             job_id = job_id,
    #             job_timestamp = job_timestamp,
    #             nnodes = num_nodes,
    #             task_def_arn = task_def_arn,
    #             cluster_name = cluster_name,
    #             container_inst_id = container_inst_id,
    #         )

    #         all_commands.append(exec_task_cmd)
    #         container_inst_ids.append(container_inst_id)
    #         ecs_task_ids.append(task_id)
    #         orch_node_names.append(node_name_orchestrated)

    #     history_file = FileManager.create_execution_history(exec_history_save_dir, all_commands)
    #     print('history_file', history_file)

    #     ## if Each node is assigned a task, write to job
    #     if len(ecs_task_ids) == num_nodes:
    #         self.gather_task_and_record_job(
    #             job_id, job_timestamp, cluster_name, num_nodes, orch_node_names, container_inst_ids, ecs_task_ids
    #         )

    #     return ecs_task_ids, orch_node_names, history_file


    # def gather_task_and_record_job(self, job_id, job_timestamp, cluster_name, num_nodes, assigned_nodes, container_inst_ids, ecs_task_ids):
    #     DynamoDBHandler.write_item(table_name = self.job_ddb_table_name, 
    #                                 item = {
    #                                     'job_id': job_id,
    #                                     'job_timestamp': job_timestamp,
    #                                     'cluster_name': cluster_name,
    #                                     'num_nodes': num_nodes,
    #                                     'assigned_nodes': assigned_nodes,
    #                                     'submittd_container_inst_ids': container_inst_ids,
    #                                     'submittd_ecs_task_ids': ecs_task_ids,
    #                                     'updated_at': datetime.now().isoformat(),
    #                                     'created_at': datetime.now().isoformat(),
    #                                     'retry': 0,
    #                                     'job_status': 'IN_PROGRESS',
    #                                 }
    #                             )

    #     return