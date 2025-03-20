from typing import Dict, List, Optional
from dataclasses import dataclass
import copy
from file_manager import FileManager
import os
import datetime
import boto3
from ddb_handler import DynamoDBHandler

from enum import Enum, unique

@unique
class UserNodeStatus(Enum):
    AVAILABLE = "AVAILABLE"
    UNAVAILABLE = "UNAVAILABLE"
    ASSIGNED = "ASSIGNED"
    UNKNOWN = "UNKNOWN"



@dataclass
class NodeInfo:
    name: str
    # ip: str
    # ibdev: List[str]
    num_gpus: int = 8
    status: bool = False
    container_inst_id: str = ""


def singleton(cls):
    instances = {}
    def get_instance(*args, **kwargs):
        if cls not in instances:
            instances[cls] = cls(*args, **kwargs)
        return instances[cls]
    return get_instance


@singleton
class NodeManager:
    def __init__(self):
        print('Node Manager initiated..')
        # self.node_config = FileManager.load_yaml(os.environ['NODE_MAPPING_PATH'])
        self.node_ibdev_str = os.environ.get('IB_DEV_LIST', "mlx5_10,mlx5_11,mlx5_12,mlx5_13")
        self.node_names = os.environ.get('NODE_NAME_LIST', "A800_node001,A800_node002").split(',')
        self.cluster_name = os.environ.get('CLUSTER_NAME', 'default-cluster')
        self.ecs_client = boto3.client('ecs')
        
        # Initialize STATIC node information from config
        self.nodes = {
            name: NodeInfo(
                name=name,
                # ip=info['ip']
                # ibdev=info['ibdev']
            )
            for name in self.node_names
            # for name, info in self.node_config.items()
        }

        # self.refresh_all_node_status()
        self.assigned_nodes = set()
        self.spare_nodes = set()
        physical_available_node_names = self.get_physical_available_node_names()
        self.spare_nodes.update(physical_available_node_names)

        self.healthcheck_locked_instances = set()


    def lock_healthcheck_instances(self, container_inst_ids):
        self.healthcheck_locked_instances.update(container_inst_ids)

    def unlock_healthcheck_instances(self, container_inst_ids):
        self.healthcheck_locked_instances.difference_update(container_inst_ids)

    def clear_healthcheck_instances(self):
        # self.healthcheck_locked_instances.difference_update(container_inst_ids)
        self.healthcheck_locked_instances.clear()

    
    def get_physical_available_node_names(self) -> List[str]:
        self.refresh_all_node_status()
        physical_available_node_names = list(filter(lambda key: self.nodes[key].status == True, self.nodes.keys()))
        return physical_available_node_names


    def refresh_all_node_status(self):
        container_instance_arns = []
        paginator = self.ecs_client.get_paginator('list_container_instances')

        for page in paginator.paginate(cluster=self.cluster_name):
            container_instance_arns.extend(page['containerInstanceArns'])

        if container_instance_arns:
            desp_response = self.ecs_client.describe_container_instances(
                    cluster=self.cluster_name,
                    containerInstances=container_instance_arns,
                    # include=['TAGS']  # Include tags in the response
                )

            for i, inst_arn in enumerate(container_instance_arns):
                container_instance_id = inst_arn.split('/')[-1]
                node_name = None
                
                # 首先找到Node属性和对应的节点名称
                for attrdict in desp_response['containerInstances'][i]['attributes']:
                    if attrdict['name'] == 'Node':
                        node_name = attrdict['value']
                        break
                
                # 只有当节点名称在self.nodes中存在时才继续处理
                # print(node_name)
                if node_name and node_name in self.nodes.keys():
                    # 更新container_instance_id
                    self.nodes[node_name].container_inst_id = container_instance_id
                    
                    # 获取物理状态
                    node_physical_status = desp_response['containerInstances'][i]['status']
                    
                    # 初始化GPU数量
                    registered_gpu = 0
                    remain_gpu = 0
                    
                    # 获取注册的GPU数量
                    for item in desp_response['containerInstances'][i]['registeredResources']:
                        if item['name'] == 'GPU':
                            registered_gpu = len(item['stringSetValue'])
                            self.nodes[node_name].num_gpus = registered_gpu
                            break
                    
                    # 获取剩余的GPU数量
                    for item in desp_response['containerInstances'][i]['remainingResources']:
                        if item['name'] == 'GPU':
                            remain_gpu = len(item['stringSetValue'])
                            break
                    
                    # 判断节点是否可用
                    node_usable = registered_gpu == remain_gpu and node_physical_status == 'ACTIVE'
                    self.nodes[node_name].status = node_usable
                    
                    # 如果节点不可用，从spare_nodes中移除
                    if not node_usable and node_name in self.spare_nodes:
                        self.spare_nodes.remove(node_name)
                    
                    print(container_instance_id, node_name, node_physical_status, registered_gpu, remain_gpu, node_usable)

        return



    ## Node assignment during node assignment
    ## release above temperary status
    def release_all_node_names(self) -> None:
        self.assigned_nodes.clear()
        self.healthcheck_lock_nodes.clear()
        self.spare_nodes.clear()
        # self.refresh_all_node_status()
        # physical_available_node_names = self.get_physical_available_node_names()
        self.spare_nodes.update(self.nodes.keys())
        return


    def assign_a_node_name(self) -> str:
        node_name = self.spare_nodes.pop()
        self.assigned_nodes.add(node_name)
        # self.update_node_status(node_name, UserNodeStatus.ASSIGNED.value)
        return node_name


    def get_node_address(self, node_name):
        return '.'.join(self.nodes.get(node_name).name.split('-')[1:5])

    def fetch_node_name(self, container_inst_id: str):
        for node_name in self.nodes.keys():
            if self.nodes[node_name].container_inst_id == container_inst_id:
                return node_name
        return None

    def get_node_status_display(self) -> List[List[str]]:
        """Get node status data for UI display, fetching from DDB"""
    
        data = []
        physical_available_node_names = self.get_physical_available_node_names()

        for node_name in self.nodes.keys():
            is_avl = False
            if node_name in physical_available_node_names:
                is_avl = True
            
            data.append([
                node_name,
                self.nodes[node_name].container_inst_id,
                self.get_node_address(node_name),
                f"✅ AVAILABLE" if is_avl else f"⬜ UNAVAILABLE"
            ])

        return data








    # def get_node_names(self) -> List[str]:
    #     return list(self.nodes.keys())

    # def get_spare_node_names(self) -> List[str]:
    #     self.refresh_all_node_status()
    #     return list(self.spare_nodes.keys())

    # def get_assigned_node_names(self) -> List[str]:
    #     self.refresh_all_node_status()
    #     return list(self.assigned_nodes.keys())

    # def assign_node_name(self, node_name: str) -> None:
    #     node = self.spare_nodes.pop(node_name)
    #     self.assigned_nodes[node_name] = node
    #     self.update_node_status(node_name, UserNodeStatus.ASSIGNED.value)



    # def release_node_name(self, node_name: str) -> None:
    #     node = self.assigned_nodes.pop(node_name)
    #     self.spare_nodes[node_name] = node
    #     self.update_node_status(node_name, UserNodeStatus.AVAILABLE.value)


    # def validate_node_count(self, requested_nodes: int) -> Optional[str]:
    #     if requested_nodes > len(self.nodes):
    #         return f"Error: Requested {requested_nodes} nodes but only {len(self.nodes)} available"
    #     return None




    # # Update DYNAMIC node information from physical node status
    # def refresh_all_node_status(self):
    #     # self.cluster_name
    #     # self.ecs_client

    #     self.release_all_node_names()

    #     container_instance_arns = []
    #     paginator = self.ecs_client.get_paginator('list_container_instances')

    #     for page in paginator.paginate(cluster=self.cluster_name):
    #         container_instance_arns.extend(page['containerInstanceArns'])

    #     if container_instance_arns:
    #         desp_response = self.ecs_client.describe_container_instances(
    #                 cluster=self.cluster_name,
    #                 containerInstances=container_instance_arns,
    #                 # include=['TAGS']  # Include tags in the response
    #             )

    #         for i, inst_arn in enumerate(container_instance_arns):

    #             container_instance_id = inst_arn.split('/')[-1]
    #             node_usable = False

    #             for attrdict in desp_response['containerInstances'][i]['attributes']:
    #                 if attrdict['name'] == 'Node':
    #                     node_name = attrdict['value']
    #                     if node_name in self.nodes.keys():
    #                         self.nodes[node_name].container_inst_id = container_instance_id
                

    #             node_physical_status = desp_response['containerInstances'][i]['status']

    #             for item in desp_response['containerInstances'][i]['registeredResources']:
    #                 if item['name'] == 'GPU':
    #                     registered_gpu = len(item['stringSetValue'])

    #                     self.nodes[node_name].num_gpus = registered_gpu

    #             for item in desp_response['containerInstances'][i]['remainingResources']:
    #                 if item['name'] == 'GPU':
    #                     remain_gpu = len(item['stringSetValue'])

    #             if registered_gpu == remain_gpu and node_physical_status == 'ACTIVE':
    #                 node_usable = True
    #                 self.nodes[node_name].status = True
    #             else:
    #                 self.nodes[node_name].status = False
    #                 self.spare_nodes.remove(node_name)

    #             print(container_instance_id, node_name, node_physical_status, registered_gpu, remain_gpu, node_usable)
        

        

    #     return

    
    # def get_ibdev_list(self, node_name: str) -> List[str]:
    #     return self.nodes.get(node_name).ibdev