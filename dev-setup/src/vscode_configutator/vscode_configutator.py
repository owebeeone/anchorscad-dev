from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Dict
import sys
try:
    import commentjson as json
except ImportError:
    sys.stderr.write("Error: commentjson is not installed. Please run "
                     "'pip install commentjson' to install it.")
    try:
        import json
    except ImportError:
        sys.stderr.write("Error: json is not installed. Cannot continue.")
        sys.exit(1)
import argparse
import uuid
import os

@dataclass
class VSCodeConfigUpdater:
    workspace_folder: Path
    python_module_dirs: List[Path] = field(default_factory=list)
    
    def __post_init__(self):
        self.python_paths = [os.path.sep.join(p.parts[:-1]) for p in self.python_module_dirs]
        self.python_separator_paths = [
            "${pathSeparator}".join(p.parts[:-1]) for p in self.python_module_dirs
        ]
    
    def _load_json(self, file_path: Path) -> Dict:
        """Load JSON file if it exists, otherwise return empty dict"""
        if file_path.exists():
            with file_path.open('r') as f:
                return json.load(f)
        return {}
    
    def _save_json(self, file_path: Path, data: Dict):
        """Save JSON data with proper formatting using atomic file operations"""
        json_content = json.dumps(data, indent=4)
        self._safe_write_text(file_path, json_content)
    
    def _safe_write_text(self, file_path: Path, content: str):
        """Write text content to file using atomic file operations"""
        # Create temporary file with random suffix in the same directory
        temp_file = file_path.with_suffix(f'.{uuid.uuid4().hex}.tmp')
        try:
            # Write to temporary file first
            temp_file.write_text(content, encoding='utf-8')
            
            # If successful, replace the original file
            temp_file.replace(file_path)
        finally:
            # Clean up temp file if it still exists (e.g., if replace failed)
            if temp_file.exists():
                temp_file.unlink()
    
    def update_env_file(self, env_file: Path, add_pythonpath: bool):
        """Update or create .env file"""
        workspace_str = self.workspace_folder
        os_sep = os.path.sep
        pythonpath = ';'.join(f'${{WORKSPACE_FOLDER}}{os_sep}{p}' for p in self.python_paths)
        
        # Dont add PYTHONPATH if it is empty or not set
        ppsuffix = ";${{PYTHONPATH}" if add_pythonpath else ""
            
        env_content = f"WORKSPACE_FOLDER={workspace_str}\n" \
                      f"PYTHONPATH={pythonpath}{ppsuffix}\n"
        self._safe_write_text(env_file, env_content)
    
    def update_settings(self, settings_file: Path, add_pythonpath: bool):
        """Update settings.json"""
        settings = self._load_json(settings_file)
        
        paths = [str(p).replace('\\', '/') for p in self.python_separator_paths]
        win_paths = ';'.join(f'${{workspaceFolder}}${{pathSeparator}}{p}' for p in paths)
        unix_paths = ':'.join(f'${{workspaceFolder}}${{pathSeparator}}{p}' for p in paths)
        
        
        ppsuffix = ";${env:PYTHONPATH}" if add_pythonpath else ""
        
        # Update only the PYTHONPATH settings
        settings.setdefault("terminal.integrated.env.windows", {})["PYTHONPATH"] = f"{win_paths}{ppsuffix}"
        settings.setdefault("terminal.integrated.env.linux", {})["PYTHONPATH"] = f"{unix_paths}{ppsuffix}"
        settings.setdefault("terminal.integrated.env.osx", {})["PYTHONPATH"] = f"{unix_paths}{ppsuffix}"
        settings["python.envFile"] = "${workspaceFolder}/.vscode/.env"
        
        self._save_json(settings_file, settings)
    
    def update_launch(self, launch_file: Path, add_pythonpath: bool):
        """Update launch.json"""
        launch_config = self._load_json(launch_file)
        if not launch_config:
            launch_config = {"version": "0.2.0", "configurations": []}
            
        paths = [str(p).replace('\\', '/') for p in self.python_separator_paths]
        win_paths = ';'.join(f'${{workspaceFolder}}${{pathSeparator}}{p}' for p in paths)
        
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
        
        ppsuffix = ";${env:PYTHONPATH}" if add_pythonpath else ""
        
        # Update only the PYTHONPATH in env
        python_config.setdefault("env", {})["PYTHONPATH"] = f"{win_paths}{ppsuffix}"
        
        self._save_json(launch_file, launch_config)
        
    @classmethod
    def relationships(clz):
        configs = {".env" : clz.update_env_file, "settings.json" : clz.update_settings, "launch.json" : clz.update_launch}
        return configs
    

def find_src_modules(root_dir: Path) -> List[Path]:
    """Find all directories containing src/__init__.py"""
    src_paths = []
    for path in root_dir.rglob('src/*/__init__.py'):
        src_dir = path.parent
        relative_path = src_dir.relative_to(root_dir)
        if 'tests' in relative_path.parts:
            continue
        src_paths.append(src_dir.relative_to(root_dir))
    return src_paths

def update_vscode_configs(args):
    """Update VS Code configuration files"""
    workspace_root =args.workspace_root.resolve()
    src_paths = find_src_modules(workspace_root)
    
    # Create .vscode directory if it doesn't exist
    vscode_dir = workspace_root / '.vscode'
    vscode_dir.mkdir(exist_ok=True)
    
    updater = VSCodeConfigUpdater(workspace_root, src_paths)
    
    # Update each configuration file
    for file, func in VSCodeConfigUpdater.relationships().items():
        func(updater, vscode_dir / file, args.add_pythonpath)


def main():
    """Main entry point with command line argument handling"""
    parser = argparse.ArgumentParser(
        description='Update VS Code configuration files for Python projects')
    parser.add_argument(
        '--workspace-root', 
        type=Path,
        default=Path.cwd(),
        help='Root directory of the workspace (default: current directory)')
    parser.add_argument(
        '--create',
        type=bool,
        default=True,
        help='True if the .vscode directory and files should be created if they do not exist')
    parser.add_argument(
        '--add_pythonpath',
        type=bool,
        default=os.environ.get('PYTHONPATH', None) and True,
        help='True if the PYTHONPATH should be added to the paths')
    
    args = parser.parse_args()

    # If not requested to create, check if the files exist
    if not args.create: 
        for file in VSCodeConfigUpdater.relationships().keys():
            if not (args.workspace_root / ".vscode" / file).exists():
                print(
                    "Error: Wrong workspace root directory? The specified workspace "
                    f"root directory does not contain the file '{file}'. "
                    f"workspace root: '{args.workspace_root}'",
                    file=sys.stderr,
                )
                return 1

    update_vscode_configs(args)
    print(f"Successfully updated VS Code configs in {args.workspace_root / '.vscode'}")



if __name__ == "__main__":
    exit(main())