import gradio as gr
import time
import os
import json
import logging
from datetime import datetime
from typing import Tuple, List, Dict, Any, Optional
from threading import Lock
from pathlib import Path

# Import managers
from node_manager import NodeManager
from training_manager import TrainingManager
from health_manager import HealthManager
from job_manager import Job, JobManager
from task_manager import TaskManager
from cloudwatch_manager import CloudWatchManager
from file_manager import FileManager

import threading

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


def get_login_user(request: gr.Request):
    return f"{request.username}"


# Constants
APP_TITLE = "Hybrid-GPU Training Console"
DEFAULT_PORT = 7860

# task_manager = TaskManager()

class EnhancedTrainingGUI:
    def __init__(self):
        self.job_manager = JobManager()
        self.health_manager = HealthManager()
        self.cloudwatch_manager = CloudWatchManager()
        self.task_manager = TaskManager()
        self.node_manager = NodeManager()
        self.submission_lock = Lock()
        self.training_manager = None
        logger.info("EnhancedTrainingGUI initialized")

    def launch_training(self, 
                      base_job_name: str, 
                      num_nodes: int, 
                      master_port: str, 
                      user_script_path: str, 
                      ecs_cluster_name: str,
                      family: str,
                      container_name: str,
                      image: str,
                      container_workdir: str,
                      host_workdir: str,
                      health_check_checkbox: bool,
                      progress=gr.Progress()) -> Tuple[gr.Markdown, List[List[str]]]:
        if not self.submission_lock.acquire(blocking=False):
            logger.warning("Another job submission is in progress")
            return (
                gr.Markdown("⚠️ Another job submission is in progress. Please wait."),
                None
            )

        try:
            logger.info(f"Launching training job: {base_job_name} with {num_nodes} nodes")
            self.training_manager = TrainingManager()
            progress(0, desc="Initializing...")
            
            # ui_task_config = {
            #     # 'family': family,
            #     # 'image': image,
            #     'traininghealth_check': health_check_checkbox
            # }
            
            progress(0.1, desc="Generating Job ID...")
            job_id, exec_history_save_dir, job_timestamp = self._generate_job_id(base_job_name)
            
            progress(0.2, desc="Assigning nodes...")
            # all_node_names = self._assign_job_nodes(num_nodes)
            # master_node_name = self._assign_job_master()
            # logger.info(f"Assigned master node: {master_node_name}")

            train_job_settings_pack = {
                'job_id': job_id,
                'job_timestamp': job_timestamp,
                'num_nodes': num_nodes,
                'master_port': master_port,
                'user_script_path': user_script_path,
                'exec_history_save_dir': exec_history_save_dir,
                'health_check_checkbox': health_check_checkbox
            }
            
            if health_check_checkbox:
                progress(0.3, desc="Setting up health check...")
                # self._setup_health_check([])
                
                progress(0.35, desc="Generating health check scripts...")
                precheck_task_def_path = self.health_manager.generate_precheck_scripts(
                    num_nodes, exec_history_save_dir, True
                )
                
                precheck_job_id = job_id+'-precheck'
                progress(0.4, desc="Submit health check Tasks...")
                precheck_task_ids, orch_node_names, container_inst_ids, precheck_history_file_path = self._run_all_tasks(
                    precheck_job_id,
                    job_timestamp,
                    num_nodes,
                    precheck_task_def_path,
                    exec_history_save_dir
                )
                
                progress(0.4, desc="Record HealthCheck Job...")
                self._record_job(
                    precheck_task_ids,
                    num_nodes,
                    precheck_job_id,
                    job_timestamp,
                    orch_node_names,
                    container_inst_ids,
                    'PRE_CHECKING'
                )

                ## Lock all instances for following training
                self.node_manager.lock_healthcheck_instances(container_inst_ids)

                self.node_manager.refresh_all_node_status()
                
                results = self._prepare_results(
                    orch_node_names,
                    precheck_task_def_path,
                    precheck_task_ids,
                    exec_history_save_dir,
                    precheck_job_id
                )


                ## Launch a background thread to polling the healthCheck job/tasks status 
                #   + submit training
                #   + record tasks to ddb
                #   + change job status on ddb existing item 

                training_job_thread = threading.Thread(
                    target = self._background_launch_training_job_after_precheck,
                    kwargs={'job_id': job_id,
                            'precheck_job_id': precheck_job_id,
                            'precheck_task_ids': precheck_task_ids,
                            'container_inst_ids': container_inst_ids,
                            'train_job_settings_pack': train_job_settings_pack
                            }
                )

                training_job_thread.start()

                
                node_data = self.node_manager.get_node_status_display()
                progress(1.0, desc="Complete!")
                return (
                    gr.Markdown("\n".join(results)),
                    node_data
                )


            progress(0.5, desc="Generating task definitions...")
            task_def_path = self._generate_nodes_script(
                num_nodes,
                master_port,
                user_script_path,
                exec_history_save_dir,
                health_check_checkbox
            )
            
            progress(0.7, desc="Launching training tasks...")
            training_task_ids, orch_node_names, container_inst_ids, history_file_path = self._run_all_tasks(
                job_id,
                job_timestamp,
                num_nodes,
                task_def_path,
                exec_history_save_dir
            )

            progress(0.8, desc="Record whole training job to DDB...")
            self._record_job(
                    training_task_ids,
                    num_nodes,
                    job_id,
                    job_timestamp,
                    orch_node_names,
                    container_inst_ids,
                    'IN_PROGRESS'
                )
            
            progress(0.9, desc="Refreshing node status...")
            self.node_manager.refresh_all_node_status()
            
            results = self._prepare_results(
                orch_node_names,
                task_def_path,
                training_task_ids,
                history_file_path,
                job_id
            )
            
            node_data = self.node_manager.get_node_status_display()

            #job_data = self.refresh_job_status()
            
            progress(1.0, desc="Complete!")
            return (
                gr.Markdown("\n".join(results)),
                node_data
            )
                
        except Exception as e:
            logger.error(f"Error launching training: {str(e)}", exc_info=True)
            return (
                gr.Markdown(f"⚠️ Error: {str(e)}"),
                None
            )
        finally:
            self.submission_lock.release()



    def _background_launch_training_job_after_precheck(self, job_id, precheck_job_id, precheck_task_ids, container_inst_ids, train_job_settings_pack):
        retry_interval=10
        retry_times=60
        timeout = retry_interval*retry_times

        succeed_healthcheck_tasks = []
        for i in range(retry_times):
            print(f"Background polling Pre-HealthChecking Status {i} times.")

            for taskid in precheck_task_ids:

                if taskid in succeed_healthcheck_tasks:
                    continue

                taskstatus = TaskManager.check_task_stop_status(taskid)
                if taskstatus == 'FAIL':
                    ## TODO keep locking healthcheck failed instance
                    self.node_manager.clear_healthcheck_instances()

                    JobManager.update_job_status(precheck_job_id, 'PRE_CHECKING_FAIL')

                    print(f"Find Pre Health Check Failed on task - {taskid}. Stop Launching Training Job.")
                    return 

                elif taskstatus == 'RUNNING':
                    continue
                elif taskstatus == 'SUCCESS':
                    succeed_healthcheck_tasks.append(taskid)

            if len(set(succeed_healthcheck_tasks)) == len(precheck_task_ids):
                ## TODO
                ## call ecs start-tasks provided with container instance ids
                
                task_def_path = self._generate_nodes_script(
                    train_job_settings_pack['num_nodes'],
                    train_job_settings_pack['master_port'],
                    train_job_settings_pack['user_script_path'],
                    train_job_settings_pack['exec_history_save_dir'],
                    train_job_settings_pack['health_check_checkbox']
                )
                
                training_task_ids, orch_node_names, container_inst_ids, history_file_path = self._run_all_tasks(
                    job_id,
                    train_job_settings_pack['job_timestamp'],
                    train_job_settings_pack['num_nodes'],
                    task_def_path,
                    train_job_settings_pack['exec_history_save_dir'],
                    container_inst_ids
                )
                
                ## Change health check job to Done
                JobManager.update_job_status(precheck_job_id, 'PRE_CHECKING_DONE')
                ## Add training JOB IN_PROGRESS
                JobManager.gather_task_and_record_job(job_id, 
                                                      train_job_settings_pack['job_timestamp'],
                                                      train_job_settings_pack['num_nodes'], 
                                                      orch_node_names, 
                                                      container_inst_ids, 
                                                      training_task_ids, 
                                                      "IN_PROGRESS")


                ## Unlock instances after task launched for re-assign
                self.node_manager.unlock_healthcheck_instances(container_inst_ids)
                
                self.node_manager.refresh_all_node_status()

                return 

            time.sleep(retry_interval)
        return


    def _generate_job_id(self, base_job_name: str) -> Tuple[str, str, str]:
        try:
            return self.training_manager.generate_job_id(base_job_name)
        except Exception as e:
            logger.error(f"Error generating job ID: {str(e)}", exc_info=True)
            raise RuntimeError(f"Failed to generate job ID: {str(e)}")

    def _assign_job_nodes(self, num_nodes: int) -> List[str]:
        try:
            return self.training_manager.assign_job_nodes(num_nodes)
        except Exception as e:
            logger.error(f"Error assigning job nodes: {str(e)}", exc_info=True)
            raise RuntimeError(f"Failed to assign job nodes: {str(e)}")

    def _assign_job_master(self) -> List[str]:
        try:
            return self.training_manager.assign_master_node()
        except Exception as e:
            logger.error(f"Error assigning job nodes: {str(e)}", exc_info=True)
            raise RuntimeError(f"Failed to assign job nodes: {str(e)}")

    
    def _setup_health_check(self, node_names: List[str]) -> None:
        try:
            self.health_manager.setup_connectivity_host_file(node_names)
        except Exception as e:
            logger.error(f"Error setting up health check: {str(e)}", exc_info=True)
            raise RuntimeError(f"Failed to setup health check: {str(e)}")


    def _generate_nodes_script(self, 
                             num_nodes: int,
                             master_port: str,
                             user_script_path: str,
                             exec_history_save_dir: str,
                             is_health_check: bool
                             ) -> List[str]:
        try:
            return self.training_manager.generate_nodes_script(
                num_nodes,
                master_port,
                user_script_path,
                exec_history_save_dir,
                is_health_check
            )

        except Exception as e:
            logger.error(f"Error generating node scripts: {str(e)}", exc_info=True)
            raise RuntimeError(f"Failed to generate node scripts: {str(e)}")


    def _run_all_tasks(self,
                     job_id: str,
                     job_timestamp: str,
                     num_nodes: int,
                     task_def_path: str,
                     exec_history_save_dir: str,
                     container_inst_ids: List[str] = None
                     ) -> Tuple[List[str], str]:
        try:
            return TaskManager.register_task_and_run_all(
                job_id,
                job_timestamp,
                num_nodes,
                task_def_path,
                exec_history_save_dir,
                container_inst_ids
            )
        except Exception as e:
            logger.error(f"Error running tasks: {str(e)}", exc_info=True)
            raise RuntimeError(f"Failed to run tasks: {str(e)}")


    def _record_job(self,
        ecs_task_ids,
        num_nodes,
        job_id,
        job_timestamp,
        orch_node_names,
        container_inst_ids,
        JOB_STATUS
    ):
        try:
            # ## if Each node is assigned a task, write to job
            if len(ecs_task_ids) == num_nodes:
                JobManager.gather_task_and_record_job(
                    job_id, job_timestamp, num_nodes, orch_node_names, container_inst_ids, ecs_task_ids, JOB_STATUS
                )
            else:
                logger.error(f"Tasks belongs to the job do not completely submitted")
        except Exception as e:
            logger.error(f"Error recording job: {str(e)}", exc_info=True)
            raise RuntimeError(f"Failed to record job: {str(e)}")


    def _prepare_results(self,
                       node_names: List[str],
                       task_def_path: str,
                       training_task_ids: List[str],
                       history_file_path: str,
                       job_id: str) -> List[str]:
        results = []
        
        for i, node_name in enumerate(node_names):
            results.append(f"\n🔷 Dispatched to Node: {node_name}")
        
        results.append(f"\n  └─ Register & Execute: `{task_def_path}`")

        results.append(f"\n📝 Execution history saved to: `{history_file_path}`")
        results.append(f"\n🔍 Job ID: {job_id}")
        
        if training_task_ids:
            results.append(f"\n  └─ Task IDs: `{training_task_ids}`")
            
        return results

    def launch_health_check(self, master_node_name: str, other_nodes_values: str) -> Tuple[str, List[List[str]]]:
        try:
            logger.info(f"Launching health check for master node: {master_node_name}")
            
            all_node_names = [master_node_name]
            
            if other_nodes_values:
                other_nodes_list = other_nodes_values.split(',')
                for node in other_nodes_list:
                    node_name = node.strip()
                    if node_name:
                        all_node_names.append(node_name)
            
            logger.info(f"Health check nodes: {all_node_names}")
            
            healthcheck_task_ids = self.health_manager.submit_health_check(all_node_names)
            
            output = f"Health check submitted for nodes: {', '.join(all_node_names)}"
            output += f"\nTask IDs: {', '.join(healthcheck_task_ids)}"
            
            history = self.health_manager.get_health_check_history()
            
            return output, history
            
        except Exception as e:
            logger.error(f"Error launching health check: {str(e)}", exc_info=True)
            return f"⚠️ Error: {str(e)}", []

    def refresh_job_status(self) -> List[List[str]]:
        try:
            return JobManager.get_jobs_data()
        except Exception as e:
            logger.error(f"Error refreshing job status: {str(e)}", exc_info=True)
            return [["Error", datetime.now().strftime("%Y-%m-%d %H:%M:%S"), f"Error: {str(e)}", "", ""]]

    def refresh_node_status(self) -> List[List[str]]:
        try:
            self.node_manager.refresh_all_node_status()
            return self.node_manager.get_node_status_display()
        except Exception as e:
            logger.error(f"Error refreshing node status: {str(e)}", exc_info=True)
            return [["Error", "", "", f"Error: {str(e)}"]]

    def release_all_nodes(self) -> List[List[str]]:
        try:
            self.node_manager.release_all_node_names()
            self.node_manager.refresh_all_node_status()
            return self.node_manager.get_node_status_display()
        except Exception as e:
            logger.error(f"Error releasing nodes: {str(e)}", exc_info=True)
            return [["Error", "", "", f"Error: {str(e)}"]]

    def view_task_logs(self, task_id: str, log_group: str, container_name: str) -> Tuple[str, str]:
        try:
            if not task_id:
                return "", "No task ID provided"
            
            logs = self.cloudwatch_manager.get_task_logs(task_id, log_group, container_name)
            
            escaped_logs = logs.replace('`', '\\`')
            return task_id, f"```\n{escaped_logs}\n```"

        except Exception as e:
            logger.error(f"Error viewing task logs: {str(e)}", exc_info=True)
            return "", f"Error fetching logs: {str(e)}"

    def _get_env_var(self, var_name: str, default: str = "") -> str:
        return os.environ.get(var_name, default)

    def _create_job_table(self, data: List[List[str]]) -> str:
        table_html = """
        <div class="interactive-table">
            <table>
                <thead>
                    <tr>
                        <th>Job ID</th>
                        <th>Timestamp</th>
                        <th>Status</th>
                        <th>Nodes</th>
                        <th>ECS Task ID</th>
                    </tr>
                </thead>
                <tbody>
        """
        
        for row in data:
            table_html += f"""
                <tr class="selectable-row">
                    <td>{row[0]}</td>
                    <td>{row[1]}</td>
                    <td>{row[2]}</td>
                    <td>{row[3]}</td>
                    <td>{row[4]}</td>
                </tr>
            """
            
        table_html += """
                </tbody>
            </table>
        </div>
        """
        return table_html

    def _create_node_table(self, data: List[List[str]]) -> str:
        table_html = """
        <div class="interactive-table">
            <table>
                <thead>
                    <tr>
                        <th>Node Name</th>
                        <th>Container Inst. ID</th>
                        <th>IP Address</th>
                        <th>Status</th>
                    </tr>
                </thead>
                <tbody>
        """
        
        for row in data:
            table_html += f"""
                <tr class="selectable-row">
                    <td>{row[0]}</td>
                    <td>{row[1]}</td>
                    <td>{row[2]}</td>
                    <td>{row[3]}</td>
                </tr>
            """
            
        table_html += """
                </tbody>
            </table>
        </div>
        """
        return table_html

    def get_custom_css(self) -> str:
        return """
        .container {
            max-width: 1200px !important;
            margin: auto;
        }
        .title {
            text-align: center;
            margin-bottom: 2em;
        }
        .status-ready {
            color: #28a745;
        }
        .status-error {
            color: #dc3545;
        }
        .interactive-table {
            margin: 1em 0;
            width: 100%;
            overflow-x: auto;
        }
        .interactive-table table {
            width: 100%;
            border-collapse: collapse;
            font-size: 14px;
        }
        .interactive-table th, .interactive-table td {
            padding: 8px 12px;
            border: 1px solid #ddd;
            text-align: left;
        }
        .interactive-table th {
            background-color: #f5f5f5;
            font-weight: bold;
        }
        .selectable-row {
            cursor: pointer;
            user-select: text;
        }
        .selectable-row:hover {
            background-color: #f8f9fa;
        }
        .selectable-row td {
            white-space: pre-wrap;
            word-break: break-word;
        }
        .gray-text input {
            color: #888888 !important;
        }
        .non-interactive-text input {
            background-color: #f0f0f0 !important;
            color: #666666 !important;
            border-color: #dddddd !important;
        }
        """



