import os
import json
import yaml
from typing import Dict, Any, List

class FileManager:
    @staticmethod
    def load_yaml(path: str) -> Dict[str, Any]:
        with open(path, 'r') as f:
            return yaml.safe_load(f)

    @staticmethod
    def load_json(path: str) -> Dict[str, Any]:
        with open(path, 'r') as f:
            return json.load(f)

    @staticmethod
    def save_json(path: str, data: Dict[str, Any]) -> None:
        directory = os.path.dirname(path)
        os.makedirs(directory, exist_ok=True)

        with open(path, 'w') as f:
            json.dump(data, f, indent=2)

    @staticmethod
    def write_script(path: str, content: str) -> None:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        os.chmod(os.path.dirname(path), 0o777)
        with open(path, 'a+') as f:
            f.write('\n')
            f.write(content)
        # os.chmod(path, 0o755)

    @staticmethod
    def create_execution_history(output_dir: str, commands: List[List[str]]) -> str:
        history_path = os.path.join(output_dir, "execution_history.sh")
        content = "#!/bin/bash\n# Execution history of commands\n\n"

        for cmd in commands:
            content = content + "\n\n" + " ".join(cmd)
        
        print(content)

        FileManager.write_script(history_path, content)

        return history_path
