from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Dict
import json
import os
import sys
import argparse
import commentjson

@dataclass
class VSCodeConfigUpdater:
    workspace_folder: Path
    python_paths: List[Path] = field(default_factory=list)
    
    def _load_json(self, file_path: Path) -> Dict:
        """Load JSON file if it exists, otherwise return empty dict"""
        if not file_path.exists():
            return {}
        
        with file_path.open('r') as f:
            return commentjson.load(f)
    
    def _save_json(self, file_path: Path, data: Dict):
        """Save JSON data with proper formatting while preserving comments"""
        
        # If file exists, load it first to preserve comments
        existing_comments = {}
        if file_path.exists():
            with file_path.open('r') as f:
                existing_content = f.read()
                existing_comments = commentjson.comments.get_comments(existing_content)
        
        # Write the new content with preserved comments
        with file_path.open('w') as f:
            commentjson.dump(data, f, indent=4, trailing_commas=False, comments=existing_comments)
    
    def update_env_file(self, env_file: Path):
        """Update or create .env file"""
        workspace_str = str(self.workspace_folder).replace('\\', '\\\\')
        paths = [str(p).replace('\\', '/') for p in self.python_paths]
        pythonpath = ';'.join(f'${{WORKSPACE_FOLDER}}/{p}' for p in paths)
        
        env_content = f'''WORKSPACE_FOLDER={workspace_str}
PYTHONPATH={pythonpath};${{PYTHONPATH}}
'''
        env_file.write_text(env_content)
    
    def update_settings(self, settings_file: Path):
        """Update settings.json"""
        settings = self._load_json(settings_file)
        
        paths = [str(p).replace('\\', '/') for p in self.python_paths]
        win_paths = ';'.join(f'${{workspaceFolder}}${{{pathSeparator}}}{p}' for p in paths)
        unix_paths = ':'.join(f'${{workspaceFolder}}${{{pathSeparator}}}{p}' for p in paths)
        
        # Update only the PYTHONPATH settings
        settings.setdefault("terminal.integrated.env.windows", {})["PYTHONPATH"] = f"{win_paths};${{env:PYTHONPATH}}"
        settings.setdefault("terminal.integrated.env.linux", {})["PYTHONPATH"] = f"{unix_paths}:${{env:PYTHONPATH}}"
        settings.setdefault("terminal.integrated.env.osx", {})["PYTHONPATH"] = f"{unix_paths}:${{env:PYTHONPATH}}"
        settings["python.envFile"] = "${workspaceFolder}/.vscode/.env"
        
        self._save_json(settings_file, settings)
    
    def update_launch(self, launch_file: Path):
        """Update launch.json"""
        launch_config = self._load_json(launch_file)
        if not launch_config:
            launch_config = {"version": "0.2.0", "configurations": []}
            
        paths = [str(p).replace('\\', '/') for p in self.python_paths]
        win_paths = ';'.join(f'${{workspaceFolder}}${{{pathSeparator}}}{p}' for p in paths)
        
        # Find or create Python configuration
        python_config = None
        for config in launch_config.get("configurations", []):
            if config.get("name") == "Python: Current File":
                python_config = config
                break
                
        if not python_config:
            python_config = {
                "name": "Python: Current File",
                "type": "python",
                "request": "launch",
                "program": "${file}",
                "cwd": "${fileDirname}",
                "console": "integratedTerminal",
                "args": ["--write", "--write_path_files"],
                "justMyCode": True,
            }
            launch_config.setdefault("configurations", []).append(python_config)
        
        # Update only the PYTHONPATH in env
        python_config.setdefault("env", {})["PYTHONPATH"] = f"{win_paths};${{env:PYTHONPATH}}"
        
        self._save_json(launch_file, launch_config)

def find_src_modules(root_dir: Path) -> List[Path]:
    """Find all directories containing src/__init__.py"""
    src_paths = []
    for path in root_dir.rglob('src/__init__.py'):
        src_dir = path.parent
        src_paths.append(src_dir.relative_to(root_dir))
    return src_paths

def update_vscode_configs(workspace_root: Path):
    """Update VS Code configuration files"""
    workspace_root = workspace_root.resolve()
    src_paths = find_src_modules(workspace_root)
    
    # Create .vscode directory if it doesn't exist
    vscode_dir = workspace_root / '.vscode'
    vscode_dir.mkdir(exist_ok=True)
    
    updater = VSCodeConfigUpdater(workspace_root, src_paths)
    
    # Update each configuration file
    updater.update_env_file(vscode_dir / '.env')
    updater.update_settings(vscode_dir / 'settings.json')
    updater.update_launch(vscode_dir / 'launch.json')

def main():
    """Main entry point with command line argument handling"""
    parser = argparse.ArgumentParser(
        description='Update VS Code configuration files for Python projects')
    parser.add_argument(
        '--workspace-root', 
        type=Path,
        default=Path.cwd(),
        help='Root directory of the workspace (default: current directory)')
    
    args = parser.parse_args()
    
    try:
        update_vscode_configs(args.workspace_root)
        print(f"Successfully updated VS Code configs in {args.workspace_root / '.vscode'}")
    except Exception as e:
        print(f"Error updating VS Code configs: {e}", file=sys.stderr)
        sys.exit(1)

if __name__ == '__main__':
    main() 