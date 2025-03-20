from datetime import datetime
from typing import List, Dict, Optional
from dataclasses import dataclass
import os
import copy

import boto3
from datetime import datetime

from file_manager import FileManager
from dist_command_generator import DistCommandGenerator
from task_manager import TaskManager


@dataclass
class HealthCheck:
    node_id: str
    timestamp: str
    status: str


class HealthManager:
    def __init__(self):
        self.task_manager = TaskManager()
        self.command_generator = DistCommandGenerator()

    
    def generate_healthcheck_savepath(self):
        timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        exec_history_save_path = f'_submit_history/Output-HealthAndConnectivtyCheck-{timestamp}'
        return exec_history_save_path, timestamp


    def setup_connectivity_host_file(self, hostname_list):
        os.system('mkdir -p /fsx/healthcheck/')
        hostfile_local_path = "/fsx/healthcheck/my_hosts"
        with open(hostfile_local_path, 'w') as f:
            f.write('\n'.join(hostname_list))



    def generate_precheck_scripts(self, num_nodes, exec_history_save_dir, health_check):

        dist_vars = self.command_generator.generate_dist_setting(
                                num_nodes,
                                exec_history_save_dir,
                                health_check
                                )

        print("generate_precheck_scripts - ", num_nodes, exec_history_save_dir, health_check)

        wrap_script_path = os.path.join(exec_history_save_dir, f"pre-health-dynamic.sh")
        FileManager.write_script(wrap_script_path, '\n'.join(dist_vars))

        precheck_task_def = self.generate_precheck_container_def(wrap_script_path)
        precheck_task_def_path = os.path.join(exec_history_save_dir, f"pre-health-task-def.json")
        FileManager.save_json(precheck_task_def_path, precheck_task_def)

        return precheck_task_def_path


        
    def generate_precheck_container_def(self, precheck_script_path):
        health_ecs_task_def = self.task_manager.get_ecs_task_def()

        health_container_def = self.task_manager.get_healthcheck_container_def()
        health_container_def['command'] = [f'/workspace/{precheck_script_path}']
        health_container_def['essential'] = True

        health_ecs_task_def['containerDefinitions'] = [health_container_def]

        return health_ecs_task_def



        




    ####################################


    def generate_healthcheck_container_def(self, node_index, dependent=True):
        health_container_def = self.task_manager.get_healthcheck_container_def()

        if node_index == 0:
            health_container_def['command'] = ['/healthcheck/healthCheckMain.sh']
        else:
            health_container_def['command'] = ['/healthcheck/healthCheckWorker.sh']
        
        if dependent:
            # health_container_def.pop('essential')
            health_container_def['essential'] = False

        return health_container_def



    def submit_health_check(self, hostname_list):
        save_path, timestampstr = self.generate_healthcheck_savepath()
        self.setup_connectivity_host_file(hostname_list)

        healthcheck_tasks = []

        for _, node_name in enumerate(reversed(hostname_list)):
            ecs_task_def = self.task_manager.get_ecs_task_def()
            node_index = hostname_list.index(node_name)

            health_container_def = self.generate_healthcheck_container_def(node_index)
            ecs_task_def['containerDefinitions'] = [health_container_def]

            node_task_def_path = os.path.join(save_path, f"task_def_{node_name}.json")
            FileManager.save_json(node_task_def_path, ecs_task_def)

            healthcheck_task_id, *_ = TaskManager.task_register_and_exec(node_task_def_path)
            healthcheck_tasks.append(healthcheck_task_id)

        return healthcheck_tasks








    '''


        for slvnode in hostname_list[1:]:
            health_container_def = self.task_manager.get_healthcheck_container_def()
            health_container_def['logConfiguration']['options']['awslogs-group'] = ecs_task_def['family']
            health_container_def['command'] = ['/healthcheck/healthCheckWorker.sh']

            slv_task_def_path = savepath + f'/Worker-{slvnode}-healthcheck-def.json'
            FileManager.save_json(slv_task_def_path, health_container_def)
            healthcheck_slv_task_id, *_ = TaskManager.task_register_and_exec(slv_task_def_path)
            healthcheck_tasks.append(healthcheck_slv_task_id)

        health_container_def = self.task_manager.get_healthcheck_container_def()
        health_container_def['logConfiguration']['options']['awslogs-group'] = ecs_task_def['family']
        health_container_def['command'] = ['/healthcheck/healthCheckMain.sh']

        master_task_def_path = savepath + f'/Master-{slvnode}-healthcheck-def.json'
        FileManager.save_json(master_task_def_path, health_container_def)
        healthcheck_master_task_id, *_ = TaskManager.task_register_and_exec(master_task_def_path)
        healthcheck_tasks.append(healthcheck_master_task_id)

        return healthcheck_tasks

    
        ecs_task_def['placementConstraints'][0]['expression'] = f"attribute:node=={node_name}"
        

        training_container_def = self.task_manager.get_training_container_def()
        training_container_def['image'] = task_config['image']
        training_container_def['logConfiguration']['options']['awslogs-group'] = f'/ecs/{task_config['family']}'
        training_container_def['command'] = ['/workspace/'+train_script_path]
        
        health_container_def = self.task_manager.get_healthcheck_container_def()
        health_container_def['logConfiguration']['options']['awslogs-group'] = f'/ecs/{task_config['family']}'
        if node_index == 0:
            health_container_def['command'] = ['/healthcheck/healthCheckMaster.sh']
        else:
            health_container_def['command'] = ['/healthcheck/healthCheckWorker.sh']




        task_def_template = FileManager.load_json('healthcheck_scripts/hybridGpuHealthCheck-task-definition.json')

        master_def = copy.deepcopy(task_def_template)
        master_def["containerDefinitions"][0]["command"][0] = "/healthcheck/healthCheckMaster.sh"

        savepath, timestampstr = self.generate_healthcheck_savepath()



        healthcheck_tasks = []
        
        for slvnode in hostname_list[1:]:
            slv_task_def = copy.deepcopy(task_def_template)
            slv_task_def["containerDefinitions"][0]["command"][0] = "/healthcheck/healthCheckSlave.sh"

            slv_task_def_path = savepath + f'/slave-{slvnode}-healthcheck-def.json'
            FileManager.save_json(slv_task_def_path, slv_task_def)
            healthcheck_slv_task_id, *_ = TaskManager.task_register_and_exec(slv_task_def_path)
            healthcheck_tasks.append(healthcheck_slv_task_id)

        mst_task_def_path = savepath + f'/master-{hostname_list[0]}-healthcheck-def.json'
        # print(mst_task_def_path)
        # print(master_def)
        FileManager.save_json(mst_task_def_path, master_def)
        healthcheck_master_task_id, *_ = TaskManager.task_register_and_exec(mst_task_def_path)

        # insert master task id
        healthcheck_tasks = [healthcheck_master_task_id] + healthcheck_tasks

        return healthcheck_tasks

    '''

