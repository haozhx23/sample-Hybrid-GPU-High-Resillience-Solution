from dataclasses import dataclass
from datetime import datetime
from typing import List, Dict, Optional

import boto3, os
from datetime import datetime
from ddb_handler import DynamoDBHandler
from task_manager import TaskManager



@dataclass
class Job:
    id: str
    timestamp: str
    status: str
    num_nodes: int
    task_ids: List[str] = None  # List to store task IDs for each node


# def singleton(cls):
#     instances = {}
#     def get_instance(*args, **kwargs):
#         if cls not in instances:
#             instances[cls] = cls(*args, **kwargs)
#         return instances[cls]
#     return get_instance


# @singleton
class JobManager:
    # def __init__(self):
    #     self.jobs: List[Job] = []
        
    # def add_job_for_display(self, job: Job) -> None:
    #     self.jobs.append(job)

    @staticmethod
    def update_job_status(job_id: str, job_status: str) -> bool:
        """Update node status in DynamoDB"""
        try:
            success = DynamoDBHandler.update_item(
                table_name=os.environ['JOB_MANAGE_TABLE'],
                key={'job_id': job_id},
                update_expression="SET job_status = :s, updated_at = :t",
                expression_values={
                    ':s': job_status,
                    ':t': datetime.now().isoformat()
                }
            )
            if success:
                print(f"Updated job {job_id} status to {job_status} in DDB")
                return True
            return False
        except Exception as e:
            print(f"Error updating job status in DDB: {str(e)}")
            return False


    @staticmethod
    def gather_task_and_record_job(job_id, job_timestamp, num_nodes, assigned_nodes, container_inst_ids, ecs_task_ids, JOB_STATUS):
        
        DynamoDBHandler.write_item(table_name = os.environ['JOB_MANAGE_TABLE'], 
                                    item = {
                                        'job_id': job_id,
                                        'job_timestamp': job_timestamp,
                                        'cluster_name': os.environ['CLUSTER_NAME'],
                                        'num_nodes': num_nodes,
                                        'assigned_nodes': assigned_nodes,
                                        'submittd_container_inst_ids': container_inst_ids,
                                        'submittd_ecs_task_ids': ecs_task_ids,
                                        'updated_at': datetime.now().isoformat(),
                                        'created_at': datetime.now().isoformat(),
                                        'retry': 0,
                                        # 'job_status': 'IN_PROGRESS',
                                        'job_status': JOB_STATUS
                                    }
                                )

        return



    @staticmethod
    def get_job_associated_tasks_from_ddb(job_id: str):
        resp = DynamoDBHandler.get_item(os.environ['JOB_MANAGE_TABLE'], 
                                        {'job_id': job_id})
        
        return dict(zip(resp['submittd_ecs_task_ids'], resp['assigned_nodes']))

    @staticmethod
    def stop_job(job_id: str) -> bool:
        job_tasks = JobManager.get_job_associated_tasks_from_ddb(job_id)
        
        for taskid in job_tasks.keys():
            try:
                if TaskManager.is_task_running(taskid):
                    resp = TaskManager.stop_ecs_task(taskid)

                    # if resp['task']['stopCode'] == "EssentialContainerExited":
                    #     NodeManager().update_node_status(job_tasks[taskid], UserNodeStatus.AVAILABLE.value)
                    # else:
                    #     NodeManager().update_node_status(job_tasks[taskid], UserNodeStatus.UNKNOWN.value)

                    # print('STOP RESP: ', resp)

                    JobManager.update_job_status(job_id, 'USER_STOPPED')
                else:
                    print(f"Task {taskid} is not running")

            except Exception as e:
                # Keep stop other tasks
                print(f"Error stopping tasks {taskid}: {str(e)}")
                # NodeManager().update_node_status(job_tasks[taskid], UserNodeStatus.UNKNOWN.value)
            
        

        return True

    @staticmethod
    def get_jobs_data() -> List[List[str]]:
        """
        Retrieves the latest 10 jobs data from DynamoDB table using job_id as primary key and status as a key field.
        Returns formatted job data for display.
        """
        try:
            # Get all jobs from DynamoDB table
            jobs_data = DynamoDBHandler.scan_table(os.environ['JOB_MANAGE_TABLE'])
            
            if not jobs_data:
                return []
            
            # Sort jobs by timestamp (most recent first)
            # Use created_at if available, otherwise fall back to job_timestamp
            sorted_jobs = sorted(
                jobs_data,
                key=lambda job: job.get('created_at', job.get('job_timestamp', '')),
                reverse=True
            )
            
            # Take only the latest N jobs
            latest_jobs = sorted_jobs[:5]

            # Format the data for display
            return [
                [
                    job.get('job_id', 'N/A'),
                    job.get('job_timestamp', 'N/A'),
                    job.get('job_status', 'N/A'),
                    str(job.get('num_nodes', 0)),
                    '\n'.join(job.get('submittd_ecs_task_ids', [])) if job.get('submittd_ecs_task_ids') else 'N/A'
                ]
                for job in latest_jobs
            ]
        except Exception as e:
            print(f"Error retrieving jobs data from DynamoDB: {str(e)}")
            return []
