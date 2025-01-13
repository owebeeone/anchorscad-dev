import os
import subprocess
import tomli
from pathlib import Path
from typing import Set, Dict
import sys
import argparse
from packaging.specifiers import SpecifierSet
from packaging.requirements import Requirement
from collections import defaultdict


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

def merge_requirements(requirements: Set[str]) -> Set[str]:
    """Merge requirements for the same package, combining their specifiers and preserving first case seen."""
    package_specs = defaultdict(SpecifierSet)
    # Track the first case we see for each package
    package_cases = {}
    
    for req_str in requirements:
        try:
            req = Requirement(req_str)
            lowercase_name = req.name.lower()
            
            # Store the first case we see for this package
            if lowercase_name not in package_cases:
                package_cases[lowercase_name] = req.name
                
            # Merge the specifiers
            package_specs[lowercase_name] &= req.specifier
        except Exception as e:
            print(f"Warning: Could not parse requirement '{req_str}': {e}")
            continue
    
    # Convert back to requirement strings using the preserved case
    merged = set()
    for lowercase_name, specifier in package_specs.items():
        original_case_name = package_cases[lowercase_name]
        if str(specifier):
            merged.add(f"{original_case_name}{specifier}")
        else:
            merged.add(original_case_name)
    
    return merged

def parse_requirements_file(file_path: Path) -> Set[str]:
    """Parse a requirements.txt file and return set of package names with versions."""
    if not file_path.exists():
        return set()
    
    dependencies = set()
    with open(file_path, 'r') as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith('#') and not line.startswith('-r'):
                dependencies.add(line)
    
    return merge_requirements(dependencies)

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
                dependencies['dependencies'].update(data['project']['dependencies'])
            
            # Get dev dependencies from tool.hatch.envs.test.dependencies
            if 'tool' in data and 'hatch' in data['tool']:
                if 'envs' in data['tool']['hatch']:
                    for env_name, env_config in data['tool']['hatch']['envs'].items():
                        if 'dependencies' in env_config:
                            dependencies['dev-dependencies'].update(env_config['dependencies'])
                                
        except Exception as e:
            print(f"Error parsing {file_path}: {e}")
    
    # Merge requirements for each dependency type
    dependencies['dependencies'] = merge_requirements(dependencies['dependencies'])
    dependencies['dev-dependencies'] = merge_requirements(dependencies['dev-dependencies'])
    
    return dependencies

def remove_local_packages(dependencies: Set[str], local_packages: Set[str]) -> Set[str]:
    """Remove local packages from a set of dependencies.
    
    Args:
        dependencies: Set of dependency strings with versions
        local_packages: Set of local package names (without versions)
    
    Returns:
        Set of dependencies with local packages removed
    """
    filtered = set()
    for dep in dependencies:
        try:
            req = Requirement(dep)
            if req.name not in local_packages:
                filtered.add(dep)
        except Exception as e:
            print(f"Warning: Could not parse requirement '{dep}': {e}")
    return filtered

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
    all_dependencies['dependencies'] = remove_local_packages(
        all_dependencies['dependencies'], 
        all_dependencies['local-packages']
    )
    all_dependencies['dev-dependencies'] = remove_local_packages(
        all_dependencies['dev-dependencies'], 
        all_dependencies['local-packages']
    )
    
    # Create union of all external dependencies
    all_dependencies['all-external-dependencies'] = (
        all_dependencies['dependencies'] | all_dependencies['dev-dependencies']
    )
    
    # Before returning, merge all external dependencies
    all_dependencies['all-external-dependencies'] = merge_requirements(
        all_dependencies['all-external-dependencies']
    )
    
    return all_dependencies

def pull_versions_from_pip(dependencies: Set[str]) -> Set[str]:
    """Runs the pip freeze command and merges the pip versions with the dependencies
    that have no version specifiers. Converts exact versions to minimum versions (>=)."""
    pip_freeze = subprocess.check_output(["uv", 'pip', 'freeze']).decode('utf-8').splitlines()
    
    # Create dictionary of lowercase package names to their minimum versions
    pip_versions = {}
    # Track the first case we see for each package
    package_cases = {}
    
    # First, create a mapping of lowercase names to original dependencies
    dep_map = {}
    for dep in dependencies:
        try:
            req = Requirement(dep)
            lowercase_name = req.name.lower()
            # Store the first case we see for this package
            if lowercase_name not in package_cases:
                package_cases[lowercase_name] = req.name
                dep_map[lowercase_name] = dep
        except Exception as e:
            print(f"Warning: Could not parse requirement '{dep}': {e}")
            continue
    
    # Process pip freeze
    for line in pip_freeze:
        try:
            req = Requirement(line)
            lowercase_name = req.name.lower()
            version = str(req.specifier).replace('==', '>=')
            pip_versions[lowercase_name] = version
        except Exception as e:
            print(f"Warning: Could not parse pip requirement '{line}': {e}")
            continue
    
    # Update dependencies with pip versions
    updated_deps = set()
    for lowercase_name, original_dep in dep_map.items():
        try:
            if lowercase_name in pip_versions:
                req = Requirement(original_dep)
                updated_deps.add(f"{package_cases[lowercase_name]}{pip_versions[lowercase_name]}")
            else:
                updated_deps.add(original_dep)
        except Exception as e:
            print(f"Warning: Could not parse requirement '{original_dep}': {e}")
            updated_deps.add(original_dep)
    
    return updated_deps


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
    
    versioned_dependencies = pull_versions_from_pip(dependencies['all-external-dependencies'])
    dependencies['versioned_dependencies'] = versioned_dependencies
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
            
        print("\nVersioned Dependencies (Combined):", file=sys.stderr)
        for dep in sorted(dependencies['versioned_dependencies']):
            print(f"  {dep}", file=sys.stderr)
    
    # Write space-separated dependencies to output file
    output_path = args.workspace_root / args.output
    with open(output_path, 'w') as f:
        f.write('\n'.join(sorted(dependencies['versioned_dependencies'])))
        f.write('\n')

if __name__ == "__main__":
    main()
    