# UI Building functions - Refactored to separate UI creation from logic
class UIBuilder:
    def __init__(self, gui):
        self.gui = gui
        self.task_manager = TaskManager()

    def build_training_tab(self):
        with gr.Column():
            gr.Markdown("## 🚀 Launch Configuration")
            
            with gr.Row():
                with gr.Column(scale=1):
                    training_configs = self._build_training_configs_group()
                    file_paths = self._build_file_paths_group()

                with gr.Column(scale=1):
                    task_configs = self._build_task_configs_group()

            with gr.Row():
                with gr.Column(scale=5):
                    pass
                with gr.Column(scale=1):
                    launch_btn = gr.Button("🚀 Launch Training", variant="primary", min_width=200)

        with gr.Row():
            with gr.Column():
                gr.Markdown("## 📊 Job Submit Status")
                with gr.Tabs() as tabs:
                    with gr.TabItem("📝 Execution Trace"):
                        output_log = gr.Markdown("Click 'Launch Training' to begin.")
                    
                    with gr.TabItem("📡 Node Availablity") as node_assignment_tab:
                        with gr.Column():
                            with gr.Row():
                                refresh_node_btn = gr.Button("🔄 Refresh", variant="secondary")
                            node_status = gr.HTML(
                                label="Node Status Overview",
                                value=self._get_initial_node_table,
                                every=30
                            )

        # Connect event handlers
        self._connect_training_tab_events(
            launch_btn, 
            training_configs, 
            file_paths,
            task_configs,
            output_log,
            node_status,
            refresh_node_btn,
            node_assignment_tab
        )

        return {
            "output_log": output_log,
            "node_status": node_status
        }

    def _build_training_configs_group(self):
        with gr.Group():
            gr.Markdown("### 📊 Training Configs")
            base_job_name = gr.Textbox(
                label="Base Job Name",
                placeholder="torch-job",
                value="torch-job",
                info="This will be used as prefix for the job ID",
                container=False
            )
            num_nodes = gr.Number(
                minimum=1,
                label="Number of Nodes",
                value=1,
                info="Number of nodes to use for distributed training",
                container=False
            )
            master_port = gr.Textbox(
                label="Master Port",
                placeholder="10000",
                value="10000",
                info="An exclusive port number for inter-node communication",
                container=False
            )
            health_check_checkbox = gr.Checkbox(
                label="🏥 Health Check Before Training Job",
                value=False,
                info="Compute Instance Health & Connectivity checks"
            )
        
        return {
            "base_job_name": base_job_name,
            "num_nodes": num_nodes,
            "master_port": master_port,
            "health_check_checkbox": health_check_checkbox
        }

    def _build_file_paths_group(self):
        with gr.Group():
            gr.Markdown("### 📁 File Paths")
            
            node_mapping_path = gr.Text(
                value=self.gui._get_env_var('ECS_CLUSTER_CONF_PATH', ''),
                info="ECS Config file incl. task def. container def. and node info.",
                label="ECS Config Files", 
                interactive=False,
                elem_classes=["non-interactive-text"]
            )
            
            user_script_path = gr.Textbox(
                label="Customized Entry Script Path",
                placeholder="train-ddp.sh",
                value="train-ddp.sh",
                info="Path to user defined entry script, e.g. pip and torchrun train.py",
                container=False
            )
        
        return {
            "node_mapping_path": node_mapping_path,
            "user_script_path": user_script_path
        }

    def _build_task_configs_group(self):
        with gr.Group():
            gr.Markdown("### 📋 ECS Task Definition Configs")
            
            ecs_cluster_name = gr.Text(
                value=self.gui._get_env_var('CLUSTER_NAME', ''),
                info="Name of ECS Cluster Control Plane",
                label="ECS Cluster Name",
                interactive=False
            )
            
            family = gr.Textbox(
                label="Task Family",
                placeholder="training-task-family",
                value=self.task_manager.ecs_task_def['family'],
                info="`family` field in ECS Task Definition",
                interactive=False,
                container=False
            )
            
            container_name = gr.Textbox(
                label="Container Name",
                placeholder="training-container",
                value=self.task_manager.training_container_def['name'],
                info="`name` field in ECS Container Definition",
                interactive=False,
                container=False
            )
            
            image = gr.Textbox(
                label="Container Image",
                placeholder="training-image:latest",
                value=self.task_manager.training_container_def['image'],
                info="`image` field in ECS Container Definition",
                interactive=False,
                container=False
            )
            
            container_workdir = gr.Textbox(
                label="Container Working Directory",
                placeholder="/workspace",
                value="/workspace",
                info="Fixed as `/workspace` dir in container",
                interactive=False,
                container=False
            )

            host_workdir = gr.Textbox(
                label="Host Working Directory",
                placeholder="/path/to/workspace",
                value=os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                info="Host workspace dir that maps to container `/workspace` dir",
                interactive=False,
                container=False
            )
        
        return {
            "ecs_cluster_name": ecs_cluster_name,
            "family": family,
            "container_name": container_name,
            "image": image,
            "container_workdir": container_workdir,
            "host_workdir": host_workdir
        }

    def _get_initial_node_table(self):
        data = self.gui.refresh_node_status()
        return self.gui._create_node_table(data)

    def _connect_training_tab_events(self, 
                                   launch_btn, 
                                   training_configs, 
                                   file_paths, 
                                   task_configs,
                                   output_log,
                                   node_status,
                                   refresh_node_btn,
                                   node_assignment_tab):
        # Launch button click event
        launch_btn.click(
            fn=self.gui.launch_training,
            inputs=[
                training_configs["base_job_name"],
                training_configs["num_nodes"],
                training_configs["master_port"],
                file_paths["user_script_path"],
                task_configs["ecs_cluster_name"],
                task_configs["family"],
                task_configs["container_name"],
                task_configs["image"],
                task_configs["container_workdir"],
                task_configs["host_workdir"],
                training_configs["health_check_checkbox"]
            ],
            outputs=[
                output_log,
                node_status
            ]
        ).then(
            fn=self._refresh_node_table,
            outputs=[node_status]
        )

        # Refresh node button click event
        refresh_node_btn.click(
            fn=self._refresh_node_table,
            outputs=[node_status]
        )

        # Tab selection event
        node_assignment_tab.select(
            fn=self._refresh_node_table,
            outputs=[node_status]
        )

    def _refresh_node_table(self):
        data = self.gui.refresh_node_status()
        return self.gui._create_node_table(data)

    def build_health_check_tab(self):
        with gr.Row():
            gr.Markdown("Input Master Node Name")

        with gr.Row():
            master_node_name = gr.Textbox(
                label="Master Node Name",
                placeholder="Enter Master node Name",
                container=False,
            )
            
        with gr.Row():
            gr.Markdown('''Input Other Pairing Nodes (Separated by ",")''')
        
        with gr.Row():
            other_nodes_names = gr.Textbox(
                label="Other Pairing Nodes Names",
                placeholder='''Enter Pairing Nodes (Separated by ",")''',
                container=False,
            )
        
        with gr.Row():
            with gr.Column(scale=3):
                pass
            with gr.Column(scale=1):
                check_btn = gr.Button("Submit Health Check", variant="primary")
        
        health_output = gr.Markdown()
        health_check_history = gr.Dataframe(
            headers=["Node ID", "Timestamp", "Status"],
            label="Health Check History",
            value=[]
        )

        # Connect event handler
        check_btn.click(
            fn=self.gui.launch_health_check,
            inputs=[master_node_name, other_nodes_names],
            outputs=[health_output, health_check_history]
        )

        return {
            "health_output": health_output,
            "health_check_history": health_check_history
        }

    def build_job_status_tab(self):
        with gr.Column():
            with gr.Blocks(elem_classes="dashboard-card"):
                with gr.Column():
                    with gr.Row():
                        gr.Markdown("## 📋 Job Status", elem_classes="card-title")
                        
                    with gr.Row():
                        job_refresh_btn = gr.Button("🔄 Refresh", variant="secondary", elem_classes="action-button")
                    
                    job_status = gr.HTML(
                        value=self._get_initial_job_table,
                        every=30,
                        elem_classes="status-table"
                    )
                    
                    job_control = self._build_job_control_section()

            log_viewer = self._build_log_viewer_section()

        # Connect event handlers
        self._connect_job_status_tab_events(
            job_refresh_btn,
            job_status,
            job_control,
            log_viewer
        )

        return {
            "job_status": job_status,
            "job_control": job_control,
            "log_viewer": log_viewer
        }

    def _build_job_control_section(self):
        with gr.Row(equal_height=True):
            with gr.Column(scale=2):
                job_id_input = gr.Textbox(
                    label="Job ID",
                    placeholder="Input Job ID to Stop",
                    interactive=True,
                    type="text"
                )
            with gr.Column(scale=2):
                pass
            with gr.Column(scale=2):
                pass
            with gr.Column(scale=1):
                stop_job_btn = gr.Button("🛑 STOP JOB", variant="stop", size="lg")
        
        return {
            "job_id_input": job_id_input,
            "stop_job_btn": stop_job_btn
        }


    def _build_log_viewer_section(self):
        with gr.Blocks(elem_classes="dashboard-card"):
            with gr.Column():
                gr.Markdown("## 📜 Job Logs", elem_classes="card-title")
                
                with gr.Row(equal_height=True, variant="compact"):
                    # with gr.Column(scale=2):
                    #     log_group_input = gr.Textbox(
                    #         label="日志组",
                    #         value=self.task_manager.training_container_def['logConfiguration']['options']['awslogs-group'],
                    #         interactive=False,
                    #         type="text"
                    #     )
                    
                    # with gr.Column(scale=2):
                    #     container_name_input = gr.Textbox(
                    #         label="容器名称",
                    #         value=self.task_manager.training_container_def['name'],
                    #         interactive=False,
                    #         type="text"
                    #     )

                    with gr.Column(scale=2):
                        log_group_input = gr.Radio(
                            choices=[self.task_manager.training_container_def['logConfiguration']['options']['awslogs-group'],
                                     self.task_manager.healthcheck_container_def['logConfiguration']['options']['awslogs-group'],
                                     ],
                            label="CloudWatch LogGroup",
                            value=self.task_manager.training_container_def['logConfiguration']['options']['awslogs-group']
                        )

                    with gr.Column(scale=2):
                        container_name_input = gr.Radio(
                            choices=[self.task_manager.training_container_def['name'],
                                     self.task_manager.healthcheck_container_def['name']
                                     ],
                            label="Container Name",
                            value=self.task_manager.training_container_def['name']
                        )
                    
                    with gr.Column(scale=2):
                        task_id_input = gr.Textbox(
                            label="ECS Task ID",
                            placeholder="ECS Task ID From Above Table",
                            interactive=True,
                            type="text"
                        )
                    
                    with gr.Column(scale=1):
                        log_refresh_btn = gr.Button("📋 Fetch Logs", variant="primary", size="lg")
                
                with gr.Row():
                    log_output = gr.Markdown(elem_classes="log-viewer")


        log_to_container = {
            self.task_manager.training_container_def['logConfiguration']['options']['awslogs-group']: self.task_manager.training_container_def['name'],
            self.task_manager.healthcheck_container_def['logConfiguration']['options']['awslogs-group']: self.task_manager.healthcheck_container_def['name']
        }

        container_to_log = {
            self.task_manager.training_container_def['name']: self.task_manager.training_container_def['logConfiguration']['options']['awslogs-group'],
            self.task_manager.healthcheck_container_def['name']: self.task_manager.healthcheck_container_def['logConfiguration']['options']['awslogs-group']
        }

        # 当日志组选择改变时，更新容器名称
        def update_container_name(log_group):
            return log_to_container[log_group]

        # 当容器名称选择改变时，更新日志组
        def update_log_group(container_name):
            return container_to_log[container_name]

        # 绑定回调函数
        log_group_input.change(
            fn=update_container_name,
            inputs=[log_group_input],
            outputs=[container_name_input]
        )

        container_name_input.change(
            fn=update_log_group,
            inputs=[container_name_input],
            outputs=[log_group_input]
        )

        
        return {
            "log_group_input": log_group_input,
            "container_name_input": container_name_input,
            "task_id_input": task_id_input,
            "log_refresh_btn": log_refresh_btn,
            "log_output": log_output
        }

    def _get_initial_job_table(self):
        jobs_data = self.gui.refresh_job_status()
        return self.gui._create_job_table(jobs_data)

    def _connect_job_status_tab_events(self, 
                                     job_refresh_btn,
                                     job_status,
                                     job_control,
                                     log_viewer):
        # Refresh job status button click event
        job_refresh_btn.click(
            fn=self._refresh_job_table,
            outputs=[job_status]
        )

        # Stop job button click event
        job_control["stop_job_btn"].click(
            fn=self._stop_job_and_refresh,
            inputs=[job_control["job_id_input"]],
            outputs=[job_control["job_id_input"], job_status]
        )

        # Log refresh button click event
        log_viewer["log_refresh_btn"].click(
            fn=self._fetch_logs,
            inputs=[
                log_viewer["task_id_input"],
                log_viewer["log_group_input"],
                log_viewer["container_name_input"]
            ],
            outputs=[log_viewer["task_id_input"], log_viewer["log_output"]]
        )

    def _refresh_job_table(self):
        jobs_data = self.gui.refresh_job_status()
        return self.gui._create_job_table(jobs_data)

    def _stop_job_and_refresh(self, job_id: str):
        if not job_id or not job_id.strip():
            return "", self._refresh_job_table()
        
        try:
            success = JobManager.stop_job(job_id.strip())
            if success:
                return "", self._refresh_job_table()
            return job_id, self._refresh_job_table()
        except Exception as e:
            logger.error(f"Error stopping job: {str(e)}", exc_info=True)
            return job_id, self._refresh_job_table()

    def _fetch_logs(self, task_id: str, log_group: str, container_name: str):
        return self.gui.view_task_logs(task_id, log_group, container_name)


