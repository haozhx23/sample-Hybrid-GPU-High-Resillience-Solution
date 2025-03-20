import subprocess
import json, os
from typing import Optional

class CloudWatchManager:

    def get_task_logs(self, task_id: str, log_group_input: str, container_name_input: str) -> str:
        """Fetch logs for a specific task from CloudWatch."""
        try:
            # Construct the log stream name
            log_stream_name = f"ecs/{container_name_input.strip()}/{task_id.strip()}"
            print(f"Fetching logs from stream: {log_stream_name}")  # Debug log
            
            # Execute aws command directly without shell
            cmd = [
                "aws", "logs", "get-log-events",
                "--log-group-name", log_group_input,
                "--log-stream-name", log_stream_name,
                "--output", "text"
            ]
            print(f"Executing command: {' '.join(cmd)}")  # Debug log
            
            # Use Popen to have more control over execution
            process = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True
            )
            
            # Get output with timeout
            try:
                stdout, stderr = process.communicate(timeout=100)
                if process.returncode != 0:
                    # if "aws: command not found" in stderr:
                    #     return "AWS CLI not found. Please ensure it is installed and in your PATH."
                    # if "Unable to locate credentials" in stderr:
                    #     return "AWS credentials not found. Please configure AWS CLI."
                    # if "ResourceNotFoundException" in stderr:
                    #     return "No logs found for this task. The log stream may not exist yet."
                    # return f"Error fetching logs: {stderr}"
                    return f"ERROR - {stderr}"
                
                if not stdout.strip():
                    return "No logs found for this task."
                
                # Parse the tab-separated output from aws logs get-log-events
                # Format: EVENTS  timestamp   message
                formatted_logs = []
                for line in stdout.splitlines():
                    parts = line.split('\t')
                    if len(parts) >= 3 and parts[0] == 'EVENTS':
                        # Extract just the message part
                        message = parts[2].strip()
                        formatted_logs.append(message)
                
                if not formatted_logs:
                    return "No log messages found for this task."
                
                return "\n".join(formatted_logs)
            except subprocess.TimeoutExpired:
                process.kill()
                return "Command timed out while fetching logs"
            
        except subprocess.CalledProcessError as e:
            error_msg = f"Error fetching logs: {str(e)}\nError output: {e.stderr}"
            print(error_msg)  # Debug log
            return error_msg
        except Exception as e:
            error_msg = f"Unexpected error: {str(e)}"
            print(error_msg)  # Debug log
            return error_msg
