import os
import tomli
from pathlib import Path
from typing import Set, Dict
import sys
import argparse


def find_local_packages(workspace_dir: Path) -> Set[str]:
    """Find local packages by looking for Python modules in the src directory structure.
    Returns the package names (directory names containing src/) rather than the module names."""
    local_packages = set()
    
    # Look for immediate subdirectories of workspace
    for package_dir in workspace_dir.iterdir():
        if not package_dir.is_dir() or package_dir.name == 'tests':
            continue
            
        # Check for src directory
        src_dir = package_dir / 'src'
        if not src_dir.is_dir():
            continue
            
        # Look for potential module directories
        for module_dir in src_dir.iterdir():
            if not module_dir.is_dir() or module_dir.name == 'tests':
                continue
                
            # Consider it a package if any of these conditions are met:
            # 1. Has __init__.py (traditional package)
            # 2. Contains .py files (namespace package)
            # 3. Contains subdirectories with .py files (nested namespace package)
            is_package = False
            
            if (module_dir / '__init__.py').exists():
                is_package = True
            else:
                # Check for any .py files in the directory or subdirectories
                for item in module_dir.rglob('*.py'):
                    is_package = True
                    break
            
            if is_package:
                # Add the package directory name instead of the module name
                local_packages.add(package_dir.name)
                # We can break here since we only need one valid module to identify the package
                break
    
    return local_packages

def parse_requirements_file(file_path: Path) -> Set[str]:
    """Parse a requirements.txt file and return set of package names."""
    if not file_path.exists():
        return set()
    
    dependencies = set()
    with open(file_path, 'r') as f:
        for line in f:
            # Skip comments, empty lines, and -r references
            line = line.strip()
            if line and not line.startswith('#') and not line.startswith('-r'):
                # Extract package name without version specifiers
                package = line.split('=')[0].split('>')[0].split('<')[0].split('~')[0].strip()
                dependencies.add(package)
    
    return dependencies

def parse_pyproject_toml(file_path: Path) -> Dict[str, Set[str]]:
    """Parse a pyproject.toml file and return dict of dependency types and their packages."""
    if not file_path.exists():
        return {}
    
    dependencies = {
        'dependencies': set(),
        'dev-dependencies': set()
    }
    
    with open(file_path, 'rb') as f:
        try:
            data = tomli.load(f)
            
            # Get main project dependencies
            if 'project' in data and 'dependencies' in data['project']:
                for dep in data['project']['dependencies']:
                    package = dep.split('=')[0].split('>')[0].split('<')[0].split('~')[0].strip()
                    dependencies['dependencies'].add(package)
            
            # Get dev dependencies from tool.hatch.envs.test.dependencies
            if 'tool' in data and 'hatch' in data['tool']:
                if 'envs' in data['tool']['hatch']:
                    for env_name, env_config in data['tool']['hatch']['envs'].items():
                        if 'dependencies' in env_config:
                            for dep in env_config['dependencies']:
                                package = dep.split('=')[0].split('>')[0].split('<')[0].split('~')[0].strip()
                                dependencies['dev-dependencies'].add(package)
                                
        except Exception as e:
            print(f"Error parsing {file_path}: {e}")
    
    return dependencies

def collect_dependencies(workspace_dir: str) -> Dict[str, Set[str]]:
    """Collect all dependencies and local packages from the workspace."""
    all_dependencies = {
        'dependencies': set(),
        'dev-dependencies': set(),
        'local-packages': set(),
        'all-external-dependencies': set()
    }
    
    workspace_path = Path(workspace_dir)
    
    # Find local packages first
    all_dependencies['local-packages'] = find_local_packages(workspace_path)
    
    # Walk through all directories
    for root, _, files in os.walk(workspace_path):
        root_path = Path(root)
        
        # Check for pyproject.toml
        pyproject_path = root_path / 'pyproject.toml'
        if pyproject_path.exists():
            deps = parse_pyproject_toml(pyproject_path)
            all_dependencies['dependencies'].update(deps['dependencies'])
            all_dependencies['dev-dependencies'].update(deps['dev-dependencies'])
        
        # Check for requirements.txt
        req_path = root_path / 'requirements.txt'
        if req_path.exists():
            deps = parse_requirements_file(req_path)
            all_dependencies['dependencies'].update(deps)
        
        # Check for requirements-dev.txt
        req_dev_path = root_path / 'requirements-dev.txt'
        if req_dev_path.exists():
            deps = parse_requirements_file(req_dev_path)
            all_dependencies['dev-dependencies'].update(deps)
    
    # Remove local packages from dependencies lists
    all_dependencies['dependencies'] -= all_dependencies['local-packages']
    all_dependencies['dev-dependencies'] -= all_dependencies['local-packages']
    
    # Create union of all external dependencies
    all_dependencies['all-external-dependencies'] = (
        all_dependencies['dependencies'] | all_dependencies['dev-dependencies']
    )
    
    return all_dependencies

def main():
    parser = argparse.ArgumentParser(
        description='Collect Python package dependencies from workspace'
    )
    parser.add_argument(
        '--workspace-root',
        type=Path,
        dest='workspace_root',
        default=Path.cwd(),
        help='Root directory of the workspace (default: current directory)'
    )
    
    parser.add_argument(
        '--verbose',
        action='store_true',
        help='Print detailed dependency information to stderr'
    )
    
    parser.add_argument(
        '--no_verbose',
        dest='verbose',
        action='store_false',
        help='Print detailed dependency information to stderr'
    )
    
    parser.set_defaults(verbose=True)
    
    parser.add_argument(
        '--output',
        type=Path,
        default='requirements.txt',
        help='Output file for dependencies (default: requirements.txt)'
    )
    
    parser.add_argument(
        "--update-requirements",
        dest='update_requirements',
        action='store_true',
        help='Update the requirements.txt file with the collected dependencies'
    )
    
    parser.add_argument(
        "--no-update-requirements",
        dest='update_requirements',
        action='store_false',
        help='Do not update the requirements.txt file with the collected dependencies'
    )
    parser.set_defaults(update_requirements=True)
    
    args = parser.parse_args()
    
    # Collect all dependencies
    dependencies = collect_dependencies(args.workspace_root)
    
    # Print verbose output if requested
    if args.verbose:
        print("\nLocal Packages:", file=sys.stderr)
        for pkg in sorted(dependencies['local-packages']):
            print(f"  {pkg}", file=sys.stderr)
            
        print("\nExternal Dependencies:", file=sys.stderr)
        for dep in sorted(dependencies['dependencies']):
            print(f"  {dep}", file=sys.stderr)
            
        print("\nDevelopment Dependencies:", file=sys.stderr)
        for dep in sorted(dependencies['dev-dependencies']):
            print(f"  {dep}", file=sys.stderr)
            
        print("\nAll External Dependencies (Combined):", file=sys.stderr)
        for dep in sorted(dependencies['all-external-dependencies']):
            print(f"  {dep}", file=sys.stderr)
    
    # Write space-separated dependencies to output file
    output_path = args.workspace_root / args.output
    with open(output_path, 'w') as f:
        f.write('\n'.join(sorted(dependencies['all-external-dependencies'])))

if __name__ == "__main__":
    main()
    