def create_interface():
    gui = EnhancedTrainingGUI()
    ui_builder = UIBuilder(gui)

    def update_welcome_message(request: gr.Request):
        return f"""
            # 🚀 {APP_TITLE}
            ### Distributed Training Management Interface
            Welcome, {request.username}!
            """

    
    with gr.Blocks(
        title=APP_TITLE,
        css=gui.get_custom_css(),
        theme=gr.themes.Soft(
            primary_hue="blue",
            secondary_hue="indigo",
        )
    ) as interface:

        # titlemd = gr.Markdown(
        #     f"""
        #     # 🚀 {APP_TITLE}
        #     ### Distributed Training Management Interface
        #     Wellcome, {the user name here}
        #     """,
        #     elem_classes=["title"]
        # )

        titlemd = gr.Markdown(
            elem_classes=["title"]
        )

        interface.load(update_welcome_message, None, titlemd)


        # interface.load(get_login_user, None, titlemd)
        
        with gr.Tabs() as tabs:
            # Launch Training Tab
            with gr.TabItem("🚀 Training Job") as training_tab_item:
                training_tab = ui_builder.build_training_tab()

            # # Health Check Tab
            # with gr.TabItem("🏥 Health Check"):
            #     health_tab = ui_builder.build_health_check_tab()

            # Job Status Tab
            with gr.TabItem("📋 Job Status", elem_id="job_status_tab") as job_status_tab_item:
                job_status_tab = ui_builder.build_job_status_tab()
        
        training_tab_item.select(
            fn=ui_builder._refresh_node_table,
            outputs=[training_tab["node_status"]]
        )

        job_status_tab_item.select(
            fn=ui_builder._refresh_job_table,
            outputs=[job_status_tab["job_status"]]
        )
    
    return interface

if __name__ == "__main__":
    # Create and launch the interface
    interface = create_interface()
    
    # Get port from environment variable or use default
    port = int(os.environ.get('GRADIO_SERVER_PORT', DEFAULT_PORT))

    # Launch the interface
    interface.launch(
        server_name="0.0.0.0",
        server_port=port,
        show_error=True,
        share=True,
        auth=[(os.environ.get('USER_NAME'), 
            os.environ.get('USER_PASSWORD')
            )]
    )
